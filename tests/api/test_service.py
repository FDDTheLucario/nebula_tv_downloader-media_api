from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from api.service import (
    _now,
    add_channel,
    check_all_channels,
    check_channel,
    episode_nfo_path,
    find_new_episodes,
    process_job,
    remove_channel,
    resolve_channels,
    seed_subscriptions_from_config,
)
from tests.api.conftest import make_content, make_episode
from utils import db, jobs_db
from utils.db import ChannelNotFoundError, load_channel_info, save_channel_info
from tests.models.nebula.test_channel import _channel_payload
from tests.models.nebula.test_episode import _episode_payload
from models.nebula.channel import NebulaChannelVideoContentDetails
from models.nebula.episode import NebulaChannelVideoContentEpisodeResult
from models.nebula.fetched import NebulaChannelVideoContentEpisodes


class Test_now:
    def test_now_returns_iso_format_string(self):
        """_now() returns a string in ISO format."""
        result = _now()
        assert isinstance(result, str)
        # Should be parseable as ISO datetime
        datetime.fromisoformat(result)


class TestEpisodeNfoPath:
    def test_episode_nfo_path_specials_for_original(self):
        """Episode with IS_NEBULA_ORIGINAL attribute -> path contains /Specials/"""
        ep = make_episode(attributes=["is_nebula_original"])
        download_path = Path("/tmp/media")
        path = episode_nfo_path(download_path, "ch-slug", ep)
        assert "Specials" in str(path)
        assert path.name == "ep-slug.nfo"

    def test_episode_nfo_path_season_for_regular(self):
        """Regular episode (no IS_NEBULA_ORIGINAL) -> path contains /Season <year>/"""
        ep = make_episode(
            attributes=["is_nebula_plus"],
            published_at="2023-06-15T10:00:00Z",
        )
        download_path = Path("/tmp/media")
        path = episode_nfo_path(download_path, "ch-slug", ep)
        assert "Season 2023" in str(path)
        assert path.name == "ep-slug.nfo"


class TestFindNewEpisodes:
    def test_find_new_episodes_returns_only_missing_nfo(self, tmp_path, config):
        """Episodes with existing NFO are excluded; others included."""
        download_path = tmp_path / "media"
        download_path.mkdir(parents=True, exist_ok=True)
        channel_slug = "ch-slug"
        ep1 = make_episode(slug="ep1", attributes=["is_nebula_plus"])
        ep2 = make_episode(slug="ep2", attributes=["is_nebula_plus"])
        content = make_content(ep1, ep2)

        # Create NFO for ep1
        nfo_path1 = episode_nfo_path(download_path, channel_slug, ep1)
        nfo_path1.parent.mkdir(parents=True, exist_ok=True)
        nfo_path1.touch()

        result = find_new_episodes(
            download_path, channel_slug, content, config.nebula_filters
        )
        slugs = [ep.slug for ep in result]
        assert "ep1" not in slugs
        assert "ep2" in slugs

    def test_find_new_episodes_applies_filters(self, tmp_path):
        """Episodes filtered out by filter_settings are excluded from results."""
        from models.configuration import ConfigurationNebulaFiltersModel

        download_path = tmp_path
        channel_slug = "ch-slug"

        # Regular video (empty attributes) — kept when include_regular_videos=True
        ep_regular = make_episode(slug="ep-regular", attributes=[])
        # Nebula Plus episode — excluded when include_nebula_plus=False
        ep_plus = make_episode(slug="ep-plus", attributes=["is_nebula_plus"])
        content = make_content(ep_regular, ep_plus)

        # Tight filter: regular videos only; exclude all special attributes
        tight_filters = ConfigurationNebulaFiltersModel(
            include_nebula_plus=False,
            include_nebula_first=False,
            include_nebula_originals=False,
            include_regular_videos=True,
        )

        result = find_new_episodes(download_path, channel_slug, content, tight_filters)
        slugs = [ep.slug for ep in result]

        assert "ep-regular" in slugs  # regular video passes through
        assert "ep-plus" not in slugs  # is_nebula_plus filtered out


class TestCheckChannel:
    def test_check_channel_enqueues_new_episodes(self, tmp_path, config, fake_auth):
        """check_channel fetches content, saves it, and enqueues new episodes."""
        download_path = tmp_path / "media"
        download_path.mkdir(parents=True, exist_ok=True)
        ep1 = make_episode(slug="ep1", attributes=["is_nebula_plus"])
        ep2 = make_episode(slug="ep2", attributes=["is_nebula_plus"])
        content = make_content(ep1, ep2)

        stub_fetch = Mock(return_value=content)
        result = check_channel("ch-slug", config, fake_auth, fetch=stub_fetch)

        # Should enqueue 2 jobs
        assert result == 2

        # Verify jobs were enqueued
        jobs = jobs_db.list_jobs(download_path)
        assert len(jobs) == 2
        slugs = {job["episode_slug"] for job in jobs}
        assert slugs == {"ep1", "ep2"}

        # Verify save_channel_info persisted the channel (spec: assert load_channel_info works)
        saved = load_channel_info("ch-slug", download_path)
        saved_ep_slugs = {ep.slug for ep in saved.episodes.results}
        assert saved_ep_slugs == {"ep1", "ep2"}

    def test_check_channel_skips_already_downloaded(self, tmp_path, config, fake_auth):
        """Episodes with existing NFO files are not enqueued."""
        download_path = tmp_path / "media"
        download_path.mkdir(parents=True, exist_ok=True)
        ep1 = make_episode(slug="ep1", attributes=["is_nebula_plus"])
        ep2 = make_episode(slug="ep2", attributes=["is_nebula_plus"])
        content = make_content(ep1, ep2)

        # Pre-create NFO for ep1
        nfo_path = download_path / "ch-slug" / "Season 2024" / "ep1" / "ep1.nfo"
        nfo_path.parent.mkdir(parents=True, exist_ok=True)
        nfo_path.touch()

        stub_fetch = Mock(return_value=content)
        result = check_channel("ch-slug", config, fake_auth, fetch=stub_fetch)

        # Should only enqueue ep2 (ep1 already exists)
        assert result == 1
        jobs = jobs_db.list_jobs(download_path)
        assert len(jobs) == 1
        assert jobs[0]["episode_slug"] == "ep2"

    def test_check_channel_sets_last_check_state(self, tmp_path, config, fake_auth):
        """check_channel sets the last_check:<slug> state."""
        download_path = tmp_path / "media"
        download_path.mkdir(parents=True, exist_ok=True)
        ep1 = make_episode(slug="ep1", attributes=["is_nebula_plus"])
        content = make_content(ep1)

        stub_fetch = Mock(return_value=content)
        check_channel("ch-slug", config, fake_auth, fetch=stub_fetch)

        state = jobs_db.get_state(download_path, "last_check:ch-slug")
        assert state is not None
        # Should be a valid ISO timestamp
        datetime.fromisoformat(state)

    def test_check_channel_idempotent_second_run_enqueues_zero(
        self, tmp_path, config, fake_auth
    ):
        """Second run with no new NFOs created -> enqueues 0 (jobs already queued)."""
        download_path = tmp_path / "media"
        download_path.mkdir(parents=True, exist_ok=True)
        ep1 = make_episode(slug="ep1", attributes=["is_nebula_plus"])
        ep2 = make_episode(slug="ep2", attributes=["is_nebula_plus"])
        content = make_content(ep1, ep2)

        stub_fetch = Mock(return_value=content)

        # First run
        result1 = check_channel("ch-slug", config, fake_auth, fetch=stub_fetch)
        assert result1 == 2

        # Second run without creating NFOs
        result2 = check_channel("ch-slug", config, fake_auth, fetch=stub_fetch)
        assert result2 == 0


class TestResolveChannels:
    def test_resolve_channels_uses_config_list(self, config, fake_auth):
        """If config has channels_to_parse, return it without calling feed."""
        stub_feed = Mock(side_effect=Exception("feed should not be called"))
        result = resolve_channels(config, fake_auth, feed=stub_feed)
        assert result == ["ch-slug"]
        stub_feed.assert_not_called()

    def test_resolve_channels_falls_back_to_feed(self, tmp_path, fake_auth):
        """If channels_to_parse is empty/None, call feed and return its result."""
        # Create a config with empty channels_to_parse
        config_dir = tmp_path / "cfg"
        config_dir.mkdir()
        config_file = config_dir / "config.ini"

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
channels_to_parse =

[downloader]
download_path = {str(tmp_path / "media")}
load_channel_data_from_db = false
skip_if_video_exists = true
check_interval_hours = 1
"""
        config_file.write_text(ini_content)

        from config.config import Config

        config = Config(config_file)
        stub_feed = Mock(return_value=["ch-from-feed"])
        result = resolve_channels(config, fake_auth, feed=stub_feed)
        assert result == ["ch-from-feed"]
        stub_feed.assert_called_once()


class TestCheckAllChannels:
    def test_check_all_channels_aggregates(self, tmp_path, config, fake_auth):
        """check_all_channels calls check_channel for each resolved channel."""
        download_path = tmp_path / "media"
        download_path.mkdir(parents=True, exist_ok=True)

        with patch("api.service.check_channel") as mock_check:
            mock_check.side_effect = [2, 3]  # Return counts for two channels

            result = check_all_channels(config, fake_auth)

            assert result == {"ch-slug": 2}  # config only has one channel
            assert mock_check.call_count == 1

        # Verify global last_check was set
        state = jobs_db.get_state(download_path, "last_check")
        assert state is not None
        datetime.fromisoformat(state)


class TestProcessJob:
    def test_process_job_invokes_downloader_with_episode(
        self, tmp_path, config, fake_auth
    ):
        """process_job invokes the downloader with correct args."""
        download_path = tmp_path / "media"
        download_path.mkdir(parents=True, exist_ok=True)

        ep = make_episode(slug="ep-slug", title="Episode Title")
        job = {
            "id": 1,
            "channel_slug": "ch-slug",
            "episode_slug": "ep-slug",
            "episode_json": ep.model_dump_json(),
            "state": "running",
            "error": None,
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
        }

        spy_downloader = Mock()
        process_job(job, config, fake_auth, downloader=spy_downloader)

        # Verify downloader was called once
        assert spy_downloader.call_count == 1
        call_args = spy_downloader.call_args
        channel_slug, channel_dir, episode, auth = call_args[0]

        assert channel_slug == "ch-slug"
        assert channel_dir == download_path / "ch-slug"
        assert episode.slug == "ep-slug"
        assert auth == fake_auth

        # Verify channel dir was created
        assert channel_dir.exists()

    def test_process_job_reconstructs_episode_from_json(
        self, tmp_path, config, fake_auth
    ):
        """Episode JSON round-trips correctly in process_job."""
        download_path = tmp_path / "media"
        download_path.mkdir(parents=True, exist_ok=True)

        ep = make_episode(slug="test-ep", title="Test Episode")
        job = {
            "id": 1,
            "channel_slug": "ch-slug",
            "episode_slug": "test-ep",
            "episode_json": ep.model_dump_json(),
            "state": "running",
            "error": None,
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
        }

        captured_episode = None

        def spy_downloader(ch_slug, ch_dir, episode, auth):
            nonlocal captured_episode
            captured_episode = episode

        process_job(job, config, fake_auth, downloader=spy_downloader)

        assert captured_episode is not None
        assert captured_episode.slug == "test-ep"
        assert captured_episode.title == "Test Episode"


# ── helpers for service module 3 tests ───────────────────────────────────────


def _make_channel_obj(**overrides):
    return NebulaChannelVideoContentDetails(**_channel_payload(**overrides))


def _make_episodes_obj(*episodes):
    return NebulaChannelVideoContentEpisodes(
        next=None, previous=None, results=list(episodes)
    )


def _make_episode_obj(**overrides):
    return NebulaChannelVideoContentEpisodeResult(**_episode_payload(**overrides))


def _config_with_empty_channels(tmp_path):
    """Return a config whose channels_to_parse is empty (for feed-fallback tests)."""
    config_dir = tmp_path / "cfg"
    config_dir.mkdir(exist_ok=True)
    config_file = config_dir / "config.ini"
    media_path = tmp_path / "media"
    config_file.write_text(
        f"""[nebula_api]
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
channels_to_parse =

[downloader]
download_path = {str(media_path)}
load_channel_data_from_db = false
skip_if_video_exists = true
check_interval_hours = 1
"""
    )
    from config.config import Config

    return Config(config_file)


class TestResolveChannelsSubscriptions:
    def test_resolve_channels_prefers_subscriptions(self, tmp_path, fake_auth):
        """Subscriptions table takes priority over config and feed."""
        # Build a config with channels_to_parse = ch-slug
        config_dir = tmp_path / "cfg2"
        config_dir.mkdir(exist_ok=True)
        config_file = config_dir / "config.ini"
        media_path = tmp_path / "media"
        config_file.write_text(
            f"""[nebula_api]
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
        )
        from config.config import Config

        config = Config(config_file)

        db.add_subscription(config.downloader.download_path, "sub-a")

        stub_feed = Mock(side_effect=Exception("feed must not be called"))
        result = resolve_channels(config, fake_auth, feed=stub_feed)
        assert result == ["sub-a"]
        stub_feed.assert_not_called()


class TestAddChannel:
    def test_add_channel_subscribes_and_checks(self, tmp_path, config, fake_auth):
        stub_check = Mock(return_value=3)
        result = add_channel(config, fake_auth, "newch", check=stub_check)
        assert result["added"] is True
        assert result["enqueued"] == 3
        assert result["error"] is None
        assert db.is_subscribed(config.downloader.download_path, "newch") is True

    def test_add_channel_check_failure_keeps_subscription(
        self, tmp_path, config, fake_auth
    ):
        stub_check = Mock(side_effect=RuntimeError("boom"))
        result = add_channel(config, fake_auth, "ch-err", check=stub_check)
        assert result["error"] == "boom"
        assert result["enqueued"] is None
        assert result["added"] is True
        assert db.is_subscribed(config.downloader.download_path, "ch-err") is True

    def test_add_channel_duplicate_added_false(self, tmp_path, config, fake_auth):
        db.add_subscription(config.downloader.download_path, "dup")
        stub_check = Mock(return_value=0)
        result = add_channel(config, fake_auth, "dup", check=stub_check)
        assert result["added"] is False
        assert result["enqueued"] == 0

    def test_add_channel_empty_slug_raises(self, tmp_path, config, fake_auth):
        with pytest.raises(ValueError):
            add_channel(config, fake_auth, "  ")


class TestRemoveChannel:
    def test_remove_channel_keeps_data_by_default(self, tmp_path, config, fake_auth):
        download_path = config.downloader.download_path
        download_path.mkdir(parents=True, exist_ok=True)
        ch_slug = "rm-ch"
        save_channel_info(
            ch_slug,
            _make_channel_obj(slug=ch_slug),
            _make_episodes_obj(_make_episode_obj(slug="ep1")),
            download_path,
        )
        db.add_subscription(download_path, ch_slug)
        jobs_db.enqueue_job(download_path, ch_slug, "ep1", '{"slug": "ep1"}')
        jobs_db.set_state(download_path, f"last_check:{ch_slug}", "ts")

        result = remove_channel(config, ch_slug)
        assert result["removed"] is True
        assert result["data_deleted"] is False
        assert db.is_subscribed(download_path, ch_slug) is False
        # data must still be there
        loaded = load_channel_info(ch_slug, download_path)
        assert len(loaded.episodes.results) == 1
        assert len(jobs_db.list_jobs(download_path)) == 1
        assert jobs_db.get_state(download_path, f"last_check:{ch_slug}") == "ts"

    def test_remove_channel_delete_data_purges(self, tmp_path, config, fake_auth):
        download_path = config.downloader.download_path
        download_path.mkdir(parents=True, exist_ok=True)
        ch_slug = "rm-ch"
        save_channel_info(
            ch_slug,
            _make_channel_obj(slug=ch_slug),
            _make_episodes_obj(_make_episode_obj(slug="ep1")),
            download_path,
        )
        db.add_subscription(download_path, ch_slug)
        jobs_db.enqueue_job(download_path, ch_slug, "ep1", '{"slug": "ep1"}')
        jobs_db.set_state(download_path, f"last_check:{ch_slug}", "ts")

        result = remove_channel(config, ch_slug, delete_data=True)
        assert result["removed"] is True
        assert result["data_deleted"] is True
        assert db.is_subscribed(download_path, ch_slug) is False
        with pytest.raises(ChannelNotFoundError):
            load_channel_info(ch_slug, download_path)
        assert len(jobs_db.list_jobs(download_path)) == 0
        assert jobs_db.get_state(download_path, f"last_check:{ch_slug}") is None

    def test_remove_channel_absent(self, tmp_path, config, fake_auth):
        result = remove_channel(config, "ghost")
        assert result["removed"] is False
        assert result["data_deleted"] is False


class TestSeedSubscriptions:
    def test_seed_subscriptions_from_config_seeds_when_empty(
        self, tmp_path, config, fake_auth
    ):
        # config fixture has channels_to_parse = ch-slug
        count = seed_subscriptions_from_config(config)
        assert count == 1
        assert db.list_subscriptions(config.downloader.download_path) == ["ch-slug"]

    def test_seed_subscriptions_idempotent(self, tmp_path, config, fake_auth):
        db.add_subscription(config.downloader.download_path, "existing")
        count = seed_subscriptions_from_config(config)
        assert count == 0
        # "ch-slug" from config must NOT have been added
        subs = db.list_subscriptions(config.downloader.download_path)
        assert "ch-slug" not in subs
        assert "existing" in subs


def _save_local_channel(download_path, slug, title=None):
    """Persist a channel row (no episodes) for search/local tests."""
    details = NebulaChannelVideoContentDetails(
        **_channel_payload(slug=slug, title=title or slug)
    )
    episodes = NebulaChannelVideoContentEpisodes(next=None, previous=None, results=[])
    save_channel_info(
        channel_slug=slug,
        channel_data=details,
        episodes_data=episodes,
        output_directory=download_path,
    )


FIXED_NOW = "2026-06-07T00:00:00"


def _now_stub(value=FIXED_NOW):
    return lambda: value


class TestGetCachedDirectory:
    def test_fetches_when_empty(self, config, fake_auth):
        from api.service import get_cached_directory
        from models.nebula.channel_directory import NebulaChannelDirectoryResult

        dp = config.downloader.download_path
        stub = Mock(
            return_value=[
                NebulaChannelDirectoryResult(slug="a", title="A"),
                NebulaChannelDirectoryResult(slug="b", title="B"),
            ]
        )
        out = get_cached_directory(config, fake_auth, fetch=stub, now=_now_stub())
        assert [c["slug"] for c in out] == ["a", "b"]
        assert all(set(c) == {"slug", "title", "avatar_url"} for c in out)
        stub.assert_called_once()
        cached = jobs_db.get_state(dp, "channel_directory_cache")
        assert cached is not None and "a" in cached

    def test_serves_fresh_cache(self, config, fake_auth):
        import json

        from api.service import get_cached_directory

        dp = config.downloader.download_path
        jobs_db.set_state(
            dp,
            "channel_directory_cache",
            json.dumps(
                {
                    "fetched_at": "2026-06-06T23:59:00",
                    "channels": [{"slug": "x", "title": "X", "avatar_url": None}],
                }
            ),
        )

        def boom(*a, **k):
            raise AssertionError("should not fetch")

        out = get_cached_directory(config, fake_auth, fetch=boom, now=_now_stub())
        assert [c["slug"] for c in out] == ["x"]

    def test_refetches_when_stale(self, config, fake_auth):
        import json

        from api.service import get_cached_directory
        from models.nebula.channel_directory import NebulaChannelDirectoryResult

        dp = config.downloader.download_path
        jobs_db.set_state(
            dp,
            "channel_directory_cache",
            json.dumps(
                {
                    "fetched_at": "2026-06-06T00:00:00",
                    "channels": [{"slug": "old", "title": "Old", "avatar_url": None}],
                }
            ),
        )
        stub = Mock(return_value=[NebulaChannelDirectoryResult(slug="new", title="New")])
        out = get_cached_directory(config, fake_auth, fetch=stub, now=_now_stub())
        assert [c["slug"] for c in out] == ["new"]
        stub.assert_called_once()

    def test_force_refetches(self, config, fake_auth):
        import json

        from api.service import get_cached_directory
        from models.nebula.channel_directory import NebulaChannelDirectoryResult

        dp = config.downloader.download_path
        jobs_db.set_state(
            dp,
            "channel_directory_cache",
            json.dumps(
                {
                    "fetched_at": "2026-06-06T23:59:00",
                    "channels": [{"slug": "x", "title": "X", "avatar_url": None}],
                }
            ),
        )
        stub = Mock(return_value=[NebulaChannelDirectoryResult(slug="y", title="Y")])
        out = get_cached_directory(
            config, fake_auth, fetch=stub, now=_now_stub(), force=True
        )
        assert [c["slug"] for c in out] == ["y"]
        stub.assert_called_once()

    def test_fetch_error_returns_stale(self, config, fake_auth):
        import json

        from api.service import get_cached_directory

        dp = config.downloader.download_path
        jobs_db.set_state(
            dp,
            "channel_directory_cache",
            json.dumps(
                {
                    "fetched_at": "2026-06-06T00:00:00",
                    "channels": [{"slug": "stale", "title": "S", "avatar_url": None}],
                }
            ),
        )

        def boom(*a, **k):
            raise RuntimeError("down")

        out = get_cached_directory(config, fake_auth, fetch=boom, now=_now_stub())
        assert [c["slug"] for c in out] == ["stale"]

    def test_fetch_error_no_cache_returns_empty(self, config, fake_auth):
        from api.service import get_cached_directory

        def boom(*a, **k):
            raise RuntimeError("down")

        out = get_cached_directory(config, fake_auth, fetch=boom, now=_now_stub())
        assert out == []

    def test_corrupt_cache_refetches(self, config, fake_auth):
        from api.service import get_cached_directory
        from models.nebula.channel_directory import NebulaChannelDirectoryResult

        dp = config.downloader.download_path
        jobs_db.set_state(dp, "channel_directory_cache", "not-json{")
        stub = Mock(return_value=[NebulaChannelDirectoryResult(slug="z", title="Z")])
        out = get_cached_directory(config, fake_auth, fetch=stub, now=_now_stub())
        assert [c["slug"] for c in out] == ["z"]


def _dir_stub(*items):
    """Return a directory() replacement yielding {slug,title,avatar_url} dicts."""
    rows = [
        {"slug": s, "title": t, "avatar_url": None}
        for s, t in items
    ]
    return Mock(return_value=rows)


class TestSearchChannels:
    def test_empty_query_returns_empty(self, config, fake_auth):
        from api.service import search_channels

        stub = Mock(side_effect=AssertionError("should not be called"))
        assert search_channels(config, fake_auth, "", directory=stub) == []
        assert search_channels(config, fake_auth, "   ", directory=stub) == []

    def test_matches_slug_substring(self, config, fake_auth):
        from api.service import search_channels

        directory = _dir_stub(
            ("jetlag", "Jetlag"),
            ("jet-lag-the-game", "Jet Lag The Game"),
            ("legaleagle", "LegalEagle"),
        )
        out = search_channels(config, fake_auth, "jet", directory=directory)
        slugs = {r["slug"] for r in out}
        assert slugs == {"jetlag", "jet-lag-the-game"}

    def test_matches_title_substring(self, config, fake_auth):
        from api.service import search_channels

        directory = _dir_stub(("tlg", "Jet Lag: The Game"))
        out = search_channels(config, fake_auth, "lag", directory=directory)
        assert [r["slug"] for r in out] == ["tlg"]

    def test_title_prefix_outranks_substring(self, config, fake_auth):
        from api.service import search_channels

        directory = _dir_stub(
            ("xyz", "Jet Lag: The Game"),  # "lag" only as substring -> rank 3
            ("abc", "Lag Masters"),  # title startswith "lag" -> rank 2
        )
        out = search_channels(config, fake_auth, "lag", directory=directory)
        assert [r["slug"] for r in out] == ["abc", "xyz"]

    def test_ranking_exact_then_prefix(self, config, fake_auth):
        from api.service import search_channels

        directory = _dir_stub(
            ("superjet", "Superjet"),
            ("jetlag", "Jetlag"),
            ("jet", "Jet"),
        )
        out = search_channels(config, fake_auth, "jet", directory=directory)
        assert [r["slug"] for r in out] == ["jet", "jetlag", "superjet"]

    def test_respects_limit(self, config, fake_auth):
        from api.service import search_channels

        directory = _dir_stub(*[(f"jet{i:02d}", f"Jet {i}") for i in range(20)])
        out = search_channels(config, fake_auth, "jet", directory=directory, limit=5)
        assert len(out) == 5

    def test_local_first_and_marks_subscribed(self, config, fake_auth):
        from api.service import search_channels

        dp = config.downloader.download_path
        _save_local_channel(dp, "jetlag", title="Local Jetlag")
        db.add_subscription(dp, "jetlag")
        directory = _dir_stub(("jetlag", "Remote Jetlag"))
        out = search_channels(config, fake_auth, "jet", directory=directory)
        assert len(out) == 1
        row = out[0]
        assert row["slug"] == "jetlag"
        assert row["source"] == "local"
        assert row["title"] == "Local Jetlag"
        assert row["subscribed"] is True

    def test_includes_remote_only(self, config, fake_auth):
        from api.service import search_channels

        directory = _dir_stub(("remoteonly", "Remote Only"))
        out = search_channels(config, fake_auth, "remote", directory=directory)
        assert len(out) == 1
        assert out[0]["source"] == "remote"
        assert out[0]["subscribed"] is False

    def test_subscription_only_local_match(self, config, fake_auth):
        from api.service import search_channels

        dp = config.downloader.download_path
        db.add_subscription(dp, "subonly")
        directory = _dir_stub()
        out = search_channels(config, fake_auth, "subonly", directory=directory)
        assert len(out) == 1
        assert out[0]["slug"] == "subonly"
        assert out[0]["source"] == "local"

    def test_case_insensitive(self, config, fake_auth):
        from api.service import search_channels

        directory = _dir_stub(("jetlag", "Jetlag"))
        out = search_channels(config, fake_auth, "JET", directory=directory)
        assert [r["slug"] for r in out] == ["jetlag"]

    def test_directory_failure_still_returns_local(self, config, fake_auth):
        from api.service import search_channels

        dp = config.downloader.download_path
        _save_local_channel(dp, "jetlag", title="Jetlag")
        directory = _dir_stub()  # simulate outage -> empty
        out = search_channels(config, fake_auth, "jet", directory=directory)
        assert [r["slug"] for r in out] == ["jetlag"]
