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

# SE-family titles that ARE the target shape on their own. "Deployment
# strategist" is Palantir's name for the forward-deployed role and is not used
# by anyone else; "forward deployed" is unambiguous. Requiring a second
# technical signal from these only loses real listings — the Palantir
# "Deployment Strategist - Intern - US Government" posting, the single most
# on-target row in the corpus, was being dropped to "skip" for exactly that.
SE_TITLE_SELF_QUALIFYING = [
    r"\bdeployment strategist\b", r"\bforward deployed\b", r"\bfde\b",
]

# SE-family titles that are too generic to stand alone and need a technical
# qualifier. "Field engineer" is 35 GE Healthcare medical-device
# apprenticeships in this corpus; "sales engineer" is enterprise-SaaS noise.
SE_TITLE_NEEDS_QUALIFIER = [
    r"\bsolutions engineer\b", r"\bsolutions architect\b",
    r"\bsales engineer\b", r"\bcustomer engineer\b",
    r"\bimplementation engineer\b", r"\bfield engineer\b",
]

SE_TITLE_PATTERNS = SE_TITLE_SELF_QUALIFYING + SE_TITLE_NEEDS_QUALIFIER

# Technical qualifiers that make a generic SE-family title a real target.
# Searched over company + title so "Scale AI — Solutions Engineer Intern"
# qualifies on the company alone.
SE_TECH_QUALIFIERS = [
    r"\bai\b", r"\bml\b", r"\bartificial intelligence\b",
    r"\bmachine learning\b", r"\bllm\b", r"\bgen ?ai\b",
    r"\bdata\b", r"\btechnical\b", r"\bplatform\b",
]

# Company names with "AI" fused on (OpenAI, CuspAI, DatologyAI) or as a domain
# (pony.ai, C3.ai). \bai\b cannot see these — "ai" is not a standalone token
# inside "OpenAI" — which is why the SE tier classified nothing at all.
#
# The camelCase arm is deliberately case-SENSITIVE via (?-i:...): it requires a
# lowercase letter followed by a capitalised "AI". That is what makes it safe.
# This corpus contains Airbnb, AIG, Air Liquide, Airgas, Fairlife, Baird,
# Kaiser, Daikin and LAIKA — a loose "ai" substring match would wreck it.
# Verified: matches 21 genuine AI companies out of 3,472, with no false hits.
_fused_ai_pat = re.compile(r"(?-i:[a-z]AI)\b|\.ai\b|\bopenai\b|\bxai\b", re.IGNORECASE)

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
    # Technology-consulting titles. Deliberately narrow: measured against the
    # full corpus, these two add 10 jobs (Protiviti, Charles River Associates)
    # where the broader candidates considered alongside them — "data & ai",
    # "digital transformation", "ai transformation" — added 60 more that were
    # almost entirely noise (Chick-fil-A, Panasonic Avionics, Zurich, Copart)
    # with zero on-target hits. This tier is where API spend goes, so recall
    # that costs precision is not free.
    r"\btechnology consulting\b", r"\bconsulting analyst\b",
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

# Title patterns that are almost always unwinnable. Retained as documentation
# of what we expect to fall through: since tier signals are now checked first
# and anything unmatched is skipped anyway, this list no longer gates anything.
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
_se_self_pat = re.compile("|".join(SE_TITLE_SELF_QUALIFYING), re.IGNORECASE)
_se_generic_pat = re.compile("|".join(SE_TITLE_NEEDS_QUALIFIER), re.IGNORECASE)
_se_tech_pat = re.compile("|".join(SE_TECH_QUALIFIERS), re.IGNORECASE)


def _is_se_shape(company_name: str, title: str) -> bool:
    """True when the listing is the primary forward-deployed/SE target shape.

    A generic SE title needs corroborating technical context. Three things
    supply it: an explicit technical/AI token, a fused-AI company name, or the
    company being a named target — NAMED_TARGETS is precisely the curated list
    of employers whose context has already been vetted, so "Anthropic —
    Solutions Architect Intern" qualifies without a second signal.
    """
    if _se_self_pat.search(title):
        return True
    if _se_generic_pat.search(title):
        blob = f"{company_name} {title}"
        return bool(
            _se_tech_pat.search(blob)
            or _fused_ai_pat.search(company_name)
            or _target_pat.search(company_name.lower())
        )
    return False


def classify(company_name: str, title: str) -> str:
    """Return 'named_target', 'solutions_engineering', 'keyword', or 'skip'.

    solutions_engineering is checked FIRST, ahead of named_target. Being the
    primary target shape is a property of the role, not of whether the employer
    happens to be on a hand-maintained list — and a named target with an SE
    title is the best case, not a reason to bury it in the named_target bucket.
    Checking named_target first is what kept "Scale AI — AI Deployment
    Strategist Intern" out of the SE tier.

    Tier signals are all checked before anything is skipped, so a title like
    'Forward Deployed Software Engineer Intern' takes its tier rather than
    being dropped by the 'software engineer' skip pattern.

    The tier only selects which scoring batch a job lands in and is stored as a
    label; it is never fed to the model, so re-routing between tiers cannot
    affect how a job is scored.
    """
    if _is_se_shape(company_name, title):
        return "solutions_engineering"
    if _target_pat.search(company_name.lower()):
        return "named_target"
    if _kw_pat.search(f"{company_name} {title}"):
        return "keyword"
    return "skip"