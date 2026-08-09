import logging
import os
from datetime import datetime

import httpx
import resend


logger = logging.getLogger(__name__)

DEFAULT_EMAIL_PROVIDER = "resend"
DEFAULT_EMAIL_FROM = "Urjaa Ornaments <onboarding@resend.dev>"


def _is_truthy(raw: str | None, *, default: bool) -> bool:
    if raw is None:
        return default

    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


class EmailService:
    @staticmethod
    def _is_enabled() -> bool:
        return _is_truthy(os.getenv("EMAIL_ENABLED"), default=True)

    @staticmethod
    def _provider() -> str:
        return (os.getenv("EMAIL_PROVIDER") or DEFAULT_EMAIL_PROVIDER).strip().lower()

    @staticmethod
    def _from_address() -> str:
        return (os.getenv("EMAIL_FROM") or DEFAULT_EMAIL_FROM).strip() or DEFAULT_EMAIL_FROM

    @staticmethod
    def _from_components() -> tuple[str | None, str]:
        raw = EmailService._from_address()
        if "<" in raw and ">" in raw:
            display_name, email_part = raw.split("<", 1)
            sender_email = email_part.split(">", 1)[0].strip()
            sender_name = display_name.strip().strip('"') or None
            if sender_email:
                return sender_name, sender_email
        return None, raw

    @staticmethod
    def _reply_to() -> str | None:
        reply_to = (os.getenv("EMAIL_REPLY_TO") or "").strip()
        return reply_to or None

    @staticmethod
    def send_email(
        *,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str,
    ) -> bool:
        if not EmailService._is_enabled():
            logger.info("Email dispatch skipped because EMAIL_ENABLED is false")
            return False

        provider = EmailService._provider()
        if provider == "resend":
            return EmailService._send_via_resend(
                to_email=to_email,
                subject=subject,
                html_body=html_body,
                text_body=text_body,
            )

        if provider == "sendgrid":
            return EmailService._send_via_sendgrid(
                to_email=to_email,
                subject=subject,
                html_body=html_body,
                text_body=text_body,
            )

        logger.warning("Email dispatch skipped due to unsupported provider", extra={"provider": provider})
        return False

    @staticmethod
    def _send_via_resend(
        *,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str,
    ) -> bool:
        api_key = (os.getenv("RESEND_API_KEY") or "").strip()
        if not api_key:
            logger.warning("Email dispatch skipped because RESEND_API_KEY is not configured")
            return False

        payload = {
            "from": EmailService._from_address(),
            "to": [to_email],
            "subject": subject,
            "html": html_body,
            "text": text_body,
        }

        reply_to = EmailService._reply_to()
        if reply_to:
            payload["reply_to"] = reply_to

        try:
            resend.api_key = api_key
            response = resend.Emails.send(payload)
            # H-6 FIX: Removed print() debug statements; use structured logger instead.
            logger.info("email_resend status=sent response=%s", response)
        except Exception as exc:
            logger.exception("Email dispatch via Resend failed")
            # H-6 FIX: Removed print() debug statements that leaked error details to stdout.
            logger.error("email_resend status=failed error=%s", str(exc))
            return False

        return True

    @staticmethod
    def _send_via_sendgrid(
        *,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str,
    ) -> bool:
        api_key = (os.getenv("SENDGRID_API_KEY") or "").strip()
        if not api_key:
            logger.warning("Email dispatch skipped because SENDGRID_API_KEY is not configured")
            return False

        sender_name, sender_email = EmailService._from_components()
        reply_to = EmailService._reply_to()

        payload = {
            "personalizations": [
                {
                    "to": [{"email": to_email}],
                    "subject": subject,
                }
            ],
            "from": {"email": sender_email},
            "content": [
                {"type": "text/plain", "value": text_body},
                {"type": "text/html", "value": html_body},
            ],
        }

        if sender_name:
            payload["from"]["name"] = sender_name

        if reply_to:
            payload["reply_to"] = {"email": reply_to}

        try:
            response = httpx.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=15,
            )
        except Exception:
            logger.exception("Email dispatch via SendGrid failed")
            return False

        if response.status_code >= 300:
            logger.error(
                "Email dispatch via SendGrid was rejected",
                extra={
                    "status_code": response.status_code,
                    "response_body": response.text[:500],
                },
            )
            return False

        return True

    @staticmethod
    def send_password_reset_email(
        *,
        to_email: str,
        full_name: str,
        reset_link: str,
        expires_in_minutes: int = 15,
    ) -> bool:
        display_name = full_name.strip() or "there"
        subject = "Reset your Urjaa account password"
        safe_expiry_minutes = max(1, expires_in_minutes)
        text_body = (
            f"Hello {display_name},\n\n"
            "We received a request to reset your Urjaa account password.\n"
            f"Use the link below to reset your password:\n{reset_link}\n\n"
            f"This link expires in {safe_expiry_minutes} minutes.\n\n"
            "If you did not request this, you can ignore this email."
        )
        html_body = (
            f"<p>Hello {display_name},</p>"
            "<p>We received a request to reset your Urjaa account password.</p>"
            f"<p><a href=\"{reset_link}\">Reset Password</a></p>"
            f"<p>This link expires in {safe_expiry_minutes} minutes.</p>"
            "<p>If you did not request this, you can safely ignore this email.</p>"
        )
        return EmailService.send_email(
            to_email=to_email,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
        )

    @staticmethod
    def send_welcome_email(*, to_email: str, full_name: str) -> bool:
        if not _is_truthy(os.getenv("SEND_WELCOME_EMAIL"), default=False):
            return False

        display_name = full_name.strip() or "there"
        subject = "Welcome to Urjaa"
        text_body = (
            f"Hello {display_name},\n\n"
            "Welcome to Urjaa Ornaments. Your account is ready and you can now manage "
            "orders, addresses, and account settings.\n\n"
            f"Sent on {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC."
        )
        html_body = (
            f"<p>Hello {display_name},</p>"
            "<p>Welcome to Urjaa Ornaments. Your account is ready and you can now manage "
            "orders, addresses, and account settings.</p>"
            f"<p>Sent on {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC.</p>"
        )
        return EmailService.send_email(
            to_email=to_email,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
        )

    @staticmethod
    def send_rating_request_email(
        to_email: str,
        user_name: str,
        product_names: list,
        rating_url: str,
    ) -> bool:
        # TODO: implement email template for rating requests
        logger.info("send_rating_request_email: stub called for %s", to_email)
        return True

    @staticmethod
    def send_review_request_email(
        to_email: str,
        user_name: str,
        product_name: str,
        review_url: str,
    ) -> bool:
        # TODO: implement email template for review requests
        logger.info("send_review_request_email: stub called for %s", to_email)
        return True
