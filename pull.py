"""Daily pull: fetch from all sources, persist to DB, expire vanished listings."""
from db import get_connection, init_db
from lib.upsert import sweep_inactive, upsert_jobs
from sources import github_lists


def main():
    """Ensure the schema exists, ingest all sources, sweep, and report."""
    init_db()
    conn = get_connection()

    try:
        before = _active_counts(conn)
        outcomes = {}
        # fetch_all fills `outcomes` as it goes; upsert_jobs drains it fully,
        # so every source has a final verdict by the time we sweep.
        stats = upsert_jobs(conn, github_lists.fetch_all(outcomes))
        swept = sweep_inactive(conn, outcomes)
        conn.commit()
        after = _active_counts(conn)
    finally:
        conn.close()

    print("\n=== PULL COMPLETE ===")
    print(f"Total seen:  {stats['total_seen']}")
    print(f"Inserted:    {stats['inserted']}")
    print(f"Updated:     {stats['updated']}")
    if stats["failed"]:
        print(f"Failed:      {stats['failed']} (see warnings above)")

    print("\n=== ACTIVE LISTINGS BY SOURCE ===")
    for source in sorted(set(before) | set(after)):
        result = swept.get(source)
        if result is None:
            note = "not in this run"
        elif result["swept"]:
            note = f"swept, {result['deactivated']} deactivated"
        else:
            note = f"NOT SWEPT — {result['reason']}"
        print(f"  {source:28s} {before.get(source, 0):6d} -> {after.get(source, 0):6d}  ({note})")


def _active_counts(conn) -> dict:
    """Return {source: active row count} for the before/after sweep report."""
    return {r["source"]: r["n"] for r in conn.execute(
        "SELECT source, COUNT(*) AS n FROM jobs WHERE active = 1 GROUP BY source")}


if __name__ == "__main__":
    main()
