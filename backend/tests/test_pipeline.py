"""End-to-end pipeline integration tests."""

import pytest
from backend.tests.utils import APIClient


class TestPipelineIntegration:
    @pytest.mark.asyncio(loop_scope="session")
    async def test_api_health(self, api_client: APIClient, setup_pipeline):
        assert await api_client.health_check(), "API health check failed"

    @pytest.mark.asyncio(loop_scope="session")
    async def test_pipeline_completes(self, api_client: APIClient, setup_pipeline):
        stats = setup_pipeline
        assert stats is not None
        assert stats.get("total_photos", 0) > 0, "No photos indexed"

    @pytest.mark.asyncio(loop_scope="session")
    async def test_all_photos_indexed(self, api_client: APIClient, setup_pipeline, manifest):
        expected = len(manifest.get("images", []))
        actual = setup_pipeline.get("total_photos", 0)
        assert actual >= expected, f"Expected {expected}+ photos, got {actual}"

    @pytest.mark.asyncio(loop_scope="session")
    async def test_exif_extraction(self, api_client: APIClient, setup_pipeline):
        stats = setup_pipeline
        exif = stats.get("stages", {}).get("exif", {})
        total = stats.get("total_photos", 0)
        assert exif.get("completed", 0) >= total * 0.9, "EXIF extraction incomplete"

    @pytest.mark.asyncio(loop_scope="session")
    async def test_thumbnail_generation(self, api_client: APIClient, setup_pipeline):
        stats = setup_pipeline
        thumbs = stats.get("stages", {}).get("thumbnails", {})
        total = stats.get("total_photos", 0)
        assert thumbs.get("completed", 0) >= total * 0.9, "Thumbnail generation incomplete"

    @pytest.mark.asyncio(loop_scope="session")
    async def test_perceptual_hashing(self, api_client: APIClient, setup_pipeline):
        stats = setup_pipeline
        hashing = stats.get("stages", {}).get("hashing", {})
        total = stats.get("total_photos", 0)
        assert hashing.get("completed", 0) >= total * 0.9, "Hashing incomplete"

    @pytest.mark.asyncio(loop_scope="session")
    async def test_face_detection(self, api_client: APIClient, setup_pipeline, manifest):
        config = manifest.get("config", {})
        if not config.get("ENABLE_FACE_DETECTION", True):
            pytest.skip("Face detection disabled")
        
        stats = setup_pipeline
        faces = stats.get("stages", {}).get("faces", {})
        assert faces.get("completed", 0) > 0, "No faces detected"

    @pytest.mark.asyncio(loop_scope="session")
    async def test_captioning(self, api_client: APIClient, setup_pipeline, manifest):
        config = manifest.get("config", {})
        if not config.get("ENABLE_CAPTIONING", True):
            pytest.skip("Captioning disabled")
        
        stats = setup_pipeline
        captions = stats.get("stages", {}).get("captioning", {})
        total = stats.get("total_photos", 0)
        assert captions.get("completed", 0) >= total * 0.5, "Captioning incomplete"

    @pytest.mark.asyncio(loop_scope="session")
    async def test_photos_retrievable(self, api_client: APIClient, setup_pipeline):
        photos = await api_client.get_photos(page_size=100)
        assert isinstance(photos, list), f"Expected list, got {type(photos)}"
        assert len(photos) > 0, "No photos returned"
        
        for photo in photos[:3]:
            assert "file_hash" in photo
            assert "file_name" in photo
            assert "file_path" in photo