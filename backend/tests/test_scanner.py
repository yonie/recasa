"""Scanner/indexing tests."""

import pytest
from backend.tests.utils import APIClient


class TestScanner:
    @pytest.mark.asyncio(loop_scope="session")
    async def test_photos_have_correct_paths(self, api_client: APIClient, setup_pipeline):
        photos = await api_client.get_photos(page_size=50)
        photos = list(photos)
        assert len(photos) > 0, "No photos found"
        
        for photo in photos:
            file_path = photo.get("file_path", "")
            file_name = photo.get("file_name", "")
            assert file_path, f"Photo missing file_path"
            assert file_name, f"Photo missing file_name"

    @pytest.mark.asyncio(loop_scope="session")
    async def test_photos_have_file_hash(self, api_client: APIClient, setup_pipeline):
        photos = await api_client.get_photos(page_size=50)
        photos = list(photos)
        
        for photo in photos:
            file_hash = photo.get("file_hash")
            assert file_hash, "Photo missing file_hash"
            assert len(file_hash) == 64, f"Invalid hash length"

    @pytest.mark.asyncio(loop_scope="session")
    async def test_photos_have_file_size(self, api_client: APIClient, setup_pipeline):
        photos = await api_client.get_photos(page_size=50)
        photos = list(photos)
        
        for photo in photos:
            file_size = photo.get("file_size")
            assert file_size is not None, "Photo missing file_size"
            assert file_size > 0, f"Invalid file_size"

    @pytest.mark.asyncio(loop_scope="session")
    async def test_photos_have_mime_type(self, api_client: APIClient, setup_pipeline):
        photos = await api_client.get_photos(page_size=50)
        photos = list(photos)
        valid_mimes = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif", None}
        
        for photo in photos:
            mime_type = photo.get("mime_type")
            # Some formats may not have mime_type detected, skip those
            if mime_type is None:
                continue
            assert mime_type in valid_mimes, f"Unexpected mime_type: {mime_type}"