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
from utils.paths import get_db_path


def _now() -> str:
    """Return current timestamp in ISO format."""
    return datetime.now().isoformat()


class ChannelNotFoundError(LookupError):
    pass


def _connect() -> sqlite3.Connection:
    """Open the single global nebula.db, creating tables if needed."""
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            slug      TEXT PRIMARY KEY,
            added_at  TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS config (
            id    INTEGER PRIMARY KEY CHECK (id = 1),
            data  TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def get_config() -> dict | None:
    """Return the stored config dict, or None if none has been saved yet."""
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT data FROM config WHERE id = 1")
        row = cursor.fetchone()
        return json.loads(row[0]) if row else None


def set_config(data: dict) -> None:
    """Persist the config dict as the single config row."""
    with closing(_connect()) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO config (id, data) VALUES (1, ?)",
            (json.dumps(data),),
        )
        conn.commit()


def save_channel_info(
    channel_slug: str,
    channel_data: NebulaChannelVideoContentDetails,
    episodes_data: NebulaChannelVideoContentEpisodes,
    output_directory: Path,
) -> Path:
    channel_directory = output_directory / channel_slug
    channel_directory.mkdir(parents=True, exist_ok=True)
    logging.info("Saving channel info for `%s` to %s", channel_slug, channel_directory)

    with closing(_connect()) as conn:
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
                    published_year = datetime.fromisoformat(
                        episode.published_at.replace("Z", "+00:00")
                    ).year
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
    channel_slug: str,
) -> NebulaChannelVideoContentResponseModel:
    logging.info("Loading channel info for `%s`", channel_slug)

    with closing(_connect()) as conn:
        cursor = conn.cursor()

        # Load channel
        cursor.execute(
            "SELECT details_json FROM channels WHERE slug = ?", (channel_slug,)
        )
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


def list_channel_slugs() -> list[str]:
    """List all channel slugs in the database, sorted alphabetically.

    Returns an empty list if the database doesn't exist or has no channels.
    """
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT slug FROM channels ORDER BY slug")
        rows = cursor.fetchall()
        return [row[0] for row in rows]


def list_channels_with_info() -> list[dict]:
    """Per saved channel, return a dict:
      {slug, title, description, avatar_url, url, website,
       episode_count, published_at}
    Sorted by title (case-insensitive), then slug. [] if no channels.
    avatar_url: from any one of the channel's episodes
    (images.channel_avatar.src); None if the channel has no episodes.
    url: canonical Nebula channel page f"https://nebula.tv/{slug}".
    website: details_json 'website' (creator's own site) or None.
    """
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT slug, details_json FROM channels")
        rows = cursor.fetchall()

        result = []
        for slug, details_json_str in rows:
            details = json.loads(details_json_str)
            title = details.get("title", slug)
            description = details.get("description")
            published_at = details.get("published_at")
            website = details.get("website")
            url = f"https://nebula.tv/{slug}"

            cursor.execute(
                "SELECT COUNT(*) FROM episodes WHERE channel_slug = ?", (slug,)
            )
            episode_count = cursor.fetchone()[0]

            cursor.execute(
                "SELECT episode_json FROM episodes WHERE channel_slug = ? LIMIT 1",
                (slug,),
            )
            ep_row = cursor.fetchone()
            avatar_url = None
            if ep_row:
                try:
                    ep_data = json.loads(ep_row[0])
                    avatar_url = (
                        ep_data.get("images", {}).get("channel_avatar", {}).get("src")
                    )
                except (json.JSONDecodeError, AttributeError):
                    pass

            result.append(
                {
                    "slug": slug,
                    "title": title,
                    "description": description,
                    "avatar_url": avatar_url,
                    "url": url,
                    "website": website,
                    "episode_count": episode_count,
                    "published_at": published_at,
                }
            )

        result.sort(key=lambda c: (c["title"].lower(), c["slug"]))
        return result


def add_subscription(slug: str) -> bool:
    """Insert slug into subscriptions. Return True if newly added,
    False if it was already present. Empty/whitespace slug → ValueError."""
    slug = slug.strip()
    if not slug:
        raise ValueError("slug required")
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO subscriptions (slug, added_at) VALUES (?, ?)",
            (slug, _now()),
        )
        conn.commit()
        return cursor.rowcount == 1


def remove_subscription(slug: str) -> bool:
    """Delete slug from subscriptions. Return True if a row was removed,
    False if the slug was not subscribed. Does NOT touch channels/episodes."""
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM subscriptions WHERE slug = ?", (slug,))
        conn.commit()
        return cursor.rowcount > 0


def list_subscriptions() -> list[str]:
    """Return all subscribed slugs, sorted alphabetically. [] if none."""
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT slug FROM subscriptions ORDER BY slug")
        return [row[0] for row in cursor.fetchall()]


def is_subscribed(slug: str) -> bool:
    """True if slug is in subscriptions."""
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM subscriptions WHERE slug = ?", (slug,))
        return cursor.fetchone() is not None


def delete_channel_data(slug: str) -> bool:
    """Delete the channels row for slug (episodes cascade). Return True if a
    channels row existed and was deleted, else False. Does NOT touch the
    subscriptions table, download_jobs, app_state, or any files on disk."""
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM channels WHERE slug = ?", (slug,))
        conn.commit()
        return cursor.rowcount > 0
