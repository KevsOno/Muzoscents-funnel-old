"""
Tests for the storefront config merge and vertical validation.
"""


class TestMergeStorefrontConfig:
    """merge_storefront_config combines stored overrides with defaults."""

    def test_none_returns_defaults(self, app_module):
        merged = app_module.merge_storefront_config(None)
        assert merged["theme"] == "modern"
        assert merged["branding"]["primary_color"] == "#3b82f6"

    def test_empty_dict_returns_defaults(self, app_module):
        merged = app_module.merge_storefront_config({})
        assert merged["theme"] == "modern"

    def test_top_level_override_wins(self, app_module):
        merged = app_module.merge_storefront_config({"theme": "minimal"})
        assert merged["theme"] == "minimal"

    def test_nested_override_preserves_siblings(self, app_module):
        merged = app_module.merge_storefront_config({
            "branding": {"primary_color": "#ff0000"},
        })
        assert merged["branding"]["primary_color"] == "#ff0000"
        # Siblings remain at their defaults
        assert merged["branding"]["accent_color"] == "#f59e0b"
        assert merged["branding"]["font_family"] == "Inter"

    def test_unknown_section_is_preserved(self, app_module):
        merged = app_module.merge_storefront_config({
            "custom_section": {"foo": "bar"},
        })
        assert merged["custom_section"] == {"foo": "bar"}

    def test_original_defaults_not_mutated(self, app_module):
        # Guard against a shallow-copy bug where overriding a nested
        # section would poison the module-level default for future calls.
        app_module.merge_storefront_config({
            "branding": {"primary_color": "#deadbe"},
        })
        second = app_module.merge_storefront_config(None)
        assert second["branding"]["primary_color"] == "#3b82f6", \
            "merge_storefront_config must not mutate DEFAULT_STOREFRONT_CONFIG"


class TestValidateOrgVertical:
    """validate_org_vertical enforces the 3-vertical whitelist."""

    def test_valid_verticals(self, app_module):
        for v in ("retail", "food", "service"):
            assert app_module.validate_org_vertical(v) == v

    def test_unknown_defaults_to_retail(self, app_module):
        assert app_module.validate_org_vertical("pharmacy") == "retail"
        assert app_module.validate_org_vertical("") == "retail"
        assert app_module.validate_org_vertical(None) == "retail"
