"""Application lifecycle tracking, decoupled from scoring.

match_scores is profile-versioned and cleared on every profile/resume edit;
application state lives here, keyed on jobs.id alone, so it survives
re-scoring and survives the listing going inactive in the feed.

Every function takes an optional conn so callers (and tests) can supply
their own database; without one, a connection is opened and closed per call.
"""
from db import get_connection

# Funnel order — also the display order for the dashboard Pipeline tab.
STATUSES = ["interested", "applied", "OA", "interview", "offer", "rejected", "withdrawn"]

# Reaching any of these stages implies an application was submitted, so
# applied_at is stamped automatically the first time one is set.
_APPLIED_STAGES = {"applied", "OA", "interview", "offer"}


def _run(conn, fn):
    """Run fn(conn) on the given conn, or on a fresh one closed afterwards."""
    if conn is not None:
        return fn(conn)
    own = get_connection()
    try:
        return fn(own)
    finally:
        own.close()


def set_status(job_id, status, notes=None, applied_at=None, conn=None):
    """Create or update the application row for a job (upsert on job_id).

    notes=None leaves any existing notes untouched; pass "" to clear them.
    applied_at is stamped with today's date the first time the status reaches
    an applied-or-later stage, unless given explicitly; once set it is never
    overwritten with NULL.
    """
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}, got {status!r}")
    if applied_at is not None:
        # Explicit date: caller is setting or correcting it — takes precedence.
        insert_val, update_expr = ":applied_at", "excluded.applied_at"
    elif status in _APPLIED_STAGES:
        # Auto-stamp: first applied-or-later transition records today (local
        # date, not UTC — an evening application must not be dated tomorrow);
        # later stage changes must not overwrite the original date.
        insert_val = "date('now', 'localtime')"
        update_expr = "COALESCE(applications.applied_at, excluded.applied_at)"
    else:
        insert_val, update_expr = ":applied_at", "applications.applied_at"

    def _upsert(c):
        c.execute(
            f"""INSERT INTO applications (job_id, status, notes, applied_at)
                VALUES (:job_id, :status, :notes, {insert_val})
                ON CONFLICT(job_id) DO UPDATE SET
                    status            = excluded.status,
                    status_updated_at = CURRENT_TIMESTAMP,
                    notes             = COALESCE(excluded.notes, applications.notes),
                    applied_at        = {update_expr}""",
            {"job_id": int(job_id), "status": status, "notes": notes,
             "applied_at": applied_at},
        )
        c.commit()

    _run(conn, _upsert)


def get_application(job_id, conn=None):
    """Return the application row for a job, or None if untracked."""
    return _run(conn, lambda c: c.execute(
        "SELECT * FROM applications WHERE job_id = ?", (int(job_id),)
    ).fetchone())


def status_map(conn=None):
    """Return {job_id: status} for every tracked job — cheap lookup for tables."""
    return _run(conn, lambda c: dict(
        c.execute("SELECT job_id, status FROM applications")
    ))


def fetch_applications(conn=None):
    """Return all tracked applications joined to job/company for display.

    Inactive jobs are included on purpose: the listing closing does not undo
    an application you already submitted.
    """
    return _run(conn, lambda c: c.execute("""
        SELECT a.job_id, a.status, a.status_updated_at, a.applied_at, a.notes,
               j.title, j.url, j.active,
               c2.name AS company
        FROM applications a
        JOIN jobs j ON j.id = a.job_id
        JOIN companies c2 ON c2.id = j.company_id
        ORDER BY a.status_updated_at DESC
    """).fetchall())
