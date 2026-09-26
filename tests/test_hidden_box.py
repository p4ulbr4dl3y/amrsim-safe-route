"""Тесты для scripts/hidden_box.py."""

import subprocess
import sys
from pathlib import Path


def test_hidden_box_cli_help():
    """Проверка, что скрипт hidden_box.py вызывается напрямую через CLI без ModuleNotFoundError."""
    script_path = Path(__file__).resolve().parent.parent / "scripts" / "hidden_box.py"
    res = subprocess.run(
        [sys.executable, str(script_path), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0
    assert "Генератор скрытых сценариев" in res.stdout
