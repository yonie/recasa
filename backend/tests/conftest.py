"""Test configuration and fixtures."""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, AsyncGenerator

import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.utils import APIClient

MANIFEST_PATH = Path(__file__).parent / "fixtures" / "manifest.json"

_pipeline_ready = False


@pytest.fixture(scope="session")
def manifest() -> dict:
    if not MANIFEST_PATH.exists():
        pytest.skip("Manifest not found")
    with open(MANIFEST_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def total_expected_photos(manifest: dict) -> int:
    return len(manifest.get("images", []))


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def api_client() -> AsyncGenerator[APIClient, None]:
    async with APIClient() as client:
        if not await client.wait_for_ready(max_seconds=60):
            pytest.fail("API not ready")
        yield client


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def setup_pipeline(api_client: APIClient, manifest: dict):
    """Setup pipeline once per session."""
    global _pipeline_ready
    
    if _pipeline_ready:
        stats = await api_client.get_processing_stats()
        return stats
    
    await api_client.clear_index()
    await asyncio.sleep(1)
    await api_client.trigger_scan()
    
    if not await api_client.wait_for_idle(max_seconds=300):
        status = await api_client.get_pipeline_status()
        pytest.fail(f"Pipeline timeout: {status.get('queues', {})}")
    
    _pipeline_ready = True
    return await api_client.get_processing_stats()


def check_stage_enabled(manifest: dict, stage_name: str) -> bool:
    config = manifest.get("config", {})
    enabled_stages = config.get("enabled_stages", [
        "exif", "geocoding", "thumbnails", "hashing", "faces", "captioning"
    ])
    return stage_name in enabled_stages


class StageTestHelper:
    def __init__(self, api_client: APIClient, manifest: dict):
        self.api_client = api_client
        self.manifest = manifest
    
    def get_images_with_faces(self) -> list[dict]:
        images = self.manifest.get("images", [])
        return [img for img in images if img.get("faces", {}).get("min_faces", 0) > 0]
    
    def get_images_without_faces(self) -> list[dict]:
        images = self.manifest.get("images", [])
        return [img for img in images if img.get("faces", {}).get("min_faces", 0) == 0]
    
    def get_images_by_category(self, category: str) -> list[dict]:
        images = self.manifest.get("images", [])
        return [img for img in images if img.get("category") == category]


@pytest.fixture
def stage_helper(api_client: APIClient, manifest: dict) -> StageTestHelper:
    return StageTestHelper(api_client, manifest)