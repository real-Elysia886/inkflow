"""inkflow - FastAPI entry point.

Usage:
    python main.py                  # run on default port 8000
    python main.py --port 8080      # custom port
    python main.py --host 0.0.0.0   # allow external access
"""

import argparse
from pathlib import Path
import uvicorn
from dotenv import load_dotenv

# Load .env from project root (works regardless of CWD)
_env_path = Path(__file__).parent / ".env"
load_dotenv(_env_path)


def main():
    parser = argparse.ArgumentParser(description="inkflow server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    args = parser.parse_args()

    uvicorn.run(
        "inkflow.api.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
