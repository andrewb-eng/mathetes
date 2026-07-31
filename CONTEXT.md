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

**Step 1: Fetch.** `github_lists.py` hits two raw GitHub JSON URLs at the `dev` branch of the community-maintained lists. Each source publishes a flat list of job objects. The normalizer converts these to a common internal shape and skips listings where `is_visible == False` or required fields (`id`, `company_name`, `title`, `url`) are missing. It does NOT skip `active == False` — inactive listings are kept and marked accordingly downstream. Season normalization handles the format difference between sources (vanshb03 uses a `season` string; SimplifyJobs uses a `terms` list): the target cycle (`Summer 2027`) wins the season field when it appears anywhere in `terms`; otherwise the first term is kept.

**Step 2: Upsert.** `lib/upsert.py` processes the normalized stream. For each job, it:
- Calls `detect_ats(url)` to identify the ATS provider and company token from the URL.
- Calls `_get_or_create_company()` — looks up by `name_normalized` (lowercased, suffixes stripped), creating the company row if new or backfilling ATS data if the company existed but the field was empty.
- Computes a `fingerprint` = SHA256[:16] of `company_normalized::title_normalized::locations_sorted`. This enables cross-source deduplication (same job posted on both sources gets the same fingerprint).
- Upserts on `UNIQUE(source, source_id)`: new listings are inserted, existing ones are updated in-place and `last_seen_at` is refreshed. ATS data, locations, and active status can all change on update.

**Step 2b: Deactivation sweep.** The upsert loop only ever touches rows still present in a feed, so before July 2026 a listing that *disappeared* stayed `active = 1` forever. One source carried 1,337 active rows against a live feed of 249. `sweep_inactive()` closes this: `fetch_all()` now records a per-source outcome (`ok` / `seen_ids` / `error`), and each successfully-fetched source has its absent rows set `active = 0`.

The guard is the point. `fetch_all()` swallows per-source fetch failures and yields nothing for a dead source, so an unguarded sweep would read a 500 as "the feed is empty now" and deactivate that source's entire corpus. A source is swept only when its fetch **succeeded and returned at least one usable listing** — a successful-but-empty payload is treated as suspect, not authoritative. Seen ids go through a temp table because a healthy source carries 20k+ live ids, past SQLite's bound-parameter limit. Reappearing listings are reactivated naturally by the next upsert. `applications` rows are unaffected by design and this is covered by a test.

The one-time backfill (2026-07-31) took the corpus from 2,834 to 1,644 active, after which both sources reconciled exactly with their live feeds. `pull.py` prints a per-source before → after table on every run, including a loud `NOT SWEPT` line when a source is skipped.

**Step 3: Score.** `match_batch.py` loads `profile.yaml` and `resume.yaml`, computes a 12-char SHA256 version hash of each, then queries all active Summer 2027-relevant jobs. Season filter (three arms): `j.season LIKE '%2027%'` (explicit cycle tags), `j.season IN ('Summer', 'N/A')` (vanshb03 stamps bare season names in a 2027-cycle repo; `N/A` is Simplify's unknown-cycle tag, assumed current), and `j.season IS NULL` (missing field, treated like `N/A`). Multi-term Simplify listings are stamped `Summer 2027` at ingest whenever that cycle appears anywhere in their `terms` list — the normalizer prefers the target cycle over `terms[0]` — so the gate can trust the stored season column and no longer scans `raw_payload`. Each job is classified by `lib/tiering.py` and scored against the requested tier. Already-scored jobs (matching `job_id + profile_version + resume_version`) are skipped — the `already_scored` set is loaded once at the start of the run. After each successful score, `conn.commit()` is called immediately so progress survives a crash mid-batch. Rate limiting: 0.2s sleep between API calls.

---

## Schema Decisions

**Why companies is a separate table.** ATS data belongs to the company, not the job. A company can have dozens of listings, all of which share the same ATS provider and token. Storing it per-company and backfilling on discovery means we don't miss it when a job is inserted before ATS detection happened to fire.

**Why `fingerprint` exists.** `(source, source_id)` is the primary uniqueness constraint, but if the same role appears in both feeds, we want to know. The fingerprint (company + normalized title + sorted locations) enables querying for cross-source duplicates without a full join. Currently unused in queries but stored for later analysis.

**Why `raw_payload` is stored on jobs.** Source schema changes happen mid-cycle as maintainers add fields. Storing the full raw JSON means we can re-derive structured fields from old listings without re-fetching, and we can inspect exactly what came from the source when a parsing issue appears.

**Why `profile_version` and `resume_version` on `match_scores`.** The UNIQUE constraint is `(job_id, profile_version, resume_version)`. This is the idempotency mechanism. Changing either YAML file changes its SHA256 hash, which changes the version string, which means all existing score rows no longer match the new version — so re-running the batch naturally scores only jobs that haven't been seen under the new profile/resume. No explicit invalidation logic needed.

**Why `class_year_eligible` is stored but not filtered in the UI.** The batch query already filters for Summer 2027-relevant seasons, but individual listings sometimes say "2026" in the title or description while being listed under a broader season tag. Storing the model's judgment lets us add a filter later without re-scoring. Currently it's not shown as a column in the Streamlit dashboard — this is a gap.

---

## The Calibration Journey

**Phase 1 (match.py — proof of concept; since removed, see git history).** The first prompt was a minimal instruction: return a JSON object with qualification and fit scores. Result: clustering around q=70–75. Claude's default behavior is to find something positive in the candidate's profile and score to the middle as a show of encouragement. A high GPA in a non-quantitative major was being treated as a strong signal for quantitative research roles, which is wrong.

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

Tier classification lives in `lib/tiering.py`. **The tier is only a queue selector and a stored label — it is never fed to the model.** `_score_one()` builds the prompt from profile, resume and the job row alone, so moving a job between tiers changes when it is scored and how it is labelled, never how it is scored.

Order matters and is deliberate: `solutions_engineering` → `named_target` → `keyword` → `skip`. All tier signals are evaluated before anything is skipped, so a title like *Forward Deployed Software Engineer Intern* takes its tier instead of being dropped by the `software engineer` skip pattern.

**`solutions_engineering` (CLI `tier3`) — the primary target shape.** Checked *first*, ahead of `named_target`: being the target shape is a property of the role, not of whether the employer happens to be on a hand-maintained list. Two title classes:

- *Self-qualifying* (`deployment strategist`, `forward deployed`, `fde`) — unambiguous on their own. Requiring a second technical signal here was dropping Palantir's *Deployment Strategist – Intern – US Government*, the most on-target row in the corpus, all the way to `skip`, because SE-only titles have no fallback in `TIER2_KEYWORDS`.
- *Qualifier-required* (`solutions engineer`, `solutions architect`, `sales engineer`, `customer engineer`, `implementation engineer`, `field engineer`) — too generic alone. `field engineer` is 35 GE Healthcare medical-device apprenticeships in this corpus; `sales engineer` is enterprise-SaaS noise. These need a technical/AI token, a fused-AI company name, or a named-target employer.

The fused-AI pattern exists because `\bai\b` cannot match *OpenAI* — `ai` is not a standalone token inside it, which is why this tier classified **nothing at all** until 2026-07-31. Its camelCase arm is deliberately case-sensitive via `(?-i:[a-z]AI)`: the corpus contains Airbnb, AIG, Air Liquide, Airgas, Fairlife, Baird, Kaiser, Daikin and LAIKA, so a loose `ai` substring match would wreck it. Verified across all 3,472 companies — 21 genuine AI companies matched, no false positives.

**`named_target` (CLI `tier1`).** ~25 companies matched by substring against the lowercased company name. All their jobs are scored regardless of title. Being a named target also satisfies the SE technical qualifier, since `NAMED_TARGETS` is precisely the curated list of already-vetted employers.

**`keyword` (CLI `tier2`).** Regex match on ~25 patterns across company name + job title: forward-deployed / applied-AI / solutions, BizOps / strategy / GTM / product analytics, defense and national security, APM / program management, and an AI-consulting-delivery arm. Quant, trading, and data-science keywords were pruned in the June 2026 cleanup.

**`skip`.** Everything else — stored but never sent to Claude; the vast majority of a ~20k pull. Note that `SKIP_TITLE_PATTERNS` is now **descriptive only**: since tier signals are checked first and anything unmatched is skipped anyway, the list no longer gates anything.

`run_daily.sh` runs `tier1`, then `tier3`, then `tier2` — priority order, so a run that dies partway has already scored the most on-target jobs. Each is capped with `--limit 60` as an unattended-spend guard.

**Tier labels on existing score rows are not retroactive.** Scoring is idempotent on `(job_id, profile_version, resume_version)` and not on tier, so the 9 FDE roles already scored under `keyword` keep that label until the profile changes and everything re-scores.

---

## Known Limitations

**Analyst-title noise at the tier level.** `SKIP_TITLE_PATTERNS` (added in the June 2026 cleanup) drops obviously unwinnable titles — SWE, ML engineer, data scientist, quant, data engineer, embedded — before any keyword match, which resolved the worst of the old noise. Tier 2 still catches product/business/operations-analyst roles, which the prompt's hard rule 7 typically scores 20–40 on qualification: technically correct behavior, but it adds a low-Q tail to the scored pool.

**Season filter includes `N/A`.** Listings where the source doesn't specify a season are assumed current and included in the scoring queue. Most are fine; some are legacy listings from prior cycles that the source never marked inactive. This adds a small tail of irrelevant scores. The model's `class_year_eligible` field catches most of these, but it's not surfaced in the UI filter.

**No pagination / rate-limit backoff on GitHub fetches.** `github_lists.py` makes one blocking GET per source. This is fine for the current two-source setup but would need retry logic and exponential backoff before adding more sources.

**Terminal shortlist lives in `winners.py`** (its predecessor `top.py` was removed), which uses `db.get_connection()` so it works from any working directory.

**Streamlit `app.py` reads from `data/mathetes.db` via `db.get_connection()`** but uses `@st.cache_data(ttl=60)`. After a batch run, you need to wait up to 60 seconds or restart the Streamlit server to see fresh scores.

**No class_year_eligible filter in the dashboard.** The field is stored and scored but not exposed as a filter column in `app.py`. Listings for wrong cycles can appear in the Targets tab if their Q/Fit scores are high enough.

**Profile and resume are gitignored.** `profile.yaml` and `resume.yaml` drive all scoring — they're not optional — but they're excluded from the repo via `.gitignore`. The committed `profile.example.yaml` / `resume.example.yaml` describe a fictional candidate so the pipeline runs as a demo out of the box; contact fields in the examples are placeholders by design.
