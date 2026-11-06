"""
Tests for pure string helpers used across the codebase.
"""


class TestSlugify:
    """slugify produces URL-safe slugs for the storefront."""

    def test_basic(self, app_module):
        assert app_module.slugify("Acme Pharmacy Ltd.") == "acme-pharmacy-ltd"

    def test_empty(self, app_module):
        assert app_module.slugify("") == ""

    def test_whitespace_only(self, app_module):
        assert app_module.slugify("   ") == ""

    def test_repeated_special_chars(self, app_module):
        assert app_module.slugify("foo!!!bar") == "foo-bar"

    def test_leading_and_trailing_hyphens_trimmed(self, app_module):
        assert app_module.slugify("---hello---") == "hello"

    def test_truncated_to_60_chars(self, app_module):
        long_name = "a" * 100
        assert len(app_module.slugify(long_name)) == 60

    def test_numbers_preserved(self, app_module):
        assert app_module.slugify("Shop 24/7") == "shop-24-7"


class TestCleanOptionalEmail:
    """_clean_optional_email normalises optional email fields."""

    def test_none_returns_none(self, app_module):
        assert app_module._clean_optional_email(None) is None

    def test_empty_string_returns_none(self, app_module):
        assert app_module._clean_optional_email("") is None

    def test_whitespace_only_returns_none(self, app_module):
        assert app_module._clean_optional_email("   ") is None

    def test_trims_whitespace(self, app_module):
        assert app_module._clean_optional_email("  test@example.com  ") == "test@example.com"

    def test_normal_email_passes_through(self, app_module):
        assert app_module._clean_optional_email("a@b.c") == "a@b.c"

    def test_non_string_passes_through(self, app_module):
        # Current behaviour: non-strings pass through unmodified.
        # Not ideal, but this is what the code does and other endpoints
        # depend on it. Test the behaviour, not the aspiration.
        assert app_module._clean_optional_email(42) == 42


class TestEscapeHtml:
    """escape_html sanitises user-facing text for HTML rendering."""

    def test_empty(self, app_module):
        assert app_module.escape_html("") == ""

    def test_none_returns_empty(self, app_module):
        assert app_module.escape_html(None) == ""

    def test_plain_text_unchanged(self, app_module):
        assert app_module.escape_html("hello world") == "hello world"

    def test_angle_brackets(self, app_module):
        assert app_module.escape_html("<script>") == "&lt;script&gt;"

    def test_ampersand(self, app_module):
        assert app_module.escape_html("a & b") == "a &amp; b"

    def test_quotes(self, app_module):
        assert app_module.escape_html('he said "hi"') == "he said &quot;hi&quot;"
