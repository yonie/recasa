"""AI captioning tests."""

import pytest
from backend.tests.utils import APIClient


class TestCaptioning:
    @pytest.mark.asyncio(loop_scope="session")
    async def test_captioning_stage_enabled(self, api_client: APIClient, setup_pipeline, manifest):
        config = manifest.get("config", {})
        if not config.get("ENABLE_CAPTIONING", True):
            pytest.skip("Captioning disabled")

    @pytest.mark.asyncio(loop_scope="session")
    async def test_captions_generated(self, api_client: APIClient, setup_pipeline, manifest):
        config = manifest.get("config", {})
        if not config.get("ENABLE_CAPTIONING", True):
            pytest.skip("Captioning disabled")
        
        stats = setup_pipeline
        captions = stats.get("stages", {}).get("captioning", {})
        total = stats.get("total_photos", 0)
        assert captions.get("completed", 0) >= total * 0.5, "Too few captions generated"