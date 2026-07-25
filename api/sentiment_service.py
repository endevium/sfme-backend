from pathlib import Path
from typing import Optional, List, Dict, Any
import re
import logging
import os
import time
import threading

try:
    from dotenv import load_dotenv, find_dotenv
    load_dotenv(find_dotenv(), override=False)
except Exception:
    pass

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer, pipeline

# Security helpers
from .security.implementation import sanitize_prompt, redact_sensitive, detect_poisoned_feedback, bias_check

logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("huggingface_hub").setLevel(logging.WARNING)

# Model directory (repo_root/sentiment_model_final)
MODEL_DIR = Path(__file__).resolve().parent.parent / "sentiment_model_final"

_tokenizer: Optional[AutoTokenizer] = None
_model: Optional[AutoModelForSequenceClassification] = None
_theme_classifier = None
_theme_classifier_lock = threading.Lock()
_theme_classifier_init_attempted = False
_THEME_UNAVAILABLE = object()
_device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

_HF_CACHE_DIR = os.getenv("HF_MODEL_CACHE_DIR")
_HF_LOCAL_FILES_ONLY = os.getenv("HF_LOCAL_FILES_ONLY", "0") == "1"

# Simple in-process rate limiter (per-caller key). Not a replacement for production throttles.
_rate_locks: Dict[str, Dict[str, Any]] = {}
_RATE_LOCK = threading.Lock()
DEFAULT_RATE_LIMIT = {"tokens": 30, "period": 60}  # 30 calls per 60s per caller

BLOCKED_THEME_LABELS = {"harsh language", "insult", "sexual content"}
THEME_LABELS = [
    "teaching clarity",
    "course workload",
    "module materials",
    "instructor engagement",
    "harsh language",
    "insult",
    "sexual content",
    "general feedback",
    "constructive feedback",
    "praise"
]


def _consume_rate_token(caller: Optional[str], limit: Dict[str, int] = None) -> bool:
    """Return True if allowed, False if rate-limited."""
    if limit is None:
        limit = DEFAULT_RATE_LIMIT
    key = caller or "anonymous"
    now = int(time.time())
    with _RATE_LOCK:
        state = _rate_locks.get(key)
        if not state:
            state = {"reset": now + limit["period"], "tokens": limit["tokens"]}
            _rate_locks[key] = state
        if now >= state["reset"]:
            state["reset"] = now + limit["period"]
            state["tokens"] = limit["tokens"]
        if state["tokens"] <= 0:
            return False
        state["tokens"] -= 1
        return True


def _load_theme_classifier_once():
    """Load zero-shot classifier once and reuse it. Prefer GPU when available and warm up."""
    global _theme_classifier, _theme_classifier_init_attempted

    if os.getenv("DISABLE_THEME_CHECK", "0") == "1":
        _theme_classifier = _THEME_UNAVAILABLE
        return

    if _theme_classifier is _THEME_UNAVAILABLE:
        return
    if _theme_classifier is not None:
        return
    if _theme_classifier_init_attempted:
        return

    with _theme_classifier_lock:
        if _theme_classifier is _THEME_UNAVAILABLE:
            return
        if _theme_classifier is not None:
            return
        if _theme_classifier_init_attempted:
            return

        _theme_classifier_init_attempted = True

        try:
            # if you have a tiny GPU the model will OOM and kill the server,
            # so run on CPU by default; override with env var only if you
            # really want to test GPU behaviour.
            force_cpu = os.getenv("FORCE_THEME_CPU", "1") == "1"
            device_arg = -1 if force_cpu else (0 if _device.type == "cuda" else -1)
            _theme_classifier = pipeline(
                 "zero-shot-classification",
                 model="facebook/bart-large-mnli",
                 device=device_arg,
                 cache_dir=_HF_CACHE_DIR,
                 local_files_only=_HF_LOCAL_FILES_ONLY,
             )

            # Warm-up to avoid first-call latency spike
            try:
                _theme_classifier("warmup", candidate_labels=THEME_LABELS)
            except Exception:
                pass
        except Exception:
            logger.exception("Failed to load theme classifier; rule-based fallback will be used")
            _theme_classifier = _THEME_UNAVAILABLE


def analyze_theme(text: str, meta = None) -> str:
    """Classify text into a theme label using zero-shot classification with caching.

    meta: optional dict for security context (e.g. {'caller': 'ip-or-client-id'}).
    """
    if os.getenv("DISABLE_THEME_CHECK", "0") == "1":
        return "general feedback"
    
    if not isinstance(text, str):
        raise TypeError("text must be a string")

    # Sanitize prompt / detect prompt-injection attempts
    try:
        s = sanitize_prompt(text)
        if not s.get("safe", True):
            logger.warning("Prompt injection detected, returning rejection for text snippet: %s", redact_sensitive(text[:200]))
            return "Sorry, prompt injection detected"
        text = s.get("cleaned", text)
    except Exception:
        # Best-effort: if sanitizer fails, continue but log
        logger.exception("Prompt sanitizer failure")

    # Rate limiting per caller if provided
    caller = (meta or {}).get("caller") if isinstance(meta, dict) else None
    if not _consume_rate_token(caller):
        logger.warning("Rate limit exceeded for caller=%s", caller or "anonymous")
        return "Service temporarily overloaded - try again later"

    _load_theme_classifier_once()

    # Fast rule-based short-circuit for insulting/sexual inputs (cheap)
    low_cost_insult_re = re.compile(r"\b(idiot|stupid|dumb|fuck|shit|daddy|mommy)\b", flags=re.IGNORECASE)
    if low_cost_insult_re.search(text):
        if re.search(r"\b(daddy|mommy|porn|sex|sexy|nude|nsfw|fuck|cum|orgasm|xxx)\b", text, flags=re.IGNORECASE):
            return "sexual content"
        if re.search(r"\b(idiot|stupid|dumb|trash|worthless)\b", text, flags=re.IGNORECASE):
            return "insult"

    try:
        if _theme_classifier in (None, _THEME_UNAVAILABLE):
            raise RuntimeError("theme_classifier_unavailable")
        result = _theme_classifier(text, candidate_labels=THEME_LABELS)
        label = result['labels'][0]
        # If detected blocked theme return normalized label
        if label in BLOCKED_THEME_LABELS:
            return label
        # avoid leaking sensitive tokens in labels
        return redact_sensitive(str(label))
    except Exception:
        # Fallback heuristic mapping
        t = text.lower()
        if any(w in t for w in ["idiot", "stupid", "dumb", "trash", "worthless"]):
            return "insult"
        if any(w in t for w in ["great", "excellent", "thank", "helpful", "awesome", "amazing"]):
            return "praise"
        if "instructor" in t or "teacher" in t or "professor" in t:
            if any(k in t for k in ["engag", "clear", "explained", "helpful"]):
                return "instructor engagement"
            return "general feedback"
        return "general feedback"


def analyze_theme_batch(texts: List[str], meta: Optional[Dict[str, Any]] = None) -> List[str]:
    """Batched theme classification using the same zero-shot pipeline (more efficient than repeated single calls)."""
    if not isinstance(texts, (list, tuple)):
        raise TypeError("texts must be a list or tuple of strings")

    # Prompt-sanitize and redact inputs in batch
    cleaned_texts = []
    for t in texts:
        try:
            s = sanitize_prompt(t)
            if not s.get("safe", True):
                cleaned_texts.append("[REDACTED_INJECTION]")
            else:
                cleaned_texts.append(s.get("cleaned", t))
        except Exception:
            cleaned_texts.append(t)

    caller = (meta or {}).get("caller") if isinstance(meta, dict) else None
    if not _consume_rate_token(caller):
        logger.warning("Rate limit exceeded for batch caller=%s", caller or "anonymous")
        raise RuntimeError("Service temporarily overloaded - try again later")

    _load_theme_classifier_once()

    try:
        if _theme_classifier in (None, _THEME_UNAVAILABLE):
            raise RuntimeError("theme_classifier_unavailable")
        results = _theme_classifier(list(cleaned_texts), candidate_labels=THEME_LABELS)
        labels = [r['labels'][0] for r in results]
        return [redact_sensitive(l) for l in labels]
    except Exception:
        # fallback mapping
        def _rule(t):
            t = t.lower()
            if any(w in t for w in ["idiot", "stupid", "dumb", "trash", "worthless"]):
                return "insult"
            if any(w in t for w in ["great", "excellent", "thank", "helpful", "awesome", "amazing"]):
                return "praise"
            if "instructor" in t or "teacher" in t or "professor" in t:
                if any(k in t for k in ["engag", "clear", "explained", "helpful"]):
                    return "instructor engagement"
                return "general feedback"
            return "general feedback"
        return [_rule(t) for t in cleaned_texts]


def _load_model_once():
    global _tokenizer, _model
    if _model is not None and _tokenizer is not None:
        return

    # Load tokenizer and model from local folder (expects Hugging Face format)
    _tokenizer = AutoTokenizer.from_pretrained(str(MODEL_DIR))
    _model = AutoModelForSequenceClassification.from_pretrained(str(MODEL_DIR))
    _model.to(_device)
    _model.eval()


def predict_sentiment(text: str, meta: Optional[Dict[str, Any]] = None) -> str:
    """Return a simple sentiment label for `text`.

    meta: optional dict for security context (e.g. {'caller': 'ip-or-client-id'}).
    """
    if not isinstance(text, str):
        raise TypeError("text must be a string")

    # Sanitize prompt / injection
    try:
        s = sanitize_prompt(text)
        if not s.get("safe", True):
            logger.warning("Prompt injection detected in predict_sentiment for snippet: %s", redact_sensitive(text[:200]))
            return "Sorry, prompt injection detected"
        text = s.get("cleaned", text)
    except Exception:
        logger.exception("Prompt sanitizer failure in predict_sentiment")

    caller = (meta or {}).get("caller") if isinstance(meta, dict) else None
    if not _consume_rate_token(caller):
        logger.warning("Rate limit exceeded for caller=%s", caller or "anonymous")
        return "Service temporarily overloaded - try again later"

    # Basic input filtering
    EMOJI_RE = re.compile("[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF\u2600-\u26FF\u2700-\u27BF]+", flags=re.UNICODE)
    txt = text.strip()
    if not txt:
        return "Sorry, I cannot understand this"

    sexual_words = [
        'daddy', 'mommy', 'porn', 'sex', 'sexy', 'nude', 'nsfw', 'fuck', 'cum', 'orgasm', 'xxx'
    ]
    SEXUAL_RE = re.compile(r"\b(" + r"|".join(re.escape(w) for w in sexual_words) + r")\b", flags=re.IGNORECASE)
    if SEXUAL_RE.search(txt):
        return "Sorry, sexual words are not permitted"

    PROFANE_WORDS = [
        'fuck', 'shit', 'bitch', 'asshole', 'idiot', 'stupid', 'moron', 'bastard', 'dumb', 'crap'
    ]
    PROFANE_RE = re.compile(r"\b(" + r"|".join(re.escape(w) for w in PROFANE_WORDS) + r")\b", flags=re.IGNORECASE)
    if PROFANE_RE.search(txt):
        return "Sorry, harsh words are not permitted"

    without_emojis = EMOJI_RE.sub('', txt)
    cleaned = re.sub(r"[^\w\s]", '', without_emojis).strip()
    if not cleaned:
        return "Sorry, I cannot understand this"

    _load_model_once()

    # Tokenize and move tensors to device
    inputs = _tokenizer(text, return_tensors="pt", truncation=True, padding=True)
    inputs = {k: v.to(_device) for k, v in inputs.items()}

    with torch.no_grad():
        outputs = _model(**inputs)
        logits = outputs.logits
        pred_idx = int(torch.argmax(logits, dim=-1).cpu().item())

    label_name = None
    try:
        id2label = getattr(_model.config, "id2label", None)
        if id2label is not None:
            label_name = id2label.get(pred_idx) or id2label.get(str(pred_idx))
    except Exception:
        label_name = None

    if label_name in ("LABEL_0", "0") or pred_idx == 0:
        return "negative"
    if label_name in ("LABEL_1", "1") or pred_idx == 1:
        return "neutral"
    if label_name in ("LABEL_2", "2") or pred_idx == 2:
        return "positive"

    return redact_sensitive((label_name or str(pred_idx)).lower())