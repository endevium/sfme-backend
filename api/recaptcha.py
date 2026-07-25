import os
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
    enforce_in_debug = bool(getattr(settings, "RECAPTCHA_ENFORCE_IN_DEBUG", False))
    if (settings.DEBUG and not enforce_in_debug) or os.getenv("DISABLE_RECAPTCHA") == "1":
        logger.debug(
            "recaptcha check bypassed (DEBUG=%s, RECAPTCHA_ENFORCE_IN_DEBUG=%s, DISABLE_RECAPTCHA=%s)",
            settings.DEBUG,
            enforce_in_debug,
            os.getenv("DISABLE_RECAPTCHA"),
        )
        return
    
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

    logger.info("reCAPTCHA verify response: %s", data)

    if not data.get("success"):
        error_codes = data.get("error-codes") or []
        logger.warning("reCAPTCHA verification failed with error-codes=%s", error_codes)
        raise ValidationError(
            {
                "recaptcha_token": "reCAPTCHA verification failed.",
                "recaptcha_error_codes": error_codes,
            }
        )