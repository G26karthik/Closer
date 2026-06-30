import uvicorn

from config import cfg
from logger import configure_logging


def main() -> None:
    configure_logging()
    uvicorn.run("api:app", host="0.0.0.0", port=cfg.PORT, reload=True)


if __name__ == "__main__":
    main()
