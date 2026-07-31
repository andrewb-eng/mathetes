"""Fetch internship listings from community-maintained GitHub repos.

Both vanshb03 and SimplifyJobs publish a JSON file at a known path that
backs their README. We hit that JSON directly instead of parsing markdown.
"""
import json
from typing import Iterator

import requests

# Source configs. Add more here as new repos appear each cycle.
SOURCES = [
    {
        "name": "vanshb03_summer2027",
        "url": "https://raw.githubusercontent.com/vanshb03/Summer2027-Internships/dev/.github/scripts/listings.json",
    },
    {
        "name": "simplifyjobs_summer2026",
        "url": "https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/dev/.github/scripts/listings.json",
    },
]

REQUEST_TIMEOUT = 30

# The internship cycle this project targets. When a multi-term listing carries
# this cycle anywhere in its terms list, it wins the season field.
TARGET_SEASON = "Summer 2027"


def _fetch_json(url: str) -> list[dict]:
    """GET a JSON URL and return the parsed list. Raises on failure."""
    resp = requests.get(url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        raise ValueError(f"Expected JSON array at {url}, got {type(data).__name__}")
    return data


def _normalize(entry: dict, source_name: str) -> dict | None:
    """
    Convert a raw listing into our internal shape, or return None to skip.

    Skip rules: missing required fields, is_visible == False.
    Active == False is kept (we mark it as expired downstream).
    """
    if not entry.get("is_visible", True):
        return None

    required = ("id", "company_name", "title", "url")
    if not all(entry.get(k) for k in required):
        return None

    # Season normalization: vanshb03 uses 'season' (string), Simplify uses
    # 'terms' (list of strings like "Summer 2026"). Collapse to one field,
    # preferring the target cycle when present — terms[0] alone can hide
    # "Summer 2027" behind an earlier season (e.g. ["Fall 2026", "Summer 2027"]).
    season = entry.get("season")
    if not season:
        terms = entry.get("terms") or []
        if any(isinstance(t, str) and t.strip() == TARGET_SEASON for t in terms):
            season = TARGET_SEASON
        elif terms:
            season = terms[0]
        else:
            season = None

    return {
        "source": source_name,
        "source_id": entry["id"],
        "company_name": entry["company_name"].strip(),
        "title": entry["title"].strip(),
        "url": entry["url"],
        "locations": entry.get("locations") or [],
        "season": season,
        "category": entry.get("category"),
        "degrees": entry.get("degrees") or [],
        "sponsorship": entry.get("sponsorship"),
        "active": bool(entry.get("active", True)),
        "posted_at": entry.get("date_posted"),
        "updated_at": entry.get("date_updated"),
        "company_url": entry.get("company_url") or None,
        "raw_payload": entry,
    }


def fetch_all(outcomes: dict | None = None) -> Iterator[dict]:
    """Yield normalized job dicts from all configured GitHub list sources.

    When `outcomes` is passed, it is filled with one entry per source:
    {"ok": bool, "seen_ids": set[str], "kept": int, "error": str | None}.

    This exists so the deactivation sweep can tell "this feed no longer lists
    that job" apart from "this feed did not load". Fetch failures are still
    swallowed per-source so one dead feed cannot abort the whole pull, but they
    are now reported instead of vanishing silently.

    Because this is a generator, an entry is only final once the caller has
    consumed that source's rows; read `outcomes` after the iterator is
    exhausted, never mid-stream.
    """
    for src in SOURCES:
        name = src["name"]
        print(f"Fetching {name}...")
        if outcomes is not None:
            outcomes[name] = {"ok": False, "seen_ids": set(), "kept": 0, "error": None}

        try:
            raw = _fetch_json(src["url"])
        except Exception as e:
            print(f"  FAILED: {e}")
            if outcomes is not None:
                outcomes[name]["error"] = f"{type(e).__name__}: {e}"
            continue

        kept = 0
        skipped = 0
        seen_ids = set()
        for entry in raw:
            normalized = _normalize(entry, name)
            if normalized is None:
                skipped += 1
                continue
            kept += 1
            seen_ids.add(str(normalized["source_id"]))
            yield normalized

        if outcomes is not None:
            outcomes[name] = {"ok": True, "seen_ids": seen_ids,
                              "kept": kept, "error": None}
        print(f"  {kept} kept, {skipped} skipped (of {len(raw)} total)")


if __name__ == "__main__":
    # Smoke test: fetch and print summary stats without persisting.
    from collections import Counter

    jobs = list(fetch_all())
    print(f"\nTotal normalized jobs: {len(jobs)}")

    by_source = Counter(j["source"] for j in jobs)
    print(f"By source: {dict(by_source)}")

    by_season = Counter(j["season"] for j in jobs)
    print(f"By season: {dict(by_season.most_common(10))}")

    print("\nSample (first job):")
    if jobs:
        sample = {k: v for k, v in jobs[0].items() if k != "raw_payload"}
        print(json.dumps(sample, indent=2, default=str))