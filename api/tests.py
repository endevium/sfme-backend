from django.test import TestCase
import time

# AI Testing

import sys
from pathlib import Path
import os
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
    
import api
from api.sentiment_service import predict_sentiment

SAMPLES = [
    ("I absolutely not recommend this course.", "negative"),
    ("meow", "Sorry, I cannot understand this"),
    ("!!!???", "Sorry, I cannot understand this"),
    ("You are an idiot", "Sorry, harsh words are not permitted"),
    ("ahhhh daddy", "Sorry, sexual words are not permitted"),
    ("lmao", "neutral"),
]

def main():
    start = time.time()
    print("PID:", os.getpid() if 'os' in globals() else None)
    print("sys.path[0]:", sys.path[0])
    print("api module id:", id(api))
    print("predict_sentiment func id:", id(predict_sentiment))
    api_keys = [k for k in sys.modules.keys() if k.startswith('api')]
    print("sys.modules api keys:", api_keys)

    for text, expected in SAMPLES:
        try:
            label = predict_sentiment(text)
        except Exception as e:
            label = f"ERROR: {e}"
        print("---")
        print("Text:", text)
        print("Predicted:", label, "(expected:", expected, ")")
        end = time.time()
        print("Time: ", end - start)

if __name__ == '__main__':
    main()