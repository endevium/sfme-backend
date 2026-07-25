from rest_framework.views import exception_handler as drf_exception_handler
from rest_framework.response import Response


def _extract_error_message(payload):
    if isinstance(payload, str):
        return payload
    if isinstance(payload, list):
        for item in payload:
            msg = _extract_error_message(item)
            if msg:
                return msg
        return None
    if isinstance(payload, dict):
        for value in payload.values():
            msg = _extract_error_message(value)
            if msg:
                return msg
    return None

def api_exception_handler(exc, context):
    resp = drf_exception_handler(exc, context)
    if resp is None:
        return None

    if isinstance(resp.data, dict) and "detail" in resp.data:
        return resp

    return Response(
        {"detail": _extract_error_message(resp.data) or "Validation error", "errors": resp.data},
        status=resp.status_code
    )