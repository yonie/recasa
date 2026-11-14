"""Directory browsing API endpoints."""

from collections import Counter
from collections.abc import Iterable

from fastapi import APIRouter
from sqlalchemy import select

from backend.app.api.deps import Page, PageSize, SessionDep
from backend.app.models import Photo
from backend.app.queries.photos import NEWEST_FIRST, VISIBLE, photo_page, summary_select
from backend.app.schemas.photo import DirectoryNode, PhotoPage

router = APIRouter(prefix="/api/directories", tags=["directories"])


def build_directory_tree(file_paths: Iterable[str]) -> list[DirectoryNode]:
    """Directory tree with recursive photo counts, children sorted by name.

    Files at the root have no directory and are not counted. A directory whose
    name starts with "_" is left out together with everything below it, as it
    always has been.
    """
    # Count per directory first: a library has a few thousand folders but
    # tens of thousands of files, so the tree is built from far fewer keys.
    per_dir: Counter[str] = Counter()
    for file_path in file_paths:
        head, sep, _ = file_path.replace("\\", "/").rpartition("/")
        if sep:
            per_dir[head] += 1

    tree: dict[str, dict] = {}
    for directory, count in per_dir.items():
        children = tree
        for part in directory.split("/"):
            node = children.get(part)
            if node is None:
                node = children[part] = {"count": 0, "children": {}}
            node["count"] += count
            children = node["children"]

    def build(children: dict[str, dict], parent_path: str) -> list[DirectoryNode]:
        nodes = []
        for name, data in sorted(children.items()):
            if name.startswith("_"):
                continue
            path = f"{parent_path}/{name}" if parent_path else name
            nodes.append(
                DirectoryNode(
                    name=name,
                    path=path,
                    photo_count=data["count"],
                    children=build(data["children"], path),
                )
            )
        return nodes

    return build(tree, "")


@router.get("", response_model=list[DirectoryNode])
async def get_directory_tree(session: SessionDep):
    """Get the full directory tree structure with photo counts."""
    paths = await session.execute(select(Photo.file_path).where(VISIBLE))
    return build_directory_tree(paths.scalars())


@router.get("/{path:path}", response_model=PhotoPage)
async def get_directory_photos(
    path: str,
    session: SessionDep,
    page: Page = 1,
    page_size: PageSize = 50,
):
    """Get photos in a specific directory."""
    # Normalize path separators
    path = path.replace("\\", "/")

    # Everything under this directory, subdirectories included. LIKE is used
    # as it always was here, so "_" and "%" in a name act as wildcards and
    # ASCII case is ignored.
    stmt = summary_select().where(Photo.file_path.like(f"{path}/%"), VISIBLE)
    return await photo_page(
        session, stmt, order_by=NEWEST_FIRST, page=page, page_size=page_size
    )
