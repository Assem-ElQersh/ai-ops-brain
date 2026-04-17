"""
Insight Engine — analyzes ticket data and produces actionable business intelligence.

This is NOT a dashboard of stats. It produces:
- Anomaly detection (sudden spikes in category/urgency)
- Recurring pattern analysis
- Agent performance trends
- Business recommendations
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, and_
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def generate_insights(db: Session) -> dict[str, Any]:
    from db.models import Ticket, TicketStatus, UrgencyLevel, CustomerFeedback

    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    two_weeks_ago = now - timedelta(days=14)

    # ── Volume anomaly ───────────────────────────────────────────────────────
    this_week = db.query(func.count(Ticket.id)).filter(Ticket.created_at >= week_ago).scalar() or 0
    last_week = db.query(func.count(Ticket.id)).filter(
        and_(Ticket.created_at >= two_weeks_ago, Ticket.created_at < week_ago)
    ).scalar() or 0

    volume_change_pct = (
        round(((this_week - last_week) / last_week) * 100, 1) if last_week > 0 else None
    )

    # ── Category breakdown this week ─────────────────────────────────────────
    category_counts = (
        db.query(Ticket.category, func.count(Ticket.id))
        .filter(Ticket.created_at >= week_ago, Ticket.category.isnot(None))
        .group_by(Ticket.category)
        .order_by(func.count(Ticket.id).desc())
        .all()
    )

    # ── Urgency breakdown this week ───────────────────────────────────────────
    urgency_counts = (
        db.query(Ticket.urgency, func.count(Ticket.id))
        .filter(Ticket.created_at >= week_ago, Ticket.urgency.isnot(None))
        .group_by(Ticket.urgency)
        .all()
    )
    critical_this_week = next(
        (c for u, c in urgency_counts if u and u.value == "critical"), 0
    )

    # ── Churn risk analysis ──────────────────────────────────────────────────
    high_churn_open = db.query(func.count(Ticket.id)).filter(
        Ticket.churn_risk == "high",
        Ticket.status.notin_([TicketStatus.resolved]),
    ).scalar() or 0

    # ── Resolution quality ───────────────────────────────────────────────────
    avg_agent_score = db.query(func.avg(Ticket.agent_self_score)).filter(
        Ticket.created_at >= week_ago, Ticket.agent_self_score.isnot(None)
    ).scalar()

    avg_satisfaction = db.query(func.avg(CustomerFeedback.score)).filter(
        CustomerFeedback.created_at >= week_ago
    ).scalar()

    # ── Recurring issues (same customer, 2+ tickets same category) ───────────
    recurring = (
        db.query(Ticket.customer_email, Ticket.category, func.count(Ticket.id).label("cnt"))
        .filter(Ticket.created_at >= week_ago, Ticket.category.isnot(None))
        .group_by(Ticket.customer_email, Ticket.category)
        .having(func.count(Ticket.id) >= 2)
        .all()
    )

    # ── Failed resolutions ────────────────────────────────────────────────────
    failed_this_week = db.query(func.count(Ticket.id)).filter(
        Ticket.created_at >= week_ago,
        Ticket.status == TicketStatus.failed,
    ).scalar() or 0

    # ── Generate recommendations ─────────────────────────────────────────────
    recommendations = []

    if volume_change_pct is not None and volume_change_pct >= 30:
        recommendations.append({
            "type": "anomaly",
            "severity": "high",
            "message": f"Ticket volume increased {volume_change_pct}% vs last week ({this_week} vs {last_week}). Investigate root cause.",
        })

    top_category = category_counts[0] if category_counts else None
    if top_category and top_category[1] >= 3:
        recommendations.append({
            "type": "pattern",
            "severity": "medium",
            "message": f"'{top_category[0].value if top_category[0] else 'Unknown'}' is the top issue this week ({top_category[1]} tickets). Consider proactive communication or process fix.",
        })

    if critical_this_week >= 3:
        recommendations.append({
            "type": "alert",
            "severity": "high",
            "message": f"{critical_this_week} critical tickets this week. Review service delivery quality immediately.",
        })

    if high_churn_open >= 2:
        recommendations.append({
            "type": "retention",
            "severity": "high",
            "message": f"{high_churn_open} high-churn-risk tickets are still open. Immediate outreach recommended to prevent cancellations.",
        })

    if avg_satisfaction is not None and float(avg_satisfaction) < 3.0:
        recommendations.append({
            "type": "quality",
            "severity": "high",
            "message": f"Average customer satisfaction is {round(float(avg_satisfaction), 1)}/5 this week. Review AI response quality and escalation handling.",
        })

    if avg_agent_score is not None and avg_satisfaction is not None:
        gap = float(avg_agent_score) - float(avg_satisfaction)
        if gap > 1.5:
            recommendations.append({
                "type": "calibration",
                "severity": "medium",
                "message": f"Agent self-score ({round(float(avg_agent_score),1)}) is significantly higher than customer satisfaction ({round(float(avg_satisfaction),1)}). Agent is overconfident — review resolution logic.",
            })

    if recurring:
        names = [f"{r[0]} ({r[2]}x {r[1].value if r[1] else '?'})" for r in recurring[:3]]
        recommendations.append({
            "type": "pattern",
            "severity": "medium",
            "message": f"Recurring issues detected this week: {', '.join(names)}. These customers need direct follow-up.",
        })

    if failed_this_week >= 2:
        recommendations.append({
            "type": "system",
            "severity": "high",
            "message": f"{failed_this_week} tickets failed to process this week. Check agent logs and API health.",
        })

    if not recommendations:
        recommendations.append({
            "type": "status",
            "severity": "low",
            "message": "No anomalies detected this week. System is operating normally.",
        })

    return {
        "generated_at": now.isoformat(),
        "period": "last_7_days",
        "summary": {
            "tickets_this_week": this_week,
            "tickets_last_week": last_week,
            "volume_change_pct": volume_change_pct,
            "critical_tickets": critical_this_week,
            "high_churn_open": high_churn_open,
            "failed_tickets": failed_this_week,
            "avg_agent_self_score": round(float(avg_agent_score), 2) if avg_agent_score else None,
            "avg_customer_satisfaction": round(float(avg_satisfaction), 2) if avg_satisfaction else None,
        },
        "top_categories": [
            {"category": cat.value if cat else "unknown", "count": cnt}
            for cat, cnt in category_counts[:5]
        ],
        "recurring_issues": [
            {"customer_email": r[0], "category": r[1].value if r[1] else "?", "count": r[2]}
            for r in recurring
        ],
        "recommendations": sorted(
            recommendations,
            key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x["severity"], 3),
        ),
    }
