import secrets
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone

from .models.OTP import EmailOTP

import csv
import io
import bleach

import re
from rest_framework.exceptions import ValidationError as DRFValidationError

PASSWORD_MAX_AGE_DAYS = 60
ALLOWED_CSV_MIME_TYPES = {
    "text/csv",
    "application/csv",
}

ANGLE_RE = re.compile(r"[<>]")
EMOJI_FALLBACK_RE = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")

def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"

def create_and_send_otp(email: str, ttl_minutes: int = 5, purpose: str = EmailOTP.Purpose.LOGIN, role: str = EmailOTP.Role.STUDENT) -> EmailOTP:
    otp = generate_otp()
    now = timezone.now()

    pending_token = secrets.token_urlsafe(32)

    record = EmailOTP.objects.create(
        email=email,
        otp=otp,
        purpose=purpose,
        role=role,
        expires_at=now + timedelta(minutes=ttl_minutes),
        pending_token=pending_token
    )

    app_name = getattr(settings, "APP_NAME", "University of Pangasinan Student Feedback and Module Evaluation System")
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", getattr(settings, "EMAIL_HOST_USER", None))

    # Subject kept short to avoid spam filters
    subject = f"Verification Code"

    # Plain-text fallback
    text_body = (
        f"{app_name} Verification Code\n\n"
        f"Your one-time code is: {otp}\n"
        f"Expires in {ttl_minutes} minutes.\n\n"
        "If you did not request this code, you can ignore this email.\n"
        "Do not share this code with anyone.\n"
    )

    # Minimal HTML (no external assets)
    html_body = f"""
    <div style="font-family: Arial, sans-serif; line-height: 1.5; color: #0f172a;">
      <h2 style="margin: 0 0 12px;">{app_name} Verification Code</h2>
      <p style="margin: 0 0 12px;">Use the code below to continue signing in:</p>
      <div style="
          display: inline-block;
          padding: 12px 16px;
          font-size: 22px;
          letter-spacing: 4px;
          font-weight: 700;
          background: #f1f5f9;
          border: 1px solid #e2e8f0;
          border-radius: 10px;
      ">{otp}</div>
      <p style="margin: 12px 0 0;">This code expires in <b>{ttl_minutes} minutes</b>.</p>
      <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 16px 0;" />
      <p style="margin: 0; font-size: 12px; color: #475569;">
        If you didn’t request this, you can ignore this email. Do not share this code with anyone.
      </p>
    </div>
    """

    msg = EmailMultiAlternatives(subject=subject, body=text_body, from_email=from_email, to=[email])
    msg.attach_alternative(html_body, "text/html")
    msg.send(fail_silently=False)

    return record

def is_password_expired(user) -> bool:
    """
    Returns True if user's password is older than PASSWORD_MAX_AGE_DAYS.
    If password_changed_at is missing/null, treat as expired (forces change).
    """
    changed_at = getattr(user, "password_changed_at", None)
    if not changed_at:
        return True
    return timezone.now() - changed_at > timedelta(days=PASSWORD_MAX_AGE_DAYS)

def validate_uploaded_csv(file_obj, *, max_bytes: int, required_columns: set[str]) -> tuple[str, csv.DictReader]:
    """
    Returns (decoded_text, csv_reader) if valid, raises DRF ValidationError otherwise.
    """
    from rest_framework.exceptions import ValidationError as DRFValidationError

    if not file_obj:
        raise DRFValidationError("No file provided.")

    # size
    if getattr(file_obj, "size", None) is not None and file_obj.size > max_bytes:
        raise DRFValidationError(f"File too large. Max is {max_bytes} bytes.")

    # extension
    name = getattr(file_obj, "name", "") or ""
    if not name.lower().endswith(".csv"):
        raise DRFValidationError("File must be a .csv")

    # content-type (best effort)
    ctype = getattr(file_obj, "content_type", "") or ""
    if ctype and ctype not in ALLOWED_CSV_MIME_TYPES:
        raise DRFValidationError(f"Invalid content type: {ctype}. Only CSV is allowed.")

    # decode
    try:
        raw = file_obj.read()
        text = raw.decode("utf-8-sig")  # handles BOM
    except Exception:
        raise DRFValidationError("CSV must be UTF-8 encoded.")

    # parse header
    reader = csv.DictReader(io.StringIO(text))
    cols = set([c.strip() for c in (reader.fieldnames or []) if c])
    missing = sorted(required_columns - cols)
    if missing:
        raise DRFValidationError({
            "detail": f"Missing required columns: {', '.join(missing)}. Found columns: {', '.join(sorted(cols))}",
            "missing": missing,
            "found": sorted(cols)
        })

    return text, reader

def sanitize_text(value: str) -> str:
    if value is None:
        return value
    value = str(value)
    return bleach.clean(value, tags=[], attributes={}, strip=True)

def validate_plain_text(value: str, *, field_name: str = "value") -> str:
    if value is None:
        return value

    value = sanitize_text(value)

    if ANGLE_RE.search(value):
        raise DRFValidationError({field_name: 'Must not contain "<" or ">".'})

    if EMOJI_FALLBACK_RE.search(value):
        raise DRFValidationError({field_name: "Emojis are not allowed."})

    return value