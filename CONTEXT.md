# Mathetes — Internal Architecture Context

*For future Claude sessions and personal reference. Written after Phase 2 shipped (two-axis scoring working end-to-end).*

---

## Data Flow

```
GitHub JSON feeds
    → sources/github_lists.py (fetch + normalize)
        → lib/upsert.py (dedup + persist)
            → data/mathetes.db
                → match_batch.py (tier filter → Claude → persist)
                    → match_scores table
                        → app.py (Streamlit read-only)
```

**Step 1: Fetch.** `github_lists.py` hits two raw GitHub JSON URLs at the `dev` branch of the community-maintained lists. Each source publishes a flat list of job objects. The normalizer converts these to a common internal shape and skips listings where `is_visible == False` or required fields (`id`, `company_name`, `title`, `url`) are missing. It does NOT skip `active == False` — inactive listings are kept and marked accordingly downstream. Season normalization handles the format difference between sources (vanshb03 uses a `season` string; SimplifyJobs uses a `terms` list).

**Step 2: Upsert.** `lib/upsert.py` processes the normalized stream. For each job, it:
- Calls `detect_ats(url)` to identify the ATS provider and company token from the URL.
- Calls `_get_or_create_company()` — looks up by `name_normalized` (lowercased, suffixes stripped), creating the company row if new or backfilling ATS data if the company existed but the field was empty.
- Computes a `fingerprint` = SHA256[:16] of `company_normalized::title_normalized::locations_sorted`. This enables cross-source deduplication (same job posted on both sources gets the same fingerprint).
- Upserts on `UNIQUE(source, source_id)`: new listings are inserted, existing ones are updated in-place and `last_seen_at` is refreshed. ATS data, locations, and active status can all change on update.

**Step 3: Score.** `match_batch.py` loads `profile.yaml` and `resume.yaml`, computes a 12-char SHA256 version hash of each, then queries all active Summer 2027-relevant jobs. Season filter: `j.season LIKE '%2027%' OR j.season IN ('Summer', 'N/A')` — the `N/A` arm catches listings with no explicit cycle, which are assumed current. Each job is classified by `lib/tiering.py` and scored against the requested tier. Already-scored jobs (matching `job_id + profile_version + resume_version`) are skipped — the `already_scored` set is loaded once at the start of the run. After each successful score, `conn.commit()` is called immediately so progress survives a crash mid-batch. Rate limiting: 0.2s sleep between API calls.

---

## Schema Decisions

**Why companies is a separate table.** ATS data belongs to the company, not the job. A company can have dozens of listings, all of which share the same ATS provider and token. Storing it per-company and backfilling on discovery means we don't miss it when a job is inserted before ATS detection happened to fire.

**Why `fingerprint` exists.** `(source, source_id)` is the primary uniqueness constraint, but if the same role appears in both feeds, we want to know. The fingerprint (company + normalized title + sorted locations) enables querying for cross-source duplicates without a full join. Currently unused in queries but stored for later analysis.

**Why `raw_payload` is stored on jobs.** Source schema changes happen mid-cycle as maintainers add fields. Storing the full raw JSON means we can re-derive structured fields from old listings without re-fetching, and we can inspect exactly what came from the source when a parsing issue appears.

**Why `profile_version` and `resume_version` on `match_scores`.** The UNIQUE constraint is `(job_id, profile_version, resume_version)`. This is the idempotency mechanism. Changing either YAML file changes its SHA256 hash, which changes the version string, which means all existing score rows no longer match the new version — so re-running the batch naturally scores only jobs that haven't been seen under the new profile/resume. No explicit invalidation logic needed.

**Why `class_year_eligible` is stored but not filtered in the UI.** The batch query already filters for Summer 2027-relevant seasons, but individual listings sometimes say "2026" in the title or description while being listed under a broader season tag. Storing the model's judgment lets us add a filter later without re-scoring. Currently it's not shown as a column in the Streamlit dashboard — this is a gap.

---

## The Calibration Journey

**Phase 1 (match.py — proof of concept).** The first prompt was a minimal instruction: return a JSON object with qualification and fit scores. Result: clustering around q=70–75. Claude's default behavior is to find something positive in the candidate's profile and score to the middle as a show of encouragement. A high GPA in a non-quantitative major was being treated as a strong signal for quantitative research roles, which is wrong.

**Phase 2 (match_batch.py — calibrated version).** The fix was explicit score-band anchors in the prompt with concrete examples of what earns each band, plus seven hard rules for role types where the candidate's profile is structurally unqualified regardless of other strengths. The hard rules are:
1. Quant research at top funds → 5–20 (requires math olympiad / PhD pipeline / prior quant output; a high GPA in a non-STEM major is not a substitute, stated explicitly in the prompt)
2. SWE intern at top tech/fintech → 15–35 (requires CS major + prior SWE internships; "two weeks of Python" doesn't qualify)
3. FDE, BizOps, Strategy, Investment Analyst at same companies → 60–85 eligible (they explicitly recruit non-CS analytical undergrads — treat differently)
4. ML/AI Research → 5–20 (requires grad-level math/ML)
5. Hardware/FPGA/embedded → 5–15
6. Defense prime SWE → 25–45 (slightly more accessible than top fintech, US citizen signal is real)
7. Data Scientist/Analyst with independent coding expectations → 20–40 (domain match is irrelevant to qualification gate)

The system prompt addition: *"You are NOT a career coach. You do not give encouragement. Score what the resume actually shows, not what the candidate hopes to become."*

The result was meaningful score spread: named-target quant/SWE roles correctly landing 15–30 range on qualification; FDE and BizOps roles at the same companies landing 55–75; pure fit mismatches getting low fit scores even at high qualification. The split-axis design becomes genuinely informative once the calibration is in place.

---

## Tiered Scoring

Tier classification lives in `lib/tiering.py`. The two active tiers:

**Tier 1 — `named_target`.** 25 specific companies matched by substring against the lowercased company name, via a compiled regex. Includes trading firms, defense tech, fintech, and AI labs. All named-target jobs are scored regardless of title. `run_daily.sh` runs `match_batch.py tier1` first so these are never missed if tier2 fails.

**Tier 2 — `keyword`.** Regex match on a set of ~15 patterns across company name + job title. Catches roles at non-named companies that look like plausible targets: quant, trading, defense, fintech, BizOps, strategy, product analytics, FDE, data science, applied AI/LLM.

**Tier 3 — `skip`.** Everything else. These jobs are stored in the database but never sent to Claude. On a typical pull of ~20k listings, the vast majority are tier 3 — SWE roles at companies the candidate has no particular interest in.

---

## Known Limitations

**No STEM-degree title filter at the tier level.** Tier 2 catches `\bdata science\b` and `\bdata analyst\b` roles, which correctly surfaces them for scoring, but the prompt's hard rule 7 then typically scores them 20–40 on qualification. These show up in the scored pool with low Q and medium Fit — technically correct behavior, but it adds noise. A pre-filter that excludes titles explicitly requiring CS/engineering majors would reduce Claude spend on obvious misses.

**Season filter includes `N/A`.** Listings where the source doesn't specify a season are assumed current and included in the scoring queue. Most are fine; some are legacy listings from prior cycles that the source never marked inactive. This adds a small tail of irrelevant scores. The model's `class_year_eligible` field catches most of these, but it's not surfaced in the UI filter.

**No pagination / rate-limit backoff on GitHub fetches.** `github_lists.py` makes one blocking GET per source. This is fine for the current two-source setup but would need retry logic and exponential backoff before adding more sources.

**`top.py` uses a hardcoded relative path (`data/mathetes.db`)** rather than importing from `db.py`. Works when run from the repo root, breaks otherwise. Should be refactored to use `db.get_connection()` for consistency.

**Streamlit `app.py` reads from `data/mathetes.db` via `db.get_connection()`** but uses `@st.cache_data(ttl=60)`. After a batch run, you need to wait up to 60 seconds or restart the Streamlit server to see fresh scores.

**No class_year_eligible filter in the dashboard.** The field is stored and scored but not exposed as a filter column in `app.py`. Listings for wrong cycles can appear in the Targets tab if their Q/Fit scores are high enough.

**Profile and resume are committed to the repo.** Contact fields in `resume.yaml` (email, phone, LinkedIn, location) should be stripped before any public push. The profile and resume YAML files drive all scoring — they're not optional — but contact details within them serve no pipeline function.
