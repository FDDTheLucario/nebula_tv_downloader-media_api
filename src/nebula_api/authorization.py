from requests import post as requests_post
import logging
from models.urls import NEBULA_USERAPI_AUTHORIZATION
from models.nebula.user_authorization import NebulaUserAPIAuthorizationTokenResponseModel


class NebulaUserAuthorization:
    def __init__(self, user_token: str, authorization_header: str | None) -> None:
        self.__user_token = user_token
        self.__authorization_header = authorization_header
        self.__fetch_authorization_token()
        self.__post_init__()

    def __fetch_authorization_token(self) -> None:
        logging.debug(
            "Fetching authorization token with user token `%s...`",
            self.__user_token[:5],
        )
        if self.__authorization_header:
            logging.debug(
                "Authorization header already set (`%s...`), not fetching authorization token",
                self.__authorization_header[:10],
            )
            return
        response = requests_post(
            url=NEBULA_USERAPI_AUTHORIZATION,
            headers={"Authorization": f"Token {self.__user_token}"},
        )
        if response.status_code == 200:
            self.__authorization_header = NebulaUserAPIAuthorizationTokenResponseModel(
                **response.json()
            ).token
            logging.info(
                "Successfully fetched authorization token from Nebula API: `%s...`",
                self.__authorization_header[:10],
            )
            return
        raise Exception(
            f"Failed to get authorization token for a given user token: `{response.content.__str__()}` with status code {response.status_code}"
        )

    def refresh_authorization_token(self) -> None:
        logging.info("Refreshing authorization token")
        self.__fetch_authorization_token()

    def __post_init__(self) -> None:
        if not self.__user_token:
            raise ValueError("User token for Nebula API must not be empty")
        if not self.__authorization_header:
            raise ValueError("Authorization header must not be empty")
        logging.debug("Passed NebulaUserAuthorzation post initialization checks")

    def get_authorization_header(self, full: bool = False) -> str:
        if full:
            return f"Bearer {self.__authorization_header}"
        return self.__authorization_header or ""

    def get_user_token(self) -> str:
        return self.__user_token

    def __repr__(self) -> str:
        return f"NebulaUserAuthorization(user_token={self.__user_token}, authorization_header={self.__authorization_header})"

    def __str__(self) -> str:
        return self.__repr__()
    def __eq__(self, o: object) -> bool:
        if not isinstance(o, NebulaUserAuthorization):
            return False
        return self.__user_token == o.get_user_token() and self.__authorization_header == o.get_authorization_header()