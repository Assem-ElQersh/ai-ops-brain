"""
Async email service using aiosmtplib (SMTP with STARTTLS).
"""
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


async def send_email(
    to_email: str,
    to_name: str,
    subject: str,
    body: str,
) -> None:
    if not settings.smtp_user or not settings.smtp_password:
        logger.warning("SMTP credentials not configured — skipping email send")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Support Team <{settings.smtp_user}>"
    msg["To"] = f"{to_name} <{to_email}>"

    plain_part = MIMEText(body, "plain", "utf-8")
    html_body = body.replace("\n", "<br>")
    html_part = MIMEText(
        f"""
        <html><body style="font-family: Arial, sans-serif; color: #333; line-height:1.6">
          <p>{html_body}</p>
          <hr style="border:none;border-top:1px solid #eee;margin-top:24px"/>
          <p style="font-size:12px;color:#888">
            This is an automated response from our AI support system.
            A human agent may follow up if further assistance is needed.
          </p>
        </body></html>
        """,
        "html",
        "utf-8",
    )
    msg.attach(plain_part)
    msg.attach(html_part)

    await aiosmtplib.send(
        msg,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user,
        password=settings.smtp_password,
        start_tls=True,
    )
    logger.info("Email sent to %s (%s)", to_email, subject)
