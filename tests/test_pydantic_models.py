"""
Tests for Pydantic validators — the guardrails that reject bad input
before it reaches the database or the AI.
"""
import pytest
from pydantic import ValidationError


class TestSafeReply:
    """SafeReply rejects suspicious patterns in AI-generated messages."""

    def test_valid_message(self, app_module):
        reply = app_module.SafeReply(
            message="Your order is on the way.",
            confidence=0.9,
            action="reply",
        )
        assert reply.message == "Your order is on the way."

    def test_message_too_long_rejected(self, app_module):
        with pytest.raises(ValidationError):
            app_module.SafeReply(
                message="x" * 801,
                confidence=0.9,
                action="reply",
            )

    def test_confidence_out_of_range_rejected(self, app_module):
        with pytest.raises(ValidationError):
            app_module.SafeReply(
                message="ok", confidence=1.5, action="reply"
            )
        with pytest.raises(ValidationError):
            app_module.SafeReply(
                message="ok", confidence=-0.1, action="reply"
            )

    def test_invalid_action_rejected(self, app_module):
        with pytest.raises(ValidationError):
            app_module.SafeReply(
                message="ok", confidence=0.9, action="launch_missiles"
            )

    def test_suspicious_order_number_rejected(self, app_module):
        # ORD-123456 without the context "your order" is rejected
        with pytest.raises(ValidationError):
            app_module.SafeReply(
                message="Your ORD-123456 has shipped!",
                confidence=0.9,
                action="reply",
            )

    def test_order_number_with_context_allowed(self, app_module):
        # Same pattern with "your order" nearby passes
        reply = app_module.SafeReply(
            message="Regarding your order, ORD-123456 has shipped.",
            confidence=0.9,
            action="reply",
        )
        assert reply.confidence == 0.9

    def test_external_url_rejected(self, app_module):
        with pytest.raises(ValidationError):
            app_module.SafeReply(
                message="Click here: https://evil.example.com/steal",
                confidence=0.9,
                action="reply",
            )

    def test_paystack_url_allowed(self, app_module):
        reply = app_module.SafeReply(
            message="Pay here: https://checkout.paystack.com/abc123",
            confidence=0.9,
            action="reply",
        )
        assert reply.confidence == 0.9

    def test_own_host_url_allowed(self, app_module):
        reply = app_module.SafeReply(
            message="See https://kevsono-kevs-digital-bos.hf.space/",
            confidence=0.9,
            action="reply",
        )
        assert reply.confidence == 0.9


class TestInventoryItem:
    """InventoryItem validates product input."""

    def test_valid_handling_categories(self, app_module):
        for cat in ("standard", "fragile", "bulky", "hazardous"):
            item = app_module.InventoryItem(
                description="Test", price_naira=100, handling_category=cat
            )
            assert item.handling_category == cat

    def test_invalid_handling_category_rejected(self, app_module):
        with pytest.raises(ValidationError):
            app_module.InventoryItem(
                description="Test",
                price_naira=100,
                handling_category="explosive",
            )

    def test_default_handling_category_is_standard(self, app_module):
        item = app_module.InventoryItem(
            description="Test", price_naira=100
        )
        assert item.handling_category == "standard"
