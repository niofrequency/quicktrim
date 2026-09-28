"""QuickTrim — split videos into sequential N-second clips. Run: streamlit run app.py"""

from __future__ import annotations

import glob
import io
import shutil
import socket
import tempfile
import zipfile
from pathlib import Path

import streamlit as st

import trim

APP_DIR = Path(__file__).resolve().parent
UPLOAD_DEFAULT_OUT = APP_DIR / "clips"


def lan_ip() -> str | None:
    """This PC's address on the local network (no packets are sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.254.254.254", 1))
            return s.getsockname()[0]
    except OSError:
        return None


def zip_bytes(paths: list[Path]) -> bytes:
    buf = io.BytesIO()
    # Videos are already compressed; storing them is as small and much faster.
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for p in paths:
            zf.write(p, p.name)
    return buf.getvalue()


# Visitors from another device (a phone on the same Wi-Fi) only get upload +
# download: no reading arbitrary paths, choosing folders, or opening windows on the PC.
is_this_pc = st.context.ip_address in (None, "127.0.0.1", "::1")
shared_on_lan = st.get_option("server.address") not in ("localhost", "127.0.0.1", "::1")

st.set_page_config(page_title="QuickTrim", page_icon="✂️", layout="centered")
st.title("✂️ QuickTrim")
st.caption("Split videos into sequential clips. Everything runs locally with ffmpeg.")

if missing := trim.missing_tools():
    st.error(f"**{' and '.join(missing)} not found on PATH.** Install ffmpeg, then restart this app.")
    st.markdown("\n".join(f"- {os_name}: `{cmd}`" for os_name, cmd in trim.INSTALL_HELP.items()))
    st.markdown(f"Downloads for other systems: {trim.INSTALL_URL}")
    st.stop()

if is_this_pc and shared_on_lan and (ip := lan_ip()):
    st.info(f"📱 On your phone (same Wi-Fi), open **http://{ip}:{st.get_option('server.port')}**")
elif not is_this_pc:
    st.caption("Clips are made on the computer running QuickTrim; download them below when done.")

# --- 1. Inputs -------------------------------------------------------------
uploads = st.file_uploader(
    "Videos",
    type=list(trim.VIDEO_EXTS),
    accept_multiple_files=True,
)
local_text = ""
if is_this_pc:
    with st.expander("…or use files already on this computer (no upload/copy)"):
        local_text = st.text_area(
            "One path per line",
            placeholder="/Users/me/Movies/source.mp4",
            help="Handy for very large files. Clips go to ./clips next to each source unless you set an output folder.",
        )
local_paths = [Path(line.strip().strip('"')).expanduser() for line in local_text.splitlines() if line.strip()]

col1, col2 = st.columns(2)
seconds = col1.number_input(
    "Clip length (seconds)",
    min_value=trim.MIN_SECONDS,
    max_value=trim.MAX_SECONDS,
    value=trim.DEFAULT_SECONDS,
    step=1,
)
remainder = col2.radio(
    "Leftover shorter than that",
    options=["keep", "drop"],
    format_func=lambda m: {"keep": "Keep as a shorter last clip", "drop": "Drop it"}[m],
)

out_text = ""
if is_this_pc:
    out_text = st.text_input(
        "Output folder",
        placeholder=f"Default: {UPLOAD_DEFAULT_OUT} for uploads, ./clips next to local files",
    )
existing = st.radio(
    "If clips with the same name already exist",
    options=["suffix", "overwrite"],
    format_func=lambda m: {"suffix": "Keep them, name new ones _v2, _v3…", "overwrite": "Overwrite"}[m],
    horizontal=True,
)
manifest = st.checkbox("Also write a manifest CSV per video")


def out_dir_for(source: Path | None) -> Path:
    if out_text.strip():
        return Path(out_text.strip().strip('"')).expanduser()
    return source.parent / "clips" if source else UPLOAD_DEFAULT_OUT


# Jobs: (display name, output stem, local path or None, upload or None)
jobs = [(f.name, Path(f.name).stem, None, f) for f in uploads or []]
jobs += [(str(p), p.stem, p, None) for p in local_paths]

# Overwriting needs an explicit confirmation when it would actually clobber files.
confirm_overwrite = True
if existing == "overwrite" and jobs:
    conflicts = []
    for _, stem, path, _ in jobs:
        folder = out_dir_for(path)
        if folder.is_dir():
            conflicts += sorted(folder.glob(f"{glob.escape(stem)}_*.mp4"))
    if conflicts:
        st.warning(f"{len(conflicts)} existing clip(s) in the output folder may be overwritten.")
        confirm_overwrite = st.checkbox("Yes, overwrite existing clips")

# --- 2. Split ----------------------------------------------------------------
if st.button("Split", type="primary", disabled=not jobs or not confirm_overwrite):
    summary = []  # (display name, out dir, results or None, error or None)
    status = st.empty()
    bar = st.progress(0.0)

    for n, (name, stem, path, upload) in enumerate(jobs, start=1):
        prefix = f"File {n}/{len(jobs)} · {name}" if len(jobs) > 1 else name
        out_dir = out_dir_for(path)

        def progress(done: int, total: int) -> None:
            status.write(f"{prefix} — clip {done}/{total}")
            bar.progress(done / total)

        status.write(f"{prefix} — reading…")
        bar.progress(0.0)
        tmp_dir = None
        try:
            if upload is not None:
                tmp_dir = tempfile.mkdtemp(prefix="quicktrim_")
                src = Path(tmp_dir) / Path(upload.name).name
                with open(src, "wb") as fh:
                    upload.seek(0)
                    shutil.copyfileobj(upload, fh)
            else:
                src = path
                if not src.is_file():
                    raise trim.TrimError(f"File not found: {src}")
            results = trim.split_video(
                src, out_dir, float(seconds), remainder,
                overwrite=existing == "overwrite", manifest=manifest,
                stem=stem, on_progress=progress,
            )
            summary.append((name, out_dir, results, None))
        except Exception as exc:  # corrupt/unreadable file: report and move on
            summary.append((name, out_dir, None, str(exc)))
        finally:
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)

    status.empty()
    bar.empty()
    st.session_state["summary"] = summary

# --- 3. Results --------------------------------------------------------------
summary = st.session_state.get("summary")
if summary:
    total = sum(len(r) for _, _, r, _ in summary if r)
    failed = [s for s in summary if s[3]]
    st.success(f"Done: {total} clip(s) written." + (f" {len(failed)} file(s) skipped." if failed else ""))

    for name, out_dir, results, error in summary:
        if error:
            st.error(f"**{name}** skipped: {error}")
            continue
        reencoded = sum(r.method == "reencode" for r in results)
        st.subheader(f"{name} → {len(results)} clip(s)")
        st.caption(
            (f"Saved to `{out_dir.resolve()}`" if is_this_pc else "Saved on the computer")
            + (f" · {reencoded} clip(s) re-encoded because keyframes didn't line up with the cut" if reencoded else "")
        )
        st.dataframe(
            [
                {
                    "file": r.path.name,
                    "start": f"{r.segment.start:.2f}",
                    "end": f"{r.segment.end:.2f}",
                    "seconds": f"{r.segment.duration:.2f}",
                    "mode": r.method,
                }
                for r in results
            ],
            hide_index=True,
        )
        clip_paths = [r.path for r in results if r.path.exists()]
        if clip_paths:
            stem = Path(name).stem
            st.download_button(
                f"⬇️ Download all {len(clip_paths)} clips (.zip)",
                data=lambda paths=clip_paths: zip_bytes(paths),
                file_name=f"{stem}_clips.zip",
                mime="application/zip",
                on_click="ignore",
                key=f"zip_{name}",
            )
            with st.expander("Download clips one by one (easiest on iPhone: open, then Share → Save Video)"):
                for p in clip_paths:
                    st.download_button(
                        f"⬇️ {p.name}",
                        data=lambda p=p: p.read_bytes(),
                        file_name=p.name,
                        mime="video/mp4",
                        on_click="ignore",
                        key=f"clip_{name}_{p.name}",
                    )

    folders = list(dict.fromkeys(out_dir.resolve() for _, out_dir, r, _ in summary if r)) if is_this_pc else []
    for i, folder in enumerate(folders):
        label = "Open output folder" if len(folders) == 1 else f"Open {folder}"
        if st.button(label, key=f"open_{i}"):
            try:
                trim.open_folder(folder)
            except Exception as exc:
                st.error(f"Couldn't open {folder}: {exc}")
