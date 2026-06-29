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
    # FDE / applied-AI archetypes (your core target shape)
    "scale ai", "shield ai", "anthropic",
    "databricks", "ramp", "applied intuition", "sierra",
    # Defense / gov tech (hire non-CS, value clearance-eligible US citizens)
    "booz allen", "saic", "leidos", "rebellion defense",
    # Fintech / infra (solutions & ops roles open to non-CS)
    "stripe", "plaid", "mercury", "brex", "modern treasury",
    # Data / GTM-engineering adjacent (forward-deployed-style roles)
    "fivetran", "retool", "vercel", "hex",
    # Growth-stage AI startups (title-agnostic, early hires do everything)
    "glean", "harvey", "hebbia", "decagon",
    # Matrix portfolio — brother referral edge
    "fivetran", "suno", "apollo graphql", "flock safety", "channel3",
    "luma ai", "lightmatter", "mashgin", "parabola", "lm studio",
    "logrocket", "cloudzero", "smartcat", "hubspot", "zendesk",
]

# Keyword signals on title + company that suggest a role you'd actually want.
TIER2_KEYWORDS = [
    # Core target shape — FDE / applied AI / solutions
    r"\bforward deployed\b", r"\bfde\b",
    r"\bapplied ai\b", r"\bai engineer\b",
    r"\bsolutions engineer\b", r"\bsolutions architect\b",
    r"\bsolutions consultant\b", r"\bimplementation\b",
    r"\bcustomer engineer\b", r"\bsales engineer\b",
    # Business / strategy / ops — non-CS-friendly
    r"\bbusiness operations\b", r"\bstrategy\b", r"\bstrategy and operations\b",
    r"\bbizops\b", r"\brevenue operations\b", r"\brevops\b",
    r"\bgo.to.market\b", r"\bgtm\b",
    r"\bproduct analyst\b", r"\bproduct analytics\b",
    r"\bbusiness analyst\b", r"\boperations analyst\b",
    # Defense / gov (you have a citizenship edge here)
    r"\bdefense\b", r"\bnational security\b", r"\bintelligence\b",
    # Product / program
    r"\bassociate product manager\b", r"\bapm\b",
    r"\bprogram manager\b", r"\btechnical program\b",
]

# Title patterns that are almost always unwinnable — skip before scoring.
SKIP_TITLE_PATTERNS = [
    r"\bsoftware engineer\b", r"\bswe\b",
    r"\bmachine learning engineer\b", r"\bml engineer\b",
    r"\bdata scientist\b",
    r"\bquant\b", r"\bquantitative\b",
    r"\bdata engineer\b", r"\bbackend\b", r"\bfrontend\b", r"\bfull stack\b",
    r"\bembedded\b", r"\bfirmware\b",
]

_target_pat = re.compile(
    r"\b(?:" + "|".join(re.escape(t) for t in NAMED_TARGETS) + r")\b",
    re.IGNORECASE,
)
_kw_pat = re.compile("|".join(TIER2_KEYWORDS), re.IGNORECASE)
_skip_pat = re.compile("|".join(SKIP_TITLE_PATTERNS), re.IGNORECASE)

def classify(company_name: str, title: str) -> str:
    """Return 'named_target', 'keyword', or 'skip'."""
    company_lc = company_name.lower()
    if _target_pat.search(company_lc):
        return "named_target"
    if _skip_pat.search(title):
        return "skip"
    blob = f"{company_name} {title}"
    if _kw_pat.search(blob):
        return "keyword"

    return "skip"