"""
Tests for the expiry verification cadence and FEFO action helper.

These are pure functions with no database dependency. They run fast
and cover the exact boundaries that decide whether an item shows up
on the verification queue.
"""
from datetime import datetime, timedelta, timezone


def _iso_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


class TestVerificationCadence:
    """_verification_cadence_days returns the window length for each bucket."""

    def test_none_expiry_returns_far_cadence(self, app_module):
        assert app_module._verification_cadence_days(None) == 60

    def test_expired_batch_uses_critical_cadence(self, app_module):
        assert app_module._verification_cadence_days(-30) == 14
        assert app_module._verification_cadence_days(0) == 14
        assert app_module._verification_cadence_days(120) == 14

    def test_warning_window_uses_30_days(self, app_module):
        assert app_module._verification_cadence_days(121) == 30
        assert app_module._verification_cadence_days(180) == 30

    def test_far_future_uses_60_days(self, app_module):
        assert app_module._verification_cadence_days(181) == 60
        assert app_module._verification_cadence_days(1000) == 60


class TestVerificationStatus:
    """_verification_status maps (last_verified_at, days_to_expiry) → (status, staleness)."""

    def test_never_verified(self, app_module):
        status, staleness = app_module._verification_status(None, days_until_expiry=100)
        assert status == "unverified"
        assert staleness is None

    def test_empty_string_treated_as_unverified(self, app_module):
        status, staleness = app_module._verification_status("", days_until_expiry=100)
        assert status == "unverified"
        assert staleness is None

    def test_malformed_timestamp_returns_unverified(self, app_module):
        status, staleness = app_module._verification_status(
            "not-a-date", days_until_expiry=100
        )
        assert status == "unverified"
        assert staleness is None

    def test_current_when_within_cadence(self, app_module):
        # 150 days → cadence 30. 5 days since verify → current.
        status, staleness = app_module._verification_status(
            _iso_days_ago(5), days_until_expiry=150
        )
        assert status == "current"
        assert staleness == 5

    def test_boundary_exactly_at_cadence_is_current(self, app_module):
        # 150 days → cadence 30. 30 days since verify → still current.
        status, staleness = app_module._verification_status(
            _iso_days_ago(30), days_until_expiry=150
        )
        assert status == "current"
        assert staleness == 30

    def test_due_when_past_cadence(self, app_module):
        # 150 days → cadence 30. 45 days since verify → due.
        status, staleness = app_module._verification_status(
            _iso_days_ago(45), days_until_expiry=150
        )
        assert status == "due"
        assert staleness == 45

    def test_boundary_at_2x_cadence_is_due(self, app_module):
        # 150 days → cadence 30. 60 days since verify → due (not overdue).
        status, _ = app_module._verification_status(
            _iso_days_ago(60), days_until_expiry=150
        )
        assert status == "due"

    def test_overdue_when_past_2x_cadence(self, app_module):
        # 150 days → cadence 30. 61 days since verify → overdue.
        status, staleness = app_module._verification_status(
            _iso_days_ago(61), days_until_expiry=150
        )
        assert status == "overdue"
        assert staleness == 61

    def test_critical_batch_has_stricter_window(self, app_module):
        # 100 days → cadence 14. 20 days since verify → overdue.
        status, _ = app_module._verification_status(
            _iso_days_ago(20), days_until_expiry=100
        )
        assert status == "overdue"


class TestFefoAction:
    """_get_fefo_action produces increasingly urgent guidance as expiry approaches."""

    def test_immediate_at_thirty_days_or_less(self, app_module):
        assert "IMMEDIATE" in app_module._get_fefo_action(30)
        assert "IMMEDIATE" in app_module._get_fefo_action(0)
        assert "IMMEDIATE" in app_module._get_fefo_action(-10)

    def test_urgent_31_to_60(self, app_module):
        assert "URGENT" in app_module._get_fefo_action(31)
        assert "URGENT" in app_module._get_fefo_action(60)

    def test_critical_61_to_90(self, app_module):
        assert "CRITICAL" in app_module._get_fefo_action(61)
        assert "CRITICAL" in app_module._get_fefo_action(90)

    def test_plan_91_to_120(self, app_module):
        assert "Plan promotion" in app_module._get_fefo_action(91)
        assert "Plan promotion" in app_module._get_fefo_action(120)

    def test_monitor_above_120(self, app_module):
        assert "Monitor" in app_module._get_fefo_action(121)
        assert "Monitor" in app_module._get_fefo_action(365)
