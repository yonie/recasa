"""Face detection and clustering tests."""

import pytest
from backend.tests.utils import APIClient


class TestFaces:
    @pytest.mark.asyncio(loop_scope="session")
    async def test_face_detection_stage_enabled(self, api_client: APIClient, setup_pipeline, manifest):
        config = manifest.get("config", {})
        if not config.get("ENABLE_FACE_DETECTION", True):
            pytest.skip("Face detection disabled")

    @pytest.mark.asyncio(loop_scope="session")
    async def test_faces_detected(self, api_client: APIClient, setup_pipeline, manifest):
        config = manifest.get("config", {})
        if not config.get("ENABLE_FACE_DETECTION", True):
            pytest.skip("Face detection disabled")
        
        stats = setup_pipeline
        faces = stats.get("stages", {}).get("faces", {})
        assert faces.get("completed", 0) > 0, "No faces detected"

    @pytest.mark.asyncio(loop_scope="session")
    async def test_no_faces_in_landscapes(self, api_client: APIClient, setup_pipeline, manifest):
        config = manifest.get("config", {})
        if not config.get("ENABLE_FACE_DETECTION", True):
            pytest.skip("Face detection disabled")
        
        stats = setup_pipeline
        faces = stats.get("stages", {}).get("faces", {})
        total = stats.get("total_photos", 0)
        assert faces.get("completed", 0) < total, "Expected some photos without faces"