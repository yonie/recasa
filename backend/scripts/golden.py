#!/usr/bin/env python3
"""API golden snapshots: prove a change leaves every API response identical.

Stdlib only, so it runs on the host as well as in the container. See
docs/TESTING.md, "Comparing two versions on a copy of the real index".

  golden.py discover BASE urls.txt      # build a fixed URL list from live ids
  golden.py capture  BASE urls.txt OUT  # fetch every URL, store normalized result
  golden.py diff     A B                # compare two captures
"""
import hashlib
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def get(base, path, timeout=120):
    req = urllib.request.Request(base + path)
    t = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.headers.get("content-type", ""), r.read(), time.monotonic() - t
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("content-type", ""), e.read(), time.monotonic() - t


def getj(base, path):
    s, ct, body, _ = get(base, path)
    return json.loads(body) if s == 200 else None


def q(**kw):
    return "?" + urllib.parse.urlencode({k: v for k, v in kw.items() if v is not None})


def items(x):
    if isinstance(x, dict):
        for k in ("items", "persons", "events", "groups", "tags", "results"):
            if isinstance(x.get(k), list):
                return x[k]
    return x if isinstance(x, list) else []


def discover(base, out):
    urls = []
    add = urls.append
    for p in ["/api/photos/stats", "/api/timeline/years", "/api/directories", "/api/duplicates",
              "/api/duplicates" + q(page=2), "/api/large-files", "/api/large-files" + q(min_size=50_000_000),
              "/api/locations/countries", "/api/locations/cities", "/api/locations/map-points",
              "/api/locations/trail", "/api/persons", "/api/persons" + q(page=2, page_size=20),
              "/api/persons/ignored", "/api/persons/groups/hidden", "/api/persons/groups/together",
              "/api/persons/groups/together" + q(min_photos=10, page_size=50), "/api/events",
              "/api/events" + q(page=2), "/api/tags", "/api/tags" + q(limit=20), "/api/tags" + q(q="beach"),
              "/api/tags" + q(q="dog"), "/api/pipeline/failures", "/api/pipeline/processing-stats",
              "/api/config/status", "/api/photos/collage" + q(favorite="true", grid=2, seed=1)]:
        add(p)

    # Photo listing: every filter, sort and order.
    for sort in ["date_taken", "file_name", "file_size", "indexed_at"]:
        for order in ["asc", "desc"]:
            add("/api/photos" + q(sort=sort, order=order, page_size=100))
    add("/api/photos" + q(page=3, page_size=50))
    add("/api/photos" + q(page=200, page_size=200))
    for f in ["favorite", "marked_for_print", "flagged", "video"]:
        for v in ["true", "false"]:
            add("/api/photos" + q(**{f: v}, page_size=100))
    add("/api/photos" + q(favorite="true", video="false", sort="file_name", order="asc"))
    for a, b in [("2019-01-01", "2019-12-31"), ("2024-06-01", "2024-06-30"), ("2000-01-01", None), (None, "2010-01-01")]:
        add("/api/photos" + q(date_from=a, date_to=b, page_size=100))

    years = [y.get("year") if isinstance(y, dict) else y for y in items(getj(base, "/api/timeline/years") or [])]
    years = [y for y in years if y]
    for y in years[:3] + years[-3:]:
        add("/api/timeline" + q(year=y))
        add("/api/timeline" + q(year=y, group_by="day"))
        add("/api/timeline" + q(year=y, month=6, group_by="day"))
        add("/api/photos/collage" + q(year=y, grid=3, seed=7))
    for g in ["year", "month", "day"]:
        add("/api/timeline" + q(group_by=g))
        add("/api/timeline" + q(group_by=g, offset=10, limit=20))
    add("/api/timeline" + q(video="true"))

    countries = items(getj(base, "/api/locations/countries") or [])
    for c in countries[:4]:
        name = c.get("country") if isinstance(c, dict) else c
        add("/api/locations/cities" + q(country=name))
        add("/api/locations/photos" + q(country=name))
        add("/api/photos" + q(country=name, page_size=100))
        cities = items(getj(base, "/api/locations/cities" + q(country=name)) or [])
        for ci in cities[:2]:
            cn = ci.get("city") if isinstance(ci, dict) else ci
            add("/api/locations/photos" + q(country=name, city=cn))
            add("/api/photos" + q(country=name, city=cn))
    add("/api/locations/trail" + q(date_from="2023-01-01", date_to="2023-12-31"))

    persons = items(getj(base, "/api/persons" + q(page_size=50)) or [])
    pids = [p["person_id"] for p in persons if isinstance(p, dict) and "person_id" in p]
    names = [p.get("name") for p in persons if isinstance(p, dict) and p.get("name")]
    for pid in pids[:6]:
        add(f"/api/persons/{pid}")
        add(f"/api/persons/{pid}/photos")
        add(f"/api/persons/{pid}/photos" + q(page=2))
        add(f"/api/persons/{pid}/thumbnail")
        add(f"/api/persons/{pid}/collage" + q(grid=2, seed=3))
    if len(pids) >= 2:
        a, b = pids[0], pids[1]
        add(f"/api/persons/groups/together/{a}/{b}/photos")
        add(f"/api/persons/groups/together/{a}/{b}/collage" + q(grid=2, seed=3))
        add("/api/persons/groups/together-n/photos" + q(person_ids=f"{a},{b}"))
        add("/api/persons/groups/together-n/collage" + q(person_ids=f"{a},{b}", grid=2, seed=3))
    if len(pids) >= 3:
        add("/api/persons/groups/together-n/photos" + q(person_ids=",".join(map(str, pids[:3]))))

    events = items(getj(base, "/api/events" + q(page_size=50)) or [])
    for e in events[:5]:
        eid = e.get("event_id")
        add(f"/api/events/{eid}")
        add(f"/api/events/{eid}/photos")
        add(f"/api/events/{eid}/collage" + q(grid=2, seed=5))

    tags = items(getj(base, "/api/tags" + q(limit=30)) or [])
    tag_names = []
    for t in tags[:6]:
        tid = t.get("tag_id")
        tag_names.append(t.get("name"))
        add(f"/api/tags/{tid}")
        add(f"/api/tags/{tid}/photos")
        add(f"/api/tags/{tid}/photos" + q(page=2))
    for tn in tag_names[:3]:
        add("/api/photos/collage" + q(tag=tn, grid=2, seed=9))

    dirs = items(getj(base, "/api/directories") or [])
    def walk(nodes, depth=0):
        for n in nodes[:3]:
            path = n.get("path") if isinstance(n, dict) else None
            if path:
                add("/api/directories/" + urllib.parse.quote(path))
                add("/api/directories/" + urllib.parse.quote(path) + q(page=2, page_size=20))
            if depth < 2 and isinstance(n, dict):
                walk(n.get("children") or [], depth + 1)
    walk(dirs)

    searches = ["beach", "dog", "snow", "birthday", "2019", "may 2020", "december", "summer 2021",
                "amsterdam", "netherlands", "IMG_", "jpg", "zzzznothing"] + tag_names[:3] + names[:3]
    for s in searches:
        add("/api/photos" + q(search=s, page_size=100))
    add("/api/photos" + q(search="beach", favorite="true"))
    add("/api/photos" + q(search="2019", sort="file_name", order="asc"))

    # Sample photos: detail, thumbs, preview, live, original.
    sample = items(getj(base, "/api/photos" + q(page_size=200, sort="file_name", order="asc")) or [])
    sample += items(getj(base, "/api/photos" + q(video="true", page_size=5)) or [])
    for p in sample[::25][:12]:
        h = p["file_hash"]
        add(f"/api/photos/{h}")
        for size in (200, 600, 1200):
            add(f"/api/photos/{h}/thumbnail/{size}")
    add("/api/photos/" + "0" * 64)
    add("/api/persons/999999")
    add("/api/events/999999")
    add("/api/tags/999999")

    seen, uniq = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    Path(out).write_text("\n".join(uniq) + "\n")
    print(f"{len(uniq)} urls -> {out}")


def norm(body, ct):
    if "json" in ct:
        try:
            return json.dumps(json.loads(body), sort_keys=True, indent=1, ensure_ascii=False)
        except ValueError:
            pass
    return f"<{ct} {len(body)} bytes sha256={hashlib.sha256(body).hexdigest()}>"


def capture(base, urls_file, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    timings = {}
    urls = [u for u in Path(urls_file).read_text().splitlines() if u]
    for i, u in enumerate(urls):
        s, ct, body, dt = get(base, u)
        name = f"{i:04d}"
        (out / f"{name}.txt").write_text(f"{u}\nstatus={s}\n{norm(body, ct)}\n")
        timings[u] = round(dt, 3)
    (out / "timings.json").write_text(json.dumps(timings, indent=1))
    slow = sorted(timings.items(), key=lambda kv: -kv[1])[:10]
    print(f"captured {len(urls)} -> {out}; total {sum(timings.values()):.1f}s; slowest:")
    for u, t in slow:
        print(f"  {t:7.2f}s {u}")


def diff(a, b):
    a, b = Path(a), Path(b)
    bad = 0
    for fa in sorted(a.glob("*.txt")):
        fb = b / fa.name
        ta = fa.read_text()
        tb = fb.read_text() if fb.exists() else "<missing>"
        if ta != tb:
            bad += 1
            print("DIFF", ta.splitlines()[0])
            import difflib
            for line in list(difflib.unified_diff(ta.splitlines(), tb.splitlines(), lineterm="", n=1))[2:30]:
                print("   ", line[:200])
    ta = json.loads((a / "timings.json").read_text())
    tb = json.loads((b / "timings.json").read_text())
    print(f"{bad} differing responses; total time {sum(ta.values()):.1f}s -> {sum(tb.values()):.1f}s")
    worse = sorted(((tb[u] - ta[u], u) for u in ta if u in tb), reverse=True)[:8]
    for d, u in worse:
        print(f"  slower {d:+.2f}s ({ta[u]:.2f} -> {tb[u]:.2f}) {u}")
    return bad


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "discover":
        discover(sys.argv[2], sys.argv[3])
    elif cmd == "capture":
        capture(sys.argv[2], sys.argv[3], sys.argv[4])
    elif cmd == "diff":
        sys.exit(1 if diff(sys.argv[2], sys.argv[3]) else 0)
