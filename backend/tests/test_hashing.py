"""Perceptual hashing tests."""

import pytest
from backend.tests.utils import APIClient


class TestHashing:
    @pytest.mark.asyncio(loop_scope="session")
    async def test_hashing_stage_enabled(self, api_client: APIClient, setup_pipeline, manifest):
        config = manifest.get("config", {})
        if not config.get("ENABLE_HASHING", True):
            pytest.skip("Hashing disabled")

    @pytest.mark.asyncio(loop_scope="session")
    async def test_hashes_generated(self, api_client: APIClient, setup_pipeline):
        stats = setup_pipeline
        hashing = stats.get("stages", {}).get("hashing", {})
        total = stats.get("total_photos", 0)
        assert hashing.get("completed", 0) >= total * 0.9, "Hashing incomplete"