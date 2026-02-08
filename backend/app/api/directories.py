"""Directory browsing API endpoints."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_session
from backend.app.models import Photo
from backend.app.schemas.photo import DirectoryNode, PhotoPage, PhotoSummary

router = APIRouter(prefix="/api/directories", tags=["directories"])


def _photo_to_summary(photo: Photo) -> PhotoSummary:
    return PhotoSummary(
        file_hash=photo.file_hash,
        file_path=photo.file_path,
        file_name=photo.file_name,
        file_size=photo.file_size,
        mime_type=photo.mime_type,
        width=photo.width,
        height=photo.height,
        date_taken=photo.date_taken,
        is_favorite=photo.is_favorite,
        thumbnail_url=f"/api/photos/{photo.file_hash}/thumbnail/600",
        has_live_photo=bool(photo.live_photo_video or photo.motion_photo),
    )


@router.get("", response_model=list[DirectoryNode])
async def get_directory_tree(session: AsyncSession = Depends(get_session)):
    """Get the full directory tree structure with photo counts."""
    result = await session.execute(select(Photo.file_path))
    paths = result.scalars().all()

    # Build tree structure
    root_children: dict[str, dict] = {}

    for file_path in paths:
        parts = file_path.replace("\\", "/").split("/")
        # Navigate/create directory nodes (all parts except filename)
        current = root_children
        for part in parts[:-1]:
            if part not in current:
                current[part] = {"_count": 0, "_children": {}}
            current[part]["_count"] += 1
            current = current[part]["_children"]

    def build_nodes(children: dict, parent_path: str = "") -> list[DirectoryNode]:
        nodes = []
        for name, data in sorted(children.items()):
            if name.startswith("_"):
                continue
            path = f"{parent_path}/{name}" if parent_path else name
            nodes.append(
                DirectoryNode(
                    name=name,
                    path=path,
                    photo_count=data["_count"],
                    children=build_nodes(data["_children"], path),
                )
            )
        return nodes

    return build_nodes(root_children)


@router.get("/{path:path}", response_model=PhotoPage)
async def get_directory_photos(
    path: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    """Get photos in a specific directory."""
    # Normalize path separators
    path = path.replace("\\", "/")

    # Match photos in this directory (not subdirectories for direct listing)
    query = select(Photo).where(
        Photo.file_path.like(f"{path}/%"),
    )

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = (await session.execute(count_query)).scalar() or 0

    # Paginate
    offset = (page - 1) * page_size
    query = query.order_by(Photo.date_taken.desc().nullslast()).offset(offset).limit(page_size)

    result = await session.execute(query)
    photos = result.scalars().all()

    return PhotoPage(
        items=[_photo_to_summary(p) for p in photos],
        total=total,
        page=page,
        page_size=page_size,
        has_more=offset + page_size < total,
    )
