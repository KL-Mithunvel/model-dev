"""Run the JavaScript unit tests (Node's built-in runner) as part of the normal `pytest` run."""

import shutil
import subprocess
from pathlib import Path

import pytest

JS_TESTS = Path(__file__).resolve().parent / "js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_javascript_unit_tests_pass():
    result = subprocess.run(
        ["node", "--test", str(JS_TESTS)], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-1500:]
