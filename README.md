# QuickTrim — local video auto-trim

Drop in a video, pick a clip length `N` (default **14 s**), and get every sequential
chunk as its own `.mp4`. Built for tools like Wan that reject clips over ~14 s:
a 3:00 source becomes `source_01.mp4` … `source_13.mp4` (12 × 14 s + one 12 s clip).

Runs entirely on your machine with ffmpeg. No accounts, no API keys, no cloud, no GPU.

## Install

1. **Install ffmpeg** (provides `ffmpeg` and `ffprobe`; both must be on your PATH):
   - Windows: `winget install ffmpeg`
   - macOS: `brew install ffmpeg`
   - Linux: `sudo apt install ffmpeg`
   - Others: https://ffmpeg.org/download.html
2. **Install the Python dependency** (Python 3.10+):
   ```
   pip install -r requirements.txt
   ```

## Run

```
streamlit run app.py
```

The page opens at `http://localhost:8501` (bound to localhost only).

1. Add one or more videos (`mp4`, `mov`, `mkv`, `webm`, `avi`), or paste paths of
   files already on disk under *…or use files already on this computer* — best for
   large files, since nothing is copied.
2. Set the clip length (1–300 s) and whether to **keep** or **drop** a shorter leftover.
3. Optionally set an output folder. Defaults: `./clips` in this folder for uploads,
   `clips/` next to the source for local paths.
4. Click **Split**. Clips are named `{name}_{01..}.mp4`; tick the manifest box to also
   write `{name}_manifest.csv` (`index,filename,start_sec,end_sec,duration_sec`).

### Command line

The same engine works without the UI:

```
python trim.py source.mp4 -n 14            # -> ./clips/source_01.mp4 ...
python trim.py *.mov -n 10 --drop --manifest -o out/
```

## How cutting works

- Duration comes from `ffprobe` (not frame count), so variable-frame-rate video is fine.
- Each clip is first **stream-copied** (`-c copy`): instant and lossless.
- Stream copy can only start on a keyframe. If a copied clip fails, or comes out more
  than 0.15 s off the requested length because keyframes don't line up with the cut,
  that clip alone is **re-encoded** (libx264 CRF 18 + AAC). The results table shows
  which mode each clip used. Sources with a keyframe every second or two (most phone
  and camera footage) are almost entirely copied.
- Videos without audio are fine; subtitle/data tracks are not carried over.
- A video shorter than `N` is exported as one clip. A leftover under 0.05 s is treated
  as rounding noise and skipped.
- A file that can't be read is skipped with an error; the rest still process.
- If clips with the same names exist, new ones get `_v2`, `_v3`, … unless you choose
  *Overwrite* (and confirm).

## Tests

```
python -m unittest -v
```
