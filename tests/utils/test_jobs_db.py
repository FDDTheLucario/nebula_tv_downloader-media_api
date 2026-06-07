import json

from utils.jobs_db import (
    DB_FILENAME,
    _connect,
    claim_next_job,
    count_jobs_by_state,
    enqueue_job,
    get_job,
    get_state,
    list_jobs,
    mark_job_done,
    mark_job_failed,
    requeue_job,
    reset_running_jobs,
    set_state,
)


# Test 1: _connect creates jobs tables
def test_connect_creates_jobs_tables(tmp_path):
    conn = _connect(tmp_path)
    try:
        assert (tmp_path / DB_FILENAME).exists()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='download_jobs'"
        )
        assert cursor.fetchone() is not None
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='app_state'"
        )
        assert cursor.fetchone() is not None
    finally:
        conn.close()


# Test 2: enqueue_new_job_returns_true_and_persists
def test_enqueue_new_job_returns_true_and_persists(tmp_path):
    episode_json = json.dumps({"slug": "ep1", "title": "Episode 1"})
    result = enqueue_job(tmp_path, "ch-slug", "ep-slug", episode_json)

    assert result is True

    jobs = list_jobs(tmp_path)
    assert len(jobs) == 1
    assert jobs[0]["state"] == "queued"
    assert jobs[0]["channel_slug"] == "ch-slug"
    assert jobs[0]["episode_slug"] == "ep-slug"
    assert jobs[0]["episode_json"] == episode_json


# Test 3: enqueue_duplicate_queued_returns_false
def test_enqueue_duplicate_queued_returns_false(tmp_path):
    episode_json = json.dumps({"slug": "ep1"})

    result1 = enqueue_job(tmp_path, "ch-slug", "ep-slug", episode_json)
    assert result1 is True

    result2 = enqueue_job(tmp_path, "ch-slug", "ep-slug", episode_json)
    assert result2 is False

    jobs = list_jobs(tmp_path)
    assert len(jobs) == 1


# Test 4: enqueue_resets_failed_job_to_queued
def test_enqueue_resets_failed_job_to_queued(tmp_path):
    episode_json = json.dumps({"slug": "ep1"})

    # Enqueue, claim, and mark failed
    enqueue_job(tmp_path, "ch-slug", "ep-slug", episode_json)
    job = claim_next_job(tmp_path)
    assert job is not None
    mark_job_failed(tmp_path, job["id"], "download failed")

    # Verify it's failed
    job_after = get_job(tmp_path, job["id"])
    assert job_after["state"] == "failed"
    assert job_after["error"] == "download failed"

    # Re-enqueue should return True
    result = enqueue_job(tmp_path, "ch-slug", "ep-slug", episode_json)
    assert result is True

    # Verify state is queued and error cleared
    job_final = get_job(tmp_path, job["id"])
    assert job_final["state"] == "queued"
    assert job_final["error"] is None


# Test 5: enqueue_done_job_not_reenqueued
def test_enqueue_done_job_not_reenqueued(tmp_path):
    episode_json = json.dumps({"slug": "ep1"})

    # Enqueue, claim, and mark done
    enqueue_job(tmp_path, "ch-slug", "ep-slug", episode_json)
    job = claim_next_job(tmp_path)
    mark_job_done(tmp_path, job["id"])

    # Verify it's done
    job_after = get_job(tmp_path, job["id"])
    assert job_after["state"] == "done"

    # Re-enqueue should return False
    result = enqueue_job(tmp_path, "ch-slug", "ep-slug", episode_json)
    assert result is False

    # Verify state is still done
    job_final = get_job(tmp_path, job["id"])
    assert job_final["state"] == "done"


# Test 5b: enqueue_running_job_returns_false
def test_enqueue_running_job_returns_false(tmp_path):
    """Enqueue on a running job returns False without changing state to queued."""
    episode_json = json.dumps({"slug": "ep1"})
    enqueue_job(tmp_path, "ch-slug", "ep-slug", episode_json)
    claim_next_job(tmp_path)  # Transitions to running

    # Attempt to re-enqueue a running job
    result = enqueue_job(tmp_path, "ch-slug", "ep-slug", episode_json)
    assert result is False

    # State must remain running, not reset to queued
    jobs = list_jobs(tmp_path)
    assert len(jobs) == 1
    assert jobs[0]["state"] == "running"


# Test 6: claim_next_job_returns_oldest_and_marks_running
def test_claim_next_job_returns_oldest_and_marks_running(tmp_path):
    ep1_json = json.dumps({"slug": "ep1"})
    ep2_json = json.dumps({"slug": "ep2"})

    enqueue_job(tmp_path, "ch-slug", "ep1", ep1_json)
    enqueue_job(tmp_path, "ch-slug", "ep2", ep2_json)

    job = claim_next_job(tmp_path)
    assert job is not None
    assert job["state"] == "running"
    assert job["episode_slug"] == "ep1"  # First enqueued


# Test 7: claim_next_job_none_when_empty
def test_claim_next_job_none_when_empty(tmp_path):
    result = claim_next_job(tmp_path)
    assert result is None


# Test 8: claim_skips_running_and_done
def test_claim_skips_running_and_done(tmp_path):
    ep1_json = json.dumps({"slug": "ep1"})
    ep2_json = json.dumps({"slug": "ep2"})
    ep3_json = json.dumps({"slug": "ep3"})

    # Enqueue 3 jobs
    enqueue_job(tmp_path, "ch-slug", "ep1", ep1_json)
    enqueue_job(tmp_path, "ch-slug", "ep2", ep2_json)
    enqueue_job(tmp_path, "ch-slug", "ep3", ep3_json)

    # Claim first
    job1 = claim_next_job(tmp_path)
    assert job1["state"] == "running"
    assert job1["episode_slug"] == "ep1"

    # Claim second
    job2 = claim_next_job(tmp_path)
    assert job2["state"] == "running"
    assert job2["episode_slug"] == "ep2"

    # Mark first as done
    mark_job_done(tmp_path, job1["id"])

    # Next claim should get third (skip the done and running ones)
    job3 = claim_next_job(tmp_path)
    assert job3 is not None
    assert job3["episode_slug"] == "ep3"


# Test 9: mark_job_done
def test_mark_job_done(tmp_path):
    episode_json = json.dumps({"slug": "ep1"})
    enqueue_job(tmp_path, "ch-slug", "ep-slug", episode_json)
    job = claim_next_job(tmp_path)

    mark_job_done(tmp_path, job["id"])

    job_after = get_job(tmp_path, job["id"])
    assert job_after["state"] == "done"


# Test 10: mark_job_failed
def test_mark_job_failed(tmp_path):
    episode_json = json.dumps({"slug": "ep1"})
    enqueue_job(tmp_path, "ch-slug", "ep-slug", episode_json)
    job = claim_next_job(tmp_path)

    mark_job_failed(tmp_path, job["id"], "network error")

    job_after = get_job(tmp_path, job["id"])
    assert job_after["state"] == "failed"
    assert job_after["error"] == "network error"


# Test 11: requeue_failed_job
def test_requeue_failed_job(tmp_path):
    episode_json = json.dumps({"slug": "ep1"})
    enqueue_job(tmp_path, "ch-slug", "ep-slug", episode_json)
    job = claim_next_job(tmp_path)
    mark_job_failed(tmp_path, job["id"], "error")

    result = requeue_job(tmp_path, job["id"])
    assert result is True

    job_after = get_job(tmp_path, job["id"])
    assert job_after["state"] == "queued"
    assert job_after["error"] is None


# Test 11b: requeue_done_job
def test_requeue_done_job(tmp_path):
    """requeue_job on a done job returns True and resets state to queued."""
    episode_json = json.dumps({"slug": "ep1"})
    enqueue_job(tmp_path, "ch-slug", "ep-slug", episode_json)
    job = claim_next_job(tmp_path)
    mark_job_done(tmp_path, job["id"])

    result = requeue_job(tmp_path, job["id"])
    assert result is True

    job_after = get_job(tmp_path, job["id"])
    assert job_after["state"] == "queued"
    assert job_after["error"] is None


# Test 12: requeue_nonexistent_returns_false
def test_requeue_nonexistent_returns_false(tmp_path):
    result = requeue_job(tmp_path, 999)
    assert result is False


# Test 13: reset_running_jobs
def test_reset_running_jobs(tmp_path):
    ep1_json = json.dumps({"slug": "ep1"})
    ep2_json = json.dumps({"slug": "ep2"})

    enqueue_job(tmp_path, "ch-slug", "ep1", ep1_json)
    enqueue_job(tmp_path, "ch-slug", "ep2", ep2_json)

    job1 = claim_next_job(tmp_path)
    job2 = claim_next_job(tmp_path)

    assert job1["state"] == "running"
    assert job2["state"] == "running"

    count = reset_running_jobs(tmp_path)
    assert count == 2

    job1_after = get_job(tmp_path, job1["id"])
    job2_after = get_job(tmp_path, job2["id"])
    assert job1_after["state"] == "queued"
    assert job2_after["state"] == "queued"


# Test 14: list_jobs_filter_by_state
def test_list_jobs_filter_by_state(tmp_path):
    ep1_json = json.dumps({"slug": "ep1"})
    ep2_json = json.dumps({"slug": "ep2"})
    ep3_json = json.dumps({"slug": "ep3"})

    enqueue_job(tmp_path, "ch-slug", "ep1", ep1_json)
    enqueue_job(tmp_path, "ch-slug", "ep2", ep2_json)
    enqueue_job(tmp_path, "ch-slug", "ep3", ep3_json)

    job1 = claim_next_job(tmp_path)
    mark_job_done(tmp_path, job1["id"])

    job2 = claim_next_job(tmp_path)
    mark_job_failed(tmp_path, job2["id"], "error")

    # job3 is still queued

    queued = list_jobs(tmp_path, state="queued")
    assert len(queued) == 1
    assert queued[0]["episode_slug"] == "ep3"

    done = list_jobs(tmp_path, state="done")
    assert len(done) == 1
    assert done[0]["state"] == "done"

    failed = list_jobs(tmp_path, state="failed")
    assert len(failed) == 1
    assert failed[0]["state"] == "failed"

    running = list_jobs(tmp_path, state="running")
    assert len(running) == 0


# Test 15: count_jobs_by_state
def test_count_jobs_by_state(tmp_path):
    ep1_json = json.dumps({"slug": "ep1"})
    ep2_json = json.dumps({"slug": "ep2"})
    ep3_json = json.dumps({"slug": "ep3"})

    enqueue_job(tmp_path, "ch-slug", "ep1", ep1_json)
    enqueue_job(tmp_path, "ch-slug", "ep2", ep2_json)
    enqueue_job(tmp_path, "ch-slug", "ep3", ep3_json)

    job1 = claim_next_job(tmp_path)
    mark_job_done(tmp_path, job1["id"])

    job2 = claim_next_job(tmp_path)
    mark_job_failed(tmp_path, job2["id"], "error")

    counts = count_jobs_by_state(tmp_path)
    assert counts["queued"] == 1
    assert counts["running"] == 0
    assert counts["done"] == 1
    assert counts["failed"] == 1


# Test 16: set_and_get_state_roundtrip
def test_set_and_get_state_roundtrip(tmp_path):
    set_state(tmp_path, "test_key", "test_value")
    value = get_state(tmp_path, "test_key")
    assert value == "test_value"


# Test 17: get_state_missing_returns_none
def test_get_state_missing_returns_none(tmp_path):
    value = get_state(tmp_path, "nonexistent")
    assert value is None


# Test 18: set_state_upsert_overwrites
def test_set_state_upsert_overwrites(tmp_path):
    set_state(tmp_path, "key", "value1")
    assert get_state(tmp_path, "key") == "value1"

    set_state(tmp_path, "key", "value2")
    assert get_state(tmp_path, "key") == "value2"


# ── new cleanup helpers ───────────────────────────────────────────────────────

from utils.jobs_db import delete_jobs_for_channel, delete_state  # noqa: E402


def test_delete_jobs_for_channel_removes_only_that_channel(tmp_path):
    ep_json = json.dumps({"slug": "ep1"})
    enqueue_job(tmp_path, "ch1", "ep1", ep_json)
    enqueue_job(tmp_path, "ch1", "ep2", json.dumps({"slug": "ep2"}))
    enqueue_job(tmp_path, "ch2", "ep3", json.dumps({"slug": "ep3"}))

    count = delete_jobs_for_channel(tmp_path, "ch1")
    assert count == 2

    remaining = list_jobs(tmp_path)
    assert len(remaining) == 1
    assert remaining[0]["channel_slug"] == "ch2"


def test_delete_jobs_for_channel_none_returns_zero(tmp_path):
    assert delete_jobs_for_channel(tmp_path, "ghost") == 0


def test_delete_state_removes_key(tmp_path):
    set_state(tmp_path, "last_check:ch", "x")
    delete_state(tmp_path, "last_check:ch")
    assert get_state(tmp_path, "last_check:ch") is None


def test_delete_state_missing_key_noop(tmp_path):
    delete_state(tmp_path, "nope")  # must not raise
