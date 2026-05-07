"""Daily pull: fetch from all sources, persist to DB, print summary."""
from db import get_connection, init_db
from lib.upsert import upsert_jobs
from sources import github_lists


def main():
    init_db()
    conn = get_connection()

    try:
        stats = upsert_jobs(conn, github_lists.fetch_all())
        conn.commit()
    finally:
        conn.close()

    print(f"\n=== PULL COMPLETE ===")
    print(f"Total seen:  {stats['total_seen']}")
    print(f"Inserted:    {stats['inserted']}")
    print(f"Updated:     {stats['updated']}")


if __name__ == "__main__":
    main()