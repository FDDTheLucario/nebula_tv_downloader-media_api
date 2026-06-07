import logging

from api.app import create_app
from config.config import Config
from nebula_api.authorization import NebulaUserAuthorization


def build():
    """Build and return the FastAPI application."""
    config = Config()
    auth = NebulaUserAuthorization(
        user_token=config.nebula_api.user_api_token,
        authorization_header=config.nebula_api.authorization_header,
    )
    return create_app(config, auth)


def main(host="0.0.0.0", port=8000) -> None:
    """Run the uvicorn server."""
    import uvicorn

    uvicorn.run(build(), host=host, port=port)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
