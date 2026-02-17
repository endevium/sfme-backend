from types import SimpleNamespace
from rest_framework import authentication, exceptions
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import TokenError
from .models import Student, Faculty, DepartmentHead
import re
import logging

logger = logging.getLogger(__name__)

class LegacyJWTAuthentication(authentication.BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request):
        auth = authentication.get_authorization_header(request).split()
        token_str = None

        if auth and auth[0].lower() == self.keyword.lower().encode():
            candidate = b" ".join(auth[1:]).decode(errors="ignore").strip()
            m = re.search(r'([A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)', candidate)
            token_str = m.group(1) if m else candidate
        else:
            raw = (
                request.META.get("HTTP_X_ACCESS_TOKEN")
                or request.META.get("HTTP_X_AUTHORIZATION")
                or request.META.get("HTTP_AUTHORIZATION")
                or request.META.get("Authorization")
                or request.GET.get("access_token")
                or request.GET.get("token")
            )
            if not raw:
                return None
            raw = raw.strip()
            if raw.lower().startswith("bearer "):
                raw = raw[7:].strip()
            m = re.search(r'([A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)', raw)
            token_str = m.group(1) if m else raw

        logger.debug("LegacyJWTAuthentication: token_str=%r", token_str)

        try:
            token = AccessToken(token_str)
        except Exception as exc:
            logger.debug("token decode error: %s", exc)
            raise exceptions.AuthenticationFailed("Invalid or expired token.")

        role = token.get("role")
        legacy_user_id = token.get("legacy_user_id")
        if not role or legacy_user_id is None:
            raise exceptions.AuthenticationFailed("Invalid token payload.")

        instance = None
        if role == "student":
            instance = Student.objects.filter(pk=legacy_user_id).first()
        elif role == "faculty":
            instance = Faculty.objects.filter(pk=legacy_user_id).first()
        elif role == "department_head":
            instance = DepartmentHead.objects.filter(pk=legacy_user_id).first()

        user = SimpleNamespace(is_authenticated=True, role=role, legacy_user_id=legacy_user_id, instance=instance)
        user = SimpleNamespace(
            pk=legacy_user_id,
            id=legacy_user_id,
            is_authenticated=True,
            role=role,
            legacy_user_id=legacy_user_id,
            instance=instance,
        )
        return (user, token)

    def authenticate_header(self, request):
        return self.keyword