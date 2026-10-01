import logging
import smtplib
import ssl
from email.message import EmailMessage

import httpx

from app.core.config import (
    ALERT_EMAIL_TO,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USER,
    SLACK_WEBHOOK_URL,
)
from app.models.ops import Alert

log = logging.getLogger("alerting")


def notify(alert: Alert) -> None:
    """Deliver an alert. Falls back to logging when no notifier is configured."""
    text = (
        f"[{alert.type}] sku={alert.sku_id} "
        f"before={alert.before} after={alert.after} {alert.currency} "
        f":: {alert.message}"
    )

    if SLACK_WEBHOOK_URL:
        try:
            httpx.post(SLACK_WEBHOOK_URL, json={"text": text}, timeout=5)
            alert.status = "sent"
            alert.notify_target = "slack"
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("slack notify failed: %s", exc)
            alert.status = "failed"
            return

    if ALERT_EMAIL_TO and SMTP_HOST:
        try:
            _send_email(text)
            alert.status = "sent"
            alert.notify_target = f"email:{ALERT_EMAIL_TO}"
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("email notify failed: %s", exc)
            alert.status = "failed"
            return

    # No notifier configured: keep pending and log for the operator.
    log.info("alert recorded (no notifier configured): %s", text)
    alert.status = "pending"


def _send_email(body: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = "Price Monitor Alert"
    msg["From"] = SMTP_USER or "price-monitor@local"
    msg["To"] = ALERT_EMAIL_TO
    msg.set_content(body)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
        if SMTP_USER and SMTP_PASSWORD:
            server.starttls(context=ssl.create_default_context())
            server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)
