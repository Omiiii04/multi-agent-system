import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

os.environ["ADK_SUPPRESS_EXPERIMENTAL_FEATURE_WARNINGS"] = "True"

if "GEMINI_API_KEY" in os.environ and "GOOGLE_API_KEY" not in os.environ:
    os.environ.setdefault("GOOGLE_API_KEY", os.environ["GEMINI_API_KEY"])
