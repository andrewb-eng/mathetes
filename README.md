# Mathetes

**A personal internship-application pipeline that aggregates ~20,000 listings, then uses Claude to score every one against my actual profile on two independent axes — how qualified I am, and how much I want it — with deliberate calibration discipline so the scores stay honest instead of encouraging.**

The hard part of using an LLM as a scorer isn't getting it to produce numbers — it's getting it to produce numbers you can *trust*. Left to its defaults, Claude clusters scores in a comfortable 70–75 band and softens hard truths to be encouraging. Mathetes is built specifically to fight that: explicit score-band anchors, hard rules for roles a given candidate realistically can't land, and a system prompt that forbids inflating scores. The result is a filter that tells me a quant-research role is a 15, not a polite 70.

This is a personal tool, not a product — built as a demonstration of applied LLM tooling: take a real workflow, identify what a model can and cannot reliably do, and engineer the constraints that make its output dependable.

---

## The core design decision: make the LLM honest, not agreeable

A naive "rate this job 0–100" prompt produces useless mush — everything lands near 70 and nothing is comparable. The scoring logic in `match_batch.py` is engineered against that failure mode:

- **Explicit score-band anchors** define what each range actually means, so the model can't drift to a vague middle.
- **Hard rules for unwinnable roles** — e.g. quant research or SWE at top fintechs for a non-CS candidate — force honest low scores instead of hopeful ones.
- **An anti-encouragement instruction** in the system prompt: *"You do not soften scores to be encouraging. You score what the data supports."*

This is the same discipline production systems use to make LLM output trustworthy: assume the raw model is biased, then constrain it against reality before you act on what it says. The calibration *is* the project — the scraping and storage are plumbing around it.

---

## Two-axis scoring

Qualification and fit are scored **independently**, on purpose. Collapsing them into one number destroys the signal:

- A role can be **Q=15, Fit=90** — quant research at a top firm: I'd love it, won't get it.
- Or **Q=70, Fit=20** — a data-entry analytics role: I could get it, don't want it.

Averaging those both produces a misleading ~50. Keeping the axes separate lets me filter on each independently — high-fit roles to stretch for, high-qualification roles as floors — instead of chasing a meaningless blended middle. Each score comes back with top match signals, top gaps, and a one-sentence verdict.

---

## How it works (pipeline)

1. **Pull** — `pull.py` fetches two community-maintained GitHub JSON feeds, normalizes each listing, detects the ATS provider from the URL, and upserts into a local SQLite database. The pipeline is **idempotent**: re-running updates changed listings and marks inactive ones without creating duplicates.

2. **Tier** — `lib/tiering.py` buckets each job into `named_target` (a company I listed by name), `keyword` (matches role-type keywords I care about), or `skip` — *before* any API call, so scoring spend stays focused and named targets always get scored.

3. **Score** — `match_batch.py` calls **Claude Haiku** on each unseen job, passing the full `profile.example.yaml` and `resume.example.yaml` alongside the listing, and gets back structured JSON: `qualification_score` and `fit_score` (independent 0–100 integers), match signals, gaps, and a verdict. Scores are idempotent on `(job_id, profile_version, resume_version)` — editing either config file triggers a fresh score only for affected jobs.

4. **Review** — `app.py` is a Streamlit dashboard: top targets (ranked by qualification + fit), the best listing per named-target company, and score-distribution charts.

---

## Key architectural details

**ATS detection** (`lib/ats_detect.py`) — parses each posting's URL to identify the applicant-tracking system (Greenhouse, Lever, Ashby, Workday, iCIMS, SmartRecruiters, Taleo, BrassRing, Jobvite, Recruitee, Workable) and extract the company's token within it. Stored per company and surfaced in the dashboard for application strategy.

**Idempotent scoring keys** — tying each score to `(job_id, profile_version, resume_version)` means re-running is cheap and safe, and editing the profile re-scores only what's affected. This is state management built like someone who expects to run the thing repeatedly, not once.

**Cost-aware tiering** — classifying jobs into score/skip buckets before spending any tokens keeps a 20k-listing corpus economically scoreable.

---

## Tech stack

- **Language:** Python 3.12
- **Reasoning:** Anthropic Claude API (Claude Haiku for scoring)
- **Storage:** SQLite
- **Dashboard:** Streamlit (read-only)
- **Config / data:** `python-dotenv`, `pyyaml`, `requests`

**Data sources:** two community-maintained internship JSON feeds (vanshb03 and SimplifyJobs), hit directly at their stable raw-JSON paths.

---

## Running it locally

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # add your ANTHROPIC_API_KEY
python db.py              # initialize schema
python pull.py            # fetch listings
python match_batch.py tier1   # score named targets
python match_batch.py tier2   # score keyword matches
streamlit run app.py     # open the dashboard
```

**Configuration:** `profile.yaml` (preferences, target companies, scoring context) and `resume.yaml` (work history, skills, education) drive every scoring decision. The versions committed here describe a **fictional example candidate** so the pipeline runs as a demo out of the box — replace them with your own to use the tool for real. Contact fields are placeholders by design; no real personal data is stored in the repo.

---

## Project status

Working, in personal use. Built as a demonstration of applied LLM tooling — calibration discipline, two-axis scoring, idempotent pipeline design — not as a product. No multi-user deployment, no data sharing, no production guarantees.

---

*Personal tool — no warranty, no support. Built to explore what an LLM can and can't reliably do, and how to constrain it so its output can be trusted.*