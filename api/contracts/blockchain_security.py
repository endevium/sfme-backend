import os
import re
from typing import Tuple
from api.sentiment_service import analyze_theme

def validate_private_key(key: str) -> bool:
    if not isinstance(key, str):
        return False
    if not key.startswith("0x"):
        return False
    hexpart = key[2:]
    if len(hexpart) != 64:
        return False
    try:
        int(hexpart, 16)
        return True
    except ValueError:
        return False

def require_env_keys():
    owner = os.getenv("WEB3_OWNER_PRIVATE_KEY", "")
    if not validate_private_key(owner):
        raise EnvironmentError("Owner private key not set or invalid")

def moderate_feedback(text: str) -> Tuple[bool, str]:
    if not isinstance(text, str) or not text.strip():
        return False, "empty"

    # Deterministic fast-path checks so explicit harmful content is blocked
    # even if upstream prompt-injection filters are noisy.
    lowered = text.lower()
    if re.search(r"\b(idiot|stupid|dumb|trash|worthless|moron|bitch|asshole)\b", lowered):
        return False, "insult"
    if re.search(r"\b(daddy|mommy|porn|sex|sexy|nude|nsfw|fuck|cum|orgasm|xxx)\b", lowered):
        return False, "sexual content"

    theme = analyze_theme(text)
    if isinstance(theme, str) and "prompt injection detected" in theme.lower():
        return False, "prompt_injection"
    if theme in ("insult", "sexual", "sexual content", "threat", 
        "harassment", "toxic", "prompt_injection"):
        return False, theme
    return True, "ok"

def prepare_feedback_hash(text: str) -> bytes:
    if not isinstance(text, str):
        raise TypeError("Feedback must be a string")
    if len(text) > 1000:
        raise ValueError("Feedback too long")
    from api.contracts.gas_tests import sha256_bytes32
    return sha256_bytes32(text)