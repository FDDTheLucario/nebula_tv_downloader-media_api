from pathlib import Path

import pytest

from config.config import Config, QuotedConfigParser


def _write_config(tmp_path: Path, text: str) -> Path:
    cfg = tmp_path / "config.ini"
    cfg.write_text(text)
    return cfg


_FULL_INI = """\
[nebula_api]
user_api_token = "abc-token"
authorization_header = "bearer-token"
user_agent = "test-agent"
token_refresh_interval_hours = 12

[nebula_filters]
category_search = news
include_nebula_first = true
include_nebula_plus = true
include_nebula_originals = false
include_regular_videos = true
channels_to_parse = nilered,tldrnewsuk

[downloader]
download_path = /tmp/downloads
load_channel_data_from_db = false
skip_if_video_exists = true
"""


def test_quoted_config_parser_strips_double_quotes(tmp_path):
    cfg = _write_config(tmp_path, '[s]\nk = "value"\n')
    parser = QuotedConfigParser()
    parser.read(cfg)
    assert parser.get("s", "k") == "value"


def test_quoted_config_parser_strips_single_quotes(tmp_path):
    cfg = _write_config(tmp_path, "[s]\nk = 'value'\n")
    parser = QuotedConfigParser()
    parser.read(cfg)
    assert parser.get("s", "k") == "value"


def test_quoted_config_parser_passes_unquoted_through(tmp_path):
    cfg = _write_config(tmp_path, "[s]\nk = value\n")
    parser = QuotedConfigParser()
    parser.read(cfg)
    assert parser.get("s", "k") == "value"


def test_config_full_parsing_from_file(tmp_path):
    cfg_path = _write_config(tmp_path, _FULL_INI)
    config = Config(cfg_path)

    assert config.nebula_api.user_api_token == "abc-token"
    assert config.nebula_api.authorization_header == "bearer-token"
    assert config.nebula_api.user_agent == "test-agent"
    assert config.nebula_api.token_refresh_interval_hours == 12

    assert config.nebula_filters.category_search == "news"
    assert config.nebula_filters.include_nebula_first is True
    assert config.nebula_filters.include_nebula_originals is False
    assert config.nebula_filters.include_regular_videos is True
    assert config.nebula_filters.channels_to_parse == ["nilered", "tldrnewsuk"]

    assert config.downloader.download_path == Path("/tmp/downloads")
    assert config.downloader.load_channel_data_from_db is False
    assert config.downloader.skip_if_video_exists is True


def test_config_category_search_false_string_becomes_none(tmp_path):
    ini = _FULL_INI.replace("category_search = news", "category_search = false")
    cfg_path = _write_config(tmp_path, ini)
    config = Config(cfg_path)
    assert config.nebula_filters.category_search is None


def test_config_empty_authorization_header_normalized_to_none(tmp_path):
    ini = _FULL_INI.replace('authorization_header = "bearer-token"', "authorization_header = ")
    cfg_path = _write_config(tmp_path, ini)
    config = Config(cfg_path)
    assert config.nebula_api.authorization_header is None


def test_config_empty_channels_to_parse_becomes_none(tmp_path):
    ini = _FULL_INI.replace("channels_to_parse = nilered,tldrnewsuk", "channels_to_parse = ")
    cfg_path = _write_config(tmp_path, ini)
    config = Config(cfg_path)
    assert config.nebula_filters.channels_to_parse is None


def test_config_set_authorization_token_mutates_in_place(tmp_path):
    cfg_path = _write_config(tmp_path, _FULL_INI)
    config = Config(cfg_path)
    config.set_nebula_authorization_token("new-token")
    assert config.nebula_api.authorization_header == "new-token"


def test_config_missing_section_raises(tmp_path):
    bad = _FULL_INI.split("[downloader]")[0]
    cfg_path = _write_config(tmp_path, bad)
    with pytest.raises(Exception):
        Config(cfg_path)


def test_config_check_interval_hours_default_is_1(tmp_path):
    # Config without check_interval_hours should default to 1
    ini = _FULL_INI  # _FULL_INI doesn't have check_interval_hours
    cfg_path = _write_config(tmp_path, ini)
    config = Config(cfg_path)
    assert config.downloader.check_interval_hours == 1


def test_config_check_interval_hours_parsed_override(tmp_path):
    # Config with check_interval_hours set to 3
    ini = _FULL_INI + "check_interval_hours = 3\n"
    cfg_path = _write_config(tmp_path, ini)
    config = Config(cfg_path)
    assert config.downloader.check_interval_hours == 3


def test_as_view_omits_token_and_exposes_values(tmp_path):
    cfg_path = _write_config(tmp_path, _FULL_INI)
    config = Config(cfg_path)
    view = config.as_view()

    assert "user_api_token" not in view["nebula_api"]
    assert view["nebula_api"]["has_token"] is True
    assert view["nebula_api"]["authorization_header"] == "bearer-token"
    assert view["nebula_filters"]["channels_to_parse"] == "nilered,tldrnewsuk"
    assert view["nebula_filters"]["category_search"] == "news"
    assert view["downloader"]["download_path"] == "/tmp/downloads"
    assert view["downloader"]["check_interval_hours"] == 1


def test_apply_updates_persists_and_mutates_in_place(tmp_path):
    cfg_path = _write_config(tmp_path, _FULL_INI)
    config = Config(cfg_path)

    config.apply_updates(
        {
            "user_api_token": "new-token",
            "authorization_header": "",
            "user_agent": "agent2",
            "token_refresh_interval_hours": "8",
            "category_search": "false",
            "include_nebula_first": "true",
            "include_nebula_plus": "",
            "include_nebula_originals": "true",
            "include_regular_videos": "",
            "channels_to_parse": "a, b ,,c",
            "download_path": "/tmp/new",
            "load_channel_data_from_db": "true",
            "skip_if_video_exists": "",
            "check_interval_hours": "5",
        }
    )

    # In-memory mutation
    assert config.nebula_api.user_api_token == "new-token"
    assert config.nebula_api.authorization_header is None
    assert config.nebula_api.token_refresh_interval_hours == 8
    assert config.nebula_filters.category_search is None
    assert config.nebula_filters.include_nebula_first is True
    assert config.nebula_filters.include_nebula_plus is False
    assert config.nebula_filters.channels_to_parse == ["a", "b", "c"]
    assert config.downloader.download_path == Path("/tmp/new")
    assert config.downloader.load_channel_data_from_db is True
    assert config.downloader.skip_if_video_exists is False
    assert config.downloader.check_interval_hours == 5

    # Persisted to disk: reloading yields the same values
    reloaded = Config(cfg_path)
    assert reloaded.nebula_api.user_api_token == "new-token"
    assert reloaded.nebula_filters.channels_to_parse == ["a", "b", "c"]
    assert reloaded.downloader.check_interval_hours == 5
    assert reloaded.nebula_filters.category_search is None


def test_apply_updates_blank_token_keeps_existing(tmp_path):
    cfg_path = _write_config(tmp_path, _FULL_INI)
    config = Config(cfg_path)

    config.apply_updates(
        {
            "user_api_token": "",
            "user_agent": "agent",
            "token_refresh_interval_hours": "6",
            "category_search": "",
            "channels_to_parse": "",
            "download_path": "/tmp/x",
            "check_interval_hours": "1",
        }
    )

    assert config.nebula_api.user_api_token == "abc-token"
    assert Config(cfg_path).nebula_api.user_api_token == "abc-token"


def test_config_seeds_defaults_when_no_ini(tmp_path):
    config = Config(migrate_from=None)
    assert config.nebula_api.user_api_token == ""
    assert config.downloader.download_path == Path("./output")
    assert config.nebula_filters.channels_to_parse is None
    # Persisted to db: a second load reads the seeded defaults
    assert Config(migrate_from=None).downloader.download_path == Path("./output")


def test_config_seeds_defaults_when_ini_missing(tmp_path):
    config = Config(migrate_from=tmp_path / "nope.ini")
    assert config.nebula_api.user_api_token == ""


def test_set_db_location_writes_pointer(monkeypatch, tmp_path):
    from utils import paths

    pointer = tmp_path / "pointer"
    monkeypatch.setattr(paths, "POINTER_FILE", pointer)
    Config.set_db_location(str(tmp_path / "elsewhere.db"))
    assert pointer.read_text() == str(tmp_path / "elsewhere.db")


def test_apply_updates_blank_user_agent_keeps_existing(tmp_path):
    cfg_path = _write_config(tmp_path, _FULL_INI)
    config = Config(cfg_path)
    config.apply_updates(
        {
            "user_api_token": "",
            "user_agent": "",
            "token_refresh_interval_hours": "6",
            "category_search": "",
            "channels_to_parse": "",
            "download_path": "/tmp/x",
            "check_interval_hours": "1",
        }
    )
    assert config.nebula_api.user_agent == "test-agent"
