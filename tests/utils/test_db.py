import json
from pathlib import Path

import pytest

from models.nebula.channel import NebulaChannelVideoContentDetails
from models.nebula.episode import NebulaChannelVideoContentEpisodeResult
from models.nebula.fetched import NebulaChannelVideoContentEpisodes
from utils.db import CHANNEL_FILENAME, EPISODES_FILENAME, load_channel_info, save_channel_info
from tests.models.nebula.test_channel import _channel_payload
from tests.models.nebula.test_episode import _episode_payload


def _channel(**overrides):
    return NebulaChannelVideoContentDetails(**_channel_payload(**overrides))


def _episodes(*episodes):
    return NebulaChannelVideoContentEpisodes(next=None, previous=None, results=list(episodes))


def _episode(**overrides):
    return NebulaChannelVideoContentEpisodeResult(**_episode_payload(**overrides))


def test_save_creates_directory_and_writes_both_files(tmp_path):
    channel_directory = save_channel_info(
        channel_slug="ch-slug",
        channel_data=_channel(),
        episodes_data=_episodes(_episode()),
        output_directory=tmp_path,
    )

    assert channel_directory == tmp_path / "ch-slug"
    assert channel_directory.is_dir()

    channel_payload = json.loads((channel_directory / CHANNEL_FILENAME).read_text())
    assert channel_payload["slug"] == "ch-slug"

    episodes_payload = json.loads((channel_directory / EPISODES_FILENAME).read_text())
    assert isinstance(episodes_payload, list)
    assert episodes_payload[0]["slug"] == "ep-slug"


def test_save_episodes_file_is_bare_results_list_not_envelope(tmp_path):
    save_channel_info(
        channel_slug="ch-slug",
        channel_data=_channel(),
        episodes_data=_episodes(_episode()),
        output_directory=tmp_path,
    )
    parsed = json.loads((tmp_path / "ch-slug" / EPISODES_FILENAME).read_text())
    assert isinstance(parsed, list)
    assert "results" not in parsed[0]


def test_save_overwrites_existing_metadata_but_preserves_unrelated_files(tmp_path):
    channel_dir = tmp_path / "ch-slug"
    channel_dir.mkdir()
    (channel_dir / "video.mp4").write_bytes(b"keep")
    (channel_dir / CHANNEL_FILENAME).write_text("stale")

    save_channel_info(
        channel_slug="ch-slug",
        channel_data=_channel(),
        episodes_data=_episodes(),
        output_directory=tmp_path,
    )

    assert (channel_dir / "video.mp4").read_bytes() == b"keep"
    assert json.loads((channel_dir / CHANNEL_FILENAME).read_text())["slug"] == "ch-slug"


def test_save_then_load_roundtrip(tmp_path):
    save_channel_info(
        channel_slug="ch-slug",
        channel_data=_channel(title="Round Trip"),
        episodes_data=_episodes(_episode(title="Ep One")),
        output_directory=tmp_path,
    )

    response = load_channel_info(channel_slug="ch-slug", output_directory=tmp_path)
    assert response.details.title == "Round Trip"
    assert len(response.episodes.results) == 1
    assert response.episodes.results[0].title == "Ep One"
    assert response.episodes.next is None
    assert response.episodes.previous is None


def test_load_missing_directory_raises(tmp_path):
    with pytest.raises(FileNotFoundError) as exc:
        load_channel_info(channel_slug="missing", output_directory=tmp_path)
    assert "missing" in str(exc.value)


def test_load_missing_episodes_file_raises(tmp_path: Path):
    channel_dir = tmp_path / "ch-slug"
    channel_dir.mkdir()
    (channel_dir / CHANNEL_FILENAME).write_text(json.dumps(_channel_payload()))

    with pytest.raises(FileNotFoundError):
        load_channel_info(channel_slug="ch-slug", output_directory=tmp_path)


def test_load_empty_episodes_list(tmp_path):
    channel_dir = tmp_path / "ch-slug"
    channel_dir.mkdir()
    (channel_dir / CHANNEL_FILENAME).write_text(json.dumps(_channel_payload()))
    (channel_dir / EPISODES_FILENAME).write_text("[]")

    response = load_channel_info(channel_slug="ch-slug", output_directory=tmp_path)
    assert response.episodes.results == []


def test_load_corrupt_channel_json_raises(tmp_path):
    channel_dir = tmp_path / "ch-slug"
    channel_dir.mkdir()
    (channel_dir / CHANNEL_FILENAME).write_text("{not json")
    (channel_dir / EPISODES_FILENAME).write_text("[]")

    with pytest.raises(json.JSONDecodeError):
        load_channel_info(channel_slug="ch-slug", output_directory=tmp_path)
