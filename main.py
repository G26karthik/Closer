"""
@file main.py
@description Local development entry point. Run `python main.py` from the closer/ directory.
             In production, Cloud Run invokes uvicorn directly via the Dockerfile CMD.
@module closer.main
"""
import uvicorn

from config import cfg
from logger import configure_logging


def main() -> None:
    configure_logging()
    uvicorn.run("api:app", host="0.0.0.0", port=cfg.PORT, reload=True)


if __name__ == "__main__":
    main()
