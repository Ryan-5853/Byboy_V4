#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(project_root))
    sys.path.insert(0, str(project_root / "framework"))
    from workflow.cli import main
else:
    from .cli import main


if __name__ == "__main__":
    raise SystemExit(main())
