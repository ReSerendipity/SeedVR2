"""Property-based tests using Hypothesis

Uses Hypothesis to generate test cases automatically, finding edge cases
that manual test design might miss.
"""

from __future__ import annotations

import pytest

try:
    from hypothesis import HealthCheck, given, settings
    from hypothesis import strategies as st
    HYPOTHESIS_AVAILABLE = True
except ImportError:
    HYPOTHESIS_AVAILABLE = False

from tests.conftest import csrf_post

# Skip all tests if hypothesis is not installed
pytestmark = pytest.mark.skipif(
    not HYPOTHESIS_AVAILABLE,
    reason="hypothesis not installed (pip install hypothesis)",
)


if HYPOTHESIS_AVAILABLE:
    # ============================================================
    # History API pagination properties
    # ============================================================

    class TestHistoryPaginationProperties:
        """Property-based tests for history API pagination"""

        @given(page=st.integers(min_value=1, max_value=100))
        @settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
        def test_valid_page_returns_200(self, test_app, page):
            """Any valid page (1-100) should return 200"""
            response = test_app.get(f"/api/system/history?page={page}&page_size=10")
            assert response.status_code == 200
            data = response.json()
            assert data["page"] == page

        @given(page_size=st.integers(min_value=1, max_value=100))
        @settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
        def test_valid_page_size_returns_200(self, test_app, page_size):
            """Any valid page_size (1-100) should return 200"""
            response = test_app.get(f"/api/system/history?page=1&page_size={page_size}")
            assert response.status_code == 200
            data = response.json()
            assert data["page_size"] == page_size

        @given(page=st.integers(max_value=0))
        @settings(max_examples=10, suppress_health_check=[HealthCheck.function_scoped_fixture])
        def test_invalid_page_returns_422(self, test_app, page):
            """Any page <= 0 should return 422"""
            response = test_app.get(f"/api/system/history?page={page}&page_size=10")
            assert response.status_code == 422

        @given(page_size=st.integers(min_value=101, max_value=10000))
        @settings(max_examples=10, suppress_health_check=[HealthCheck.function_scoped_fixture])
        def test_oversize_page_size_returns_422(self, test_app, page_size):
            """Any page_size > 100 should return 422"""
            response = test_app.get(f"/api/system/history?page=1&page_size={page_size}")
            assert response.status_code == 422

    # ============================================================
    # Settings round-trip properties
    # ============================================================

    class TestSettingsProperties:
        """Property-based tests for settings API"""

        @given(
            cfg_scale=st.floats(min_value=1.0, max_value=10.0, allow_nan=False, allow_infinity=False)
        )
        @settings(max_examples=10, suppress_health_check=[HealthCheck.function_scoped_fixture])
        def test_cfg_scale_validation(self, test_app, cfg_scale):
            """Any cfg_scale in [1.0, 10.0] should pass validation"""
            response = csrf_post(
                test_app,
                "/api/ui/parameters/validate",
                json={"cfg_scale": cfg_scale},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["data"]["valid"] is True

        @given(
            denoising=st.floats(min_value=0.4, max_value=0.8, allow_nan=False, allow_infinity=False)
        )
        @settings(max_examples=10, suppress_health_check=[HealthCheck.function_scoped_fixture])
        def test_denoising_strength_validation(self, test_app, denoising):
            """Any denoising_strength in [0.4, 0.8] (recommended range) should pass validation"""
            response = csrf_post(
                test_app,
                "/api/ui/parameters/validate",
                json={"denoising_strength": denoising},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["data"]["valid"] is True
