import logging
import requests
from django.conf import settings
from rest_framework.exceptions import ValidationError

logger = logging.getLogger(__name__)

def verify_recaptcha_v2(*, token: str | None, remote_ip: str | None = None) -> None:
    """
    Validates reCAPTCHA v2 (including Invisible).
    Frontend sends token as: 'g-recaptcha-response' (we accept it as recaptcha_token).
    """
    secret = getattr(settings, "RECAPTCHA_SECRET_KEY", "") or ""
    if not secret:
        return

    if not token or not isinstance(token, str):
        raise ValidationError({"recaptcha_token": "reCAPTCHA is required."})

    payload = {"secret": secret, "response": token}
    if remote_ip:
        payload["remoteip"] = remote_ip

    try:
        r = requests.post("https://www.google.com/recaptcha/api/siteverify", data=payload, timeout=5)
        r.raise_for_status()
        data = r.json()
    except Exception:
        raise ValidationError({"recaptcha_token": "reCAPTCHA verification failed. Please try again."})

    logger.warning("reCAPTCHA verify response: %s", data)

    if not data.get("success"):
        raise ValidationError({"recaptcha_token": "reCAPTCHA verification failed."})