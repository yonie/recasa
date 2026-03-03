"""Consistency tests to verify DB matches filesystem."""
import asyncio
import os
from pathlib import Path

import pytest

from backend.app.database import async_session
from backend.app.models import Photo
from backend.app.config import settings
from sqlalchemy import select, func


PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".webp", ".gif", ".cr2", ".nef", ".dng", ".arw"}


def count_photos_on_disk() -> dict[str, int]:
    """Count photos by year from filesystem."""
    photos_dir = settings.photos_dir
    year_counts: dict[str, int] = {}
    
    if not photos_dir.exists():
        return year_counts
    
    for entry in photos_dir.iterdir():
        if entry.is_dir() and entry.name[:4].isdigit():
            year = entry.name[:4]
            if year not in year_counts:
                year_counts[year] = 0
            
            for root, _, files in os.walk(entry):
                for f in files:
                    if Path(f).suffix.lower() in PHOTO_EXTENSIONS:
                        year_counts[year] = year_counts.get(year, 0) + 1
    
    return year_counts


async def count_photos_in_db() -> dict[str, int]:
    """Count photos by year from database."""
    async with async_session() as session:
        result = await session.execute(
            select(
                func.substr(Photo.date_taken, 1, 4).label("year"),
                func.count(Photo.file_hash)
            )
            .where(Photo.date_taken.is_not(None))
            .group_by(func.substr(Photo.date_taken, 1, 4))
        )
        
        year_counts: dict[str, int] = {}
        for row in result:
            year = str(row.year)
            year_counts[year] = row[1]
        
        result = await session.execute(
            select(Photo.file_path)
            .where(Photo.date_taken.is_(None))
        )
        
        for row in result:
            path = row[0]
            parts = path.split("/")
            for part in parts:
                if part and part[:4].isdigit():
                    year = part[:4]
                    year_counts[year] = year_counts.get(year, 0) + 1
                    break
        
        return year_counts


class TestConsistency:
    """Test suite for DB/filesystem consistency."""
    
    def test_years_match(self):
        """Verify all year folders on disk have entries in the DB."""
        disk_years = set(count_photos_on_disk().keys())
        db_years = set(asyncio.run(count_photos_in_db()).keys())
        
        disk_counts = count_photos_on_disk()
        missing_and_populated = {y for y in disk_years - db_years if disk_counts.get(y, 0) > 0}
        
        assert len(missing_and_populated) == 0, (
            f"Years with photos on disk but not in DB: {missing_and_populated}"
        )
    
    def test_photo_count_matches(self):
        """Verify total photo count roughly matches disk."""
        disk_counts = count_photos_on_disk()
        disk_total = sum(disk_counts.values())
        
        db_counts = asyncio.run(count_photos_in_db())
        db_total = sum(db_counts.values())
        
        diff = abs(disk_total - db_total)
        tolerance = max(50, disk_total * 0.05)
        
        assert diff <= tolerance, (
            f"Photo count mismatch: disk={disk_total}, db={db_total}, diff={diff}"
        )


if __name__ == "__main__":
    import datetime
    print("=== Filesystem vs Database Consistency Check ===\n")
    
    disk = count_photos_on_disk()
    db = asyncio.run(count_photos_in_db())
    
    disk_years = set(disk.keys())
    db_years = set(db.keys())
    
    print(f"Years on disk: {sorted(disk_years)}")
    print(f"Years in DB:   {sorted(db_years)}")
    print()
    
    missing = disk_years - db_years
    populated_missing = {y for y in missing if disk.get(y, 0) > 0}
    if populated_missing:
        print(f"⚠️  Years with photos MISSING from DB: {sorted(populated_missing)}")
    
    extra = db_years - disk_years
    if extra:
        print(f"Years in DB but not on disk: {sorted(extra)}")
    print()
    
    print("Photo counts by year:")
    print(f"{'Year':<6} {'Disk':>8} {'DB':>8} {'Diff':>8}")
    print("-" * 32)
    
    all_years = sorted(disk_years | db_years, key=int)
    for year in all_years:
        d = disk.get(year, 0)
        b = db.get(year, 0)
        diff = d - b
        marker = " ⚠️" if abs(diff) > 100 else ""
        print(f"{year:<6} {d:>8} {b:>8} {diff:>+8}{marker}")
    
    disk_total = sum(disk.values())
    db_total = sum(db.values())
    print("-" * 32)
    print(f"{'Total':<6} {disk_total:>8} {db_total:>8} {disk_total - db_total:>+8}")
    
    print(f"\nNewest year in DB: {max(db_years) if db_years else 'N/A'}")
    print(f"Current year: {datetime.datetime.now().year}")