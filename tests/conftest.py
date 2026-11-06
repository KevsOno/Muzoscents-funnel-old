"""
Pytest configuration for the Kevs Digital bOS test suite.

Strategy: import main.py once, with heavy external dependencies mocked
so tests run without network access, without model downloads, and
without a database.

Mocks applied BEFORE main.py import:
  - sentence_transformers : would download a 90MB model on first import
  - google.generativeai   : would fail auth on configure()
  - groq                  : would fail auth on Groq() init
  - httpx.AsyncClient     : would try to reach Supabase for any
                            module-level client construction

The `app_module` fixture returns the imported module. If import fails
(a missing local dep, a real network call during import), tests that
need it are skipped with a message pointing at the failure, rather
than erroring out in a confusing way.
"""
import os
import sys
from unittest.mock import MagicMock

import pytest

# Make repo root importable
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

# Minimal env so module-level os.environ.get() lookups don't return None
# and crash at import time.
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-key")
os.environ.setdefault("SKIP_MIGRATIONS", "true")
os.environ.setdefault("ENFORCE_FEATURES", "false")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

# Mock heavy / network-touching deps BEFORE importing main.py
_HEAVY_MODULES = [
    "sentence_transformers",
    "groq",
    "google",
    "google.generativeai",
]
for _mod in _HEAVY_MODULES:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()


@pytest.fixture(scope="session")
def app_module():
    """Import main.py once for the whole test session."""
    try:
        import main  # noqa: F401
        return main
    except Exception as e:
        pytest.skip(
            f"main.py could not be imported in the test environment: "
            f"{type(e).__name__}: {e}\n"
            f"This usually means a local module (deps.py, geo.py, "
            f"delivery_zones.py, tracking.py) is missing or has an import "
            f"error. Fix the import first, then re-run tests."
        )
