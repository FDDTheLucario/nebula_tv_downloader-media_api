from pathlib import Path

import pytest
from pydantic import ValidationError

from models.configuration import (
    ConfigurationDownloaderModel,
    ConfigurationModel,
    ConfigurationNebulaAPIModel,
    ConfigurationNebulaFiltersModel,
)


def test_nebula_api_model_blank_authorization_header_normalized_to_none():
    model = ConfigurationNebulaAPIModel(
        user_api_token="tok", authorization_header="", user_agent="ua",
        token_refresh_interval_hours=6,
    )
    assert model.authorization_header is None


def test_nebula_api_model_keeps_provided_authorization_header():
    model = ConfigurationNebulaAPIModel(
        user_api_token="tok",
        authorization_header="bearer-token",
        user_agent="ua",
        token_refresh_interval_hours=6,
    )
    assert model.authorization_header == "bearer-token"


def test_nebula_api_model_missing_required_raises():
    with pytest.raises(ValidationError):
        ConfigurationNebulaAPIModel(
            authorization_header=None, user_agent="ua", token_refresh_interval_hours=6
        )


def test_filters_model_drops_empty_channel_strings():
    model = ConfigurationNebulaFiltersModel(
        channels_to_parse=["nilered", "", "tldrnewsuk", ""]
    )
    assert model.channels_to_parse == ["nilered", "tldrnewsuk"]


def test_filters_model_none_channels_remain_none():
    model = ConfigurationNebulaFiltersModel(channels_to_parse=None)
    assert model.channels_to_parse is None


def test_filters_model_all_empty_channels_become_empty_list():
    model = ConfigurationNebulaFiltersModel(channels_to_parse=["", ""])
    assert model.channels_to_parse == []


def test_filters_model_empty_list_remains_none():
    model = ConfigurationNebulaFiltersModel(channels_to_parse=[])
    assert model.channels_to_parse is None


def test_filters_model_defaults():
    model = ConfigurationNebulaFiltersModel()
    assert model.category_search is None
    assert model.include_nebula_first is True
    assert model.include_nebula_plus is True
    assert model.include_nebula_originals is True
    assert model.include_regular_videos is False
    assert model.channels_to_parse is None


def test_downloader_model_coerces_path():
    model = ConfigurationDownloaderModel(
        download_path="/tmp/foo", load_channel_data_from_db=False, skip_if_video_exists=True
    )
    assert isinstance(model.download_path, Path)
    assert model.download_path == Path("/tmp/foo")


def test_downloader_model_path_input_remains_path():
    model = ConfigurationDownloaderModel(
        download_path=Path("/tmp/bar"),
        load_channel_data_from_db=True,
        skip_if_video_exists=False,
    )
    assert model.download_path == Path("/tmp/bar")


def test_aggregate_configuration_model_composes_subsections():
    model = ConfigurationModel(
        nebula_api=ConfigurationNebulaAPIModel(
            user_api_token="t", authorization_header=None, user_agent="ua",
            token_refresh_interval_hours=6,
        ),
        nebula_filters=ConfigurationNebulaFiltersModel(),
        downloader=ConfigurationDownloaderModel(
            download_path="/tmp/x", load_channel_data_from_db=False, skip_if_video_exists=False
        ),
    )
    assert model.nebula_api.user_api_token == "t"
    assert model.nebula_filters.include_nebula_plus is True
    assert model.downloader.download_path == Path("/tmp/x")
