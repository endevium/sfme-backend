import secrets
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone

from .models.OTP import EmailOTP

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