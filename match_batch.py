"""Batch-score jobs against the candidate profile/resume with Claude.

Usage: python match_batch.py [tier1|tier2|tier3|all] [--dry-run]
(tier1 = named_target, tier2 = keyword, tier3 = solutions_engineering)

Scoring is idempotent on (job_id, profile_version, resume_version): each score
row is keyed to the SHA256 of the profile and resume YAML, so re-running only
scores jobs not yet seen under the current config, and editing either file
naturally triggers a fresh pass. Commits after every score so progress
survives a crash mid-batch.
"""
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import yaml
from anthropic import Anthropic
from dotenv import load_dotenv

from db import get_connection
from lib.tiering import classify

load_dotenv(override=True)

ROOT = Path(__file__).parent
PROFILE_PATH = ROOT / "profile.yaml"
RESUME_PATH = ROOT / "resume.yaml"

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 1024


def _get_client() -> Anthropic:
    """Build the Anthropic client, exiting with a clear message if the key is missing."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ANTHROPIC_API_KEY is not set. Add it to .env (see .env.example) or the environment.")
    return Anthropic(api_key=api_key)


def _load_yaml(path: Path) -> dict:
    """Parse a YAML config file, exiting with a clear message if missing or invalid."""
    try:
        return yaml.safe_load(path.read_text())
    except FileNotFoundError:
        sys.exit(f"Missing config file: {path}. Copy {path.stem}.example.yaml to {path.name} to get started.")
    except yaml.YAMLError as e:
        sys.exit(f"Could not parse {path}: {e}")


def _file_version(path: Path) -> str:
    """Return a short content hash used as the idempotency key for score rows."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


SYSTEM_PROMPT = """You are an internship-matching analyst. You evaluate a single \
internship listing against a candidate's resume and profile, and return strictly \
formatted JSON. You do not soften scores to be encouraging. You score what the \
data supports."""


USER_TEMPLATE = """Evaluate this internship for the candidate.

# CANDIDATE PROFILE
```yaml
{profile_yaml}
```

# CANDIDATE RESUME
```yaml
{resume_yaml}
```

# JOB LISTING
Company: {company}
Title: {title}
Locations: {locations}
Season: {season}
Sponsorship: {sponsorship}
URL: {url}

Return ONLY a JSON object with this exact schema, no prose, no markdown fences:

{{
  "qualification_score": <int 0-100>,
  "fit_score": <int 0-100>,
  "class_year_eligible": <bool>,
  "top_matches": [<3-5 short strings>],
  "top_gaps": [<3-5 short strings>],
  "fit_reasoning": "<one sentence>",
  "summary": "<one sentence>"
}}

# SCORING METHODOLOGY — READ CAREFULLY

You are evaluating from the perspective of a recruiter or hiring manager doing \
first-pass resume screening. You are NOT a career coach. You do not give \
encouragement. Score what the resume actually shows, not what the candidate \
hopes to become. 

## qualification_score anchors:

- 85-100: Top decile applicant. Resume shows clear evidence of the specific \
skills required. For SWE roles: CS major or equivalent, prior SWE internships, \
demonstrable open-source or competitive work. For quant: top math/CS program, \
ML olympiad or research, prior quant exposure. Score in this range only when \
the candidate is genuinely competitive against the best applicants.

- 65-84: Above-average applicant who would clear initial resume screen and \
likely get a recruiter call. Has the core requirements with one or two soft \
gaps. Should not be the default score.

- 45-64: In the realistic application pool but below the cut line. Resume \
gets read but does not advance.

- 25-44: Significant gap. Resume would be auto-rejected without referral. \
The candidate's strengths are real but in the wrong domain for this role.

- 5-24: Major gap. Wrong major, missing required skills, or insufficient \
depth. Auto-rejected.

- 0-4: Hard miss. The role requires something the candidate fundamentally \
does not have (PhD, security clearance they cannot obtain, specific licensure).

## Hard rules — these override the bands above:

1. Quantitative research and quantitative researcher roles at top funds \
(Jane Street, Citadel, HRT, Two Sigma, Jump, Optiver, IMC, Akuna, DRW, \
Millennium, Point72, AQR) require demonstrated math/CS research output: \
PhD pipeline, math olympiad, published research, or top-tier quant prior. \
A high GPA in a non-quantitative or humanities major is not a substitute. Score these 5-20 unless the \
resume shows comparable prior experience.

2. Software Engineer Intern roles at top tech and fintech (Stripe, Plaid, \
Ramp, Robinhood, Databricks, Citadel, Anduril, Palantir, OpenAI, Anthropic, \
Jane Street SWE) require CS major or strong CS minor with multiple prior \
SWE internships, GitHub portfolio, or demonstrably hard projects. \
"Two weeks of Python, two shipped beginner projects" does not qualify. \
Score these 15-35 even when the candidate is a strong analytical thinker.

3. Forward Deployed Engineer, BizOps, Strategy, and Investment Analyst roles \
at the same companies are different. They explicitly recruit non-CS \
analytical undergrads. Score these on actual fit. Palantir's "Year at \
Palantir," Point72 Academy Investment Analyst, AQR Summer Analyst Portfolio, \
Anthropic Fellows Economics, and similar roles can score 60-85 for a \
strong analytical non-CS candidate.

4. ML/AI Research Intern, Applied Scientist, and Research Engineer roles \
require graduate-level math/ML coursework or research. Score 5-20 for \
undergrads without that background.

5. Hardware/FPGA/embedded roles require EE or CompE coursework. Score \
5-15 for psych/econ majors regardless of other strengths.

6. Defense primes (Lockheed, Northrop, Raytheon, L3Harris, General Dynamics) \
SWE intern roles are slightly more accessible than top fintech but still \
prefer CS majors. Score 25-45 for a non-CS candidate, higher if there is \
a clearance angle (US citizen with no foreign ties is a real signal).

7. Data Scientist, Data Analyst, Analytics Engineer, and "Insights" roles \
that expect independent SQL/Python/modeling from scratch are a qualification \
gate, not a domain match. Even when the domain (behavioral/consumer data) is a \
perfect fit, score qualification 20-40 if the role expects the candidate to \
build pipelines or models unaided. This is a qualification gate: roles \
requiring independent production analytics code score low even when the \
domain is a strong fit.

## fit_score is independent of qualification_score.

A role can be q=15 and fit=90 (the candidate would love it but cannot get \
it) or q=70 and fit=20 (qualified but explicitly does not want it). \
fit_score reflects what the candidate *wants*, drawn from preferences and \
context_for_scoring in the profile. Do not let high fit pull qualification \
upward.

fit_score is HIGH when the role matches what the candidate wants, per the
profile's preferences, target_archetypes, and positive_signals:
- implementation / deployment / post-sales solutions-engineering scope at an \
AI company — this is the candidate's PRIMARY target and a top-fit signal. \
Pre-sales or demo-only SE scope is NOT this signal (lighter technical, \
further from the goal) — do not credit it as primary-target fit.
- build-heavy AI consulting / implementation-delivery scope (scope the \
problem, build the system, deploy it, manage the stakeholder) — the same \
motion as solutions engineering and equally a top-fit signal. Titles like \
"AI Implementation", "AI Solutions Consultant", "GenAI Consultant", and \
"AI Delivery" qualify when the work is shipping working systems for clients.
- touches consumer/behavioral data, or automates real workflows with AI
- early-stage with equity, or owns a P&L / core metric (wealth via ownership)
- operator / solutions / forward-deployed / growth scope, close to revenue
- values builders who ship by directing AI over traditional engineers

fit_score is LOW when the role hits the profile's hard_negatives:
- capped salary, no ownership or equity upside
- back-office or pure-analyst seat with no metric to own
- the candidate would be the hands-on-keyboard engineer
- advisory- or strategy-only consulting with no build-or-deploy artifact \
(assessments, roadmaps, governance decks, pure research) — score fit LOW \
regardless of firm prestige; it does not match the candidate's \
artifact-building trajectory

A behavioral-data-science role at a hot startup is the canonical split:
HIGH fit (domain the candidate wants), LOW qualification (needs a coder). Surface the
split — do not average the two into a misleading middle.

## Intra-band discrimination — no anchor-snapping:

The bands set the range; the exact integer within the band must be earned by \
specifics of THIS listing. Your score will be ranked against dozens of other \
roles landing in the same band, so a tie carries no information. Do not default \
to round or repeated anchor values (70, 72, 85, 88) — use the full integer \
range of the band, differentiating on concrete signals:

- How directly the title and listing language match the candidate's target \
shape: implementation/deployment-flavored Solutions Engineering titles \
("Solutions Engineer", "Deployment Strategist", "Implementation Engineer", \
"Customer Engineer", "Applied AI Solutions", or "Forward Deployed" roles \
with SE scope), together with build-heavy AI consulting / delivery titles \
("AI Implementation", "AI Solutions Consultant", "GenAI Consultant", \
"AI Delivery" — delivery scope, not advisory), are the candidate's PRIMARY \
target — score their fit at the top of the band, co-equal with or slightly \
above pure "Forward Deployed Engineer" and "Applied AI Engineer" titles, \
which remain HIGH-fit reach roles. All of these outrank a generic title at \
an AI company.
- Company stage and context against the profile's preferences: Series A–D \
with real revenue and equity upside outranks pre-seed or slow large-cap.
- Specificity of overlap between what the listing asks for and what the \
resume actually shows (named tools, workflows, or domains in common).

Apply this to qualification_score and fit_score independently. Two roles \
should receive the same score only when they are genuinely indistinguishable \
on all of the above.

## class_year_eligible:

True if the listing is for Summer 2027 internships and the candidate's \
graduation year (May 2028) means they would be a rising senior. False if \
the listing is for a different cycle (Summer 2026 already happening, \
Winter 2025/2026, etc.) or explicitly requires a different class year."""


def _score_one(client, job, profile, resume, profile_v, resume_v, tier):
    """Score one job with Claude and return the parsed score dict.

    Raises on API failure or unparseable output; the caller counts those as
    failures and moves on.
    """
    user_msg = USER_TEMPLATE.format(
        profile_yaml=yaml.safe_dump(profile, sort_keys=False),
        resume_yaml=yaml.safe_dump(resume, sort_keys=False),
        company=job["company_name"],
        title=job["title"],
        locations=json.loads(job["locations_json"]),
        season=job["season"] or "unspecified",
        sponsorship=job["sponsorship"] or "unspecified",
        url=job["url"],
    )

    resp = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )

    text = resp.content[0].text.strip()
    # Defensive: strip markdown fences if Claude includes them despite instructions.
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    parsed = json.loads(text)
    parsed["_job_id"] = job["id"]
    parsed["_tier"] = tier
    parsed["_profile_v"] = profile_v
    parsed["_resume_v"] = resume_v
    return parsed


def _persist(conn, score):
    """Insert one score row; the UNIQUE constraint makes duplicate inserts no-ops."""
    conn.execute(
        """INSERT OR IGNORE INTO match_scores
           (job_id, profile_version, resume_version,
            qualification_score, fit_score, class_year_eligible,
            top_matches_json, top_gaps_json, fit_reasoning, summary,
            tier, model)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            score["_job_id"], score["_profile_v"], score["_resume_v"],
            score["qualification_score"], score["fit_score"],
            1 if score["class_year_eligible"] else 0,
            json.dumps(score["top_matches"]),
            json.dumps(score["top_gaps"]),
            score.get("fit_reasoning"), score.get("summary"),
            score["_tier"], MODEL,
        ),
    )


def candidate_jobs(conn, tier_filter):
    """Yield active Summer 2027-relevant jobs matching the requested tier.

    Season gate — one arm per tagging pattern observed in the feeds:
    - season LIKE '%2027%': explicit cycle tags. Multi-term Simplify listings
      are stamped 'Summer 2027' at ingest whenever that cycle appears anywhere
      in their terms list (see sources/github_lists.py), so the stored column
      is trustworthy here.
    - season IN ('Summer', 'N/A'): vanshb03 stamps bare season names and its
      repo is 2027-cycle, so bare 'Summer' means Summer 2027; 'N/A' is
      Simplify's unknown-cycle tag, assumed current.
    - season IS NULL: source omitted the field; treated like 'N/A' rather
      than silently dropped.
    """
    rows = conn.execute("""
        SELECT j.*, c.name AS company_name
        FROM jobs j
        JOIN companies c ON c.id = j.company_id
        WHERE j.active = 1
          AND (j.season LIKE '%2027%'
               OR j.season IN ('Summer', 'N/A')
               OR j.season IS NULL)
        ORDER BY j.posted_at DESC
    """).fetchall()

    for row in rows:
        tier = classify(row["company_name"], row["title"])
        if tier in tier_filter:
            yield row, tier


def run(tier_filter, limit=None, dry_run=False):
    """Score every unscored job in the given tiers, committing after each one."""
    profile = _load_yaml(PROFILE_PATH)
    resume = _load_yaml(RESUME_PATH)
    profile_v = _file_version(PROFILE_PATH)
    resume_v = _file_version(RESUME_PATH)

    conn = get_connection()

    already_scored = {
        r[0] for r in conn.execute(
            "SELECT job_id FROM match_scores WHERE profile_version=? AND resume_version=?",
            (profile_v, resume_v),
        )
    }

    queue = []
    for job, tier in candidate_jobs(conn, tier_filter):
        if job["id"] in already_scored:
            continue
        queue.append((job, tier))

    if limit:
        queue = queue[:limit]

    print(f"Profile v{profile_v}, Resume v{resume_v}")
    print(f"Tiers: {tier_filter}")
    print(f"Queue size: {len(queue)}\n")

    if dry_run:
        for job, tier in queue[:20]:
            print(f"  [{tier}] {job['company_name']} — {job['title']}")
        if len(queue) > 20:
            print(f"  ... and {len(queue) - 20} more")
        conn.close()
        return

    client = _get_client()
    scored = 0
    failed = 0
    for i, (job, tier) in enumerate(queue, 1):
        try:
            score = _score_one(client, job, profile, resume, profile_v, resume_v, tier)
            _persist(conn, score)
            conn.commit()
            scored += 1
            print(f"[{i}/{len(queue)}] {job['company_name'][:25]:<25} {job['title'][:40]:<40} "
                  f"q={score['qualification_score']:>3} fit={score['fit_score']:>3}")
        except Exception as e:
            failed += 1
            print(f"[{i}/{len(queue)}] FAILED on {job['company_name']}: {type(e).__name__}: {e}")
        time.sleep(0.2)

    print(f"\nScored: {scored}, Failed: {failed}")
    conn.close()


if __name__ == "__main__":
    args = sys.argv[1:]
    dry = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]

    # --limit N caps how many jobs one invocation will score. This is a spend
    # guard for the unattended launchd run: a cycle-opening surge in postings
    # should cost a capped number of Haiku calls, not an unbounded one. The
    # rest stay queued and are picked up by the next run.
    limit = None
    if "--limit" in args:
        i = args.index("--limit")
        try:
            limit = int(args[i + 1])
        except (IndexError, ValueError):
            sys.exit("--limit requires an integer, e.g. --limit 50")
        del args[i:i + 2]

    if not args or args[0] == "tier1":
        run(["named_target"], limit=limit, dry_run=dry)
    elif args[0] == "tier2":
        run(["keyword"], limit=limit, dry_run=dry)
    elif args[0] == "tier3":
        run(["solutions_engineering"], limit=limit, dry_run=dry)
    elif args[0] == "all":
        run(["named_target", "solutions_engineering", "keyword"],
            limit=limit, dry_run=dry)
    else:
        sys.exit("Usage: python match_batch.py [tier1|tier2|tier3|all] "
                 "[--dry-run] [--limit N]")