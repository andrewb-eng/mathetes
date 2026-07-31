"""Decide which jobs are worth Claude tokens.

Tier 1: company name matches a named target → always score.
Tier SE: solutions-engineering-family title WITH a technical/AI qualifier →
         primary target shape, always score.
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
    # Matrix portfolio — brother referral edge (fivetran listed above)
    "suno", "apollo graphql", "flock safety", "channel3",
    "luma ai", "lightmatter", "mashgin", "parabola", "lm studio",
    "logrocket", "cloudzero", "smartcat", "hubspot", "zendesk",
]

# SE-family titles — the candidate's PRIMARY target shape, but only when the
# listing carries a technical/AI qualifier. A bare generic-SaaS "Sales
# Engineer" with no such signal is enterprise-sales noise and must not match.
SE_TITLE_PATTERNS = [
    r"\bsolutions engineer\b", r"\bsolutions architect\b",
    r"\bsales engineer\b", r"\bcustomer engineer\b",
    r"\bdeployment strategist\b", r"\bimplementation engineer\b",
    r"\bfield engineer\b",
]

# Technical qualifiers that make an SE-family title a real target. Searched
# over company + title so "Scale AI — Solutions Engineer Intern" qualifies.
SE_TECH_QUALIFIERS = [
    r"\bai\b", r"\bml\b", r"\bartificial intelligence\b",
    r"\bmachine learning\b", r"\bllm\b", r"\bgen ?ai\b",
    r"\bdata\b", r"\btechnical\b", r"\bplatform\b",
]

# Keyword signals on title + company that suggest a role you'd actually want.
TIER2_KEYWORDS = [
    # Core target shape — FDE / applied AI / solutions
    r"\bforward deployed\b", r"\bfde\b",
    r"\bapplied ai\b", r"\bai engineer\b",
    r"\bsolutions engineer\b", r"\bsolutions architect\b",
    r"\bsolutions consultant\b", r"\bimplementation\b",
    r"\bcustomer engineer\b", r"\bsales engineer\b",
    # AI consulting — delivery side. Tiering only queues these for scoring;
    # the delivery-vs-advisory fit filter lives in the scoring prompt.
    r"\b(?:gen(?:erative)?\s?ai|ai)\s?consultant\b", r"\bai delivery\b",
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
_se_title_pat = re.compile("|".join(SE_TITLE_PATTERNS), re.IGNORECASE)
_se_tech_pat = re.compile("|".join(SE_TECH_QUALIFIERS), re.IGNORECASE)


def classify(company_name: str, title: str) -> str:
    """Return 'named_target', 'solutions_engineering', 'keyword', or 'skip'.

    Tier signals are checked before skip patterns: a title that matches a
    keyword (e.g. 'Forward Deployed Software Engineer Intern') takes that
    tier even when it also matches a skip pattern like 'software engineer'.
    solutions_engineering outranks keyword so SE-family titles (which also
    appear in TIER2_KEYWORDS) land in the primary-target tier.
    """
    company_lc = company_name.lower()
    if _target_pat.search(company_lc):
        return "named_target"
    blob = f"{company_name} {title}"
    if _se_title_pat.search(title) and _se_tech_pat.search(blob):
        return "solutions_engineering"
    if _kw_pat.search(blob):
        return "keyword"
    if _skip_pat.search(title):
        return "skip"

    return "skip"