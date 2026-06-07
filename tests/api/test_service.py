from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from api.service import (
    _now,
    check_all_channels,
    check_channel,
    episode_nfo_path,
    find_new_episodes,
    process_job,
    resolve_channels,
)
from tests.api.conftest import make_content, make_episode
from utils import jobs_db
from utils.db import load_channel_info


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

        assert "ep-regular" in slugs   # regular video passes through
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
