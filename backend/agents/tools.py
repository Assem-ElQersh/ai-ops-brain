"""
Agent tools. Each tool has a real side-effect (DB write, API call, etc.).
Tools are injected with the current DB session and ticket_id at runtime.

The agent decides WHICH tools to call and IN WHAT ORDER based on context.
"""
import json
import logging
from typing import Optional

from langchain_core.tools import tool
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def make_tools(db: Session, ticket_id: str):

    # ── Context & Decision tools ─────────────────────────────────────────────

    @tool
    def get_customer_profile(customer_email: str) -> str:
        """
        Get the full profile of this customer: ticket history, churn risk signals,
        VIP status, and any recurring patterns. Call this FIRST on every ticket.

        Args:
            customer_email: The customer's email address.
        """
        from db.models import Ticket, TicketStatus

        tickets = (
            db.query(Ticket)
            .filter(Ticket.customer_email == customer_email)
            .filter(Ticket.id != ticket_id)
            .order_by(Ticket.created_at.desc())
            .limit(10)
            .all()
        )

        if not tickets:
            return json.dumps({
                "is_new_customer": True,
                "ticket_count": 0,
                "churn_risk": "low",
                "is_vip": False,
                "patterns": [],
                "history": [],
            })

        resolved = [t for t in tickets if t.status == TicketStatus.resolved]
        unresolved = [t for t in tickets if t.status not in (TicketStatus.resolved, TicketStatus.failed)]
        critical_count = sum(1 for t in tickets if t.urgency and t.urgency.value == "critical")
        repeat_categories = {}
        for t in tickets:
            if t.category:
                repeat_categories[t.category.value] = repeat_categories.get(t.category.value, 0) + 1

        # Churn risk heuristic
        if len(tickets) >= 3 and critical_count >= 2:
            churn_risk = "high"
        elif len(unresolved) >= 2 or critical_count >= 1:
            churn_risk = "medium"
        else:
            churn_risk = "low"

        # VIP: 5+ tickets or 2+ critical resolved satisfactorily
        is_vip = len(tickets) >= 5 or (critical_count >= 2 and len(resolved) >= 2)

        patterns = [
            f"{cat}: {count} occurrence(s)"
            for cat, count in repeat_categories.items()
            if count >= 2
        ]

        return json.dumps({
            "is_new_customer": False,
            "ticket_count": len(tickets),
            "resolved_count": len(resolved),
            "unresolved_count": len(unresolved),
            "critical_count": critical_count,
            "churn_risk": churn_risk,
            "is_vip": is_vip,
            "recurring_patterns": patterns,
            "history": [
                {
                    "id": str(t.id),
                    "subject": t.subject,
                    "urgency": t.urgency.value if t.urgency else "unclassified",
                    "status": t.status.value,
                    "satisfaction_score": t.satisfaction_score,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                }
                for t in tickets[:5]
            ],
        })

    @tool
    def assess_and_classify(
        urgency: str,
        category: str,
        summary: str,
        reasoning: str,
        churn_risk: str,
        is_vip: bool,
        decision_notes: str,
    ) -> str:
        """
        Classify the ticket and record the agent's reasoning about how to handle it.
        Call this after get_customer_profile.

        Args:
            urgency: One of: low, medium, high, critical
            category: One of: billing, technical, service_quality, scheduling,
                      cancellation, feedback, other
            summary: One-sentence summary of the issue.
            reasoning: Why this urgency/category was assigned.
            churn_risk: Assessed churn risk: low, medium, or high.
            is_vip: Whether this customer should receive VIP handling.
            decision_notes: What approach the agent decided to take and why
                            (e.g. "VIP + high churn risk → priority escalation + compensation offer").
        """
        from db.models import Ticket, TicketStatus, UrgencyLevel, TicketCategory

        valid_urgency = {e.value for e in UrgencyLevel}
        valid_category = {e.value for e in TicketCategory}
        if urgency not in valid_urgency:
            return f"Invalid urgency '{urgency}'. Must be one of {valid_urgency}"
        if category not in valid_category:
            return f"Invalid category '{category}'. Must be one of {valid_category}"

        ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
        if not ticket:
            return "Ticket not found"

        ticket.urgency = UrgencyLevel(urgency)
        ticket.category = TicketCategory(category)
        ticket.ai_summary = summary
        ticket.ai_reasoning = reasoning
        ticket.churn_risk = churn_risk
        ticket.is_vip = is_vip
        ticket.agent_decision_notes = decision_notes
        ticket.status = TicketStatus.processing
        db.commit()

        return json.dumps({
            "classified": True,
            "urgency": urgency,
            "category": category,
            "churn_risk": churn_risk,
            "is_vip": is_vip,
        })

    @tool
    def draft_response(response_text: str) -> str:
        """
        Store the AI-drafted response for the customer.
        Tailor the tone based on context: VIP customers get a senior-tone response,
        high-churn customers get a compensation offer, new customers get a warm welcome.

        Args:
            response_text: The full reply text addressed to the customer.
        """
        from db.models import Ticket

        ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
        if not ticket:
            return "Ticket not found"

        ticket.ai_response = response_text
        db.commit()
        return "Response drafted and saved."

    @tool
    def send_auto_reply(customer_email: str, customer_name: str, response_text: str) -> str:
        """
        Send the drafted reply to the customer via email.

        Args:
            customer_email: Recipient email.
            customer_name: Customer's name.
            response_text: The reply body.
        """
        import asyncio
        from services.email_service import send_email
        from db.models import Ticket, ActionLog

        try:
            asyncio.run(send_email(
                to_email=customer_email,
                to_name=customer_name,
                subject="Re: Your Support Request",
                body=response_text,
            ))
            ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
            if ticket:
                ticket.auto_replied = True
                db.add(ActionLog(ticket_id=ticket_id, action_type="email_auto_reply",
                                 status="success", detail=f"Sent to {customer_email}"))
                db.commit()
            return f"Email sent to {customer_email}"
        except Exception as exc:
            logger.error("Email failed: %s", exc)
            db.add(ActionLog(ticket_id=ticket_id, action_type="email_auto_reply",
                             status="failed", detail=str(exc)))
            db.commit()
            return f"Email failed: {exc}. Continue with remaining steps."

    @tool
    def escalate_to_slack(
        reason: str,
        urgency: str,
        customer_name: str,
        summary: str,
        is_vip: bool = False,
        churn_risk: str = "low",
        ticket_url: Optional[str] = None,
    ) -> str:
        """
        Send an escalation alert to the Slack support channel.
        Use this when urgency is high/critical, OR when churn_risk is high,
        OR when the customer is VIP. Do NOT call this for low/medium tickets
        unless churn_risk or VIP status justifies it.

        Args:
            reason: Why this ticket is being escalated.
            urgency: The urgency level.
            customer_name: Name of the customer.
            summary: Short issue summary.
            is_vip: Whether this is a VIP customer.
            churn_risk: Assessed churn risk level.
            ticket_url: Optional dashboard URL.
        """
        import asyncio
        from services.notifier import send_slack_alert
        from db.models import Ticket, ActionLog, TicketStatus

        try:
            asyncio.run(send_slack_alert(
                urgency=urgency,
                customer_name=customer_name,
                summary=summary,
                reason=reason,
                ticket_id=ticket_id,
                ticket_url=ticket_url,
                is_vip=is_vip,
                churn_risk=churn_risk,
            ))
            ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
            if ticket:
                ticket.escalated = True
                ticket.status = TicketStatus.escalated
                db.add(ActionLog(ticket_id=ticket_id, action_type="slack_escalation",
                                 status="success", detail=reason))
                db.commit()
            return "Escalation sent to Slack."
        except Exception as exc:
            logger.error("Slack escalation failed: %s", exc)
            db.add(ActionLog(ticket_id=ticket_id, action_type="slack_escalation",
                             status="failed", detail=str(exc)))
            db.commit()
            return f"Slack failed: {exc}. Consider fallback (email escalation)."

    @tool
    def escalate_via_email(
        escalation_summary: str,
        urgency: str,
        customer_name: str,
        reason: str,
    ) -> str:
        """
        Fallback escalation: send an alert to the support manager's email
        when Slack is unavailable. Use this if escalate_to_slack fails.

        Args:
            escalation_summary: Brief summary of why this needs attention.
            urgency: Urgency level.
            customer_name: Customer's name.
            reason: Reason for escalation.
        """
        import asyncio
        from services.email_service import send_email
        from db.models import ActionLog
        from config import get_settings

        settings = get_settings()
        if not settings.support_email:
            return "No support email configured — escalation skipped."

        body = (
            f"ESCALATION ALERT — {urgency.upper()}\n\n"
            f"Customer: {customer_name}\n"
            f"Reason: {reason}\n\n"
            f"{escalation_summary}\n\n"
            f"Ticket ID: {ticket_id}"
        )
        try:
            asyncio.run(send_email(
                to_email=settings.support_email,
                to_name="Support Manager",
                subject=f"[{urgency.upper()}] Escalation: {customer_name}",
                body=body,
            ))
            db.add(ActionLog(ticket_id=ticket_id, action_type="email_escalation",
                             status="success", detail=reason))
            db.commit()
            return "Email escalation sent to support manager."
        except Exception as exc:
            db.add(ActionLog(ticket_id=ticket_id, action_type="email_escalation",
                             status="failed", detail=str(exc)))
            db.commit()
            return f"Email escalation also failed: {exc}"

    @tool
    def self_evaluate_and_resolve(
        resolution_summary: str,
        self_score: int,
        resolution_successful: bool,
        improvement_notes: str,
    ) -> str:
        """
        Mark the ticket resolved AND have the agent score its own performance.
        This creates a feedback loop for tracking resolution quality over time.
        Always call this as the FINAL step.

        Args:
            resolution_summary: What was done to resolve this ticket.
            self_score: Agent's self-assessment of resolution quality (1-5).
                        5 = fully resolved, customer will be satisfied.
                        3 = partial resolution, may need follow-up.
                        1 = escalated only, no direct resolution.
            resolution_successful: Whether the issue was actually resolved (True/False).
            improvement_notes: What could be improved next time for similar tickets.
        """
        from datetime import datetime, timezone
        from db.models import Ticket, TicketStatus, ActionLog

        ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
        if not ticket:
            return "Ticket not found"

        if ticket.status != TicketStatus.escalated:
            ticket.status = TicketStatus.resolved
        ticket.resolved_at = datetime.now(timezone.utc)
        ticket.agent_self_score = max(1, min(5, self_score))
        ticket.resolution_successful = resolution_successful

        db.add(ActionLog(
            ticket_id=ticket_id,
            action_type="resolved",
            status="success",
            detail=f"[self_score={self_score}/5] {resolution_summary} | Notes: {improvement_notes}",
        ))
        db.commit()
        return json.dumps({
            "resolved": True,
            "self_score": self_score,
            "resolution_successful": resolution_successful,
        })

    return [
        get_customer_profile,
        assess_and_classify,
        draft_response,
        send_auto_reply,
        escalate_to_slack,
        escalate_via_email,
        self_evaluate_and_resolve,
    ]
