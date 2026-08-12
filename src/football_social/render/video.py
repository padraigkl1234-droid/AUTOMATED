"""Turn a static card into a short vertical video.

TikTok's video endpoint and Instagram Reels both want motion. A still image
held for six seconds technically uploads, but it is treated as low-effort by
both recommenders. A slow push-in plus a wipe on the accent bar costs one
ffmpeg call and reads as intentional.

No audio track is added. Music is the single biggest copyright exposure on
both platforms, and silent uploads let the creator add licensed audio from
the in-app library at review time -- which also performs better than an
embedded track.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from ..config import out_dir

log = logging.getLogger(__name__)

DURATION = 6          # seconds -- long enough to read, short enough to loop
FPS = 30
ZOOM_END = 1.08       # gentle push-in; more than this looks like a glitch


class FFmpegMissing(RuntimeError):
    pass


def available() -> bool:
    return shutil.which("ffmpeg") is not None


def from_card(image_path: Path, *, duration: int = DURATION) -> Path:
    """Render a 1080x1920 H.264 MP4 from a still card."""
    if not available():
        raise FFmpegMissing(
            "ffmpeg not found. Install it (apt install ffmpeg / brew install "
            "ffmpeg) -- TikTok has no still-image path in this pipeline."
        )

    out = out_dir() / f"{image_path.stem}.mp4"
    frames = duration * FPS

    # zoompan works on a scaled-up source so the push-in does not soften the
    # type. 'd' is frames per input image; we feed a single looped still.
    vf = (
        f"scale=2160:3840,"
        f"zoompan=z='min(zoom+{(ZOOM_END - 1) / frames:.6f},{ZOOM_END})'"
        f":d={frames}:s=1080x1920:fps={FPS},"
        f"format=yuv420p"
    )

    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-loop", "1", "-i", str(image_path),
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "20",
        "-movflags", "+faststart",   # required for streaming ingest
        str(out),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr.strip()[:500]}")

    log.info("encoded %s (%.1f MB)", out.name, out.stat().st_size / 1e6)
    return out
