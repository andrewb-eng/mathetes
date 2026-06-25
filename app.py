"""Streamlit dashboard for mathetes match scores."""
import json

import pandas as pd
import streamlit as st

from db import get_connection

st.set_page_config(page_title="Mathetes", layout="wide")


@st.cache_data(ttl=60)
def load_data():
    conn = get_connection()

    scores = conn.execute("""
        SELECT
            c.name                          AS company,
            j.title,
            j.locations_json,
            j.url,
            c.ats_provider,
            ms.qualification_score          AS q_score,
            ms.fit_score,
            ms.summary,
            ms.tier,
            ms.created_at
        FROM match_scores ms
        JOIN jobs j ON j.id = ms.job_id
        JOIN companies c ON c.id = j.company_id
    """).fetchall()

    total_jobs = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    total_scored = conn.execute("SELECT COUNT(*) FROM match_scores").fetchone()[0]
    total_active = conn.execute("SELECT COUNT(*) FROM jobs WHERE active = 1").fetchone()[0]
    last_refreshed = conn.execute(
        "SELECT MAX(created_at) FROM match_scores"
    ).fetchone()[0]

    conn.close()

    rows = []
    for r in scores:
        locs = json.loads(r["locations_json"])
        rows.append({
            "company":   r["company"],
            "title":     r["title"],
            "locations": ", ".join(locs) if locs else "—",
            "url":       r["url"],
            "ats":       r["ats_provider"] or "unknown",
            "q_score":   r["q_score"],
            "fit_score": r["fit_score"],
            "combined":  r["q_score"] + r["fit_score"],
            "summary":   r["summary"] or "",
            "tier":      r["tier"],
            "created_at": r["created_at"],
        })

    df = pd.DataFrame(rows)
    return df, total_jobs, total_scored, total_active, last_refreshed


df, total_jobs, total_scored, total_active, last_refreshed = load_data()

LINK_COL = st.column_config.LinkColumn("url", display_text="open")
SCORE_COL = lambda label: st.column_config.NumberColumn(label, format="%d")

COLUMN_ORDER = ["company", "title", "locations", "q_score", "fit_score", "summary", "url"]
COLUMN_CONFIG = {
    "url":       LINK_COL,
    "q_score":   SCORE_COL("Q"),
    "fit_score": SCORE_COL("Fit"),
}

tab1, tab2, tab3 = st.tabs(["Targets", "By Company", "Stats"])


# ── Tab 1: Targets ────────────────────────────────────────────────────────────
with tab1:
    st.subheader("Top targets (Q ≥ 40, ranked by Q + Fit)")

    targets = (
        df[df["q_score"] >= 40]
        .sort_values("combined", ascending=False)
        .head(30)
        .reset_index(drop=True)
    )

    st.dataframe(
        targets[COLUMN_ORDER],
        column_config=COLUMN_CONFIG,
        width="stretch",
        hide_index=True,
    )

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
        q_hist = (
            df.assign(bucket=lambda d: (d["q_score"] // 10) * 10)
            .groupby("bucket")
            .size()
            .reindex(range(0, 100, 10), fill_value=0)
            .rename(index=lambda b: f"{b}–{b+9}")
            .rename("count")
        )
        st.bar_chart(q_hist)

    with col_f:
        st.markdown("**Fit score distribution**")
        f_hist = (
            df.assign(bucket=lambda d: (d["fit_score"] // 10) * 10)
            .groupby("bucket")
            .size()
            .reindex(range(0, 100, 10), fill_value=0)
            .rename(index=lambda b: f"{b}–{b+9}")
            .rename("count")
        )
        st.bar_chart(f_hist)

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
