"""Deactivation-sweep tests.

The sweep is the fix for listings that never expire: upsert_jobs only ever
saw the rows still present in a feed, so a row that disappeared stayed
active forever (~1,100 phantom-active rows on one source alone).

The guard matters more than the sweep. fetch_all() swallows per-source fetch
failures, so a 500 yields zero rows — and an unguarded sweep would read that
as "the feed is empty now" and deactivate the source's entire corpus.
"""
import sqlite3
from pathlib import Path

import pytest

from lib.upsert import deactivate_missing, sweep_inactive, upsert_jobs

SCHEMA = Path(__file__).parent.parent / "schema.sql"


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA.read_text())
    yield c
    c.close()


def _job(source, source_id, company="Acme", title="Solutions Engineer Intern"):
    return {
        "source": source, "source_id": source_id,
        "company_name": company, "title": title,
        "url": f"https://example.com/{source_id}", "locations": ["NYC"],
        "season": "Summer 2027", "category": "Tech", "degrees": ["Bachelor's"],
        "sponsorship": "Offers Sponsorship", "active": True,
        "posted_at": 1750000000, "updated_at": 1750000000,
        "company_url": "https://example.com", "raw_payload": {},
    }


def _active_ids(conn, source):
    return {r["source_id"] for r in conn.execute(
        "SELECT source_id FROM jobs WHERE source = ? AND active = 1", (source,))}


class TestDeactivateMissing:
    def test_rows_missing_from_feed_go_inactive(self, conn):
        upsert_jobs(conn, [_job("s1", "a"), _job("s1", "b"), _job("s1", "c")])
        assert _active_ids(conn, "s1") == {"a", "b", "c"}

        n = deactivate_missing(conn, "s1", {"a", "c"})

        assert n == 1
        assert _active_ids(conn, "s1") == {"a", "c"}

    def test_other_sources_are_untouched(self, conn):
        upsert_jobs(conn, [_job("s1", "a"), _job("s2", "a"), _job("s2", "b")])

        deactivate_missing(conn, "s1", set())

        assert _active_ids(conn, "s1") == set()
        assert _active_ids(conn, "s2") == {"a", "b"}

    def test_already_inactive_rows_are_not_recounted(self, conn):
        upsert_jobs(conn, [_job("s1", "a"), _job("s1", "b")])
        assert deactivate_missing(conn, "s1", {"a"}) == 1
        # Second sweep with the same feed changes nothing.
        assert deactivate_missing(conn, "s1", {"a"}) == 0

    def test_reappearing_listing_is_reactivated_by_upsert(self, conn):
        upsert_jobs(conn, [_job("s1", "a"), _job("s1", "b")])
        deactivate_missing(conn, "s1", {"a"})
        assert _active_ids(conn, "s1") == {"a"}

        upsert_jobs(conn, [_job("s1", "a"), _job("s1", "b")])  # b is back

        assert _active_ids(conn, "s1") == {"a", "b"}

    def test_handles_more_ids_than_sqlite_variable_limit(self, conn):
        # 21k+ live ids per source in production; a naive NOT IN (?,?,...)
        # blows past SQLITE_MAX_VARIABLE_NUMBER.
        upsert_jobs(conn, [_job("s1", str(i)) for i in range(1200)])
        n = deactivate_missing(conn, "s1", {str(i) for i in range(1200) if i % 2 == 0})
        assert n == 600


class TestSweepGuard:
    """A failed or empty fetch must never deactivate a corpus."""

    def test_failed_fetch_is_not_swept(self, conn):
        upsert_jobs(conn, [_job("s1", "a"), _job("s1", "b")])

        res = sweep_inactive(conn, {
            "s1": {"ok": False, "seen_ids": set(), "kept": 0, "error": "500 Server Error"}
        })

        assert res["s1"]["swept"] is False
        assert res["s1"]["deactivated"] == 0
        assert _active_ids(conn, "s1") == {"a", "b"}, "a 500 wiped the corpus"

    def test_successful_but_empty_payload_is_not_swept(self, conn):
        # A 200 with [] is indistinguishable from a schema change upstream.
        upsert_jobs(conn, [_job("s1", "a"), _job("s1", "b")])

        res = sweep_inactive(conn, {
            "s1": {"ok": True, "seen_ids": set(), "kept": 0, "error": None}
        })

        assert res["s1"]["swept"] is False
        assert _active_ids(conn, "s1") == {"a", "b"}

    def test_healthy_source_is_swept(self, conn):
        upsert_jobs(conn, [_job("s1", "a"), _job("s1", "b")])

        res = sweep_inactive(conn, {
            "s1": {"ok": True, "seen_ids": {"a"}, "kept": 1, "error": None}
        })

        assert res["s1"]["swept"] is True
        assert res["s1"]["deactivated"] == 1
        assert _active_ids(conn, "s1") == {"a"}

    def test_one_source_failing_does_not_block_the_other(self, conn):
        upsert_jobs(conn, [_job("s1", "a"), _job("s1", "b"),
                           _job("s2", "x"), _job("s2", "y")])

        sweep_inactive(conn, {
            "s1": {"ok": False, "seen_ids": set(), "kept": 0, "error": "timeout"},
            "s2": {"ok": True, "seen_ids": {"x"}, "kept": 1, "error": None},
        })

        assert _active_ids(conn, "s1") == {"a", "b"}
        assert _active_ids(conn, "s2") == {"x"}


class TestApplicationsSurvive:
    """schema.sql promises an application outlives its listing. Verify it."""

    def test_application_survives_deactivation(self, conn):
        upsert_jobs(conn, [_job("s1", "a")])
        job_id = conn.execute("SELECT id FROM jobs WHERE source_id = 'a'").fetchone()["id"]
        conn.execute(
            "INSERT INTO applications (job_id, status) VALUES (?, 'applied')", (job_id,))

        deactivate_missing(conn, "s1", set())

        row = conn.execute(
            "SELECT status FROM applications WHERE job_id = ?", (job_id,)).fetchone()
        assert row is not None, "sweep destroyed an application record"
        assert row["status"] == "applied"
        assert conn.execute(
            "SELECT active FROM jobs WHERE id = ?", (job_id,)).fetchone()["active"] == 0
