"""Streamlit dashboard for mathetes match scores."""
import json
import sqlite3

import pandas as pd
import streamlit as st

from db import get_connection
from lib.applications import STATUSES, fetch_applications, get_application, set_status, status_map

st.set_page_config(page_title="Mathetes", layout="wide")


def _json_list(raw) -> list[str]:
    """Parse a JSON-array column defensively; malformed or empty data becomes []."""
    try:
        val = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return []
    return [str(item) for item in val] if isinstance(val, list) else []


@st.cache_data(ttl=60)
def load_data():
    """Load match scores for the latest profile version, plus corpus totals.

    Restricting to the latest profile_version matches winners.py, so the
    dashboard never blends scores from superseded profile/resume edits.
    Cached for 60s per Streamlit session.
    """
    conn = get_connection()
    try:
        # Look up the latest profile_version once and parameterize both
        # filtered queries with it, so the table and the "Scored" count can
        # never drift apart. None (no scores yet) matches no rows, which the
        # empty-df guard below handles.
        latest = conn.execute(
            "SELECT profile_version FROM match_scores ORDER BY id DESC LIMIT 1"
        ).fetchone()
        latest_version = latest[0] if latest else None

        scores = conn.execute("""
            SELECT
                j.id                            AS job_id,
                c.name                          AS company,
                j.title,
                j.locations_json,
                j.url,
                c.ats_provider,
                ms.qualification_score          AS q_score,
                ms.fit_score,
                ms.class_year_eligible,
                ms.top_matches_json,
                ms.top_gaps_json,
                ms.fit_reasoning,
                ms.summary,
                ms.tier,
                ms.created_at
            FROM match_scores ms
            JOIN jobs j ON j.id = ms.job_id
            JOIN companies c ON c.id = j.company_id
            WHERE ms.profile_version = ?
        """, (latest_version,)).fetchall()

        total_jobs = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        total_scored = conn.execute(
            "SELECT COUNT(*) FROM match_scores WHERE profile_version = ?",
            (latest_version,),
        ).fetchone()[0]
        total_active = conn.execute("SELECT COUNT(*) FROM jobs WHERE active = 1").fetchone()[0]
        last_refreshed = conn.execute(
            "SELECT MAX(created_at) FROM match_scores"
        ).fetchone()[0]
    finally:
        conn.close()

    rows = []
    for r in scores:
        locs = _json_list(r["locations_json"])
        rows.append({
            "job_id":    r["job_id"],
            "company":   r["company"],
            "title":     r["title"],
            "locations": ", ".join(locs) if locs else "—",
            "url":       r["url"],
            "ats":       r["ats_provider"] or "unknown",
            "q_score":   r["q_score"],
            "fit_score": r["fit_score"],
            "combined":  r["q_score"] + r["fit_score"],
            "eligible":  bool(r["class_year_eligible"]),
            "top_matches": _json_list(r["top_matches_json"]),
            "top_gaps":  _json_list(r["top_gaps_json"]),
            "fit_reasoning": r["fit_reasoning"] or "",
            "summary":   r["summary"] or "",
            "tier":      r["tier"],
            "created_at": r["created_at"],
        })

    df = pd.DataFrame(rows)
    return df, total_jobs, total_scored, total_active, last_refreshed


try:
    df, total_jobs, total_scored, total_active, last_refreshed = load_data()
    # Application state is deliberately NOT cached: status edits must show
    # immediately, and the table is tiny.
    app_status = status_map()
except sqlite3.OperationalError as e:
    st.error(f"Database not ready ({e}). Run `python db.py` then `python pull.py` first.")
    st.stop()

if df.empty:
    st.info("No match scores yet — run `python pull.py` then `python match_batch.py tier1`.")
    st.stop()


def _score_col(label: str) -> st.column_config.NumberColumn:
    """Column config for a whole-number score column with a short header."""
    return st.column_config.NumberColumn(label, format="%d")


def _score_hist(frame: pd.DataFrame, col: str) -> pd.Series:
    """Bucket a 0-100 score column into decades for a bar chart.

    A score of exactly 100 is folded into the top bucket (labeled 90–100)
    rather than a phantom "100" bucket the reindex would drop.
    """
    return (
        frame.assign(bucket=(frame[col].clip(upper=99) // 10) * 10)
        .groupby("bucket")
        .size()
        .reindex(range(0, 100, 10), fill_value=0)
        .rename(index=lambda b: f"{b}–{b+9}" if b < 90 else "90–100")
        .rename("count")
    )


COLUMN_ORDER = ["company", "title", "locations", "q_score", "fit_score", "summary", "url"]
TARGET_COLUMNS = ["company", "title", "status", "locations", "q_score", "fit_score", "top_gaps", "summary", "url"]
COLUMN_CONFIG = {
    "url":       st.column_config.LinkColumn("url", display_text="open"),
    "q_score":   _score_col("Q"),
    "fit_score": _score_col("Fit"),
    "top_gaps":  st.column_config.TextColumn("Top gaps"),
    "status":    st.column_config.TextColumn("Status"),
}

tab1, tab2, tab3, tab4 = st.tabs(["Targets", "By Company", "Stats", "Pipeline"])


# ── Tab 1: Targets ────────────────────────────────────────────────────────────
with tab1:
    st.subheader("Top targets (Q ≥ 40, ranked by Q + Fit)")

    eligible_only = st.checkbox("Only class-year-eligible roles", value=True)

    targets = df[df["q_score"] >= 40]
    if eligible_only:
        targets = targets[targets["eligible"]]
    targets = (
        targets.sort_values("combined", ascending=False)
        .head(30)
        .reset_index(drop=True)
    )

    if targets.empty:
        st.info("No roles match the current filter.")
    else:
        targets["status"] = targets["job_id"].map(app_status).fillna("—")
        table = targets[TARGET_COLUMNS].copy()
        table["top_gaps"] = targets["top_gaps"].map(lambda gaps: "; ".join(gaps) if gaps else "—")
        st.dataframe(
            table,
            column_config=COLUMN_CONFIG,
            width="stretch",
            hide_index=True,
        )

        st.markdown("---")
        st.markdown("**Role detail**")
        selected = st.selectbox(
            "Role detail",
            targets.index,
            format_func=lambda i: f"{targets.at[i, 'company']} — {targets.at[i, 'title']}",
            label_visibility="collapsed",
        )
        role = targets.loc[selected]

        st.markdown("✅ Class-year eligible" if role["eligible"] else "⚠️ Not class-year eligible")
        if role["fit_reasoning"]:
            st.markdown(f"**Fit reasoning:** {role['fit_reasoning']}")

        col_matches, col_gaps = st.columns(2)
        with col_matches:
            st.markdown("**Top matches**")
            st.markdown("\n".join(f"- {m}" for m in role["top_matches"]) or "_none recorded_")
        with col_gaps:
            st.markdown("**Top gaps**")
            st.markdown("\n".join(f"- {g}" for g in role["top_gaps"]) or "_none recorded_")

        st.markdown("**Application status**")
        job_id = int(role["job_id"])
        existing = get_application(job_id)
        current_status = existing["status"] if existing else None
        col_status, col_notes, col_save = st.columns([1, 2, 1], vertical_alignment="bottom")
        with col_status:
            chosen = st.selectbox(
                "Status",
                ["(untracked)"] + STATUSES,
                index=(STATUSES.index(current_status) + 1) if current_status else 0,
                key=f"status_{job_id}",
            )
        with col_notes:
            notes = st.text_input(
                "Notes",
                value=(existing["notes"] or "") if existing else "",
                key=f"notes_{job_id}",
            )
        with col_save:
            if st.button("Save", disabled=(chosen == "(untracked)"), key=f"save_{job_id}"):
                set_status(job_id, chosen, notes=notes)
                st.rerun()
        if existing:
            applied = f" · applied {existing['applied_at']}" if existing["applied_at"] else ""
            st.caption(f"Tracked: {existing['status']} since {existing['status_updated_at']}{applied}")

    st.caption(f"Last refreshed: {last_refreshed}")


# ── Tab 2: By Company ─────────────────────────────────────────────────────────
with tab2:
    st.subheader("Best job per named-target company")

    named = df[df["tier"] == "named_target"].copy()
    best = (
        named.sort_values("combined", ascending=False)
        .drop_duplicates(subset=["company"], keep="first")
        .sort_values("combined", ascending=False)
        .reset_index(drop=True)
    )

    st.dataframe(
        best[COLUMN_ORDER],
        column_config=COLUMN_CONFIG,
        width="stretch",
        hide_index=True,
    )

    st.caption(f"Last refreshed: {last_refreshed}")


# ── Tab 3: Stats ──────────────────────────────────────────────────────────────
with tab3:
    st.subheader("Stats")

    c1, c2, c3 = st.columns(3)
    c1.metric("Total jobs", total_jobs)
    c2.metric("Active jobs", total_active)
    c3.metric("Scored", total_scored)

    st.markdown("---")

    col_q, col_f = st.columns(2)

    with col_q:
        st.markdown("**Qualification score distribution**")
        st.bar_chart(_score_hist(df, "q_score"))

    with col_f:
        st.markdown("**Fit score distribution**")
        st.bar_chart(_score_hist(df, "fit_score"))

    st.markdown("---")
    st.markdown("**Jobs by ATS provider**")

    ats_counts = (
        df.drop_duplicates(subset=["company", "title"])
        .groupby("ats")
        .size()
        .sort_values(ascending=False)
        .rename("jobs")
    )
    st.bar_chart(ats_counts)

    st.caption(f"Last refreshed: {last_refreshed}")


# ── Tab 4: Pipeline ───────────────────────────────────────────────────────────
with tab4:
    st.subheader("Application pipeline")

    tracked = fetch_applications()

    if not tracked:
        st.info("No applications tracked yet — pick a role on the Targets tab and set its status.")
    else:
        counts = {s: 0 for s in STATUSES}
        for r in tracked:
            counts[r["status"]] += 1
        metric_cols = st.columns(len(STATUSES))
        for col, s in zip(metric_cols, STATUSES):
            col.metric(s, counts[s])

        st.markdown("---")

        pipeline_df = pd.DataFrame([{
            "company":   r["company"],
            "title":     r["title"],
            "status":    r["status"],
            "listing":   "active" if r["active"] else "closed",
            "applied":   r["applied_at"] or "—",
            "updated":   r["status_updated_at"],
            "notes":     r["notes"] or "",
            "url":       r["url"],
        } for r in tracked])

        for s in STATUSES:
            group = pipeline_df[pipeline_df["status"] == s]
            if group.empty:
                continue
            st.markdown(f"**{s}** ({len(group)})")
            st.dataframe(
                group.drop(columns=["status"]),
                column_config={"url": st.column_config.LinkColumn("url", display_text="open")},
                width="stretch",
                hide_index=True,
            )
