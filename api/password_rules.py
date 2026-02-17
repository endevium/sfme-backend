import re
from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError

def validate_strong_password(password: str, user=None) -> None:
    """
    Rules:
      - at least 10 chars
      - at least 1 uppercase
      - at least 1 lowercase
      - at least 1 digit
      - at least 1 special char
      - no spaces
      - must not be common (uses Django validators)
    """
    if not password:
        raise serializers.ValidationError("New password is required.")

    if len(password) < 10:
        raise serializers.ValidationError("New password must be at least 10 characters.")

    if " " in password:
        raise serializers.ValidationError("New password must not contain spaces.")

    if not re.search(r"[A-Z]", password):
        raise serializers.ValidationError("New password must contain at least 1 uppercase letter.")

    if not re.search(r"[a-z]", password):
        raise serializers.ValidationError("New password must contain at least 1 lowercase letter.")

    if not re.search(r"\d", password):
        raise serializers.ValidationError("New password must contain at least 1 number.")

    if not re.search(r"[^\w\s]", password):
        raise serializers.ValidationError("New password must contain at least 1 special character (e.g. !@#$).")

    try:
        validate_password(password, user=user)
    except DjangoValidationError as e:
        raise serializers.ValidationError(list(e.messages))