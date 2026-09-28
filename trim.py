"""ffprobe + ffmpeg helpers for splitting a video into sequential N-second clips.

Everything runs locally through the ffmpeg/ffprobe binaries on PATH.
Paths are always passed as argv items (never through a shell), so spaces and
other odd characters in filenames are safe.
"""

from __future__ import annotations

import csv
import math
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

VIDEO_EXTS = ("mp4", "mov", "mkv", "webm", "avi")
MIN_SECONDS = 1
MAX_SECONDS = 300
DEFAULT_SECONDS = 14

# A leftover shorter than this is container/rounding noise (e.g. a 168.02s
# file cut at 14s), not a real clip, so it is never exported on its own.
TAIL_EPSILON = 0.05
# Stream-copied clip whose duration is further than this from the plan is
# treated as a failed copy and re-encoded instead.
COPY_TOLERANCE = 0.15

INSTALL_HELP = {
    "Windows": "winget install ffmpeg",
    "macOS": "brew install ffmpeg",
    "Linux": "sudo apt install ffmpeg",
}
INSTALL_URL = "https://ffmpeg.org/download.html"


class TrimError(Exception):
    """A source file could not be probed or cut."""


@dataclass
class Segment:
    index: int  # 1-based
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class ClipResult:
    segment: Segment
    path: Path
    method: str  # "copy" or "reencode"


def missing_tools() -> list[str]:
    """Names of required binaries that are not on PATH."""
    return [tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None]


def probe_duration(path: str | os.PathLike) -> float:
    """Container duration in seconds, from ffprobe (not frame count, so VFR is fine)."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    out = proc.stdout.strip()
    if proc.returncode != 0 or not out or out == "N/A":
        detail = proc.stderr.strip() or "no duration reported"
        raise TrimError(f"ffprobe could not read {Path(path).name}: {detail}")
    try:
        duration = float(out.splitlines()[0])
    except ValueError as exc:
        raise TrimError(f"ffprobe returned an invalid duration for {Path(path).name}: {out!r}") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise TrimError(f"{Path(path).name} has no usable duration ({duration})")
    return duration


def probe_video_codec(path: str | os.PathLike) -> str:
    """Codec name of the first video stream (e.g. "h264", "hevc"), or "" if unknown."""
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=codec_name",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.stdout.strip().splitlines()[0] if proc.returncode == 0 and proc.stdout.strip() else ""


def plan_segments(duration: float, seconds: float, remainder: str = "keep") -> list[Segment]:
    """Split [0, duration) into sequential chunks of `seconds`.

    remainder="keep": the last clip may be shorter (count = ceil(duration / N)).
    remainder="drop": a leftover shorter than N is discarded (count = floor(duration / N)).
    A video shorter than N always yields one clip containing the whole video.
    """
    if seconds <= 0:
        raise ValueError("clip length must be positive")
    if remainder not in ("keep", "drop"):
        raise ValueError(f"unknown remainder mode: {remainder}")

    full = int((duration + TAIL_EPSILON) // seconds)
    leftover = duration - full * seconds
    count = full + 1 if remainder == "keep" and leftover > TAIL_EPSILON else full
    if count == 0:
        count = 1  # duration < N: export the whole video

    segments = []
    for i in range(count):
        start = i * seconds
        end = min((i + 1) * seconds, duration)
        segments.append(Segment(i + 1, start, end))
    return segments


def output_names(stem: str, count: int, out_dir: Path, overwrite: bool) -> list[Path]:
    """`{stem}_{index:02d}.mp4` paths; if not overwriting and any exist, add `_v2`, `_v3`, ..."""
    width = max(2, len(str(count)))

    def names(suffix: str) -> list[Path]:
        return [out_dir / f"{stem}_{i:0{width}d}{suffix}.mp4" for i in range(1, count + 1)]

    paths = names("")
    if overwrite:
        return paths
    version = 2
    while any(p.exists() for p in paths):
        paths = names(f"_v{version}")
        version += 1
    return paths


def existing_outputs(stem: str, count: int, out_dir: Path) -> list[Path]:
    """Planned output files that already exist (used to ask before overwriting)."""
    return [p for p in output_names(stem, count, out_dir, overwrite=True) if p.exists()]


def _ffmpeg(args: list[str]) -> subprocess.CompletedProcess:
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y", *args]
    return subprocess.run(cmd, capture_output=True, text=True)


def _stream_args(src: str, start: float, length: float) -> list[str]:
    # First video stream plus any audio; "?" keeps silent videos working.
    # Subtitle/data tracks are dropped because many can't live in .mp4.
    return [
        "-ss", f"{start:.3f}", "-i", src, "-t", f"{length:.3f}",
        "-map", "0:v:0", "-map", "0:a?", "-sn", "-dn",
    ]


def _usable(path: Path, expected: float) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        actual = probe_duration(path)
    except TrimError:
        return False
    return abs(actual - expected) <= COPY_TOLERANCE


def cut_clip(src: str | os.PathLike, start: float, length: float, dst: Path, codec: str = "") -> str:
    """Write one clip. Tries lossless stream copy first, re-encodes if that fails.

    `codec` is the source's video codec; HEVC (iPhone footage) gets the `hvc1`
    tag, without which Apple devices refuse to play the copied .mp4.
    Returns "copy" or "reencode". Raises TrimError if both fail.
    """
    src = str(src)
    tag = ["-tag:v", "hvc1"] if codec == "hevc" else []
    copy = _ffmpeg([
        *_stream_args(src, start, length),
        "-c", "copy", *tag, "-avoid_negative_ts", "make_zero",
        str(dst),
    ])
    if copy.returncode == 0 and _usable(dst, length):
        return "copy"

    encode = _ffmpeg([
        *_stream_args(src, start, length),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-c:a", "aac", "-movflags", "+faststart",
        str(dst),
    ])
    if encode.returncode == 0 and dst.exists() and dst.stat().st_size > 0:
        return "reencode"

    dst.unlink(missing_ok=True)
    detail = (encode.stderr or copy.stderr).strip().splitlines()
    raise TrimError(f"ffmpeg failed on {dst.name}: {detail[-1] if detail else 'unknown error'}")


def write_manifest(path: Path, results: list[ClipResult]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["index", "filename", "start_sec", "end_sec", "duration_sec"])
        for r in results:
            s = r.segment
            writer.writerow([s.index, r.path.name, f"{s.start:.2f}", f"{s.end:.2f}", f"{s.duration:.2f}"])


def split_video(
    src: str | os.PathLike,
    out_dir: str | os.PathLike,
    seconds: float = DEFAULT_SECONDS,
    remainder: str = "keep",
    overwrite: bool = False,
    manifest: bool = False,
    stem: Optional[str] = None,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> list[ClipResult]:
    """Split one video into sequential clips in `out_dir`.

    `stem` overrides the output name prefix (useful when `src` is a temp copy
    of an uploaded file). `on_progress(done, total)` is called after each clip.
    """
    src = Path(src)
    stem = stem or src.stem
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    segments = plan_segments(probe_duration(src), seconds, remainder)
    codec = probe_video_codec(src)
    paths = output_names(stem, len(segments), out, overwrite)

    results = []
    for seg, dst in zip(segments, paths):
        method = cut_clip(src, seg.start, seg.duration, dst, codec)
        results.append(ClipResult(seg, dst, method))
        if on_progress:
            on_progress(seg.index, len(segments))

    if manifest:
        write_manifest(out / f"{stem}_manifest.csv", results)
    return results


def open_folder(path: str | os.PathLike) -> None:
    """Open a folder in the OS file browser."""
    path = str(path)
    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def _main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Split videos into sequential N-second clips.")
    parser.add_argument("videos", nargs="+")
    parser.add_argument("-n", "--seconds", type=float, default=DEFAULT_SECONDS)
    parser.add_argument("-o", "--out", help="output folder (default: ./clips next to each source)")
    parser.add_argument("--drop", action="store_true", help="discard a leftover shorter than N")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--manifest", action="store_true")
    args = parser.parse_args(argv)

    if missing := missing_tools():
        print(f"Missing: {', '.join(missing)}. Install ffmpeg:", file=sys.stderr)
        for os_name, cmd in INSTALL_HELP.items():
            print(f"  {os_name}: {cmd}", file=sys.stderr)
        return 2

    failed = 0
    for video in args.videos:
        out = args.out or Path(video).resolve().parent / "clips"
        try:
            results = split_video(
                video, out, args.seconds, "drop" if args.drop else "keep",
                overwrite=args.overwrite, manifest=args.manifest,
                on_progress=lambda i, n: print(f"  clip {i}/{n}", end="\r"),
            )
        except TrimError as exc:
            failed += 1
            print(file=sys.stderr)
            print(f"SKIP {video}: {exc}", file=sys.stderr)
            continue
        print(f"\n{video}: {len(results)} clips -> {out}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
