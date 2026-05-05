"""Tutor selection workflow package."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRAMEWORK_ROOT = PROJECT_ROOT / "framework"
if str(FRAMEWORK_ROOT) not in sys.path:
    sys.path.insert(0, str(FRAMEWORK_ROOT))

from .workflow import TutorSelectWorkflow

__all__ = ["TutorSelectWorkflow"]
