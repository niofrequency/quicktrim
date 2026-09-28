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

### Use it from your phone (same Wi-Fi)

Run it on your PC with network access turned on:

```
streamlit run app.py --server.address 0.0.0.0
```

On Windows you can just double-click **`run-phone.bat`** instead.

The page on the PC then shows a line like *On your phone, open http://192.168.1.20:8501*.
Open that address in Safari/Chrome on your phone, pick videos from your camera roll,
tap **Split**, then download the clips:

- **Download all (.zip)**: saved to the Files app; tap it to unzip.
- **One by one**: open a clip, then Share → *Save Video* to put it in Photos.

Notes:
- The PC must stay on and awake, and both devices must be on the same network.
- **Windows:** when the firewall asks, allow Python on *Private networks*, and make sure
  your Wi-Fi is set to *Private* (Settings → Network → Wi-Fi → your network).
- **Mac:** allow incoming connections for Python if macOS asks.
- Anyone on the same Wi-Fi can open the page while it's running like this, so use it on
  your home network. Phone visitors can only upload and download: typing file paths,
  choosing output folders and opening folders are available only on the PC itself.
- iPhone video (HEVC) clips are tagged so they play in Photos and QuickTime.

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

## Hosting

This is a local-only app: it needs a long-running Streamlit server, the ffmpeg binary
and your local disk, so it can't run on serverless hosts like Vercel.
`vercel.json` turns off Vercel's automatic Git deployments for this repo.

## Tests

```
python -m unittest -v
```
