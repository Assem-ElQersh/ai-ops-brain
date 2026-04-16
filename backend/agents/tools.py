"""
Tools available to the support agent.
Each tool performs a real side-effect: DB write, Slack alert, email send, etc.
"""
import json
import logging
from typing import Optional

from langchain_core.tools import tool
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# The DB session and ticket_id are injected at runtime via a closure factory.
# This avoids global state and keeps tools testable.


def make_tools(db: Session, ticket_id: str):
    """
    Returns a list of LangChain tools bound to the current DB session and ticket.
    """

    @tool
    def classify_ticket(
        urgency: str,
        category: str,
        summary: str,
        reasoning: str,
    ) -> str:
        """
        Classify the support ticket.

        Args:
            urgency: One of: low, medium, high, critical
            category: One of: billing, technical, service_quality, scheduling,
                      cancellation, feedback, other
            summary: A one-sentence summary of the issue.
            reasoning: Brief explanation of why this urgency/category was assigned.
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
        ticket.status = TicketStatus.processing
        db.commit()

        return json.dumps({
            "classified": True,
            "urgency": urgency,
            "category": category,
        })

    @tool
    def draft_response(response_text: str) -> str:
        """
        Store the AI-drafted response that will be sent to the customer.

        Args:
            response_text: The full auto-reply text addressed to the customer.
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
        Send an automatic email reply to the customer.

        Args:
            customer_email: Recipient email address.
            customer_name: Customer's name for personalization.
            response_text: The reply body to send.
        """
        import asyncio
        from services.email_service import send_email
        from db.models import Ticket, ActionLog

        try:
            asyncio.run(
                send_email(
                    to_email=customer_email,
                    to_name=customer_name,
                    subject="Re: Your Support Request",
                    body=response_text,
                )
            )
            ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
            if ticket:
                ticket.auto_replied = True
                db.add(ActionLog(
                    ticket_id=ticket_id,
                    action_type="email_auto_reply",
                    status="success",
                    detail=f"Auto-reply sent to {customer_email}",
                ))
                db.commit()
            return f"Auto-reply sent to {customer_email}"
        except Exception as exc:
            logger.error("Failed to send auto-reply: %s", exc)
            db.add(ActionLog(
                ticket_id=ticket_id,
                action_type="email_auto_reply",
                status="failed",
                detail=str(exc),
            ))
            db.commit()
            return f"Failed to send email: {exc}"

    @tool
    def escalate_to_slack(
        reason: str,
        urgency: str,
        customer_name: str,
        summary: str,
        ticket_url: Optional[str] = None,
    ) -> str:
        """
        Send an escalation alert to the Slack support channel.

        Args:
            reason: Why this ticket is being escalated.
            urgency: The urgency level (high or critical).
            customer_name: Name of the affected customer.
            summary: Short summary of the issue.
            ticket_url: Optional URL to the ticket in the dashboard.
        """
        import asyncio
        from services.notifier import send_slack_alert
        from db.models import Ticket, ActionLog, TicketStatus

        try:
            asyncio.run(
                send_slack_alert(
                    urgency=urgency,
                    customer_name=customer_name,
                    summary=summary,
                    reason=reason,
                    ticket_id=ticket_id,
                    ticket_url=ticket_url,
                )
            )
            ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
            if ticket:
                ticket.escalated = True
                ticket.status = TicketStatus.escalated
                db.add(ActionLog(
                    ticket_id=ticket_id,
                    action_type="slack_escalation",
                    status="success",
                    detail=reason,
                ))
                db.commit()
            return "Escalation alert sent to Slack."
        except Exception as exc:
            logger.error("Slack escalation failed: %s", exc)
            db.add(ActionLog(
                ticket_id=ticket_id,
                action_type="slack_escalation",
                status="failed",
                detail=str(exc),
            ))
            db.commit()
            return f"Slack escalation failed: {exc}"

    @tool
    def mark_resolved(resolution_note: str) -> str:
        """
        Mark the ticket as resolved after all actions are complete.

        Args:
            resolution_note: Brief note on how the ticket was resolved.
        """
        from datetime import datetime, timezone
        from db.models import Ticket, TicketStatus, ActionLog

        ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
        if not ticket:
            return "Ticket not found"

        if ticket.status != TicketStatus.escalated:
            ticket.status = TicketStatus.resolved
        ticket.resolved_at = datetime.now(timezone.utc)
        db.add(ActionLog(
            ticket_id=ticket_id,
            action_type="mark_resolved",
            status="success",
            detail=resolution_note,
        ))
        db.commit()
        return "Ticket marked as resolved."

    @tool
    def query_customer_history(customer_email: str) -> str:
        """
        Look up previous tickets from this customer to provide context.

        Args:
            customer_email: The customer's email address.
        """
        from db.models import Ticket

        past_tickets = (
            db.query(Ticket)
            .filter(Ticket.customer_email == customer_email)
            .filter(Ticket.id != ticket_id)
            .order_by(Ticket.created_at.desc())
            .limit(5)
            .all()
        )

        if not past_tickets:
            return "No previous tickets found for this customer."

        history = []
        for t in past_tickets:
            history.append({
                "id": str(t.id),
                "subject": t.subject,
                "urgency": t.urgency.value if t.urgency else "unclassified",
                "status": t.status.value,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            })

        return json.dumps(history, indent=2)

    return [
        classify_ticket,
        draft_response,
        send_auto_reply,
        escalate_to_slack,
        mark_resolved,
        query_customer_history,
    ]
