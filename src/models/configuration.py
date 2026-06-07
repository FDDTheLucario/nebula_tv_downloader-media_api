from pathlib import Path

from pydantic import BaseModel, field_validator


class ConfigurationNebulaAPIModel(BaseModel):
    user_api_token: str
    authorization_header: str | None = None
    user_agent: str
    token_refresh_interval_hours: int

    @field_validator("authorization_header", mode="after")
    @classmethod
    def _empty_header_to_none(cls, value: str | None) -> str | None:
        return value or None


class ConfigurationNebulaFiltersModel(BaseModel):
    category_search: str | None = None
    include_nebula_first: bool = True
    include_nebula_plus: bool = True
    include_nebula_originals: bool = True
    include_regular_videos: bool = False
    channels_to_parse: list[str] | None = None

    @field_validator("channels_to_parse", mode="after")
    @classmethod
    def _drop_empty_channels(cls, value: list[str] | None) -> list[str] | None:
        return list(filter(None, value)) if value else None


class ConfigurationDownloaderModel(BaseModel):
    download_path: Path
    load_channel_data_from_db: bool
    skip_if_video_exists: bool
    check_interval_hours: int = 1


class ConfigurationModel(BaseModel):
    nebula_api: ConfigurationNebulaAPIModel
    nebula_filters: ConfigurationNebulaFiltersModel
    downloader: ConfigurationDownloaderModel
