"""Thumbnail generation tests."""

import pytest
from tests.utils import APIClient


class TestThumbnails:
    @pytest.mark.asyncio(loop_scope="session")
    async def test_thumbnails_stage_enabled(self, api_client: APIClient, setup_pipeline, manifest):
        config = manifest.get("config", {})
        if not config.get("ENABLE_THUMBNAILS", True):
            pytest.skip("Thumbnails disabled")

    @pytest.mark.asyncio(loop_scope="session")
    async def test_thumbnails_generated(self, api_client: APIClient, setup_pipeline):
        stats = setup_pipeline
        thumbs = stats.get("stages", {}).get("thumbnails", {})
        total = stats.get("total_photos", 0)
        assert thumbs.get("completed", 0) >= total * 0.9, "Thumbnail generation incomplete"