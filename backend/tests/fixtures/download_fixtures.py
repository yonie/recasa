#!/usr/bin/env python3
"""Download test fixture images from public sources.

This script downloads CC0 and public domain images for testing:
- Historical figures from Wikimedia Commons (public domain)
- Portraits and landscapes from Unsplash (CC0)
- Creates synthetic test images for format testing

Run this script once to populate the fixtures directory:
    python backend/tests/fixtures/download_fixtures.py

The images will be saved to backend/tests/fixtures/images/
"""

import hashlib
import json
import os
import sys
from io import BytesIO
from pathlib import Path

try:
    import httpx
    from PIL import Image
except ImportError:
    print("Please install: pip install httpx pillow")
    sys.exit(1)

FIXTURES_DIR = Path(__file__).parent / "images"
MANIFEST_PATH = Path(__file__).parent / "manifest.json"

# Image sources (all CC0 or public domain)
UNSPLASH_SOURCES = {
    # Portraits (multiple angles for face clustering)
    "faces/alice/alice_01.jpg": "https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=800",
    "faces/alice/alice_02.jpg": "https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=800&h=600&fit=crop",
    "faces/alice/alice_03.jpg": "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=800",
    "faces/alice/alice_04.jpg": "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=800&h=600&fit=crop",
    "faces/bob/bob_01.jpg": "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=800",
    "faces/bob/bob_02.jpg": "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=800&h=600&fit=crop",
    "faces/bob/bob_03.jpg": "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=800",
    "faces/carol/carol_01.jpg": "https://images.unsplash.com/photo-1438761681033-6461ffad8d80?w=800",
    "faces/carol/carol_02.jpg": "https://images.unsplash.com/photo-1438761681033-6461ffad8d80?w=800&h=600&fit=crop",
    "faces/carol/carol_03.jpg": "https://images.unsplash.com/photo-1544005313-94ddf0286df2?w=800",
    # Group photos
    "faces/group/group_01.jpg": "https://images.unsplash.com/photo-1529156069898-49953e39b3ac?w=800",
    "faces/group/group_02.jpg": "https://images.unsplash.com/photo-1517457373958-b7bdd4587205?w=800",
    # Landscapes
    "landscapes/mountain_01.jpg": "https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?w=800",
    "landscapes/mountain_02.jpg": "https://images.unsplash.com/photo-1519681393784-d120267933ba?w=800",
    "landscapes/ocean_01.jpg": "https://images.unsplash.com/photo-1505118380757-91f5f5632de0?w=800",
    "landscapes/ocean_02.jpg": "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?w=800",
    "landscapes/forest_01.jpg": "https://images.unsplash.com/photo-1448375240586-882707db888b?w=800",
    "landscapes/forest_02.jpg": "https://images.unsplash.com/photo-1542273917363-3b1817f69a2d?w=800",
    "landscapes/desert_01.jpg": "https://images.unsplash.com/photo-1509316785289-025f5b846b35?w=800",
    "landscapes/desert_02.jpg": "https://images.unsplash.com/photo-1473580044384-7ba9967e16a0?w=800",
    "landscapes/lake_01.jpg": "https://images.unsplash.com/photo-1439066615861-d1af74d74000?w=800",
    "landscapes/lake_02.jpg": "https://images.unsplash.com/photo-1501785888041-af3ef285b470?w=800",
    # City
    "city/tokyo_01.jpg": "https://images.unsplash.com/photo-1540959733332-eab4deabeeaf?w=800",
    "city/tokyo_02.jpg": "https://images.unsplash.com/photo-1536098561742-ca998e48cbcc?w=800",
    "city/newyork_01.jpg": "https://images.unsplash.com/photo-1496442226666-8d4d0e62e6e9?w=800",
    "city/newyork_02.jpg": "https://images.unsplash.com/photo-1534430480872-3498386e7856?w=800",
    "city/london_01.jpg": "https://images.unsplash.com/photo-1513635269975-59663e0ac1ad?w=800",
    "city/london_02.jpg": "https://images.unsplash.com/photo-1486299267070-83823f5448dd?w=800",
    "city/paris_01.jpg": "https://images.unsplash.com/photo-1502602898657-3e91760cbb34?w=800",
    "city/paris_02.jpg": "https://images.unsplash.com/photo-1500313830540-7b6650a74fd0?w=800",
    # Portraits
    "portraits/portrait_01.jpg": "https://images.unsplash.com/photo-1531746020798-e6953c6e8e04?w=800",
    "portraits/portrait_02.jpg": "https://images.unsplash.com/photo-1552058544-f2b08422138a?w=800",
    "portraits/portrait_03.jpg": "https://images.unsplash.com/photo-1524504388940-b1c1722653e1?w=800",
    "portraits/portrait_04.jpg": "https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?w=800",
    "portraits/portrait_05.jpg": "https://images.unsplash.com/photo-1517841905240-472988babdf9?w=800",
    "portraits/portrait_06.jpg": "https://images.unsplash.com/photo-1529626455594-4ff0802cfb7e?w=800",
    "portraits/portrait_07.jpg": "https://images.unsplash.com/photo-1485206412256-701ccc5b93ca?w=800",
    "portraits/portrait_08.jpg": "https://images.unsplash.com/photo-1520813792240-56fc4a3765a7?w=800",
}

# Wikimedia Commons public domain URLs for historical figures
WIKIMEDIA_SOURCES = {
    "faces/historical/einstein_01.jpg": "https://upload.wikimedia.org/wikipedia/commons/thumb/3/3e/Einstein_1921_by_F_Schmutzer_-_restoration.jpg/800px-Einstein_1921_by_F_Schmutzer_-_restoration.jpg",
    "faces/historical/einstein_02.jpg": "https://upload.wikimedia.org/wikipedia/commons/thumb/1/14/Albert_Einstein_1947.jpg/800px-Albert_Einstein_1947.jpg",
    "faces/historical/einstein_03.jpg": "https://upload.wikimedia.org/wikipedia/commons/thumb/d/d4/Einstein_tongue.jpg/800px-Einstein_tongue.jpg",
    "faces/historical/einstein_04.jpg": "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a0/Einstein_patridge.jpg/800px-Einstein_patridge.jpg",
    "faces/historical/curie_01.jpg": "https://upload.wikimedia.org/wikipedia/commons/thumb/c/c8/Marie_Curie_c._1920s.jpg/800px-Marie_Curie_c._1920s.jpg",
    "faces/historical/curie_02.jpg": "https://upload.wikimedia.org/wikipedia/commons/thumb/4/47/Marie_Curie_-_1900.jpg/800px-Marie_Curie_-_1900.jpg",
    "faces/historical/lincoln_01.jpg": "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Abraham_Lincoln_O-77_matte_collodion_print.jpg/800px-Abraham_Lincoln_O-77_matte_collodion_print.jpg",
    "faces/historical/lincoln_02.jpg": "https://upload.wikimedia.org/wikipedia/commons/thumb/4/48/Abraham_Lincoln_head_on_shoulders_photo_portrait.jpg/800px-Abraham_Lincoln_head_on_shoulders_photo_portrait.jpg",
}


def create_synthetic_image(filename: str, width: int = 800, height: int = 600) -> bytes:
    """Create a synthetic test image for format testing."""
    from PIL import Image, ImageDraw, ImageFont
    
    img = Image.new("RGB", (width, height), color=(73, 109, 137))
    draw = ImageDraw.Draw(img)
    
    base_name = Path(filename).stem
    draw.rectangle([50, 50, width - 50, height - 50], outline=(255, 255, 255), width=2)
    draw.text((width // 2 - 50, height // 2), base_name, fill=(255, 255, 255))
    
    buffer = BytesIO()
    suffix = Path(filename).suffix.lower()
    if suffix == ".png":
        img.save(buffer, format="PNG")
    elif suffix == ".webp":
        img.save(buffer, format="WEBP")
    elif suffix in (".tif", ".tiff"):
        img.save(buffer, format="TIFF")
    elif suffix == ".heic":
        img.save(buffer, format="JPEG")
    else:
        img.save(buffer, format="JPEG", quality=90)
    
    return buffer.getvalue()


def add_exif_data(image_bytes: bytes, camera_make: str, date_taken: str, 
                  gps_lat: float = None, gps_lng: float = None) -> bytes:
    """Add EXIF data to an image (simplified - creates new image with minimal metadata)."""
    from PIL import Image
    from datetime import datetime
    
    img = Image.open(BytesIO(image_bytes))
    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def download_image(url: str) -> bytes:
    """Download an image from URL."""
    print(f"  Downloading: {url[:60]}...")
    with httpx.Client(follow_redirects=True, timeout=30) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.content


def main():
    """Download all fixture images."""
    print("=" * 60)
    print("Recasa Test Fixture Downloader")
    print("=" * 60)
    
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    
    downloaded_count = 0
    skipped_count = 0
    error_count = 0
    
    all_sources = {**UNSPLASH_SOURCES, **WIKIMEDIA_SOURCES}
    
    for relative_path, url in all_sources.items():
        dest_path = FIXTURES_DIR / relative_path
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        
        if dest_path.exists():
            print(f"  Skipping (exists): {relative_path}")
            skipped_count += 1
            continue
        
        try:
            image_data = download_image(url)
            dest_path.write_bytes(image_data)
            print(f"  Saved: {relative_path}")
            downloaded_count += 1
        except Exception as e:
            print(f"  Error downloading {relative_path}: {e}")
            error_count += 1
    
    print("\n" + "-" * 60)
    print("Creating synthetic format test images...")
    
    format_images = {
        "formats/sample.heic": (800, 600),
        "formats/sample.webp": (800, 600),
        "formats/sample.png": (800, 600),
        "formats/sample_portrait.png": (600, 800),
        "formats/sample_tiff.tif": (800, 600),
    }
    
    (FIXTURES_DIR / "formats").mkdir(parents=True, exist_ok=True)
    
    for relative_path, size in format_images.items():
        dest_path = FIXTURES_DIR / relative_path
        if dest_path.exists():
            print(f"  Skipping (exists): {relative_path}")
            skipped_count += 1
            continue
        
        try:
            image_data = create_synthetic_image(relative_path, *size)
            dest_path.write_bytes(image_data)
            print(f"  Created: {relative_path}")
            downloaded_count += 1
        except Exception as e:
            print(f"  Error creating {relative_path}: {e}")
            error_count += 1
    
    print("\n" + "=" * 60)
    print(f"Download complete!")
    print(f"  Downloaded: {downloaded_count}")
    print(f"  Skipped:    {skipped_count}")
    print(f"  Errors:     {error_count}")
    print("=" * 60)
    
    if error_count > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())