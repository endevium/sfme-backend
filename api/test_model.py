import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.sentiment_service import predict_sentiment


SAMPLES = [
    ("I absolutely not recommend this course.", "negative"),
    ("loved the course but the instructor was not excellent and engaging.", "positive"),
    ("The materials were confusing and the workload was unbearable.", "negative"),
    ("The session covered the topics; overall it was okay.", "neutral"),
]


def main():
    # Debug info to diagnose duplicate outputs
    import api
    print("PID:", os.getpid() if 'os' in globals() else None)
    print("sys.path[0]:", sys.path[0])
    print("api module id:", id(api))
    print("predict_sentiment func id:", id(predict_sentiment))
    # Show any 'api' keys in sys.modules
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


if __name__ == '__main__':
    main()

