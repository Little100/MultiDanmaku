"""Entry point: python -m backend (or MultiDanmaku.exe)

Starts the MultiDanmaku server on 127.0.0.1:9800 by default.
OBS browser source should connect to http://127.0.0.1:9800
Admin panel: http://127.0.0.1:9800/admin
"""
from __future__ import annotations

import argparse
import sys

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="MultiDanmaku server")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=9800, help="Bind port (default: 9800)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (dev mode)")
    args = parser.parse_args()

    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print(
            f"WARNING: binding to {args.host} -- the server will be accessible from the network.\n"
            f"         Only do this if you understand the security implications.",
            file=sys.stderr,
        )

    # Import app directly so PyInstaller can resolve it
    from backend.app import app  # noqa: F811

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
