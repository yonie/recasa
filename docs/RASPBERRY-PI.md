# Running Recasa on a Raspberry Pi 5

A Pi is a good host for Recasa once the library is indexed: it is always on, it
draws a few watts, and serving photos is cheap. The expensive work (face
detection, captioning, thumbnailing) is one-time, and an existing index can be
carried over rather than rebuilt.

Everything below was measured on a Pi 5 (4 cores, 16 GB RAM, USB SSD), not
inferred.

## It runs on aarch64

The image builds natively on arm64 in about six minutes and lands at ~1.6 GB.
Only `insightface` and `reverse-geocoder` compile from source, and `insightface`
takes about 16 seconds; everything else in the ML stack (`onnxruntime`,
`rawpy`, `opencv-python-headless`, `scikit-learn`, `scipy`, `av`, `pillow-heif`
) ships prebuilt `manylinux_2_17_aarch64` wheels.

A 71-photo library covering JPEG, PNG, WebP, HEIC, Olympus ORF and MP4
processed end to end in 61 seconds with face detection on, and the API stayed
between 2.6 ms and 12.9 ms throughout. Serving was verified by decoding what the
endpoints actually return, not just checking for HTTP 200: ORF renders to a
full-resolution JPEG preview, HEIC decodes, and MP4 gets a thumbnail extracted
through PyAV.

## Before you start

### Enable memory cgroup accounting

Raspberry Pi OS ships with `cgroup_disable=memory` on the kernel command line.
Docker discards `--memory` and `deploy.resources.limits` when that is set, with
only a warning at container start, so a memory limit you write is not a limit
you have. Recasa holds whole images in memory while thumbnailing, so on a box
that also runs other services this matters.

Check:

```bash
cat /proc/cmdline | tr ' ' '\n' | grep cgroup
```

If it says `cgroup_disable=memory`, edit `/boot/firmware/cmdline.txt` (it is a
single line: do not add a newline), remove that token, add
`cgroup_enable=memory cgroup_memory=1`, and reboot. Then put a memory limit back
in your compose file.

### Keep `/data` off the root disk

A Pi's root filesystem is usually small. Docker named volumes live under
`/var/lib/docker` on that root disk, and Recasa's `/data` (index, thumbnails,
previews, face models) starts in the gigabytes and grows with the library. Use
a bind mount onto whatever large disk holds the photos instead: point
`RECASA_DATA_PATH` in `.env` there.

### Tune concurrency down

Set `MAX_CONCURRENT=2` in `.env` rather than the default 4. Face detection is CPU-bound and the Pi has
four cores; leaving headroom is what keeps the API responsive while the pipeline
runs. On a box that serves as well as processes, responsiveness beats throughput.

## Never point Recasa at an incomplete library

This is the one that bites hardest. The scanner removes index entries for files
that are no longer on disk, and that cascades to faces, captions, favourites and
flags. If you start Recasa against a photo directory that is still being copied,
still syncing, or simply not mounted, a scan will treat the whole library as
deleted.

`_cleanup_removed_files` in `backend/app/services/scanner.py` refuses to proceed
when the library is *unavailable* rather than emptied: when `PHOTOS_DIR` is not
a readable directory, or when a sweep of it turned up no photos at all. There is
deliberately no cap on how many entries may be cleaned up at once, because
deleting a large folder is a normal thing to do and a threshold would leave the
index permanently unable to converge.

Those checks catch an unmounted disk. They do **not** catch a library that is
merely incomplete: a half-finished copy looks exactly like a partial deletion,
and nothing in the app can tell the difference. So the rule stands: **finish the
copy before you start the container.**

## Carrying an existing index across

The index is worth far more than it looks: it holds every face embedding,
every generated caption, and all your favourites and flags. Copy it rather than
rebuild it.

Recasa stores `file_path` relative to `PHOTOS_DIR`, and both hosts mount the
library at `/photos`, so no path rewriting is needed.

The database runs in WAL mode, so take the copy with the container **stopped**:
a clean shutdown checkpoints the WAL, and copying `/data` wholesale then gives a
consistent snapshot. Copying a live database will not.

```bash
# On the old host, with the container stopped:
docker run --rm -v <data-volume>:/data:ro alpine tar czf - -C /data . \
  | ssh <pi> 'mkdir -p /path/to/data && tar xzf - -C /path/to/data'
```

Then point `RECASA_DATA_PATH` at the copied directory, start the Pi with
`docker compose up -d`, and confirm the counts match
before retiring the old instance.

## Run only one instance

Favourites, flags, print marks and person names are written into the index.
Two instances against two copies of the library means two diverging sets of
them, with no merge path. Stop the old one at cutover.

## Networking

Check the link speed before blaming the app:

```bash
cat /sys/class/net/eth0/speed
sudo ethtool eth0 | grep -A3 'Link partner advertised'
```

A Pi 5 negotiates gigabit. If it reports 100, and the link partner advertises
only `10/100baseT`, the switch port is the limit rather than the cable. Full-size
previews are a few MB each, so a 100 Mb link caps you at roughly four full-screen
photos per second across all viewers.
