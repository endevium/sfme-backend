import re
import os
import threading
import logging
from collections import Counter
from typing import List, Dict, Tuple, Any

try:
    from dotenv import load_dotenv, find_dotenv
    load_dotenv(find_dotenv(), override=False)
except Exception:
    pass

logger = logging.getLogger(__name__)

_prompt_injection_classifier = None
_prompt_injection_lock = threading.Lock()
_prompt_injection_init_attempted = False
_PROMPT_INJECTION_UNAVAILABLE = object()
_PROMPT_INJECTION_MODEL = "ProtectAI/deberta-v3-base-prompt-injection"
_PROMPT_INJECTION_THRESHOLD = float(os.getenv("PROMPT_INJECTION_SCORE_THRESHOLD", "0.50"))
_PROMPT_INJECTION_CACHE_DIR = os.getenv("HF_MODEL_CACHE_DIR")
_PROMPT_INJECTION_LOCAL_FILES_ONLY = os.getenv("PROMPT_INJECTION_LOCAL_FILES_ONLY", "0") == "1"


def _load_prompt_injection_classifier_once():
    """Lazily load ProtectAI classifier once. Returns None if unavailable."""
    global _prompt_injection_classifier, _prompt_injection_init_attempted

    if _prompt_injection_classifier is _PROMPT_INJECTION_UNAVAILABLE:
        return None
    if _prompt_injection_classifier is not None:
        return _prompt_injection_classifier
    if _prompt_injection_init_attempted:
        return None

    with _prompt_injection_lock:
        if _prompt_injection_classifier is _PROMPT_INJECTION_UNAVAILABLE:
            return None
        if _prompt_injection_classifier is not None:
            return _prompt_injection_classifier
        if _prompt_injection_init_attempted:
            return None

        _prompt_injection_init_attempted = True

        try:
            import torch
            from transformers import AutoTokenizer, AutoModelForSequenceClassification, pipeline

            tokenizer = AutoTokenizer.from_pretrained(
                _PROMPT_INJECTION_MODEL,
                cache_dir=_PROMPT_INJECTION_CACHE_DIR,
                local_files_only=_PROMPT_INJECTION_LOCAL_FILES_ONLY,
            )
            model = AutoModelForSequenceClassification.from_pretrained(
                _PROMPT_INJECTION_MODEL,
                cache_dir=_PROMPT_INJECTION_CACHE_DIR,
                local_files_only=_PROMPT_INJECTION_LOCAL_FILES_ONLY,
            )
            _prompt_injection_classifier = pipeline(
                "text-classification",
                model=model,
                tokenizer=tokenizer,
                truncation=True,
                max_length=512,
                device=0 if torch.cuda.is_available() else -1,
            )
            logger.debug("Prompt-injection classifier loaded once: %s", _PROMPT_INJECTION_MODEL)
            return _prompt_injection_classifier
        except Exception:
            logger.exception("Failed to load prompt-injection classifier; continuing with heuristic detection")
            _prompt_injection_classifier = _PROMPT_INJECTION_UNAVAILABLE
            return None


def _is_injection_label(label: str) -> bool:
    """Map model labels to injection/non-injection decision."""
    normalized = str(label).strip().lower()
    if normalized in {"1", "label_1", "injection", "prompt_injection", "malicious", "jailbreak"}:
        return True
    if normalized in {"0", "label_0", "safe", "benign", "not_injection"}:
        return False
    return "inject" in normalized or "jailbreak" in normalized


def _detect_prompt_injection_with_model(text: str) -> Tuple[bool, Dict[str, Any]]:
    """Run model inference; returns (flagged, info)."""
    classifier = _load_prompt_injection_classifier_once()
    if not classifier:
        return False, {"available": False, "reason": "model_unavailable"}

    try:
        prediction = classifier(text)[0]
        label = str(prediction.get("label", ""))
        score = float(prediction.get("score", 0.0))
        flagged = _is_injection_label(label) and score >= _PROMPT_INJECTION_THRESHOLD
        return flagged, {
            "available": True,
            "reason": "model_detection" if flagged else "model_safe",
            "label": label,
            "score": score,
            "threshold": _PROMPT_INJECTION_THRESHOLD,
        }
    except Exception:
        logger.exception("Prompt-injection model inference failed; continuing with heuristic detection")
        return False, {"available": True, "reason": "model_error"}

def sanitize_prompt(text: str) -> Dict[str, Any]:
    """Detect and sanitize prompt-injection using regex heuristics + ProtectAI classifier."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")

    # Model-based detector first to capture non-obvious attacks.
    model_flagged, model_info = _detect_prompt_injection_with_model(text)
    if model_flagged:
        return {
            "safe": False,
            "reason": "prompt_injection_model",
            "cleaned": "[REDACTED_INJECTION]",
            "meta": model_info,
        }

    lowered = text.lower()
    suspicious_patterns = [
        r"ignore (previous|prior) instructions",
        r"disregard (previous|prior) instructions",
        r"ignore all previous",
        r"forget (previous|prior) instructions",
        r"you should always",
        r"you must",
        r"do not follow earlier",
        r"override (system|instructions)",
    ]
    for p in suspicious_patterns:
        if re.search(p, lowered):
            cleaned = re.sub(p, "[REDACTED_INJECTION]", text, flags=re.IGNORECASE)
            return {
                "safe": False,
                "reason": "prompt_injection_pattern",
                "cleaned": cleaned,
                "meta": model_info,
            }

    if re.search(r"(from now on|from now onwards).{0,40}\b(do|always|must|never)\b", lowered):
        cleaned = re.sub(r"(from now on|from now onwards).{0,40}\b(do|always|must|never)\b", "[REDACTED_INJECTION]", text, flags=re.IGNORECASE)
        return {
            "safe": False,
            "reason": "prompt_injection_imperative",
            "cleaned": cleaned,
            "meta": model_info,
        }

    return {"safe": True, "reason": None, "cleaned": text, "meta": model_info}


def detect_poisoned_feedback(feedbacks: List[Dict[str, str]], identical_threshold: float = 0.6, user_rate_threshold: float = 0.6) -> Tuple[bool, Dict[str, Any]]:
    """
    Heuristic detector for training-data-poisoning style feedback.
    feedbacks: list of {'user': str, 'text': str}
    """
    if not feedbacks:
        return False, {"reason": "no_data"}

    texts = [f.get("text", "").strip().lower() for f in feedbacks]
    users = [f.get("user", "").strip().lower() for f in feedbacks]

    text_counts = Counter(texts)
    most_common_text, most_common_count = text_counts.most_common(1)[0]

    user_counts = Counter(users)
    most_common_user, most_common_user_count = user_counts.most_common(1)[0]

    n = len(feedbacks)
    info = {
        "n": n,
        "most_common_text": most_common_text,
        "most_common_text_frac": most_common_count / n,
        "most_common_user": most_common_user,
        "most_common_user_frac": most_common_user_count / n,
    }

    if info["most_common_text_frac"] >= identical_threshold:
        return True, {"reason": "identical_texts", **info}
    if info["most_common_user_frac"] >= user_rate_threshold:
        return True, {"reason": "single_user_flood", **info}

    return False, {"reason": "ok", **info}


def bias_check(records: List[Dict[str, Any]], group_key: str, positive_key: str, disparity_threshold: float = 0.2) -> Tuple[bool, Dict[str, Any]]:
    """
    Simple group-bias detector. Flags when disparity between groups' positive rates exceeds threshold.
    """
    if not records:
        return False, {"reason": "no_data"}

    groups: Dict[Any, Dict[str, int]] = {}
    for r in records:
        g = r.get(group_key)
        p = bool(r.get(positive_key))
        groups.setdefault(g, {"pos": 0, "n": 0})
        groups[g]["n"] += 1
        groups[g]["pos"] += int(p)

    rates = {g: (v["pos"] / v["n"] if v["n"] else 0.0) for g, v in groups.items()}
    max_rate = max(rates.values())
    min_rate = min(rates.values())
    disparity = max_rate - min_rate
    info = {"rates": rates, "max_rate": max_rate, "min_rate": min_rate, "disparity": disparity, "threshold": disparity_threshold}
    return (disparity > disparity_threshold), info


def redact_sensitive(text: str) -> str:
    """
    Redact obvious sensitive items: emails, hex private keys (0x...), SSN-like patterns.
    """
    if not isinstance(text, str):
        raise TypeError("text must be a string")

    s = text
    s = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[REDACTED_EMAIL]", s)
    s = re.sub(r"0x[a-fA-F0-9]{40,128}", "[REDACTED_KEY]", s)
    s = re.sub(r"\b\d{3}-\d{2}-\d{4}\b", "[REDACTED_SSN]", s)
    s = re.sub(r"\b\d{9}\b", "[REDACTED_SSN]", s)
    return s