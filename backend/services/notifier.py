"""
Slack notification service — includes VIP/churn context in alerts.
"""
import logging
import time
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
CHURN_EMOJI = {"low": "🟢", "medium": "🟡", "high": "🔴"}


async def send_slack_alert(
    urgency: str,
    customer_name: str,
    summary: str,
    reason: str,
    ticket_id: str,
    ticket_url: Optional[str] = None,
    is_vip: bool = False,
    churn_risk: str = "low",
) -> None:
    if not settings.slack_webhook_url:
        logger.warning("SLACK_WEBHOOK_URL not configured — skipping")
        return

    color = URGENCY_COLORS.get(urgency, "#cccccc")
    emoji = URGENCY_EMOJI.get(urgency, ":bell:")
    churn_icon = CHURN_EMOJI.get(churn_risk, "⚪")
    vip_badge = " ⭐ VIP" if is_vip else ""
    dashboard_link = ticket_url or f"http://localhost:8501/?ticket={ticket_id}"

    header = f"{emoji} *Support Escalation — {urgency.upper()}{vip_badge}*"
    if is_vip or churn_risk == "high":
        header += "\n:fire: *HIGH PRIORITY — VIP or churn risk customer*"

    payload = {
        "text": header,
        "attachments": [
            {
                "color": color,
                "fields": [
                    {"title": "Customer", "value": f"{customer_name}{vip_badge}", "short": True},
                    {"title": "Urgency", "value": urgency.upper(), "short": True},
                    {"title": "Churn Risk", "value": f"{churn_icon} {churn_risk.upper()}", "short": True},
                    {"title": "VIP", "value": "Yes ⭐" if is_vip else "No", "short": True},
                    {"title": "Issue Summary", "value": summary, "short": False},
                    {"title": "Escalation Reason", "value": reason, "short": False},
                    {"title": "Ticket ID", "value": ticket_id, "short": True},
                    {"title": "Dashboard", "value": f"<{dashboard_link}|View Ticket>", "short": True},
                ],
                "footer": "AI Operations Brain",
                "ts": time.time(),
            }
        ],
    }

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(settings.slack_webhook_url, json=payload)
        response.raise_for_status()
        logger.info("Slack alert sent for ticket %s", ticket_id)
