"""Tiering classification tests.

These pin the behaviour that was silently broken: solutions_engineering
classified nothing at all across the entire 23k-row corpus.
"""
from lib.tiering import classify


class TestSolutionsEngineering:
    """SE-family titles with a technical signal are the primary target shape."""

    def test_fused_ai_company_name_qualifies(self):
        # "OpenAI" is not a word-boundary match for \bai\b, which is why this
        # returned "keyword" before and the SE tier stayed empty.
        assert classify("OpenAI", "Solutions Engineer Intern") == "solutions_engineering"

    def test_spaced_ai_company_name_qualifies(self):
        assert classify("Scale AI", "Solutions Engineer Intern") == "solutions_engineering"

    def test_named_target_does_not_mask_se_shape(self):
        # A named target with an SE title is the best case, not a reason to
        # hide the role in the named_target bucket.
        assert classify("Sierra", "Deployment Strategist Intern") == "solutions_engineering"
        assert classify("Anthropic", "Solutions Architect Intern") == "solutions_engineering"

    def test_deployment_strategist_is_self_qualifying(self):
        # The canonical FDE title. Nobody outside that org shape uses it, so it
        # does not need a separate technical qualifier. This exact listing was
        # being dropped to "skip" — the single most on-target row in the corpus.
        assert classify(
            "Palantir", "Deployment Strategist - Intern - US Government"
        ) == "solutions_engineering"

    def test_generic_saas_sales_engineer_is_not_se_tier(self):
        # The whole reason the technical qualifier exists: enterprise-sales
        # noise must not reach the primary-target tier.
        assert classify("Salesforce", "Sales Engineer Intern") != "solutions_engineering"

    def test_medical_device_field_engineer_is_not_se_tier(self):
        # 35 of these exist in the corpus. Field service, not forward-deployed.
        assert classify("GE Healthcare", "Field Engineer Apprentice") != "solutions_engineering"


class TestNamedTarget:
    def test_named_target_without_se_title_still_matches(self):
        assert classify("Databricks", "Software Engineer Intern") == "named_target"

    def test_non_target_company_is_not_named_target(self):
        assert classify("Chick-fil-A", "Digital Transformation Intern") != "named_target"


class TestSkipOrdering:
    def test_tier_signal_beats_skip_pattern(self):
        # "Forward Deployed Software Engineer" also matches the "software
        # engineer" skip pattern; the tier signal must win.
        result = classify("Palantir", "Forward Deployed Software Engineer Intern")
        assert result in ("keyword", "solutions_engineering")

    def test_plain_swe_is_skipped(self):
        assert classify("Some Startup", "Software Engineer Intern") == "skip"

    def test_unrelated_role_is_skipped(self):
        assert classify("Chick-fil-A", "Restaurant Team Member") == "skip"
