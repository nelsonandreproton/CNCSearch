"""Shared pytest fixtures.

Ensures the project root is importable so `import cncsearch...` works
regardless of the working directory pytest is invoked from.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
