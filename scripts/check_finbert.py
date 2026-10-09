"""Explicit local download/inference check, no news or market data invented/stored."""
import json
import os
from pathlib import Path

os.environ.setdefault("HF_HOME", str(Path(__file__).resolve().parents[1] / ".cache" / "huggingface"))

from src.platform.news import analyze  # noqa: E402

if __name__ == "__main__":
    result = analyze({"id": "synthetic-smoke-only", "title": "The company reported higher revenue and profit.",
                      "description": "", "language": "en"})
    print(json.dumps({"test_input": "synthetic; not a real news item", "result": result}, indent=2))
