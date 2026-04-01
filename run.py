#!/usr/bin/env python3
"""Entry point for the relay server."""

from relay.app import create_app_from_config
from relay.config import Config

config = Config()
app = create_app_from_config(config)

if __name__ == "__main__":
    app.run(host=config.host, port=config.port)
