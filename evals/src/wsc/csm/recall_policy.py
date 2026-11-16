"""Recall selection without loading any optional numerical dependencies."""
import os

MODES = ("lexical", "vector", "hybrid")


def mode() -> str:
    value = os.environ.get("WSC_CSM_RECALL", "lexical").strip().lower()
    return value if value in MODES else "lexical"
