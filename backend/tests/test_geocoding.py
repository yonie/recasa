"""Geocoding tests."""

import pytest
from backend.tests.utils import APIClient


class TestGeocoding:
    @pytest.mark.asyncio(loop_scope="session")
    async def test_geocoding_stage_enabled(self, api_client: APIClient, setup_pipeline, manifest):
        config = manifest.get("config", {})
        if not config.get("ENABLE_GEOCODING", True):
            pytest.skip("Geocoding disabled")