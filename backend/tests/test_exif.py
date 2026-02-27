"""EXIF extraction tests."""

import pytest
from tests.utils import APIClient


class TestEXIF:
    @pytest.mark.asyncio(loop_scope="session")
    async def test_exif_stage_enabled(self, api_client: APIClient, setup_pipeline, manifest):
        config = manifest.get("config", {})
        if not config.get("ENABLE_EXIF_EXTRACTION", True):
            pytest.skip("EXIF extraction disabled")

    @pytest.mark.asyncio(loop_scope="session")
    async def test_exif_extracted(self, api_client: APIClient, setup_pipeline):
        stats = setup_pipeline
        exif = stats.get("stages", {}).get("exif", {})
        total = stats.get("total_photos", 0)
        assert exif.get("completed", 0) >= total * 0.9, "EXIF extraction incomplete"