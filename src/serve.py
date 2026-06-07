import logging

from api.app import create_app
from config.config import Config
from nebula_api.authorization import NebulaUserAuthorization


class _UnconfiguredAuth:
    """Stand-in auth used when no API token is configured yet.

    Lets the web UI start so the user can enter a token on the settings page;
    any call that actually needs Nebula credentials raises until configured.
    """

    def get_authorization_header(self, full: bool = False) -> str:
        raise RuntimeError("Nebula API token not configured")

    def refresh_authorization_token(self) -> None:
        pass


def build():
    """Build and return the FastAPI application.

    If no API token is configured, the app starts in an unconfigured mode
    (background worker/scheduler off) so the token can be set via the UI.
    """
    config = Config()
    if not config.nebula_api.user_api_token:
        logging.warning(
            "No Nebula API token configured; starting in setup mode. "
            "Set a token on /settings, then restart."
        )
        return create_app(config, _UnconfiguredAuth(), start_background=False)

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
