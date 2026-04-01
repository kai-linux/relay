#!/usr/bin/env python3
"""Entry point for the relay server.

Usage:
    python run.py          # creates .venv if needed, installs deps, starts server
"""

import os
import subprocess
import sys

VENV_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv")
VENV_PYTHON = os.path.join(VENV_DIR, "bin", "python")


def ensure_venv():
    """Create .venv and install the package if not already set up."""
    if sys.executable == VENV_PYTHON or sys.prefix != sys.base_prefix:
        return  # already running inside the venv

    if not os.path.exists(VENV_PYTHON):
        print("Creating .venv ...")
        subprocess.check_call([sys.executable, "-m", "venv", VENV_DIR])
        print("Installing relay into .venv ...")
        subprocess.check_call([VENV_PYTHON, "-m", "pip", "install", "-e", "."])

    # Re-exec this script inside the venv
    os.execv(VENV_PYTHON, [VENV_PYTHON, __file__] + sys.argv[1:])


ensure_venv()

from relay.app import create_app_from_config  # noqa: E402
from relay.config import Config  # noqa: E402

config = Config()
app = create_app_from_config(config)

if __name__ == "__main__":
    app.run(host=config.host, port=config.port)
