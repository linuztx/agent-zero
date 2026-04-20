from __future__ import annotations

import importlib
import importlib.util
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from helpers.errors import format_error
from helpers.print_style import PrintStyle


_LOCK = threading.Lock()
_CHECKED = False
_PLUGIN_DIR = Path(__file__).resolve().parents[1]
_REQUIREMENTS_FILE = _PLUGIN_DIR / "requirements.txt"


def has_discord() -> bool:
    return importlib.util.find_spec("discord") is not None


def ensure_dependencies() -> None:
    global _CHECKED

    if _CHECKED and has_discord():
        return

    with _LOCK:
        if _CHECKED and has_discord():
            return
        if has_discord():
            _CHECKED = True
            return

        _install_discord()
        importlib.invalidate_caches()

        if not has_discord():
            raise RuntimeError("Discord dependency 'discord.py' is still unavailable after installation")

        _CHECKED = True


def _install_discord() -> None:
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("Discord plugin requires 'uv' to install discord.py automatically")
    if not _REQUIREMENTS_FILE.is_file():
        raise RuntimeError(f"Discord plugin requirements file not found: {_REQUIREMENTS_FILE}")

    cmd = [
        uv,
        "pip",
        "install",
        "--python",
        sys.executable,
        "-r",
        str(_REQUIREMENTS_FILE),
    ]

    PrintStyle.info("Discord: discord.py not found, installing plugin dependency")
    try:
        subprocess.check_call(cmd, cwd=str(_PLUGIN_DIR))
    except Exception as e:
        raise RuntimeError(f"Failed to install Discord dependency 'discord.py': {format_error(e)}") from e
