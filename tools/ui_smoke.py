"""Kept for old habits: the browser checks now live in tools/scenarios/smoke.py.

    python tools/dev_run.py run smoke --headless      # what this file used to do
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dev_run import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(["run", "smoke", "--headless", *sys.argv[1:]]))
