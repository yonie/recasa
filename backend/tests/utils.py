"""Test utilities for integration tests."""

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx

import os

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")


class APIClient:
    """HTTP client for testing the Recasa API."""

    def __init__(self, base_url: str = BASE_URL, timeout: float = 300):
        self.base_url = base_url
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    async def get(self, path: str, **kwargs) -> httpx.Response:
        return await self._client.get(f"{self.base_url}{path}", **kwargs)

    async def post(self, path: str, **kwargs) -> httpx.Response:
        return await self._client.post(f"{self.base_url}{path}", **kwargs)

    async def health_check(self) -> bool:
        """Check if the API is healthy."""
        try:
            r = await self._client.get(f"{self.base_url}/api/health", timeout=5.0)
            return r.status_code == 200
        except Exception:
            return False

    async def wait_for_ready(self, max_seconds: int = 60) -> bool:
        """Wait for the API to be ready."""
        for _ in range(max_seconds):
            if await self.health_check():
                return True
            await asyncio.sleep(1)
        return False

    async def get_pipeline_status(self) -> dict[str, Any]:
        """Get current pipeline status."""
        r = await self.get("/api/pipeline/status")
        r.raise_for_status()
        return r.json()

    async def get_processing_stats(self) -> dict[str, Any]:
        """Get processing statistics."""
        r = await self.get("/api/pipeline/processing-stats")
        r.raise_for_status()
        return r.json()

    async def clear_index(self) -> dict[str, Any]:
        """Clear the photo index."""
        r = await self.post("/api/scan/clear-index")
        r.raise_for_status()
        return r.json()

    async def trigger_scan(self) -> dict[str, Any]:
        """Trigger a photo scan."""
        r = await self.post("/api/scan/trigger")
        r.raise_for_status()
        return r.json()

    async def stop_pipeline(self) -> dict[str, Any]:
        """Stop the pipeline."""
        r = await self.post("/api/pipeline/stop")
        r.raise_for_status()
        return r.json()

    async def wait_for_idle(self, max_seconds: int = 300, poll_interval: float = 2.0) -> bool:
        """Wait for all queues to be empty (pipeline idle)."""
        empty_count = 0
        for _ in range(int(max_seconds / poll_interval)):
            status = await self.get_pipeline_status()
            queues = status.get("queues", {})
            total_in_queues = sum(queues.values())
            if total_in_queues == 0:
                empty_count += 1
                if empty_count >= 2:
                    return True
            else:
                empty_count = 0
            await asyncio.sleep(poll_interval)
        return False

    async def get_photos(self, page_size: int = 100) -> list[dict[str, Any]]:
        """Get list of photos."""
        r = await self.get(f"/api/photos?page_size={page_size}")
        r.raise_for_status()
        data = r.json()
        return data.get("items", [])

    async def get_config_status(self) -> dict[str, Any]:
        """Get configuration status."""
        r = await self.get("/api/config/status")
        r.raise_for_status()
        return r.json()


def load_manifest(manifest_path: Path | None = None) -> dict[str, Any]:
    """Load the test fixtures manifest."""
    if manifest_path is None:
        manifest_path = Path(__file__).parent / "fixtures" / "manifest.json"
    with open(manifest_path) as f:
        return json.load(f)


def get_fixture_images() -> list[Path]:
    """Get list of all test fixture images."""
    fixtures_dir = Path(__file__).parent / "fixtures" / "images"
    images = []
    for category in ["faces", "landscapes", "city", "portraits", "formats"]:
        category_dir = fixtures_dir / category
        if category_dir.exists():
            for img in category_dir.rglob("*"):
                if img.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}:
                    images.append(img)
    return sorted(images)


def count_images_by_category() -> dict[str, int]:
    """Count images in each category."""
    fixtures_dir = Path(__file__).parent / "fixtures" / "images"
    counts = {}
    for category in ["faces", "landscapes", "city", "portraits", "formats"]:
        category_dir = fixtures_dir / category
        if category_dir.exists():
            count = len([
                f for f in category_dir.rglob("*")
                if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
            ])
            if count > 0:
                counts[category] = count
    return counts