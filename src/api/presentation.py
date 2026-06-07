import json

_BADGE_LABELS = {
    "is_nebula_original": "Original",
    "is_nebula_plus": "Plus",
    "is_nebula_first": "First",
}


def format_duration(seconds) -> str:
    """Seconds → 'M:SS' or 'H:MM:SS'. None/0/negative → '0:00'."""
    if seconds is None or not isinstance(seconds, (int, float)) or seconds <= 0:
        return "0:00"
    seconds = int(seconds)
    if seconds < 3600:
        m, s = divmod(seconds, 60)
        return f"{m}:{s:02d}"
    h, remainder = divmod(seconds, 3600)
    m, s = divmod(remainder, 60)
    return f"{h}:{m:02d}:{s:02d}"


def attribute_badges(attributes) -> list[str]:
    """Map attribute value strings → human labels, stable order.

    Unknown values (incl. free_sample_eligible) are skipped. None → [].
    """
    if not attributes:
        return []
    return [_BADGE_LABELS[v] for v in attributes if v in _BADGE_LABELS]


def decorate_job(job: dict) -> dict:
    """Return a shallow copy of job with an added 'episode' key.

    Parse job['episode_json']; on success episode = {
        title, url, thumbnail_url, channel_title, duration, duration_display,
        published_at, published_date, badges, share_url
    }. On missing/invalid JSON or KeyError → episode = None (row still renders
    via episode_slug fallback in the template). Never raises.
    """
    try:
        ep = json.loads(job["episode_json"])
        thumbnail_url = ep.get("images", {}).get("thumbnail", {}).get("src")
        url = ep.get("share_url") or ep.get("episode_url")
        duration_display = format_duration(ep.get("duration"))
        badges = attribute_badges(ep.get("attributes"))
        published_at = ep.get("published_at") or ""
        if published_at and len(published_at) >= 10:
            published_date = published_at[:10]
        else:
            published_date = published_at
        episode = {
            "title": ep.get("title"),
            "url": url,
            "thumbnail_url": thumbnail_url,
            "channel_title": ep.get("channel_title"),
            "duration": ep.get("duration"),
            "duration_display": duration_display,
            "published_at": published_at,
            "published_date": published_date,
            "badges": badges,
            "share_url": ep.get("share_url"),
        }
    except (AttributeError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        episode = None
    return {**job, "episode": episode}
