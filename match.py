"""Score a single job against profile + resume using Claude.

Tonight's goal: prove the prompt works on one job. Tomorrow we batch.
"""
import json
import os
import sqlite3
import yaml
from pathlib import Path
from anthropic import Anthropic
from dotenv import load_dotenv
from db import get_connection

load_dotenv(override=True)

ROOT = Path(__file__).parent
PROFILE_PATH = ROOT / "profile.yaml"
RESUME_PATH = ROOT / "resume.yaml"

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 1024

client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


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
  "qualification_score": <int 0-100, how qualified the candidate is>,
  "fit_score": <int 0-100, how well this matches their stated preferences and \
context_for_scoring>,
  "class_year_eligible": <bool, true if class_year matches the job's expected \
graduation window for Summer 2027 internship>,
  "top_matches": [<3-5 short strings, what makes this a fit>],
  "top_gaps": [<3-5 short strings, what's missing or risky>],
  "fit_reasoning": "<one sentence on why fit_score is what it is>",
  "summary": "<one sentence overall verdict>"
}}

Scoring guidance:
- qualification_score reflects whether the candidate could plausibly land an \
interview given the resume and developing skills. Internships are not new-grad \
roles; weight willingness to learn and project work appropriately.
- fit_score is independent. A role can be a 90 qualification fit and a 20 fit \
score if the candidate explicitly said they don't want it.
- class_year_eligible is the hard filter. If the listing is clearly for a \
different graduation year, mark false even if scores are high."""


def score_job(job_row: sqlite3.Row, profile: dict, resume: dict) -> dict:
    """Call Claude with one job. Return parsed score dict."""
    user_msg = USER_TEMPLATE.format(
        profile_yaml=yaml.safe_dump(profile, sort_keys=False),
        resume_yaml=yaml.safe_dump(resume, sort_keys=False),
        company=job_row["company_name"],
        title=job_row["title"],
        locations=json.loads(job_row["locations_json"]),
        season=job_row["season"] or "unspecified",
        sponsorship=job_row["sponsorship"] or "unspecified",
        url=job_row["url"],
    )

    resp = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )

    text = resp.content[0].text.strip()
    # Defensive: strip markdown fences if Claude includes them
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    return json.loads(text)


def fetch_one_test_job(conn: sqlite3.Connection) -> sqlite3.Row | None:
    """Pick one active Summer 2027 job for a smoke test."""
    return conn.execute("""
        SELECT j.*, c.name AS company_name
        FROM jobs j
        JOIN companies c ON c.id = j.company_id
        WHERE j.active = 1
          AND (j.season LIKE '%2027%' OR j.season = 'Summer')
        ORDER BY j.posted_at DESC
        LIMIT 1
    """).fetchone()


if __name__ == "__main__":
    profile = _load_yaml(PROFILE_PATH)
    resume = _load_yaml(RESUME_PATH)

    conn = get_connection()
    job = fetch_one_test_job(conn)
    if job is None:
        print("No Summer 2027 jobs found. Try widening the filter.")
        conn.close()
        exit()

    print(f"Scoring: {job['company_name']} — {job['title']}")
    print(f"URL: {job['url']}\n")

    result = score_job(job, profile, resume)
    print(json.dumps(result, indent=2))
    conn.close()