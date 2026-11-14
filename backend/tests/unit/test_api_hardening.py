"""Input handling of the HTTP layer: paths, ids, bodies, caching, imports."""

import asyncio
import base64
import random
import sys
from pathlib import Path

import httpx
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))

from api_fixtures import h, run_with_client  # noqa: E402

from backend.app.api import limits  # noqa: E402
from backend.app.api.files import contained_path  # noqa: E402
from backend.app.api.persons import MAX_GROUP_SIZE, _parse_person_ids  # noqa: E402
from backend.app.api.responses import CollageCache, collage_key  # noqa: E402
from backend.app.services import collage, user_data  # noqa: E402

# --- paths and ids --------------------------------------------------------


def test_contained_path_stays_inside(tmp_path):
    assert contained_path(tmp_path, "2020/a.jpg") == tmp_path / "2020" / "a.jpg"
    assert contained_path(tmp_path, "2020/../2021/a.jpg") == tmp_path / "2021" / "a.jpg"
    assert contained_path(tmp_path, "../etc/passwd") is None
    assert contained_path(tmp_path, "a/../../x") is None
    assert contained_path(tmp_path, "/etc/passwd") is None
    assert contained_path(tmp_path, "") is None
    assert contained_path(tmp_path, ".") is None
    assert contained_path(tmp_path, "a\x00b") is None


def test_parse_person_ids():
    assert _parse_person_ids("1, 2,x,3") == [1, 2, 3]
    with pytest.raises(Exception) as exc:
        _parse_person_ids("1")
    assert exc.value.status_code == 400
    with pytest.raises(Exception) as exc:
        _parse_person_ids(",".join(str(i) for i in range(MAX_GROUP_SIZE + 1)))
    assert exc.value.status_code == 400
    # Non-ASCII digits and numbers too large for SQLite are not ids.
    assert _parse_person_ids("1,2,٣,9" + "9" * 30) == [1, 2]


def test_hostile_requests_get_client_errors():
    async def body(client):
        return {
            "bad_hash": (await client.get("/api/photos/..%2e/preview")).status_code,
            "short_hash": (await client.get("/api/photos/abc/thumbnail/600")).json(),
            "huge_id": (await client.get("/api/persons/99999999999999999999")).status_code,
            "huge_page": (await client.get("/api/photos", params={"page": 10**20})).status_code,
            "many_ids": (
                await client.post("/api/persons/groups/hide", json={"person_ids": list(range(51))})
            ).status_code,
        }

    result = run_with_client(body)
    assert result["bad_hash"] == 404
    assert result["short_hash"] == {"detail": "Thumbnail not found"}
    assert result["huge_id"] == 422
    assert result["huge_page"] == 422
    assert result["many_ids"] == 422


def test_unknown_photo_still_404_with_same_detail():
    async def body(client):
        missing = h(999)
        return [
            (await client.get(f"/api/photos/{missing}")).json(),
            (await client.get(f"/api/photos/{missing}/original")).json(),
            (await client.get(f"/api/photos/{missing}/live")).json(),
            (await client.post(f"/api/photos/{missing}/favorite")).json(),
        ]

    assert run_with_client(body) == [
        {"detail": "Photo not found"},
        {"detail": "Photo not found"},
        {"detail": "Live photo video not found"},
        {"detail": "Photo not found"},
    ]


# --- body size limit ------------------------------------------------------


async def _echo_app(scope, receive, send):
    body = b""
    while True:
        message = await receive()
        body += message.get("body", b"")
        if not message.get("more_body"):
            break
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": str(len(body)).encode()})


def _post(path: str, content, headers=None) -> httpx.Response:
    app = limits.BodySizeLimitMiddleware(_echo_app)

    async def main():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            return await client.post(path, content=content, headers=headers)

    return asyncio.run(main())


def test_body_limit_by_content_length(monkeypatch):
    monkeypatch.setattr(limits, "DEFAULT_MAX_BODY", 10)
    assert _post("/api/x", b"x" * 10).text == "10"
    response = _post("/api/x", b"x" * 11)
    assert response.status_code == 413
    assert response.json() == {"detail": "Request body too large"}


def test_body_limit_per_path(monkeypatch):
    monkeypatch.setattr(limits, "DEFAULT_MAX_BODY", 10)
    monkeypatch.setattr(limits, "BODY_LIMITS", {"/api/user-data/import": 100})
    assert _post("/api/user-data/import", b"x" * 50).text == "50"
    assert _post("/api/user-data/import", b"x" * 101).status_code == 413


def test_body_limit_streamed(monkeypatch):
    monkeypatch.setattr(limits, "DEFAULT_MAX_BODY", 10)

    async def chunks():
        for _ in range(5):
            yield b"xxxx"

    assert _post("/api/x", chunks()).status_code == 413


# --- collage --------------------------------------------------------------


def test_vectorised_pick_matches_reference():
    rng = random.Random(3)
    for trial in range(40):
        n = rng.randint(2, 300)
        phs = []
        for _ in range(n):
            roll = rng.random()
            if roll < 0.15:
                phs.append(None)
            elif roll < 0.4:
                phs.append(rng.getrandbits(4))  # clusters of near-duplicates
            else:
                phs.append(rng.getrandbits(64))
        start = rng.randrange(n)
        needed = rng.choice([4, 9, 16, 36, n])
        assert collage._greedy_farthest_numpy(phs, start, needed) == collage._greedy_farthest(
            phs, start, needed
        ), trial


def test_select_diverse_falls_back_for_odd_phashes():
    hashes = [f"h{i}" for i in range(10)]
    phashes = ["-1f", "ff", None, "0", "1" * 20] + ["%016x" % (i * 977) for i in range(5)]
    picked = collage._select_diverse(hashes, phashes, 4, random.Random(0))
    assert len(picked) == len(set(picked)) <= 4


def test_collage_cache_is_bounded_lru():
    cache = CollageCache(max_bytes=10)
    cache.put("a", b"1234")
    cache.put("b", b"1234")
    assert cache.get("a") == b"1234"  # a is now most recent
    cache.put("c", b"1234")  # over budget: b goes
    assert cache.get("b") is None
    assert cache.get("a") == b"1234" and cache.get("c") == b"1234"
    cache.put("big", b"x" * 11)
    assert cache.get("big") is None


def test_collage_key_depends_on_everything_drawn():
    rows = [("h1", "ab"), ("h2", None)]
    key = collage_key(rows, 2, 0)
    assert key == collage_key(list(rows), 2, 0)
    assert key != collage_key(rows, 3, 0)
    assert key != collage_key(rows, 2, 1)
    assert key != collage_key(list(reversed(rows)), 2, 0)
    assert key != collage_key([("h1", "ab"), ("h2", "cd")], 2, 0)


# --- user data import -----------------------------------------------------


def _b64(vec: np.ndarray) -> str:
    return base64.b64encode(vec.astype("<f4").tobytes()).decode()


def _faces(vectors_by_person: dict[int, list[np.ndarray]]):
    import pickle

    faces, face_id = [], 0
    for pid, vecs in vectors_by_person.items():
        for v in vecs:
            face_id += 1
            faces.append((face_id, pid, pickle.dumps(v.astype(np.float32))))
    return faces


def _vec(seed: int) -> np.ndarray:
    return np.random.default_rng(seed).standard_normal(user_data.ENCODING_DIM)


def test_match_persons_ignores_malformed_entries():
    a, b = _vec(1), _vec(2)
    faces = _faces({10: [a, a + 0.01, a - 0.01], 20: [b, b + 0.01]})
    exported = [
        "not a dict",
        {"name": 123, "encodings": [_b64(a), _b64(a + 0.02)]},  # bad name type
        {"name": "Eva", "ignored": "yes", "encodings": [_b64(b), _b64(b + 0.02)]},
        {"name": "Nobody", "encodings": "not a list"},
        {"name": "Garbage", "encodings": [42, "%%%", _b64(np.zeros(3))]},
    ]
    assert user_data._match_persons(exported, faces) == {
        10: {"name": None, "ignored": False},
        20: {"name": "Eva", "ignored": True},
    }


def test_votes_identical_when_blocked(monkeypatch):
    rng = np.random.default_rng(7)
    current = rng.standard_normal((50, user_data.ENCODING_DIM)).astype(np.float32)
    current /= np.linalg.norm(current, axis=1, keepdims=True)
    ids = [i % 5 for i in range(50)]
    exported = [current[i] + rng.standard_normal(user_data.ENCODING_DIM) * 0.05 for i in range(30)]

    whole = user_data._vote_person_ids(exported, current, ids)
    monkeypatch.setattr(user_data, "_SIMILARITY_BLOCK_CELLS", 100)  # two rows per block
    blocked = user_data._vote_person_ids(exported, current, ids)
    assert whole == blocked
    assert list(whole.items()) == list(blocked.items())  # same vote order too


def test_hidden_groups_tolerate_malformed_members():
    a, b = _vec(1), _vec(2)
    faces = _faces({10: [a, a + 0.01], 20: [b, b + 0.01]})
    good = {"members": [{"encodings": [_b64(a)]}, {"encodings": [_b64(b)]}]}
    bad = [{"members": 5}, {"members": [1, 2]}, "x", {"members": [{"encodings": 3}, {}]}]
    restored, unresolved = user_data._match_hidden_groups([good, *bad], faces)
    assert restored == ["10,20"]
    assert unresolved == bad


def test_import_rejects_shapes_without_500():
    async def body(client):
        files = {"file": ("x.json", b'{"version": 2, "favorites": "abc", "persons": {"a": 1}}')}
        typed = (await client.post("/api/user-data/import", files=files)).json()
        deep = b'{"version": 2, "persons": ' + b"[" * 100000 + b"]" * 100000 + b"}"
        nested = (await client.post("/api/user-data/import", files={"file": ("d.json", deep)}))
        favs = {"file": ("f.json", f'{{"version": 2, "favorites": ["{h(1)}", "{h(1)}", 7]}}')}
        restored = (await client.post("/api/user-data/import", files=favs)).json()
        return typed, nested.json(), restored

    typed, nested, restored = run_with_client(body)
    assert typed["status"] == "ok" and typed["favorites_restored"] == 0
    assert nested["status"] == "error"
    assert restored["status"] == "ok" and restored["favorites_restored"] == 1
