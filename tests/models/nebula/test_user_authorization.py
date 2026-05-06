import pytest
from pydantic import ValidationError

from models.nebula.user_authorization import NebulaUserAPIAuthorizationTokenResponseModel


def test_user_authorization_model_parses_token():
    model = NebulaUserAPIAuthorizationTokenResponseModel(token="abc.def.ghi")
    assert model.token == "abc.def.ghi"


def test_user_authorization_model_missing_token_raises():
    with pytest.raises(ValidationError):
        NebulaUserAPIAuthorizationTokenResponseModel()


def test_user_authorization_model_extra_fields_ignored():
    model = NebulaUserAPIAuthorizationTokenResponseModel(token="t", unrelated="x")
    assert model.token == "t"
    assert not hasattr(model, "unrelated")
