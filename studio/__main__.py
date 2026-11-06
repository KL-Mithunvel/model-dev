"""Start the app: ``python -m studio [--config path]``."""

import argparse
from pathlib import Path

import uvicorn

from studio.api.app import create_app
from studio.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Local Vision Studio")
    parser.add_argument("--config", type=Path, default=None, help="Path to a config.yaml")
    args = parser.parse_args()
    config = load_config(args.config)
    host, port = config["app"]["host"], config["app"]["port"]
    print(f"Local Vision Studio -> http://{host}:{port}  (Ctrl+C to stop)")
    uvicorn.run(create_app(config), host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
