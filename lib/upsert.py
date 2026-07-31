"""Persist normalized jobs into the SQLite DB. Idempotent."""
import hashlib
import json
import sqlite3
from typing import Iterable

from lib.ats_detect import detect_ats


def _normalize_company_name(name: str) -> str:
    """Lowercase, strip whitespace and common suffixes for matching."""
    n = name.lower().strip()
    for suffix in (", inc.", ", inc", " inc.", " inc", ", llc", " llc",
                   ", ltd.", " ltd.", ", ltd", " ltd", " corporation", " corp."):
        if n.endswith(suffix):
            n = n[: -len(suffix)].strip()
    return n


def _fingerprint(company_norm: str, title: str, locations: list[str]) -> str:
    """Stable hash for cross-source dedup."""
    title_norm = title.lower().strip()
    locs_norm = "|".join(sorted(loc.lower().strip() for loc in locations))
    raw = f"{company_norm}::{title_norm}::{locs_norm}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _get_or_create_company(conn: sqlite3.Connection, name: str,
                           ats_provider: str | None, ats_token: str | None,
                           company_url: str | None) -> int:
    """Return company.id, creating the row if needed."""
    name_norm = _normalize_company_name(name)
    row = conn.execute(
        "SELECT id, ats_provider FROM companies WHERE name_normalized = ?",
        (name_norm,),
    ).fetchone()

    if row is not None:
        # Backfill ATS info if we didn't have it before.
        if ats_provider and not row["ats_provider"]:
            conn.execute(
                "UPDATE companies SET ats_provider = ?, ats_token = ? WHERE id = ?",
                (ats_provider, ats_token, row["id"]),
            )
        return row["id"]

    cur = conn.execute(
        """INSERT INTO companies (name, name_normalized, ats_provider, ats_token, company_url)
           VALUES (?, ?, ?, ?, ?)""",
        (name, name_norm, ats_provider, ats_token, company_url),
    )
    return cur.lastrowid


def upsert_jobs(conn: sqlite3.Connection, jobs: Iterable[dict]) -> dict:
    """
    Upsert a stream of normalized job dicts.

    A malformed entry is counted and skipped rather than aborting the whole
    pull. Returns a stats dict: {inserted, updated, failed, total_seen}.
    """
    stats = {"inserted": 0, "updated": 0, "failed": 0, "total_seen": 0}

    for job in jobs:
        stats["total_seen"] += 1
        try:
            _upsert_one(conn, job, stats)
        except (KeyError, TypeError, ValueError, sqlite3.Error) as e:
            stats["failed"] += 1
            company = job.get("company_name", "?") if isinstance(job, dict) else "?"
            print(f"  upsert failed for {company!r}: {type(e).__name__}: {e}")

    return stats


def deactivate_missing(conn: sqlite3.Connection, source: str,
                       seen_ids: Iterable[str]) -> int:
    """Mark rows inactive when the current feed no longer lists them.

    upsert_jobs only ever touches rows still present in a feed, so without this
    a listing that disappears stays active forever. Returns the number of rows
    newly deactivated (rows already inactive are not recounted).

    Callers must go through sweep_inactive() rather than calling this directly
    with an empty set — see the guard documented there.

    The seen ids go through a temp table rather than a NOT IN (?, ?, ...) list
    because a healthy source carries 20k+ live ids, far past SQLite's bound
    parameter limit.
    """
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS _seen_ids (source_id TEXT PRIMARY KEY)")
    conn.execute("DELETE FROM _seen_ids")
    conn.executemany("INSERT OR IGNORE INTO _seen_ids (source_id) VALUES (?)",
                     ((str(sid),) for sid in seen_ids))

    cur = conn.execute(
        """UPDATE jobs SET active = 0
           WHERE source = ? AND active = 1
             AND source_id NOT IN (SELECT source_id FROM _seen_ids)""",
        (source,),
    )
    deactivated = cur.rowcount
    conn.execute("DELETE FROM _seen_ids")
    return deactivated


def sweep_inactive(conn: sqlite3.Connection, outcomes: dict) -> dict:
    """Deactivate vanished listings, but only for sources that fetched cleanly.

    This guard is the whole point. github_lists.fetch_all() swallows per-source
    fetch failures and simply yields nothing for a dead source, so an
    unguarded sweep would read a 500 — or an upstream schema change — as "the
    feed is empty now" and deactivate that source's entire corpus. A source is
    swept only when its fetch succeeded AND returned at least one usable
    listing; a successful-but-empty payload is treated as suspect, not as
    authoritative emptiness.

    `outcomes` is the dict populated by fetch_all(). Returns
    {source: {"swept": bool, "deactivated": int, "reason": str | None}}.
    """
    results = {}
    for source, outcome in outcomes.items():
        if not outcome.get("ok"):
            results[source] = {"swept": False, "deactivated": 0,
                               "reason": f"fetch failed: {outcome.get('error')}"}
        elif not outcome.get("seen_ids"):
            results[source] = {"swept": False, "deactivated": 0,
                               "reason": "fetch returned no usable listings"}
        else:
            results[source] = {
                "swept": True,
                "deactivated": deactivate_missing(conn, source, outcome["seen_ids"]),
                "reason": None,
            }
    return results


def _upsert_one(conn: sqlite3.Connection, job: dict, stats: dict) -> None:
    """Insert or update a single job row, bumping the matching stats counter."""
    ats_provider, ats_token = detect_ats(job["url"])
    company_id = _get_or_create_company(
        conn, job["company_name"], ats_provider, ats_token, job["company_url"]
    )

    fingerprint = _fingerprint(
        _normalize_company_name(job["company_name"]),
        job["title"],
        job["locations"],
    )

    existing = conn.execute(
        "SELECT id FROM jobs WHERE source = ? AND source_id = ?",
        (job["source"], job["source_id"]),
    ).fetchone()

    if existing is not None:
        conn.execute(
            """UPDATE jobs SET
                   title = ?, locations_json = ?, url = ?,
                   ats_provider = ?, ats_token = ?,
                   season = ?, category = ?, degrees_json = ?,
                   sponsorship = ?, active = ?,
                   posted_at = ?, updated_at = ?,
                   last_seen_at = CURRENT_TIMESTAMP,
                   raw_payload = ?
               WHERE id = ?""",
            (
                job["title"],
                json.dumps(job["locations"]),
                job["url"],
                ats_provider, ats_token,
                job["season"], job["category"],
                json.dumps(job["degrees"]),
                job["sponsorship"],
                1 if job["active"] else 0,
                job["posted_at"], job["updated_at"],
                json.dumps(job["raw_payload"]),
                existing["id"],
            ),
        )
        stats["updated"] += 1
    else:
        conn.execute(
            """INSERT INTO jobs
               (company_id, source, source_id, fingerprint, title,
                locations_json, url, ats_provider, ats_token,
                season, category, degrees_json, sponsorship,
                is_internship, active, posted_at, updated_at, raw_payload)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)""",
            (
                company_id, job["source"], job["source_id"], fingerprint,
                job["title"], json.dumps(job["locations"]), job["url"],
                ats_provider, ats_token,
                job["season"], job["category"],
                json.dumps(job["degrees"]),
                job["sponsorship"],
                1 if job["active"] else 0,
                job["posted_at"], job["updated_at"],
                json.dumps(job["raw_payload"]),
            ),
        )
        stats["inserted"] += 1