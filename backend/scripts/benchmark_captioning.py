#!/usr/bin/env python
"""Benchmark different Ollama vision models for captioning performance.

Usage:
    python scripts/benchmark_captioning.py --images /photos/2025 --count 10
    python scripts/benchmark_captioning.py --images ./test_images --count 5 --models qwen3-vl:2b qwen3-vl:4b
"""

import argparse
import asyncio
import base64
import io
import os
import re
import sys
import time
from pathlib import Path

import httpx


DEFAULT_MODELS = [
    "qwen3-vl:2b-instruct",
    "qwen3-vl:4b-instruct",
    "qwen3-vl:8b-instruct",
    "qwen3-vl:30b-a3b-instruct",
    "qwen3-vl:235b-instruct-cloud",
]

COMBINED_PROMPT = """Analyze this photo and provide:

1. CAPTION: One or two concise sentences describing the main subject, setting, and notable details. Be specific and descriptive.

2. TAGS: A comma-separated list of specific objects, scenes, activities, locations/landmarks, colors, mood, weather, time of day. Be specific (e.g. 'golden retriever' not 'dog', 'Eiffel Tower' not 'tower').

Format your response exactly like this:
CAPTION: [your caption here]
TAGS: [tag1, tag2, tag3, ...]"""

MAX_IMAGE_DIMENSION = 1024
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")


def strip_think_blocks(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def prepare_image_base64(filepath: Path) -> str | None:
    try:
        from PIL import Image, ImageOps

        with Image.open(filepath) as img:
            try:
                img = ImageOps.exif_transpose(img)
            except Exception:
                pass

            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")

            if max(img.width, img.height) > MAX_IMAGE_DIMENSION:
                img.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION), Image.Resampling.LANCZOS)

            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=85)
            return base64.b64encode(buffer.getvalue()).decode("utf-8")

    except Exception as e:
        print(f"  Error preparing image {filepath}: {e}")
        return None


async def check_model_available(client: httpx.AsyncClient, model: str) -> bool:
    try:
        response = await client.get(f"{OLLAMA_URL}/api/tags", timeout=10.0)
        if response.status_code == 200:
            data = response.json()
            models = [m["name"] for m in data.get("models", [])]
            return model in models
    except Exception:
        pass
    return False


async def caption_image(client: httpx.AsyncClient, model: str, image_base64: str) -> tuple[str | None, float]:
    start = time.time()
    try:
        response = await client.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": model,
                "prompt": COMBINED_PROMPT,
                "images": [image_base64],
                "stream": False,
                "options": {
                    "temperature": 0.3,
                    "num_predict": 300,
                },
            },
            timeout=180.0,
        )

        elapsed = time.time() - start

        if response.status_code == 200:
            data = response.json()
            raw = strip_think_blocks(data.get("response", ""))
            return raw, elapsed
        else:
            print(f"    Error: HTTP {response.status_code}")
            return None, elapsed

    except httpx.TimeoutException:
        elapsed = time.time() - start
        print(f"    Timeout after {elapsed:.1f}s")
        return None, elapsed
    except Exception as e:
        elapsed = time.time() - start
        print(f"    Error: {e}")
        return None, elapsed


def parse_response(raw: str) -> tuple[str | None, list[str]]:
    caption = None
    tags = []

    caption_match = re.search(r"CAPTION:\s*(.+?)(?=TAGS:|$)", raw, re.DOTALL | re.IGNORECASE)
    if caption_match:
        caption = caption_match.group(1).strip()

    tags_match = re.search(r"TAGS:\s*(.+?)$", raw, re.DOTALL | re.IGNORECASE)
    if tags_match:
        tags_raw = tags_match.group(1).strip()
        tag_list = [t.strip().lower() for t in tags_raw.split(",")]
        tags = [t for t in tag_list if 2 <= len(t) <= 80][:10]

    return caption, tags


async def benchmark_model(model: str, images: list[tuple[Path, str]], client: httpx.AsyncClient) -> dict:
    print(f"\n{'='*60}")
    print(f"Model: {model}")
    print(f"{'='*60}")

    available = await check_model_available(client, model)
    if not available:
        print(f"  Model not available locally. Attempting to pull...")
        try:
            pull_response = await client.post(
                f"{OLLAMA_URL}/api/pull",
                json={"name": model},
                timeout=600.0,
            )
            if pull_response.status_code != 200:
                print(f"  Failed to pull model: HTTP {pull_response.status_code}")
                return {"model": model, "available": False, "error": "pull_failed"}
        except Exception as e:
            print(f"  Failed to pull model: {e}")
            return {"model": model, "available": False, "error": str(e)}

    times = []
    successes = 0
    samples = []

    for filepath, image_base64 in images:
        print(f"  Processing: {filepath.name}...", end=" ", flush=True)
        response, elapsed = await caption_image(client, model, image_base64)
        times.append(elapsed)

        if response:
            successes += 1
            caption, tags = parse_response(response)
            print(f"{elapsed:.2f}s")
            if len(samples) < 2:
                samples.append({
                    "file": filepath.name,
                    "caption": caption[:100] + "..." if caption and len(caption) > 100 else caption,
                    "tags": tags[:5] if tags else [],
                    "time": elapsed,
                })
        else:
            print(f"FAILED ({elapsed:.2f}s)")

    if not times:
        return {"model": model, "available": True, "error": "no_images"}

    return {
        "model": model,
        "available": True,
        "total_images": len(images),
        "successful": successes,
        "total_time": sum(times),
        "avg_time": sum(times) / len(times),
        "min_time": min(times),
        "max_time": max(times),
        "samples": samples,
    }


def print_summary(results: list[dict]):
    print(f"\n{'='*80}")
    print("BENCHMARK SUMMARY")
    print(f"{'='*80}")
    print(f"{'Model':<40} {'Avg Time':>10} {'Success':>10} {'Total':>10}")
    print("-" * 80)

    for r in results:
        if not r.get("available"):
            print(f"{r['model']:<40} {'UNAVAILABLE':>10}")
        elif "error" in r:
            print(f"{r['model']:<40} {'ERROR':>10}")
        else:
            print(f"{r['model']:<40} {r['avg_time']:>8.2f}s  {r['successful']:>5}/{r['total_images']:<5} {r['total_time']:>8.1f}s")

    print("-" * 80)

    print("\nSAMPLE OUTPUTS:")
    for r in results:
        if r.get("samples"):
            print(f"\n{r['model']}:")
            for s in r["samples"]:
                print(f"  {s['file']}: {s['time']:.2f}s")
                print(f"    Caption: {s['caption']}")
                print(f"    Tags: {', '.join(s['tags'])}")


async def main():
    global OLLAMA_URL
    
    parser = argparse.ArgumentParser(description="Benchmark Ollama vision models for captioning")
    parser.add_argument("--images", required=True, help="Directory containing test images")
    parser.add_argument("--count", type=int, default=10, help="Number of images to test (default: 10)")
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS, help="Models to benchmark")
    parser.add_argument("--ollama-url", default=os.environ.get("OLLAMA_URL", "http://localhost:11434"), help="Ollama API URL")
    args = parser.parse_args()

    OLLAMA_URL = args.ollama_url

    images_dir = Path(args.images)
    if not images_dir.exists():
        print(f"Error: Directory not found: {images_dir}")
        sys.exit(1)

    supported_extensions = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
    image_files = []
    for ext in supported_extensions:
        image_files.extend(images_dir.glob(f"**/*{ext}"))
        image_files.extend(images_dir.glob(f"**/*{ext.upper()}"))

    image_files = sorted(image_files, key=lambda p: str(p))[: args.count]

    if not image_files:
        print(f"Error: No images found in {images_dir}")
        sys.exit(1)

    print(f"Found {len(image_files)} images to benchmark")

    print("\nPreparing images...")
    prepared_images = []
    for filepath in image_files:
        image_base64 = prepare_image_base64(filepath)
        if image_base64:
            prepared_images.append((filepath, image_base64))
            print(f"  Prepared: {filepath.name}")

    if not prepared_images:
        print("Error: Could not prepare any images")
        sys.exit(1)

    print(f"\nPrepared {len(prepared_images)} images for benchmarking")

    async with httpx.AsyncClient() as client:
        results = []
        for model in args.models:
            result = await benchmark_model(model, prepared_images, client)
            results.append(result)

    print_summary(results)


if __name__ == "__main__":
    asyncio.run(main())