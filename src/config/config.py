from configparser import ConfigParser
from pathlib import Path
from models.configuration import (
    ConfigurationModel,
    ConfigurationNebulaAPIModel,
    ConfigurationNebulaFiltersModel,
    ConfigurationDownloaderModel,
)


class QuotedConfigParser(ConfigParser):
    def get(self, section, option, **kwargs):
        value = super().get(section, option, **kwargs)
        return value.strip('"').strip("'")


class Config:
    def __init__(self, config_path: Path = Path("config/config.ini")) -> None:
        config_original = QuotedConfigParser()
        config_original.read(config_path)
        self.__config = ConfigurationModel(
            nebula_api=ConfigurationNebulaAPIModel(
                user_api_token=config_original.get("nebula_api", "user_api_token"),
                authorization_header=config_original.get(
                    "nebula_api", "authorization_header"
                ),
                user_agent=config_original.get("nebula_api", "user_agent")
                if config_original.get("nebula_api", "user_agent")
                else None,
                token_refresh_interval_hours=config_original.get("nebula_api", "token_refresh_interval_hours")
                if config_original.get("nebula_api", "token_refresh_interval_hours") else 6,
            ),
            nebula_filters=ConfigurationNebulaFiltersModel(
                category_search=str(
                    config_original.get("nebula_filters", "category_search")
                )
                if not config_original.get("nebula_filters", "category_search") == "false"
                else None,
                include_nebula_first=config_original.getboolean(
                    "nebula_filters", "include_nebula_first"
                ),
                include_nebula_plus=config_original.getboolean(
                    "nebula_filters", "include_nebula_plus"
                ),
                include_nebula_originals=config_original.getboolean(
                    "nebula_filters", "include_nebula_originals"
                ),
                include_regular_videos=config_original.getboolean(
                    "nebula_filters", "include_regular_videos"
                ),
                channels_to_parse=config_original.get(
                    "nebula_filters", "channels_to_parse"
                ).split(",")
                if config_original["nebula_filters"]["channels_to_parse"]
                else None,
            ),
            downloader=ConfigurationDownloaderModel(
                download_path=config_original.get("downloader", "download_path"),
                load_channel_data_from_db=config_original.get("downloader", "load_channel_data_from_db"),
                skip_if_video_exists=config_original.get("downloader", "skip_if_video_exists"),
            ),
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
