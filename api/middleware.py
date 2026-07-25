import re
import logging
from urllib.parse import unquote
from django.http import HttpResponseForbidden

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
        self.path_traversal_pattern = re.compile(
            r'\.\.(?:/|\\|%2f|%5c|%u2216|%c0%af|%255c|%252f)',
            re.IGNORECASE,
        )

    def __call__(self, request):
        # Check raw path and full URL path for traversal payloads.
        for target in (request.path or '', request.get_full_path() or ''):
            if self._contains_path_traversal(target):
                logger.warning(
                    f"Path traversal attempt detected in URL path: {target} from IP {self._get_client_ip(request)}"
                )
                return HttpResponseForbidden("Invalid request")

        # Check GET parameters
        for key, values in request.GET.lists():
            for value in values:
                if self._contains_sql_injection(value):
                    logger.warning(f"SQL injection attempt detected in GET parameter {key}: {value} from IP {self._get_client_ip(request)}")
                    return HttpResponseForbidden("Invalid request")
                if self._contains_path_traversal(value):
                    logger.warning(
                        f"Path traversal attempt detected in GET parameter {key}: {value} from IP {self._get_client_ip(request)}"
                    )
                    return HttpResponseForbidden("Invalid request")

        # Check POST data
        if request.method == 'POST':
            for key, values in request.POST.lists():
                for value in values:
                    if self._contains_sql_injection(value):
                        logger.warning(f"SQL injection attempt detected in POST parameter {key}: {value} from IP {self._get_client_ip(request)}")
                        return HttpResponseForbidden("Invalid request")
                    if self._contains_path_traversal(value):
                        logger.warning(
                            f"Path traversal attempt detected in POST parameter {key}: {value} from IP {self._get_client_ip(request)}"
                        )
                        return HttpResponseForbidden("Invalid request")

        # Check JSON data for API requests. Avoid accessing request.body for
        # multipart/form-data (file uploads) because accessing `request.body`
        # after `request.POST` / `request.FILES` has been evaluated raises
        # RawPostDataException. Only inspect the body when the content type
        # indicates JSON-like payloads.
        content_type = (request.META.get('CONTENT_TYPE') or request.content_type or '').lower()
        if content_type.startswith('application/json'):
            try:
                import json
                # Accessing request.body is safe here because the parser hasn't
                # consumed the stream for JSON requests.
                body = request.body
                if body:
                    body_data = json.loads(body.decode('utf-8'))
                    if self._check_json_for_sql_injection(body_data):
                        logger.warning(f"SQL injection attempt detected in JSON body from IP {self._get_client_ip(request)}")
                        return HttpResponseForbidden("Invalid request")
                    if self._check_json_for_path_traversal(body_data):
                        logger.warning(f"Path traversal attempt detected in JSON body from IP {self._get_client_ip(request)}")
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

    def _contains_path_traversal(self, value):
        """Check whether a string contains path traversal payloads."""
        if not isinstance(value, str):
            return False

        # Inspect original and repeatedly URL-decoded values to catch
        # encoded/double-encoded traversal payloads.
        candidates = [value]
        decoded = value
        for _ in range(3):
            next_decoded = unquote(decoded)
            if next_decoded == decoded:
                break
            candidates.append(next_decoded)
            decoded = next_decoded

        for candidate in candidates:
            lowered = candidate.lower()
            normalized = lowered.replace('\\', '/')

            if self.path_traversal_pattern.search(lowered):
                return True

            if normalized.startswith('../') or '/..' in normalized or normalized == '..':
                return True

        return False

    def _check_json_for_path_traversal(self, data):
        """Recursively check JSON data for path traversal payloads."""
        if isinstance(data, dict):
            for _key, value in data.items():
                if isinstance(value, str) and self._contains_path_traversal(value):
                    return True
                if isinstance(value, (dict, list)) and self._check_json_for_path_traversal(value):
                    return True
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, str) and self._contains_path_traversal(item):
                    return True
                if isinstance(item, (dict, list)) and self._check_json_for_path_traversal(item):
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