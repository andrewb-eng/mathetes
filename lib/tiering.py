"""Decide which jobs are worth Claude tokens.

Tier 1: company name matches a named target → always score.
Tier 2: title or company hints at an industry of interest → score with
        cheaper prompt.
Tier 3: skip for now.
"""
import re

# Companies you explicitly listed as realistic targets in profile.yaml.
# Match is fuzzy: substring, case-insensitive, normalized.
NAMED_TARGETS = [
    "palantir", "anduril", "scale ai", "shield ai", "rebellion defense",
    "jane street", "akuna", "drw", "citadel securities", "citadel",
    "two sigma", "jump trading", "hudson river", "optiver", "imc",
    "jpmorgan", "morgan stanley",
    "stripe", "ramp", "mercury", "plaid", "brex", "modern treasury",
    "wealthfront", "betterment", "robinhood", "public",
    "bridgewater", "aqr", "renaissance", "millennium", "point72",
    "booz allen", "saic", "leidos", "raytheon", "lockheed",
    "northrop", "general dynamics", "l3harris",
    "openai", "anthropic", "ramp", "databricks",
]

# Keyword signals on title + company that suggest a role you'd actually want.
TIER2_KEYWORDS = [
    r"\bquant",
    r"\btrading\b", r"\btrader\b",
    r"\bsystematic\b",
    r"\bdefense\b", r"\bintelligence\b", r"\bnational security\b",
    r"\bfintech\b",
    r"\bbizops\b", r"\bbusiness operations\b", r"\bstrategy\b",
    r"\bproduct analyst\b", r"\bproduct analytics\b",
    r"\bdata analyst\b", r"\bdata science\b",
    r"\bforward deployed\b", r"\bfde\b",
    r"\binvestment analyst\b", r"\bresearch associate\b",
    r"\bml infrastructure\b", r"\bapplied ai\b", r"\bllm\b",
]

_target_pat = re.compile(
    r"\b(?:" + "|".join(re.escape(t) for t in NAMED_TARGETS) + r")\b",
    re.IGNORECASE,
)
_kw_pat = re.compile("|".join(TIER2_KEYWORDS), re.IGNORECASE)


def classify(company_name: str, title: str) -> str:
    """Return 'named_target', 'keyword', or 'skip'."""
    company_lc = company_name.lower()
    if _target_pat.search(company_lc):
        return "named_target"

    blob = f"{company_name} {title}"
    if _kw_pat.search(blob):
        return "keyword"

    return "skip"