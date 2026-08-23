"""Small SMTP email helper for scheduled digests."""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage


class EmailDeliveryError(RuntimeError):
    """Safe SMTP failure classification without retaining message content."""

    def __init__(self, stage: str, *, delivery_unknown: bool = False):
        super().__init__(f"SMTP failed during {stage}")
        self.stage = stage
        self.delivery_unknown = delivery_unknown


def smtp_configured() -> bool:
    host = os.environ.get("SMTP_HOST", "").strip()
    username = (os.environ.get("SMTP_USER") or os.environ.get("SMTP_USERNAME") or "").strip()
    password = os.environ.get("SMTP_PASS") or os.environ.get("SMTP_PASSWORD") or ""
    sender = (os.environ.get("SMTP_FROM") or os.environ.get("SMTP_FROM_EMAIL") or "").strip()
    try:
        port = int(os.environ.get("SMTP_PORT", "587") or "587")
    except ValueError:
        return False
    return bool(host and username and password and sender and 1 <= port <= 65535)


def email_configured() -> bool:
    return smtp_configured()


def email_provider() -> str:
    if smtp_configured():
        return "smtp"
    return "none"


def send_email(
    to_email: str,
    subject: str,
    text_body: str,
    html_body: str,
    list_unsubscribe_url: str | None = None,
) -> None:
    host = os.environ.get("SMTP_HOST", "").strip()
    username = (os.environ.get("SMTP_USER") or os.environ.get("SMTP_USERNAME") or "").strip()
    password = os.environ.get("SMTP_PASS") or os.environ.get("SMTP_PASSWORD") or ""
    from_header = (os.environ.get("SMTP_FROM") or "").strip()
    from_email = (os.environ.get("SMTP_FROM_EMAIL") or "").strip()
    from_name = os.environ.get("SMTP_FROM_NAME", "Job Hunter SG").strip() or "Job Hunter SG"
    reply_to = (os.environ.get("SMTP_REPLY_TO") or "").strip()
    port = int(os.environ.get("SMTP_PORT", "587") or "587")
    use_ssl = os.environ.get("SMTP_USE_SSL", "").lower() in {"1", "true", "yes"}
    use_tls = os.environ.get("SMTP_USE_TLS", "true").lower() not in {"0", "false", "no"}

    if not smtp_configured():
        raise RuntimeError("SMTP is not configured")

    message = EmailMessage()
    message["From"] = from_header or f"{from_name} <{from_email}>"
    message["To"] = to_email
    message["Subject"] = subject
    if reply_to:
        message["Reply-To"] = reply_to
    if list_unsubscribe_url:
        message["List-Unsubscribe"] = f"<{list_unsubscribe_url}>"
        message["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    smtp_cls = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
    try:
        smtp = smtp_cls(host, port, timeout=30)
    except Exception as exc:
        raise EmailDeliveryError("connect") from exc
    try:
        try:
            if use_tls and not use_ssl:
                smtp.starttls()
            smtp.login(username, password)
        except Exception as exc:
            raise EmailDeliveryError("authentication") from exc
        try:
            smtp.send_message(message)
        except Exception as exc:
            # An exception while awaiting the DATA response cannot establish
            # whether the server accepted the message.
            raise EmailDeliveryError("data_response", delivery_unknown=True) from exc
    except EmailDeliveryError:
        smtp.close()
        raise
    else:
        try:
            smtp.quit()
        except Exception:
            smtp.close()
