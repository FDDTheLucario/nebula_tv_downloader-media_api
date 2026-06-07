import pytest
from types import SimpleNamespace

from config.config import Config
from models.nebula.fetched import (
    NebulaChannelVideoContentResponseModel,
    NebulaChannelVideoContentEpisodes,
)
from models.nebula.episode import NebulaChannelVideoContentEpisodeResult
from models.nebula.channel import NebulaChannelVideoContentDetails
from tests.models.nebula.test_channel import _channel_payload
from tests.models.nebula.test_episode import _episode_payload


@pytest.fixture
def config(tmp_path):
    """Create a minimal valid config.ini for testing."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    config_file = config_dir / "config.ini"

    media_path = tmp_path / "media"

    ini_content = f"""[nebula_api]
user_api_token = test-token
authorization_header = preset-header
user_agent = test-agent
token_refresh_interval_hours = 6

[nebula_filters]
category_search = false
include_nebula_first = true
include_nebula_plus = true
include_nebula_originals = true
include_regular_videos = true
channels_to_parse = ch-slug

[downloader]
download_path = {str(media_path)}
load_channel_data_from_db = false
skip_if_video_exists = true
check_interval_hours = 1
"""

    config_file.write_text(ini_content)
    return Config(config_file)


@pytest.fixture
def fake_auth():
    """Create a fake authorization object for testing."""
    return SimpleNamespace(
        get_authorization_header=lambda full=False: "Bearer test",
        refresh_authorization_token=lambda: None,
    )


def make_episode(**overrides):
    """Build an episode from a payload with optional overrides."""
    return NebulaChannelVideoContentEpisodeResult(**_episode_payload(**overrides))


def make_content(*episodes):
    """Build a NebulaChannelVideoContentResponseModel from channel + episode payloads."""
    channel_details = NebulaChannelVideoContentDetails(**_channel_payload())
    episodes_list = NebulaChannelVideoContentEpisodes(
        next=None, previous=None, results=list(episodes) if episodes else []
    )
    return NebulaChannelVideoContentResponseModel(
        details=channel_details, episodes=episodes_list
    )
