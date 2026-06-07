import json
import logging
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from models.nebula.channel import NebulaChannelVideoContentDetails
from models.nebula.episode import NebulaChannelVideoContentEpisodeResult
from models.nebula.fetched import (
    NebulaChannelVideoContentEpisodes,
    NebulaChannelVideoContentResponseModel,
)

DB_FILENAME = "nebula.db"


class ChannelNotFoundError(LookupError):
    pass


def _connect(output_directory: Path) -> sqlite3.Connection:
    output_directory.mkdir(parents=True, exist_ok=True)
    db_path = output_directory / DB_FILENAME
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            slug          TEXT PRIMARY KEY,
            details_json  TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS episodes (
            channel_slug    TEXT NOT NULL,
            slug            TEXT NOT NULL,
            published_year  INTEGER,
            episode_json    TEXT NOT NULL,
            PRIMARY KEY (channel_slug, slug),
            FOREIGN KEY (channel_slug) REFERENCES channels(slug) ON DELETE CASCADE
        )
    """)
    conn.commit()
    return conn


def save_channel_info(
    channel_slug: str,
    channel_data: NebulaChannelVideoContentDetails,
    episodes_data: NebulaChannelVideoContentEpisodes,
    output_directory: Path,
) -> Path:
    channel_directory = output_directory / channel_slug
    channel_directory.mkdir(parents=True, exist_ok=True)
    logging.info("Saving channel info for `%s` to %s", channel_slug, channel_directory)

    with closing(_connect(output_directory)) as conn:
        cursor = conn.cursor()

        # Upsert channel
        channel_json = json.dumps(channel_data.model_dump(), default=str)
        cursor.execute(
            "INSERT OR REPLACE INTO channels (slug, details_json) VALUES (?, ?)",
            (channel_slug, channel_json),
        )

        # Delete existing episodes for this channel and insert new ones
        cursor.execute("DELETE FROM episodes WHERE channel_slug = ?", (channel_slug,))

        for episode in episodes_data.results:
            episode_json = json.dumps(episode.model_dump(), default=str)
            published_year = None
            if episode.published_at:
                try:
                    published_year = datetime.fromisoformat(episode.published_at.replace("Z", "+00:00")).year
                except (ValueError, AttributeError):
                    pass

            cursor.execute(
                """INSERT INTO episodes
                   (channel_slug, slug, published_year, episode_json)
                   VALUES (?, ?, ?, ?)""",
                (channel_slug, episode.slug, published_year, episode_json),
            )

        conn.commit()

    return channel_directory


def load_channel_info(
    channel_slug: str, output_directory: Path
) -> NebulaChannelVideoContentResponseModel:
    logging.info("Loading channel info for `%s` from %s", channel_slug, output_directory)

    with closing(_connect(output_directory)) as conn:
        cursor = conn.cursor()

        # Load channel
        cursor.execute("SELECT details_json FROM channels WHERE slug = ?", (channel_slug,))
        row = cursor.fetchone()

        if row is None:
            raise ChannelNotFoundError(f"Channel {channel_slug} not found")

        channel_payload = json.loads(row[0])
        channel_details = NebulaChannelVideoContentDetails(**channel_payload)

        # Load episodes
        cursor.execute(
            "SELECT episode_json FROM episodes WHERE channel_slug = ? ORDER BY slug",
            (channel_slug,),
        )
        episodes_payload = [
            NebulaChannelVideoContentEpisodeResult(**json.loads(row[0]))
            for row in cursor.fetchall()
        ]

        return NebulaChannelVideoContentResponseModel(
            details=channel_details,
            episodes=NebulaChannelVideoContentEpisodes(
                next=None, previous=None, results=episodes_payload
            ),
        )


def list_channel_slugs(output_directory: Path) -> list[str]:
    """List all channel slugs in the database, sorted alphabetically.

    Returns an empty list if the database doesn't exist or has no channels.
    """
    with closing(_connect(output_directory)) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT slug FROM channels ORDER BY slug")
        rows = cursor.fetchall()
        return [row[0] for row in rows]
