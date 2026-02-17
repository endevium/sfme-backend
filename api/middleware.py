import re
import logging
from django.http import HttpResponseForbidden
from django.conf import settings

logger = logging.getLogger(__name__)

class SQLInjectionProtectionMiddleware:
    """
    Middleware to detect and prevent SQL injection attempts
    """

    def __init__(self, get_response):
        self.get_response = get_response
        # Common SQL injection patterns
        self.sql_patterns = [
            r';\s*(select|insert|update|delete|drop|create|alter)\s',
            r'union\s+select',
            r'--\s*$',
            r'/\*.*\*/',
            r';\s*$',
            r'xp_cmdshell',
            r'exec\s*\(',
            r'cast\s*\(',
            r'convert\s*\(',
            r'information_schema',
            r'sysobjects',
            r'systables',
        ]

    def __call__(self, request):
        # Check GET parameters
        for key, values in request.GET.lists():
            for value in values:
                if self._contains_sql_injection(value):
                    logger.warning(f"SQL injection attempt detected in GET parameter {key}: {value} from IP {self._get_client_ip(request)}")
                    return HttpResponseForbidden("Invalid request")

        # Check POST data
        if request.method == 'POST':
            for key, values in request.POST.lists():
                for value in values:
                    if self._contains_sql_injection(value):
                        logger.warning(f"SQL injection attempt detected in POST parameter {key}: {value} from IP {self._get_client_ip(request)}")
                        return HttpResponseForbidden("Invalid request")

        # Check JSON data for API requests
        if hasattr(request, 'body') and request.body:
            try:
                import json
                body_data = json.loads(request.body.decode('utf-8'))
                if self._check_json_for_sql_injection(body_data):
                    logger.warning(f"SQL injection attempt detected in JSON body from IP {self._get_client_ip(request)}")
                    return HttpResponseForbidden("Invalid request")
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass  # Not JSON, continue

        response = self.get_response(request)
        return response

    def _contains_sql_injection(self, value):
        """Check if a string contains SQL injection patterns"""
        if not isinstance(value, str):
            return False

        value_lower = value.lower()
        for pattern in self.sql_patterns:
            if re.search(pattern, value_lower, re.IGNORECASE):
                return True
        return False

    def _check_json_for_sql_injection(self, data):
        """Recursively check JSON data for SQL injection patterns"""
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, str) and self._contains_sql_injection(value):
                    return True
                elif isinstance(value, (dict, list)):
                    if self._check_json_for_sql_injection(value):
                        return True
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, str) and self._contains_sql_injection(item):
                    return True
                elif isinstance(item, (dict, list)):
                    if self._check_json_for_sql_injection(item):
                        return True
        return False

    def _get_client_ip(self, request):
        """Get the client IP address"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip