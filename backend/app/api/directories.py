"""Directory browsing API endpoints."""

from collections import Counter
from collections.abc import Iterable

from fastapi import APIRouter
from sqlalchemy import ColumnElement, and_, select

from backend.app.api.deps import Page, PageSize, SessionDep
from backend.app.models import Photo
from backend.app.queries.photos import NEWEST_FIRST, VISIBLE, photo_page, summary_select
from backend.app.schemas.photo import DirectoryNode, PhotoPage
from backend.app.services.scanner import is_library_name

router = APIRouter(prefix="/api/directories", tags=["directories"])


def build_directory_tree(file_paths: Iterable[str]) -> list[DirectoryNode]:
    """Directory tree with recursive photo counts, children sorted by name.

    Files at the root have no directory and are not counted. A hidden
    directory (".stversions" and the like) is left out with everything below
    it, by the scanner's own rule: such paths are never indexed, and one still
    in an older index is on its way out. A name starting with "_" is an
    ordinary folder.
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
            if not is_library_name(name):
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


def under_directory(path: str) -> ColumnElement[bool]:
    """Photos anywhere below directory ``path``, subdirectories included.

    An exact, case-sensitive prefix match on ``path + "/"``, written as a
    range: every such string sorts from ``path/`` up to just before
    ``path0`` ("0" being the character after "/"). LIKE treated "_" and "%"
    in a folder name as wildcards and ignored ASCII case, so 2026_09 also
    listed 2026-09; a range is also one an index on file_path could serve.
    """
    return and_(Photo.file_path >= f"{path}/", Photo.file_path < f"{path}0")


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

    stmt = summary_select().where(under_directory(path), VISIBLE)
    return await photo_page(
        session, stmt, order_by=NEWEST_FIRST, page=page, page_size=page_size
    )
