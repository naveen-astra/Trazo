"""Run the control plane: ``python -m trazo_server``."""

import sys

import uvicorn
from pydantic import ValidationError

from trazo_server.config import Settings


def main() -> None:
    # Built here, before uvicorn starts, so a production deploy with a weak
    # or default secret fails immediately with every problem listed, rather
    # than inside a worker's traceback.
    try:
        settings = Settings()
    except ValidationError as exc:
        messages = [
            str(error["msg"]).removeprefix("Value error, ") for error in exc.errors()
        ]
        print("trazo: invalid configuration", file=sys.stderr)
        for message in messages:
            print(message, file=sys.stderr)
        sys.exit(2)

    uvicorn.run(
        "trazo_server.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        proxy_headers=True,
        forwarded_allow_ips=settings.forwarded_allow_ips,
        server_header=False,
    )


if __name__ == "__main__":
    main()
