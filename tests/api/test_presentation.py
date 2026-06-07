from tests.api.conftest import make_episode
from api.presentation import attribute_badges, decorate_job, format_duration


def test_format_duration_none_is_zero():
    assert format_duration(None) == "0:00"


def test_format_duration_zero_and_negative():
    assert format_duration(0) == "0:00"
    assert format_duration(-5) == "0:00"


def test_format_duration_under_minute():
    assert format_duration(5) == "0:05"


def test_format_duration_minutes():
    assert format_duration(120) == "2:00"
    assert format_duration(605) == "10:05"


def test_format_duration_hours():
    assert format_duration(3661) == "1:01:01"


def test_attribute_badges_maps_known():
    result = attribute_badges(["is_nebula_original", "is_nebula_plus"])
    assert result == ["Original", "Plus"]


def test_attribute_badges_skips_unknown():
    result = attribute_badges(["free_sample_eligible", "is_nebula_first"])
    assert result == ["First"]


def test_attribute_badges_none_empty():
    assert attribute_badges(None) == []
    assert attribute_badges([]) == []


def test_decorate_job_parses_episode():
    ep = make_episode(title="My Vid", duration=125, attributes=["is_nebula_plus"])
    job = {
        "id": 1,
        "channel_slug": "ch-slug",
        "episode_slug": "ep-slug",
        "state": "queued",
        "error": None,
        "episode_json": ep.model_dump_json(),
    }
    result = decorate_job(job)
    episode = result["episode"]
    assert episode is not None
    assert episode["title"] == "My Vid"
    assert episode["duration_display"] == "2:05"
    assert episode["badges"] == ["Plus"]
    assert episode["thumbnail_url"] == "https://example.com/img.jpg"
    assert episode["url"] == "https://nebula.tv/ep"
    assert episode["published_date"] == "2024-01-01"


def test_decorate_job_keeps_original_keys():
    ep = make_episode()
    job = {
        "id": 42,
        "channel_slug": "ch-slug",
        "episode_slug": "ep-slug",
        "state": "done",
        "error": None,
        "episode_json": ep.model_dump_json(),
    }
    result = decorate_job(job)
    assert result["id"] == 42
    assert result["state"] == "done"
    assert result["episode_slug"] == "ep-slug"


def test_decorate_job_invalid_json_episode_none():
    job = {
        "id": 1,
        "channel_slug": "ch-slug",
        "episode_slug": "ep-slug",
        "state": "queued",
        "error": None,
        "episode_json": "not json",
    }
    result = decorate_job(job)
    assert result["episode"] is None
    assert result["id"] == 1


def test_decorate_job_missing_episode_json_key():
    job = {
        "id": 1,
        "channel_slug": "ch-slug",
        "episode_slug": "ep-slug",
        "state": "queued",
        "error": None,
    }
    result = decorate_job(job)
    assert result["episode"] is None


def test_decorate_job_json_list_episode_none():
    """Valid JSON that is a list (not dict) must not raise; episode → None."""
    job = {
        "id": 2,
        "channel_slug": "ch-slug",
        "episode_slug": "ep-slug",
        "state": "queued",
        "error": None,
        "episode_json": "[]",
    }
    result = decorate_job(job)
    assert result["episode"] is None
    assert result["id"] == 2


def test_decorate_job_json_int_episode_none():
    """Valid JSON that is an int (not dict) must not raise; episode → None."""
    job = {
        "id": 3,
        "channel_slug": "ch-slug",
        "episode_slug": "ep-slug",
        "state": "queued",
        "error": None,
        "episode_json": "123",
    }
    result = decorate_job(job)
    assert result["episode"] is None


def test_decorate_job_json_null_episode_none():
    """Valid JSON null must not raise; episode → None."""
    job = {
        "id": 4,
        "channel_slug": "ch-slug",
        "episode_slug": "ep-slug",
        "state": "queued",
        "error": None,
        "episode_json": "null",
    }
    result = decorate_job(job)
    assert result["episode"] is None


def test_format_duration_exactly_one_hour():
    assert format_duration(3600) == "1:00:00"


def test_format_duration_float_input():
    assert format_duration(125.9) == "2:05"
