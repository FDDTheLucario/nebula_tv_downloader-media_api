from http import HTTPStatus

import pytest

from models.urls import NEBULA_USERAPI_AUTHORIZATION
from NebulaAPI.Authorization import NebulaUserAuthorization, NebulaUserAPIAuthorizationTokenResponseModel
import tests.consts

def test_authorization_valid_api_key_no_configured_auth_header_expect_header_to_be_set(requests_mock):
    auth_request = requests_mock.post(
        url=str(NEBULA_USERAPI_AUTHORIZATION),
        headers={
            "Authorization": f"Token {tests.consts.API_KEY}"
        },
        status_code=HTTPStatus.OK,
        json={
            "token": tests.consts.AUTH_TOKEN
        }
    )

    nebula_authorizer = NebulaUserAuthorization(
        user_token=tests.consts.API_KEY,
        authorization_header=None
    )

    expected_authorizer = NebulaUserAuthorization(
        user_token=tests.consts.API_KEY,
        authorization_header=tests.consts.AUTH_TOKEN
    )

    expected_to_string = f"NebulaUserAuthorization(user_token={tests.consts.API_KEY}, authorization_header={tests.consts.AUTH_TOKEN})"


    full_auth_header = nebula_authorizer.get_authorization_header(full=True)

    assert nebula_authorizer == expected_authorizer
    assert auth_request.call_count == 1
    assert full_auth_header == f"Bearer {tests.consts.AUTH_TOKEN}"
    assert nebula_authorizer.__str__() == expected_to_string


def test_authorization_valid_api_key_configured_auth_header_expect_header_to_not_change(requests_mock):
    auth_request = requests_mock.post(
        url=str(NEBULA_USERAPI_AUTHORIZATION)
    )

    nebula_authorizer = NebulaUserAuthorization(
        user_token=tests.consts.API_KEY,
        authorization_header=tests.consts.AUTH_TOKEN
    )

    expected_authorizer = NebulaUserAuthorization(
        user_token=tests.consts.API_KEY,
        authorization_header=tests.consts.AUTH_TOKEN
    )

    assert nebula_authorizer == expected_authorizer
    assert auth_request.call_count == 0

def test_authorization_invalid_api_key_verify_exception_bubbles(requests_mock):
    auth_request = requests_mock.post(
        url=str(NEBULA_USERAPI_AUTHORIZATION),
        headers={
            "Authorization": f"Token {tests.consts.API_KEY}"
        },
        status_code=HTTPStatus.BAD_REQUEST,
        text=tests.consts.BAD_REQUEST
    )
    with pytest.raises(Exception) as e:
        NebulaUserAuthorization(
            user_token=tests.consts.API_KEY,
            authorization_header=None
        )

    assert str(e.value) == f"Failed to get authorization token for a given user token: `{bytes(tests.consts.BAD_REQUEST, 'utf-8')}` with status code {HTTPStatus.BAD_REQUEST}"
