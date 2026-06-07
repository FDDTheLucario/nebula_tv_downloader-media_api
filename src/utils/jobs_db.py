import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

DB_FILENAME = "nebula.db"


def _now() -> str:
    """Return current timestamp in ISO format."""
    return datetime.now().isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict:
    """Convert sqlite3.Row to dict."""
    return dict(row)


def _connect(output_directory: Path) -> sqlite3.Connection:
    """Connect to nebula.db, create tables if needed, set row_factory."""
    output_directory.mkdir(parents=True, exist_ok=True)
    db_path = output_directory / DB_FILENAME
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    conn.execute("""
        CREATE TABLE IF NOT EXISTS download_jobs (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_slug  TEXT NOT NULL,
            episode_slug  TEXT NOT NULL,
            episode_json  TEXT NOT NULL,
            state         TEXT NOT NULL DEFAULT 'queued',
            error         TEXT,
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL,
            UNIQUE(channel_slug, episode_slug)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS app_state (
            key    TEXT PRIMARY KEY,
            value  TEXT
        )
    """)
    conn.commit()
    return conn


def enqueue_job(
    output_directory: Path, channel_slug: str, episode_slug: str, episode_json: str
) -> bool:
    """
    Insert a queued job. Idempotent on (channel_slug, episode_slug).
    - If no row exists → insert, return True
    - If existing row state is 'failed' → reset to 'queued', clear error, return True
    - If existing state is 'queued'/'running'/'done' → leave untouched, return False
    """
    with closing(_connect(output_directory)) as conn:
        cursor = conn.cursor()

        # Check if job exists
        cursor.execute(
            "SELECT id, state FROM download_jobs WHERE channel_slug = ? AND episode_slug = ?",
            (channel_slug, episode_slug),
        )
        row = cursor.fetchone()

        if row is None:
            # New job: insert as queued
            now = _now()
            cursor.execute(
                """INSERT INTO download_jobs
                   (channel_slug, episode_slug, episode_json, state, created_at, updated_at)
                   VALUES (?, ?, ?, 'queued', ?, ?)""",
                (channel_slug, episode_slug, episode_json, now, now),
            )
            conn.commit()
            return True

        job_id, state = row
        if state == "failed":
            # Reset failed job to queued
            now = _now()
            cursor.execute(
                "UPDATE download_jobs SET state = 'queued', error = NULL, updated_at = ? WHERE id = ?",
                (now, job_id),
            )
            conn.commit()
            return True

        # Job exists in queued/running/done state: leave untouched
        return False


def claim_next_job(output_directory: Path) -> dict | None:
    """
    Atomically pick the oldest queued job and flip it to running.
    Use BEGIN IMMEDIATE; SELECT id WHERE state='queued' ORDER BY id LIMIT 1;
    UPDATE that id → running + updated_at; COMMIT.
    Return the job as a dict (post-update state='running'), or None if none queued.
    """
    with closing(_connect(output_directory)) as conn:
        cursor = conn.cursor()

        # Begin atomic transaction
        cursor.execute("BEGIN IMMEDIATE")

        try:
            # Find oldest queued job
            cursor.execute(
                "SELECT id FROM download_jobs WHERE state = 'queued' ORDER BY id LIMIT 1"
            )
            row = cursor.fetchone()

            if row is None:
                conn.commit()
                return None

            job_id = row[0]

            # Update to running
            now = _now()
            cursor.execute(
                "UPDATE download_jobs SET state = 'running', updated_at = ? WHERE id = ?",
                (now, job_id),
            )

            conn.commit()

            # Fetch and return the updated job
            cursor.execute(
                """SELECT id, channel_slug, episode_slug, episode_json, state, error, created_at, updated_at
                   FROM download_jobs WHERE id = ?""",
                (job_id,),
            )
            job_row = cursor.fetchone()
            return _row_to_dict(job_row) if job_row else None

        except Exception:
            conn.rollback()
            raise


def mark_job_done(output_directory: Path, job_id: int) -> None:
    """Set job state to 'done' and update updated_at."""
    with closing(_connect(output_directory)) as conn:
        cursor = conn.cursor()
        now = _now()
        cursor.execute(
            "UPDATE download_jobs SET state = 'done', updated_at = ? WHERE id = ?",
            (now, job_id),
        )
        conn.commit()


def mark_job_failed(output_directory: Path, job_id: int, error: str) -> None:
    """Set job state to 'failed', set error, and update updated_at."""
    with closing(_connect(output_directory)) as conn:
        cursor = conn.cursor()
        now = _now()
        cursor.execute(
            "UPDATE download_jobs SET state = 'failed', error = ?, updated_at = ? WHERE id = ?",
            (error, now, job_id),
        )
        conn.commit()


def requeue_job(output_directory: Path, job_id: int) -> bool:
    """
    If job exists and state in {failed, done}: set queued, clear error, bump updated_at, return True.
    Else return False.
    """
    with closing(_connect(output_directory)) as conn:
        cursor = conn.cursor()

        # Check if job exists and is in failed or done state
        cursor.execute("SELECT state FROM download_jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()

        if row is None:
            return False

        state = row[0]
        if state not in ("failed", "done"):
            return False

        # Reset to queued
        now = _now()
        cursor.execute(
            "UPDATE download_jobs SET state = 'queued', error = NULL, updated_at = ? WHERE id = ?",
            (now, job_id),
        )
        conn.commit()
        return True


def reset_running_jobs(output_directory: Path) -> int:
    """
    Set every 'running' job back to 'queued' (crash recovery on startup).
    Return count of jobs reset.
    """
    with closing(_connect(output_directory)) as conn:
        cursor = conn.cursor()

        # Count running jobs
        cursor.execute("SELECT COUNT(*) FROM download_jobs WHERE state = 'running'")
        count = cursor.fetchone()[0]

        # Update running to queued
        now = _now()
        cursor.execute(
            "UPDATE download_jobs SET state = 'queued', updated_at = ? WHERE state = 'running'",
            (now,),
        )
        conn.commit()

        return count


def list_jobs(
    output_directory: Path, state: str | None = None, limit: int = 200
) -> list[dict]:
    """
    List jobs (newest first, ORDER BY id DESC).
    Optional state filter. Return list of dicts.
    """
    with closing(_connect(output_directory)) as conn:
        cursor = conn.cursor()

        if state is None:
            cursor.execute(
                """SELECT id, channel_slug, episode_slug, episode_json, state, error, created_at, updated_at
                   FROM download_jobs ORDER BY id DESC LIMIT ?""",
                (limit,),
            )
        else:
            cursor.execute(
                """SELECT id, channel_slug, episode_slug, episode_json, state, error, created_at, updated_at
                   FROM download_jobs WHERE state = ? ORDER BY id DESC LIMIT ?""",
                (state, limit),
            )

        return [_row_to_dict(row) for row in cursor.fetchall()]


def get_job(output_directory: Path, job_id: int) -> dict | None:
    """Get a job by id. Return dict or None."""
    with closing(_connect(output_directory)) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, channel_slug, episode_slug, episode_json, state, error, created_at, updated_at
               FROM download_jobs WHERE id = ?""",
            (job_id,),
        )
        row = cursor.fetchone()
        return _row_to_dict(row) if row else None


def count_jobs_by_state(output_directory: Path) -> dict[str, int]:
    """
    Count jobs by state. Always return all four keys: queued, running, done, failed.
    Default 0 if absent.
    """
    with closing(_connect(output_directory)) as conn:
        cursor = conn.cursor()

        # Initialize all states to 0
        counts = {"queued": 0, "running": 0, "done": 0, "failed": 0}

        # Query counts by state
        cursor.execute("SELECT state, COUNT(*) FROM download_jobs GROUP BY state")
        for state, count in cursor.fetchall():
            if state in counts:
                counts[state] = count

        return counts


def set_state(output_directory: Path, key: str, value: str) -> None:
    """Upsert key-value into app_state."""
    with closing(_connect(output_directory)) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO app_state (key, value) VALUES (?, ?)",
            (key, value),
        )
        conn.commit()


def get_state(output_directory: Path, key: str) -> str | None:
    """Get value from app_state by key. Return None if missing."""
    with closing(_connect(output_directory)) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM app_state WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row[0] if row else None
