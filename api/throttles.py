from rest_framework.throttling import SimpleRateThrottle

class LoginRateThrottle(SimpleRateThrottle):
    scope = "login"

    def get_cache_key(self, request, view):
        """
        Make login throttling effective even when client IP detection is unreliable
        (dev server, proxies, CORS, etc).

        Priority:
        - email (login/send-otp) -> throttles per account identity
        - pending_token (verify-otp) -> throttles per pending login/session
        - IP ident fallback
        """
        data = getattr(request, "data", {}) or {}

        raw_email = data.get("email")
        if isinstance(raw_email, str) and raw_email.strip():
            ident = f"email:{raw_email.strip().lower()}"
            return self.cache_format % {"scope": self.scope, "ident": ident}

        raw_pending = data.get("pending_token")
        if isinstance(raw_pending, str) and raw_pending.strip():
            ident = f"pending:{raw_pending.strip()}"
            return self.cache_format % {"scope": self.scope, "ident": ident}

        ident = self.get_ident(request)
        if not ident:
            return None
        ident = f"ip:{ident}"
        return self.cache_format % {"scope": self.scope, "ident": ident}


class AIRequestRateThrottle(SimpleRateThrottle):
    scope = "ai_requests"

    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        if not ident:
            return None
        return self.cache_format % {"scope": self.scope, "ident": ident}