from configparser import ConfigParser
from pathlib import Path

from models.configuration import (
    ConfigurationModel,
    ConfigurationNebulaAPIModel,
    ConfigurationNebulaFiltersModel,
    ConfigurationDownloaderModel,
)
from utils import db
from utils.paths import get_db_path, set_db_path

DEFAULT_INI_PATH = Path("config/config.ini")

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/16.1 Safari/605.1.15"
)

DEFAULT_CONFIG: dict = {
    "nebula_api": {
        "user_api_token": "",
        "authorization_header": None,
        "user_agent": _DEFAULT_USER_AGENT,
        "token_refresh_interval_hours": 6,
    },
    "nebula_filters": {
        "category_search": None,
        "include_nebula_first": False,
        "include_nebula_plus": True,
        "include_nebula_originals": True,
        "include_regular_videos": False,
        "channels_to_parse": None,
    },
    "downloader": {
        "download_path": "./output",
        "load_channel_data_from_db": False,
        "skip_if_video_exists": True,
        "check_interval_hours": 1,
    },
}


class QuotedConfigParser(ConfigParser):
    def get(self, section, option, **kwargs):
        value = super().get(section, option, **kwargs)
        return value.strip('"').strip("'")


def _ini_to_dict(config_path: Path) -> dict:
    """Parse a legacy config.ini into the canonical config dict (migration)."""
    p = QuotedConfigParser()
    p.read(config_path)

    category = p.get("nebula_filters", "category_search")
    channels = [c.strip() for c in p.get("nebula_filters", "channels_to_parse").split(",")]
    channels = list(filter(None, channels))

    refresh = 6
    if p.has_option("nebula_api", "token_refresh_interval_hours"):
        refresh = int(p.get("nebula_api", "token_refresh_interval_hours") or 6)

    interval = 1
    if p.has_option("downloader", "check_interval_hours"):
        interval = int(p.get("downloader", "check_interval_hours") or 1)

    return {
        "nebula_api": {
            "user_api_token": p.get("nebula_api", "user_api_token"),
            "authorization_header": p.get("nebula_api", "authorization_header") or None,
            "user_agent": p.get("nebula_api", "user_agent") or _DEFAULT_USER_AGENT,
            "token_refresh_interval_hours": refresh,
        },
        "nebula_filters": {
            "category_search": None if category in ("", "false") else category,
            "include_nebula_first": p.getboolean("nebula_filters", "include_nebula_first"),
            "include_nebula_plus": p.getboolean("nebula_filters", "include_nebula_plus"),
            "include_nebula_originals": p.getboolean(
                "nebula_filters", "include_nebula_originals"
            ),
            "include_regular_videos": p.getboolean(
                "nebula_filters", "include_regular_videos"
            ),
            "channels_to_parse": channels or None,
        },
        "downloader": {
            "download_path": p.get("downloader", "download_path"),
            "load_channel_data_from_db": p.getboolean(
                "downloader", "load_channel_data_from_db", fallback=False
            ),
            "skip_if_video_exists": p.getboolean(
                "downloader", "skip_if_video_exists", fallback=True
            ),
            "check_interval_hours": interval,
        },
    }


class Config:
    """Application configuration, persisted as a single row in the global db.

    On first use (no config row yet) the config is seeded — from a legacy
    ``config.ini`` if one exists (one-time migration), otherwise from built-in
    defaults. After that the db is the single source of truth and the INI is
    ignored.
    """

    def __init__(self, migrate_from: Path | None = DEFAULT_INI_PATH) -> None:
        data = db.get_config()
        if data is None:
            data = self._seed(migrate_from)
        self.__config = self._build_model(data)

    @staticmethod
    def _seed(migrate_from: Path | None) -> dict:
        if migrate_from is not None and Path(migrate_from).exists():
            data = _ini_to_dict(Path(migrate_from))
        else:
            data = {k: dict(v) for k, v in DEFAULT_CONFIG.items()}
        db.set_config(data)
        return data

    @staticmethod
    def _build_model(data: dict) -> ConfigurationModel:
        return ConfigurationModel(
            nebula_api=ConfigurationNebulaAPIModel(**data["nebula_api"]),
            nebula_filters=ConfigurationNebulaFiltersModel(**data["nebula_filters"]),
            downloader=ConfigurationDownloaderModel(**data["downloader"]),
        )

    @property
    def nebula_api(self) -> ConfigurationNebulaAPIModel:
        return self.__config.nebula_api

    @property
    def nebula_filters(self) -> ConfigurationNebulaFiltersModel:
        return self.__config.nebula_filters

    @property
    def downloader(self) -> ConfigurationDownloaderModel:
        return self.__config.downloader

    def set_nebula_authorization_token(self, token: str) -> None:
        self.__config.nebula_api.authorization_header = token

    def _to_dict(self) -> dict:
        api = self.__config.nebula_api
        filters = self.__config.nebula_filters
        dl = self.__config.downloader
        return {
            "nebula_api": {
                "user_api_token": api.user_api_token,
                "authorization_header": api.authorization_header,
                "user_agent": api.user_agent,
                "token_refresh_interval_hours": api.token_refresh_interval_hours,
            },
            "nebula_filters": {
                "category_search": filters.category_search,
                "include_nebula_first": filters.include_nebula_first,
                "include_nebula_plus": filters.include_nebula_plus,
                "include_nebula_originals": filters.include_nebula_originals,
                "include_regular_videos": filters.include_regular_videos,
                "channels_to_parse": filters.channels_to_parse,
            },
            "downloader": {
                "download_path": str(dl.download_path),
                "load_channel_data_from_db": dl.load_channel_data_from_db,
                "skip_if_video_exists": dl.skip_if_video_exists,
                "check_interval_hours": dl.check_interval_hours,
            },
        }

    def as_view(self) -> dict:
        """Return current config values for rendering an edit form.

        The secret ``user_api_token`` is intentionally omitted; the UI leaves
        its field blank and only updates it when a new value is submitted.
        ``db_path`` is the bootstrap pointer, not part of the stored config.
        """
        api = self.__config.nebula_api
        filters = self.__config.nebula_filters
        dl = self.__config.downloader
        return {
            "nebula_api": {
                "authorization_header": api.authorization_header or "",
                "user_agent": api.user_agent,
                "token_refresh_interval_hours": api.token_refresh_interval_hours,
                "has_token": bool(api.user_api_token),
            },
            "nebula_filters": {
                "category_search": filters.category_search or "",
                "include_nebula_first": filters.include_nebula_first,
                "include_nebula_plus": filters.include_nebula_plus,
                "include_nebula_originals": filters.include_nebula_originals,
                "include_regular_videos": filters.include_regular_videos,
                "channels_to_parse": ",".join(filters.channels_to_parse or []),
            },
            "downloader": {
                "download_path": str(dl.download_path),
                "load_channel_data_from_db": dl.load_channel_data_from_db,
                "skip_if_video_exists": dl.skip_if_video_exists,
                "check_interval_hours": dl.check_interval_hours,
            },
            "db_path": str(get_db_path()),
        }

    def apply_updates(self, data: dict) -> None:
        """Validate, apply, and persist a flat dict of submitted form values.

        A blank ``user_api_token`` keeps the current token. Empty/``"false"``
        sentinels are normalised the same way migration does. Mutates the
        in-memory model in place so holders of this Config see changes live,
        then persists to the global db. ``db_path`` is handled separately by the
        caller (it requires a restart) and is ignored here.
        """
        api = self.__config.nebula_api
        token = (data.get("user_api_token") or "").strip()
        category = (data.get("category_search") or "").strip()
        channels = [c.strip() for c in (data.get("channels_to_parse") or "").split(",")]
        channels = list(filter(None, channels))

        new_model = ConfigurationModel(
            nebula_api=ConfigurationNebulaAPIModel(
                user_api_token=token or api.user_api_token,
                authorization_header=data.get("authorization_header") or None,
                user_agent=data.get("user_agent") or api.user_agent,
                token_refresh_interval_hours=int(
                    data.get("token_refresh_interval_hours") or 6
                ),
            ),
            nebula_filters=ConfigurationNebulaFiltersModel(
                category_search=None if category in ("", "false") else category,
                include_nebula_first=bool(data.get("include_nebula_first")),
                include_nebula_plus=bool(data.get("include_nebula_plus")),
                include_nebula_originals=bool(data.get("include_nebula_originals")),
                include_regular_videos=bool(data.get("include_regular_videos")),
                channels_to_parse=channels or None,
            ),
            downloader=ConfigurationDownloaderModel(
                download_path=data.get("download_path"),
                load_channel_data_from_db=bool(data.get("load_channel_data_from_db")),
                skip_if_video_exists=bool(data.get("skip_if_video_exists")),
                check_interval_hours=int(data.get("check_interval_hours") or 1),
            ),
        )
        self.__config = new_model
        db.set_config(self._to_dict())

    @staticmethod
    def set_db_location(path: str) -> None:
        """Persist a new global db location (takes effect on next restart)."""
        set_db_path(path)
