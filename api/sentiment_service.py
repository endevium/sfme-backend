from pathlib import Path
from typing import Optional

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer


# Model directory (repo_root/sentiment_model_final)
MODEL_DIR = Path(__file__).resolve().parent.parent / "sentiment_model_final"

_tokenizer: Optional[AutoTokenizer] = None
_model: Optional[AutoModelForSequenceClassification] = None
_device = torch.device("cuda" if torch.cuda.is_available() else "cpu")


def _load_model_once():
    global _tokenizer, _model
    if _model is not None and _tokenizer is not None:
        return

    # Load tokenizer and model from local folder (expects Hugging Face format)
    _tokenizer = AutoTokenizer.from_pretrained(str(MODEL_DIR))
    _model = AutoModelForSequenceClassification.from_pretrained(str(MODEL_DIR))
    _model.to(_device)
    _model.eval()


def predict_sentiment(text: str) -> str:
    """Return a simple sentiment label for `text`.

    Loads model/tokenizer once and reuses them on subsequent calls.
    Returns one of: 'negative', 'neutral', 'positive' when possible, otherwise the raw label.
    """
    if not isinstance(text, str):
        raise TypeError("text must be a string")

    _load_model_once()

    # Tokenize and move tensors to device
    inputs = _tokenizer(text, return_tensors="pt", truncation=True, padding=True)
    inputs = {k: v.to(_device) for k, v in inputs.items()}

    with torch.no_grad():
        outputs = _model(**inputs)
        logits = outputs.logits
        pred_idx = int(torch.argmax(logits, dim=-1).cpu().item())

    # Try to read a human-readable label from model config
    label_name = None
    try:
        id2label = getattr(_model.config, "id2label", None)
        if id2label is not None:
            # id2label keys may be ints or strings
            label_name = id2label.get(pred_idx) or id2label.get(str(pred_idx))
    except Exception:
        label_name = None

    # Friendly mapping used in training: 0=negative,1=neutral,2=positive
    if label_name in ("LABEL_0", "0") or pred_idx == 0:
        return "negative"
    if label_name in ("LABEL_1", "1") or pred_idx == 1:
        return "neutral"
    if label_name in ("LABEL_2", "2") or pred_idx == 2:
        return "positive"

    # Fallback to whatever label_name is or numeric index
    return (label_name or str(pred_idx)).lower()
