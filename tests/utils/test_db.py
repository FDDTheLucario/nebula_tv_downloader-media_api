import json
import sqlite3
from unittest.mock import patch

import pytest

from models.nebula.channel import NebulaChannelVideoContentDetails
from models.nebula.episode import NebulaChannelVideoContentEpisodeResult
from models.nebula.fetched import NebulaChannelVideoContentEpisodes
from models.nebula.video_attributes import VideoNebulaAttributes
from utils.db import (
    DB_FILENAME,
    ChannelNotFoundError,
    _connect,
    load_channel_info,
    save_channel_info,
)
from tests.models.nebula.test_channel import _channel_payload
from tests.models.nebula.test_episode import _episode_payload


def _channel(**overrides):
    return NebulaChannelVideoContentDetails(**_channel_payload(**overrides))


def _episodes(*episodes):
    return NebulaChannelVideoContentEpisodes(next=None, previous=None, results=list(episodes))


def _episode(**overrides):
    return NebulaChannelVideoContentEpisodeResult(**_episode_payload(**overrides))


# Test 1: _connect creates db file and schema
def test_connect_creates_db_file_and_schema(tmp_path):
    conn = _connect(tmp_path)
    try:
        assert (tmp_path / DB_FILENAME).exists()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='channels'"
        )
        assert cursor.fetchone() is not None
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='episodes'"
        )
        assert cursor.fetchone() is not None
    finally:
        conn.close()


# Test 2: save_channel_info creates channel directory and returns it
def test_save_creates_channel_directory_and_returns_it(tmp_path):
    channel_directory = save_channel_info(
        channel_slug="ch-slug",
        channel_data=_channel(),
        episodes_data=_episodes(),
        output_directory=tmp_path,
    )

    assert channel_directory == tmp_path / "ch-slug"
    assert channel_directory.is_dir()


# Test 3: save_channel_info writes channel row
def test_save_writes_channel_row(tmp_path):
    save_channel_info(
        channel_slug="ch-slug",
        channel_data=_channel(),
        episodes_data=_episodes(),
        output_directory=tmp_path,
    )

    conn = _connect(tmp_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT details_json FROM channels WHERE slug = ?", ("ch-slug",))
        row = cursor.fetchone()
        assert row is not None
        details = json.loads(row[0])
        assert details["slug"] == "ch-slug"
    finally:
        conn.close()


# Test 4: save_channel_info writes one row per episode
def test_save_writes_one_row_per_episode(tmp_path):
    episodes_to_save = _episodes(_episode(slug="ep1"), _episode(slug="ep2"))
    save_channel_info(
        channel_slug="ch-slug",
        channel_data=_channel(),
        episodes_data=episodes_to_save,
        output_directory=tmp_path,
    )

    conn = _connect(tmp_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT episode_json, published_year FROM episodes WHERE channel_slug = ?", ("ch-slug",))
        rows = cursor.fetchall()
        assert len(rows) == 2
        for row in rows:
            episode = json.loads(row[0])
            assert "slug" in episode
            # published_year should be parsed from published_at: "2024-01-01T00:00:00Z"
            published_year = row[1]
            assert published_year == 2024
    finally:
        conn.close()


# Test 5: save_channel_info with empty episode list
def test_save_empty_episode_list(tmp_path):
    save_channel_info(
        channel_slug="ch-slug",
        channel_data=_channel(),
        episodes_data=_episodes(),
        output_directory=tmp_path,
    )

    conn = _connect(tmp_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM episodes WHERE channel_slug = ?", ("ch-slug",))
        count = cursor.fetchone()[0]
        assert count == 0

        cursor.execute("SELECT COUNT(*) FROM channels WHERE slug = ?", ("ch-slug",))
        channel_count = cursor.fetchone()[0]
        assert channel_count == 1
    finally:
        conn.close()


# Test 6: save then load roundtrip
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


# Test 7: save overwrites and replaces episode set
def test_save_overwrites_replaces_episode_set(tmp_path):
    save_channel_info(
        channel_slug="ch-slug",
        channel_data=_channel(),
        episodes_data=_episodes(_episode(slug="ep1"), _episode(slug="ep2")),
        output_directory=tmp_path,
    )

    response = load_channel_info(channel_slug="ch-slug", output_directory=tmp_path)
    assert len(response.episodes.results) == 2

    # Re-save with only 1 episode
    save_channel_info(
        channel_slug="ch-slug",
        channel_data=_channel(),
        episodes_data=_episodes(_episode(slug="ep1")),
        output_directory=tmp_path,
    )

    response = load_channel_info(channel_slug="ch-slug", output_directory=tmp_path)
    assert len(response.episodes.results) == 1


# Test 8: save preserves unrelated files in channel dir
def test_save_preserves_unrelated_files_in_channel_dir(tmp_path):
    channel_dir = tmp_path / "ch-slug"
    channel_dir.mkdir(parents=True, exist_ok=True)
    (channel_dir / "video.mp4").write_bytes(b"keep")

    save_channel_info(
        channel_slug="ch-slug",
        channel_data=_channel(),
        episodes_data=_episodes(),
        output_directory=tmp_path,
    )

    assert (channel_dir / "video.mp4").read_bytes() == b"keep"


# Test 9: save two channels are isolated
def test_save_two_channels_are_isolated(tmp_path):
    save_channel_info(
        channel_slug="ch-a",
        channel_data=_channel(slug="ch-a"),
        episodes_data=_episodes(_episode(slug="ep-a1"), _episode(slug="ep-a2")),
        output_directory=tmp_path,
    )

    save_channel_info(
        channel_slug="ch-b",
        channel_data=_channel(slug="ch-b"),
        episodes_data=_episodes(_episode(slug="ep-b1")),
        output_directory=tmp_path,
    )

    response_a = load_channel_info(channel_slug="ch-a", output_directory=tmp_path)
    assert len(response_a.episodes.results) == 2

    response_b = load_channel_info(channel_slug="ch-b", output_directory=tmp_path)
    assert len(response_b.episodes.results) == 1


# Test 10: load missing channel raises ChannelNotFoundError
def test_load_missing_channel_raises_ChannelNotFoundError(tmp_path):
    with pytest.raises(ChannelNotFoundError) as exc:
        load_channel_info(channel_slug="missing", output_directory=tmp_path)
    assert "missing" in str(exc.value)


# Test 11: load empty episode set returns empty results
def test_load_empty_episode_set_returns_empty_results(tmp_path):
    save_channel_info(
        channel_slug="ch-slug",
        channel_data=_channel(),
        episodes_data=_episodes(),
        output_directory=tmp_path,
    )

    response = load_channel_info(channel_slug="ch-slug", output_directory=tmp_path)
    assert response.episodes.results == []


# Test 12: load corrupt episode json raises
def test_load_corrupt_episode_json_raises(tmp_path):
    # Save valid channel first
    save_channel_info(
        channel_slug="ch-slug",
        channel_data=_channel(),
        episodes_data=_episodes(_episode()),
        output_directory=tmp_path,
    )

    # Corrupt an episode JSON directly in the database
    conn = _connect(tmp_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE episodes SET episode_json = ? WHERE channel_slug = ?",
            ("{not json", "ch-slug"),
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(json.JSONDecodeError):
        load_channel_info(channel_slug="ch-slug", output_directory=tmp_path)


# Test 13: roundtrip preserves nested model fields
def test_roundtrip_preserves_nested_model_fields(tmp_path):
    save_channel_info(
        channel_slug="ch-slug",
        channel_data=_channel(),
        episodes_data=_episodes(_episode()),
        output_directory=tmp_path,
    )

    response = load_channel_info(channel_slug="ch-slug", output_directory=tmp_path)
    episode = response.episodes.results[0]
    # Verify nested image fields roundtrip correctly
    assert str(episode.images.thumbnail.src) == "https://example.com/img.jpg"
    # Verify attributes list roundtrips correctly
    assert episode.attributes == [VideoNebulaAttributes.IS_NEBULA_PLUS]


# Test 14a: list_channel_slugs on empty db returns empty list
def test_list_channel_slugs_empty_db(tmp_path):
    from utils.db import list_channel_slugs
    result = list_channel_slugs(tmp_path)
    assert result == []


# Test 14b: list_channel_slugs returns all slugs sorted
def test_list_channel_slugs_returns_sorted_slugs(tmp_path):
    from utils.db import list_channel_slugs
    save_channel_info(
        channel_slug="zulu-ch",
        channel_data=_channel(slug="zulu-ch"),
        episodes_data=_episodes(),
        output_directory=tmp_path,
    )
    save_channel_info(
        channel_slug="alpha-ch",
        channel_data=_channel(slug="alpha-ch"),
        episodes_data=_episodes(),
        output_directory=tmp_path,
    )
    result = list_channel_slugs(tmp_path)
    assert result == ["alpha-ch", "zulu-ch"]


# Test 14: save is atomic on failure
def test_save_is_atomic_on_failure(tmp_path):
    # First save: 2 episodes (committed)
    save_channel_info(
        channel_slug="ch-slug",
        channel_data=_channel(),
        episodes_data=_episodes(_episode(slug="ep1"), _episode(slug="ep2")),
        output_directory=tmp_path,
    )

    response = load_channel_info(channel_slug="ch-slug", output_directory=tmp_path)
    assert len(response.episodes.results) == 2

    # Create wrapper classes to intercept and fail during episode INSERT
    class FailingCursor:
        def __init__(self, real_cursor, call_count_list, failed_list):
            self._real = real_cursor
            self._call_count = call_count_list
            self._failed = failed_list

        def execute(self, sql, params=None):
            self._call_count[0] += 1
            # Sequence: call 1=channel insert, call 2=delete, call 3+=episode inserts
            # Fail on first episode INSERT (call 3)
            if "INSERT INTO episodes" in sql and self._call_count[0] == 3:
                self._failed[0] = True
                raise sqlite3.OperationalError("Simulated INSERT failure during episode save")
            return self._real.execute(sql, params)

        def fetchall(self):
            return self._real.fetchall()

        def fetchone(self):
            return self._real.fetchone()

        def __getattr__(self, name):
            return getattr(self._real, name)

    class FailingConnection:
        def __init__(self, real_conn, call_count_list, failed_list):
            self._real = real_conn
            self._call_count = call_count_list
            self._failed = failed_list

        def cursor(self):
            return FailingCursor(self._real.cursor(), self._call_count, self._failed)

        def commit(self):
            return self._real.commit()

        def close(self):
            return self._real.close()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self._real.close()

        def __getattr__(self, name):
            return getattr(self._real, name)

    call_count = [0]
    insert_phase_failed = [False]
    original_connect_func = _connect

    def patched_connect(output_directory):
        conn = original_connect_func(output_directory)
        return FailingConnection(conn, call_count, insert_phase_failed)

    # Patch _connect and run second save with failure injection
    with patch("utils.db._connect", patched_connect):
        call_count[0] = 0

        # Second save attempt with 3 episodes - should fail during INSERT
        with pytest.raises(sqlite3.OperationalError):
            save_channel_info(
                channel_slug="ch-slug",
                channel_data=_channel(title="New Title"),
                episodes_data=_episodes(
                    _episode(slug="ep3"),
                    _episode(slug="ep4"),
                    _episode(slug="ep5"),
                ),
                output_directory=tmp_path,
            )

        # Confirm the patch fired during INSERT phase (proof it's not faked)
        assert insert_phase_failed[0], "Patch must fire during INSERT phase, not before"

    # Verify transaction rolled back: original state intact (2 episodes, original title)
    response = load_channel_info(channel_slug="ch-slug", output_directory=tmp_path)
    assert len(response.episodes.results) == 2
    assert response.details.title == "Channel"  # Original title unchanged
