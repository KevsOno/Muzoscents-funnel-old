"""
Tests for effective_features and effective_limit — the functions that
resolve what a given org can do based on plan tier + overrides + status.

These are the rules that gate every feature endpoint. If they regress,
some customers get features they didn't pay for (revenue leak) or lose
features they paid for (churn trigger).
"""


class TestEffectiveFeatures:
    """Feature resolution: tier defaults + overrides, with suspension as kill switch."""

    def test_suspended_org_gets_nothing(self, app_module):
        org = {
            "status": "suspended",
            "plan_tier": "supermarket_large",  # even the top tier
            "feature_overrides": {"ecommerce": True},  # even with override
        }
        features = app_module.effective_features(org)
        assert all(v is False for v in features.values()), \
            "A suspended org must have every feature disabled"

    def test_churned_org_gets_nothing(self, app_module):
        org = {"status": "churned", "plan_tier": "supermarket_large"}
        features = app_module.effective_features(org)
        assert all(v is False for v in features.values())

    def test_active_org_no_tier_all_disabled(self, app_module):
        org = {"status": "active"}
        features = app_module.effective_features(org)
        # All features default to False when the tier is unknown
        assert all(v is False for v in features.values())

    def test_tier_features_applied(self, app_module):
        # supermarket_large has ecommerce: True per the tier catalog
        org = {"status": "active", "plan_tier": "supermarket_large"}
        features = app_module.effective_features(org)
        assert features["ecommerce"] is True
        assert features["multi_location"] is True

    def test_convenience_has_no_multi_location(self, app_module):
        # convenience has multi_location: False per the tier catalog
        org = {"status": "active", "plan_tier": "convenience"}
        features = app_module.effective_features(org)
        assert features["ecommerce"] is True
        assert features["multi_location"] is False

    def test_override_can_grant_denied_feature(self, app_module):
        # convenience denies multi_location; override grants it
        org = {
            "status": "active",
            "plan_tier": "convenience",
            "feature_overrides": {"multi_location": True},
        }
        features = app_module.effective_features(org)
        assert features["multi_location"] is True

    def test_override_can_revoke_granted_feature(self, app_module):
        # supermarket_large grants multi_location; override revokes it
        org = {
            "status": "active",
            "plan_tier": "supermarket_large",
            "feature_overrides": {"multi_location": False},
        }
        features = app_module.effective_features(org)
        assert features["multi_location"] is False

    def test_no_tier_but_override_grants(self, app_module):
        # No plan tier but an explicit override still applies
        org = {
            "status": "active",
            "feature_overrides": {"ecommerce": True},
        }
        features = app_module.effective_features(org)
        assert features["ecommerce"] is True
        # Every other feature defaults to False
        assert features["hr_module"] is False


class TestEffectiveLimit:
    """Numeric limit resolution: overrides win, else tier defaults."""

    def test_override_wins(self, app_module):
        org = {
            "plan_tier": "convenience",
            "limits_overrides": {"locations": 50},
        }
        assert app_module.effective_limit(org, "locations") == 50

    def test_falls_back_to_tier(self, app_module):
        # convenience has max_locations: 1
        org = {"plan_tier": "convenience"}
        assert app_module.effective_limit(org, "locations") == 1

    def test_unlimited_tier_returns_none(self, app_module):
        # supermarket_large has max_skus: None
        org = {"plan_tier": "supermarket_large"}
        assert app_module.effective_limit(org, "skus") is None

    def test_unknown_metric_returns_none(self, app_module):
        org = {"plan_tier": "supermarket_large"}
        assert app_module.effective_limit(org, "does_not_exist") is None

    def test_override_to_none_means_unlimited(self, app_module):
        # convenience has max_locations: 1; override to None means unlimited
        org = {
            "plan_tier": "convenience",
            "limits_overrides": {"locations": None},
        }
        assert app_module.effective_limit(org, "locations") is None
