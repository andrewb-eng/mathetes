"""Batch score jobs across tiers. Idempotent on (job, profile_version, resume_version)."""
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

client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def _file_version(path: Path) -> str:
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
- touches consumer/behavioral data, or automates real workflows with AI
- early-stage with equity, or owns a P&L / core metric (wealth via ownership)
- operator / solutions / forward-deployed / growth scope, close to revenue
- values builders who ship by directing AI over traditional engineers

fit_score is LOW when the role hits the profile's hard_negatives:
- capped salary, no ownership or equity upside
- back-office or pure-analyst seat with no metric to own
- the candidate would be the hands-on-keyboard engineer

A behavioral-data-science role at a hot startup is the canonical split:
HIGH fit (domain the candidate wants), LOW qualification (needs a coder). Surface the
split — do not average the two into a misleading middle.

## class_year_eligible:

True if the listing is for Summer 2027 internships and the candidate's \
graduation year (May 2028) means they would be a rising senior. False if \
the listing is for a different cycle (Summer 2026 already happening, \
Winter 2025/2026, etc.) or explicitly requires a different class year."""
def _score_one(job, profile, resume, profile_v, resume_v, tier):
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
    """Yield active Summer 2027-relevant jobs matching the requested tier."""
    rows = conn.execute("""
        SELECT j.*, c.name AS company_name
        FROM jobs j
        JOIN companies c ON c.id = j.company_id
        WHERE j.active = 1
          AND (j.season LIKE '%2027%' OR j.season IN ('Summer', 'N/A'))
        ORDER BY j.posted_at DESC
    """).fetchall()

    for row in rows:
        tier = classify(row["company_name"], row["title"])
        if tier in tier_filter:
            yield row, tier


def run(tier_filter, limit=None, dry_run=False):
    profile = yaml.safe_load(PROFILE_PATH.read_text())
    resume = yaml.safe_load(RESUME_PATH.read_text())
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

    scored = 0
    failed = 0
    for i, (job, tier) in enumerate(queue, 1):
        try:
            score = _score_one(job, profile, resume, profile_v, resume_v, tier)
            _persist(conn, score)
            conn.commit()
            scored += 1
            print(f"[{i}/{len(queue)}] {job['company_name'][:25]:<25} {job['title'][:40]:<40} "
                  f"q={score['qualification_score']:>3} fit={score['fit_score']:>3}")
        except Exception as e:
            failed += 1
            print(f"[{i}/{len(queue)}] FAILED on {job['company_name']}: {e}")
        time.sleep(0.2)

    print(f"\nScored: {scored}, Failed: {failed}")
    conn.close()


if __name__ == "__main__":
    args = sys.argv[1:]
    dry = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]

    if not args or args[0] == "tier1":
        run(["named_target"], dry_run=dry)
    elif args[0] == "tier2":
        run(["keyword"], dry_run=dry)
    elif args[0] == "all":
        run(["named_target", "keyword"], dry_run=dry)
    else:
        print(f"Usage: python match_batch.py [tier1|tier2|all] [--dry-run]")