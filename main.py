#!/usr/bin/env python3
"""ModBridge entry point (PySide6). Requires: pip install -r requirements.txt."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from modrinth_app.app import run


if __name__ == "__main__":
    sys.exit(run())
