from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

import main
from models.nebula.channel import NebulaChannelVideoContentDetails
from models.nebula.episode import NebulaChannelVideoContentEpisodeResult
from models.nebula.fetched import (
    NebulaChannelVideoContentEpisodes,
    NebulaChannelVideoContentResponseModel,
)
from models.nebula.streaming import (
    NebulaVideoContentStreamingResponseModel,
    NebulaVideoContentStreamSubtitles,
)
from tests.models.nebula.test_channel import _channel_payload
from tests.models.nebula.test_episode import _episode_payload


def _episode(**overrides):
    return NebulaChannelVideoContentEpisodeResult(**_episode_payload(**overrides))


def _channel(**overrides):
    images = {
        "banner": {"src": "https://example.com/banner.jpg"},
        "avatar": {"src": "https://example.com/avatar.jpg"},
    }
    return NebulaChannelVideoContentDetails(**_channel_payload(images=images, **overrides))


def _response(channel_overrides=None, episodes=()):
    return NebulaChannelVideoContentResponseModel(
        details=_channel(**(channel_overrides or {})),
        episodes=NebulaChannelVideoContentEpisodes(
            next=None, previous=None, results=list(episodes)
        ),
    )


def _streaming():
    return NebulaVideoContentStreamingResponseModel(
        manifest="https://example.com/manifest.m3u8",
        download=None,
        iframe=None,
        bif={},
        subtitles=[
            NebulaVideoContentStreamSubtitles(
                language_code="en",
                url="https://example.com/sub.vtt",
                language="English",
            )
        ],
    )


def _make_config(
    channels_to_parse=None,
    category_search=None,
    load_from_db=False,
    download_path=Path("/tmp/unused"),
    token_refresh_interval_hours=6,
    include_nebula_originals=True,
    include_nebula_plus=True,
    include_nebula_first=True,
    include_regular_videos=False,
):
    config = MagicMock()
    config.nebula_api.user_api_token = "tok"
    config.nebula_api.authorization_header = "hdr"
    config.nebula_api.token_refresh_interval_hours = token_refresh_interval_hours
    config.nebula_filters.channels_to_parse = channels_to_parse
    config.nebula_filters.category_search = category_search
    config.nebula_filters.include_nebula_originals = include_nebula_originals
    config.nebula_filters.include_nebula_plus = include_nebula_plus
    config.nebula_filters.include_nebula_first = include_nebula_first
    config.nebula_filters.include_regular_videos = include_regular_videos
    config.downloader.load_channel_data_from_db = load_from_db
    config.downloader.download_path = download_path
    return config


def _make_auth(header: str = "hdr"):
    auth = MagicMock()
    auth.get_authorization_header.return_value = f"Bearer {header}"
    return auth


# ---------- remove_downloaded_episodes_from_results ----------


def test_remove_downloaded_episodes_all_missing_returns_all(tmp_path):
    season_dir = tmp_path / "Season 2024"
    season_dir.mkdir()
    structure = {2024: season_dir}
    episodes = [_episode(slug="a"), _episode(slug="b")]

    result = main.remove_downloaded_episodes_from_results(episodes, structure)
    assert [e.slug for e in result] == ["a", "b"]


def test_remove_downloaded_episodes_skips_already_downloaded(tmp_path):
    season_dir = tmp_path / "Season 2024"
    (season_dir / "a").mkdir(parents=True)
    (season_dir / "a" / "a.nfo").write_text("<x/>")
    (season_dir / "b").mkdir()
    structure = {2024: season_dir}
    episodes = [_episode(slug="a"), _episode(slug="b")]

    result = main.remove_downloaded_episodes_from_results(episodes, structure)
    assert [e.slug for e in result] == ["b"]


def test_remove_downloaded_episodes_groups_by_publication_year(tmp_path):
    dir_2023 = tmp_path / "Season 2023"
    dir_2024 = tmp_path / "Season 2024"
    dir_2023.mkdir()
    dir_2024.mkdir()
    (dir_2023 / "a").mkdir()
    (dir_2023 / "a" / "a.nfo").write_text("<x/>")
    structure = {2023: dir_2023, 2024: dir_2024}
    episodes = [
        _episode(slug="a", published_at="2023-06-01T00:00:00Z"),
        _episode(slug="b", published_at="2024-06-01T00:00:00Z"),
    ]

    result = main.remove_downloaded_episodes_from_results(episodes, structure)
    assert [e.slug for e in result] == ["b"]


# ---------- create_directory_structure_for_channel ----------


def test_create_directory_structure_writes_nfo_and_thumbnails_per_year(mocker, tmp_path):
    mock_thumb = mocker.patch.object(main, "download_thumbnail")
    mock_nfo = mocker.patch.object(main, "create_nfo_for_channel")
    response = _response()
    channel_dir = tmp_path / "ch-slug"
    channel_dir.mkdir()

    structure = main.create_directory_structure_for_channel(
        "ch-slug", response, channel_dir, {2023, 2024}
    )

    mock_nfo.assert_called_once_with(
        channel_data=response.details, channel_directory=channel_dir
    )
    thumb_targets = {c.args[1] for c in mock_thumb.call_args_list}
    assert channel_dir / "backdrop.jpg" in thumb_targets
    assert channel_dir / "logo.jpg" in thumb_targets
    assert channel_dir / "ch-slug.jpg" in thumb_targets
    assert channel_dir / "season2023-poster.jpg" in thumb_targets
    assert channel_dir / "season2024-poster.jpg" in thumb_targets

    assert (channel_dir / "Season 2023").is_dir()
    assert (channel_dir / "Season 2024").is_dir()
    assert structure[2023] == channel_dir / "Season 2023"
    assert structure[2024] == channel_dir / "Season 2024"


def test_create_directory_structure_no_years_skips_season_dirs(mocker, tmp_path):
    mocker.patch.object(main, "download_thumbnail")
    mocker.patch.object(main, "create_nfo_for_channel")
    channel_dir = tmp_path / "ch-slug"
    channel_dir.mkdir()

    structure = main.create_directory_structure_for_channel(
        "ch-slug", _response(), channel_dir, set()
    )

    assert dict(structure) == {}
    assert not any(p.name.startswith("Season ") for p in channel_dir.iterdir())


# ---------- download_episode ----------


def test_download_episode_original_uses_specials_dir(mocker, tmp_path):
    mocker.patch.object(main, "download_thumbnail")
    mocker.patch.object(main, "download_video")
    mocker.patch.object(main, "download_subtitles")
    mocker.patch.object(main, "create_nfo_for_video")
    mocker.patch.object(main, "get_streaming_information_by_episode", return_value=_streaming())

    episode = _episode(slug="ep", attributes=["is_nebula_original"])
    main.download_episode("ch", tmp_path, episode, _make_auth())
    assert (tmp_path / "Specials" / "ep").is_dir()


def test_download_episode_non_original_uses_season_year_dir(mocker, tmp_path):
    mocker.patch.object(main, "download_thumbnail")
    mocker.patch.object(main, "download_video")
    mocker.patch.object(main, "download_subtitles")
    mocker.patch.object(main, "create_nfo_for_video")
    mocker.patch.object(main, "get_streaming_information_by_episode", return_value=_streaming())

    episode = _episode(slug="ep", attributes=["is_nebula_plus"], published_at="2024-03-01T00:00:00Z")
    main.download_episode("ch", tmp_path, episode, _make_auth())
    assert (tmp_path / "Season 2024" / "ep").is_dir()


def test_download_episode_skips_download_video_when_file_exists(mocker, tmp_path):
    mocker.patch.object(main, "download_thumbnail")
    mock_download_video = mocker.patch.object(main, "download_video")
    mocker.patch.object(main, "download_subtitles")
    mocker.patch.object(main, "create_nfo_for_video")
    mocker.patch.object(main, "get_streaming_information_by_episode", return_value=_streaming())

    episode = _episode(slug="ep", attributes=["is_nebula_plus"], published_at="2024-03-01T00:00:00Z")
    season_dir = tmp_path / "Season 2024" / "ep"
    season_dir.mkdir(parents=True)
    (season_dir / "ep").write_bytes(b"already downloaded")

    main.download_episode("ch", tmp_path, episode, _make_auth())
    mock_download_video.assert_not_called()


def test_download_episode_invokes_subtitles_and_nfo(mocker, tmp_path):
    mocker.patch.object(main, "download_thumbnail")
    mocker.patch.object(main, "download_video")
    mock_subs = mocker.patch.object(main, "download_subtitles")
    mock_nfo = mocker.patch.object(main, "create_nfo_for_video")
    streaming = _streaming()
    mocker.patch.object(main, "get_streaming_information_by_episode", return_value=streaming)

    episode = _episode(slug="ep", attributes=[], published_at="2024-03-01T00:00:00Z")
    main.download_episode("ch", tmp_path, episode, _make_auth())
    mock_subs.assert_called_once_with(
        subtitles=streaming.subtitles,
        output_directory=tmp_path / "Season 2024" / "ep",
    )
    mock_nfo.assert_called_once_with(episode, tmp_path / "Season 2024" / "ep")


# ---------- main ----------


def test_main_uses_configured_channels_when_set(mocker, tmp_path):
    config = _make_config(channels_to_parse=["ch1"], download_path=tmp_path)
    auth = _make_auth()
    mock_feed = mocker.patch.object(main, "get_all_channels_slugs_from_video_feed")
    mocker.patch.object(main, "get_channel_video_content", return_value=_response())
    mocker.patch.object(main, "save_channel_info", return_value=tmp_path / "ch1")
    mocker.patch.object(
        main, "create_directory_structure_for_channel", return_value={}
    )
    mocker.patch.object(main, "remove_downloaded_episodes_from_results", return_value=[])

    main.main(config=config, auth=auth)
    mock_feed.assert_not_called()


def test_main_falls_back_to_video_feed_when_no_channels_configured(mocker, tmp_path):
    config = _make_config(channels_to_parse=None, download_path=tmp_path)
    auth = _make_auth()
    mock_feed = mocker.patch.object(
        main, "get_all_channels_slugs_from_video_feed", return_value=["ch1"]
    )
    mocker.patch.object(main, "get_channel_video_content", return_value=_response())
    mocker.patch.object(main, "save_channel_info", return_value=tmp_path / "ch1")
    mocker.patch.object(main, "create_directory_structure_for_channel", return_value={})
    mocker.patch.object(main, "remove_downloaded_episodes_from_results", return_value=[])

    main.main(config=config, auth=auth)
    mock_feed.assert_called_once()
    assert mock_feed.call_args.kwargs["category_feed_selector"] is None
    assert mock_feed.call_args.kwargs["cursor_times_limit_fetch_maximum"] == 1


def test_main_loads_channel_from_db_when_flag_set(mocker, tmp_path):
    config = _make_config(channels_to_parse=["ch1"], load_from_db=True, download_path=tmp_path)
    auth = _make_auth()
    mock_load = mocker.patch.object(main, "load_channel_info", return_value=_response())
    mock_remote = mocker.patch.object(main, "get_channel_video_content")
    mocker.patch.object(main, "save_channel_info", return_value=tmp_path / "ch1")
    mocker.patch.object(main, "create_directory_structure_for_channel", return_value={})
    mocker.patch.object(main, "remove_downloaded_episodes_from_results", return_value=[])

    main.main(config=config, auth=auth)
    mock_load.assert_called_once_with(channel_slug="ch1", output_directory=tmp_path)
    mock_remote.assert_not_called()


def test_main_fetches_channel_remotely_when_flag_unset(mocker, tmp_path):
    config = _make_config(channels_to_parse=["ch1"], load_from_db=False, download_path=tmp_path)
    auth = _make_auth()
    mock_load = mocker.patch.object(main, "load_channel_info")
    mock_remote = mocker.patch.object(main, "get_channel_video_content", return_value=_response())
    mocker.patch.object(main, "save_channel_info", return_value=tmp_path / "ch1")
    mocker.patch.object(main, "create_directory_structure_for_channel", return_value={})
    mocker.patch.object(main, "remove_downloaded_episodes_from_results", return_value=[])

    main.main(config=config, auth=auth)
    mock_remote.assert_called_once_with(
        channel_slug="ch1", authorization_header="Bearer hdr"
    )
    mock_load.assert_not_called()


def test_main_downloads_each_pending_episode(mocker, tmp_path):
    config = _make_config(channels_to_parse=["ch1"], download_path=tmp_path)
    auth = _make_auth()
    pending = [_episode(slug="a"), _episode(slug="b")]
    mocker.patch.object(main, "get_channel_video_content", return_value=_response(episodes=pending))
    mocker.patch.object(main, "save_channel_info", return_value=tmp_path / "ch1")
    mocker.patch.object(main, "create_directory_structure_for_channel", return_value={})
    mocker.patch.object(main, "remove_downloaded_episodes_from_results", return_value=pending)
    mock_download = mocker.patch.object(main, "download_episode")

    main.main(config=config, auth=auth)
    assert mock_download.call_count == 2
    assert mock_download.call_args_list == [
        call("ch1", tmp_path / "ch1", pending[0], auth),
        call("ch1", tmp_path / "ch1", pending[1], auth),
    ]


def test_main_refreshes_token_after_interval_elapses(mocker, tmp_path):
    config = _make_config(
        channels_to_parse=["ch1"],
        download_path=tmp_path,
        token_refresh_interval_hours=1,
    )
    auth = _make_auth()
    pending = [_episode(slug="a"), _episode(slug="b")]
    mocker.patch.object(main, "get_channel_video_content", return_value=_response(episodes=pending))
    mocker.patch.object(main, "save_channel_info", return_value=tmp_path / "ch1")
    mocker.patch.object(main, "create_directory_structure_for_channel", return_value={})
    mocker.patch.object(main, "remove_downloaded_episodes_from_results", return_value=pending)
    mocker.patch.object(main, "download_episode")

    base = datetime(2024, 1, 1, 12, 0, 0)
    later = base + timedelta(hours=2)
    times = iter([base, later, later, later])

    class _StubDatetime:
        @staticmethod
        def now():
            return next(times)

        @staticmethod
        def fromisoformat(s):
            return datetime.fromisoformat(s)

    mocker.patch.object(main, "datetime", _StubDatetime)
    main.main(config=config, auth=auth)
    auth.refresh_authorization_token.assert_called_once()
