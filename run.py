#!/usr/bin/env python3
"""Entry point for the relay server.

Usage:
    python run.py          # creates .venv if needed, installs deps, starts server
"""

import os
import subprocess
import sys

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_DIR = os.path.join(ROOT_DIR, ".venv")
VENV_PYTHON = os.path.join(VENV_DIR, "bin", "python")
STAMP_FILE = os.path.join(VENV_DIR, ".relay_stamp")


def _needs_install():
    """Check if we need to (re)install — compares pyproject.toml mtime to stamp."""
    if not os.path.exists(VENV_PYTHON):
        return True
    if not os.path.exists(STAMP_FILE):
        return True
    stamp_mtime = os.path.getmtime(STAMP_FILE)
    pyproject = os.path.join(ROOT_DIR, "pyproject.toml")
    if os.path.exists(pyproject) and os.path.getmtime(pyproject) > stamp_mtime:
        return True
    return False


def ensure_venv():
    """Create .venv and install the package if needed."""
    if sys.prefix != sys.base_prefix:
        return  # already running inside a venv

    if _needs_install():
        if not os.path.exists(VENV_PYTHON):
            print("Creating .venv ...")
            subprocess.check_call([sys.executable, "-m", "venv", VENV_DIR])
        print("Installing relay into .venv ...")
        subprocess.check_call(
            [VENV_PYTHON, "-m", "pip", "install", "-q", "-e", "."]
        )
        # Touch stamp so we don't reinstall until pyproject.toml changes
        open(STAMP_FILE, "w").close()

    # Re-exec this script inside the venv
    os.execv(VENV_PYTHON, [VENV_PYTHON, __file__] + sys.argv[1:])


def ensure_certs():
    """Generate a self-signed TLS cert if none exists."""
    cert_dir = os.path.join(ROOT_DIR, ".certs")
    cert_file = os.path.join(cert_dir, "cert.pem")
    key_file = os.path.join(cert_dir, "key.pem")

    if os.path.exists(cert_file) and os.path.exists(key_file):
        return cert_file, key_file

    os.makedirs(cert_dir, exist_ok=True)
    print("Generating self-signed TLS certificate ...")
    subprocess.check_call([
        "openssl", "req", "-x509",
        "-newkey", "rsa:2048",
        "-keyout", key_file,
        "-out", cert_file,
        "-days", "365",
        "-nodes",
        "-subj", "/CN=relay",
    ])
    print(f"Certs written to {cert_dir}/")
    return cert_file, key_file


ensure_venv()

import asyncio  # noqa: E402

from hypercorn.asyncio import serve  # noqa: E402
from hypercorn.config import Config as HyperConfig  # noqa: E402

from relay.app import create_app_from_config  # noqa: E402
from relay.config import Config  # noqa: E402

config = Config()
app = create_app_from_config(config)

if __name__ == "__main__":
    cert_file, key_file = ensure_certs()

    hyper = HyperConfig()
    hyper.bind = [f"{config.host}:{config.port}"]
    hyper.certfile = cert_file
    hyper.keyfile = key_file

    print(f"\n  relay running at https://0.0.0.0:{config.port}")
    print(f"  Accept the self-signed cert warning in your browser.\n")

    asyncio.run(serve(app, hyper))
