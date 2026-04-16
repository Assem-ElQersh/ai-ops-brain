"""
Slack notification service using Incoming Webhooks.
"""
import logging
from typing import Optional

import httpx

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

URGENCY_COLORS = {
    "low": "#36a64f",
    "medium": "#ffcc00",
    "high": "#ff8800",
    "critical": "#ff0000",
}

URGENCY_EMOJI = {
    "low": ":information_source:",
    "medium": ":warning:",
    "high": ":rotating_light:",
    "critical": ":sos:",
}


async def send_slack_alert(
    urgency: str,
    customer_name: str,
    summary: str,
    reason: str,
    ticket_id: str,
    ticket_url: Optional[str] = None,
) -> None:
    if not settings.slack_webhook_url:
        logger.warning("SLACK_WEBHOOK_URL not configured — skipping Slack alert")
        return

    color = URGENCY_COLORS.get(urgency, "#cccccc")
    emoji = URGENCY_EMOJI.get(urgency, ":bell:")
    dashboard_link = ticket_url or f"http://localhost:8501/?ticket={ticket_id}"

    payload = {
        "text": f"{emoji} *Support Escalation — {urgency.upper()}*",
        "attachments": [
            {
                "color": color,
                "fields": [
                    {"title": "Customer", "value": customer_name, "short": True},
                    {"title": "Urgency", "value": urgency.upper(), "short": True},
                    {"title": "Issue Summary", "value": summary, "short": False},
                    {"title": "Escalation Reason", "value": reason, "short": False},
                    {"title": "Ticket ID", "value": ticket_id, "short": True},
                    {"title": "Dashboard", "value": f"<{dashboard_link}|View Ticket>", "short": True},
                ],
                "footer": "AI Operations Brain",
                "ts": __import__("time").time(),
            }
        ],
    }

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(settings.slack_webhook_url, json=payload)
        response.raise_for_status()
        logger.info("Slack alert sent for ticket %s (urgency=%s)", ticket_id, urgency)
