"""Run the control plane: ``python -m trazo_server``."""

import uvicorn

from trazo_server.config import Settings


def main() -> None:
    settings = Settings()
    uvicorn.run(
        "trazo_server.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
    )


if __name__ == "__main__":
    main()
