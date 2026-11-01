"""Riduzione di video e immagini sotto un limite di dimensione, con ffmpeg."""

import re
import shutil
import subprocess
from pathlib import Path

MAX_SIZE = 9_900_000  # 9,9 MB

VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

AUDIO_BITRATE = 96_000
MIN_VIDEO_BITRATE = 50_000
FFMPEG_TIMEOUT = 900


class CompressionError(Exception):
    """Errore mostrabile all'utente."""


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def _run(args: list[str]) -> None:
    result = subprocess.run(
        [_ffmpeg(), "-hide_banner", "-y", *args],
        capture_output=True,
        text=True,
        timeout=FFMPEG_TIMEOUT,
    )
    if result.returncode != 0:
        last_line = result.stderr.strip().splitlines()[-1:] or ["errore sconosciuto"]
        raise CompressionError(f"Compressione non riuscita: {last_line[0]}")


def _duration(path: Path) -> float:
    # ffmpeg senza output esce con errore, ma stampa comunque la durata.
    stderr = subprocess.run(
        [_ffmpeg(), "-hide_banner", "-i", str(path)], capture_output=True, text=True, timeout=60
    ).stderr
    match = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", stderr)
    if not match:
        raise CompressionError(f"Impossibile leggere la durata di {path.name}.")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _mb(size: int) -> str:
    return f"{size / 1_000_000:.1f}".replace(".", ",") + " MB"


def _compress_video(src: Path, max_size: int) -> Path:
    # Bitrate medio che fa stare il video nel limite, con un margine per il container.
    budget = max_size * 8 / _duration(src) * 0.95
    out = src.with_name(src.stem + "_small.mp4")
    for _ in range(3):
        audio = min(AUDIO_BITRATE, budget * 0.2)
        video = budget - audio
        if video < MIN_VIDEO_BITRATE:
            raise CompressionError(f"Il video {src.name} è troppo lungo per stare in {_mb(max_size)}.")
        side = 720 if video >= 800_000 else 480 if video >= 250_000 else 360
        # Limita il lato corto a `side` pixel, sia per video orizzontali sia verticali.
        scale = f"scale='if(gt(iw,ih),-2,min(iw,{side}))':'if(gt(iw,ih),min(ih,{side}),-2)'"
        _run([
            "-i", str(src),
            "-map", "0:v:0", "-map", "0:a:0?",
            "-vf", scale, "-pix_fmt", "yuv420p",
            "-c:v", "libx264", "-preset", "veryfast",
            "-b:v", str(int(video)), "-maxrate", str(int(video * 1.2)), "-bufsize", str(int(video * 2)),
            "-c:a", "aac", "-b:a", str(int(audio)),
            "-movflags", "+faststart",
            str(out),
        ])
        size = out.stat().st_size
        if size <= max_size:
            break
        budget *= max_size / size * 0.9
    else:
        raise CompressionError(f"Non è stato possibile ridurre {src.name} sotto {_mb(max_size)}.")
    src.unlink()
    return out.replace(src.with_suffix(".mp4"))


def _compress_image(src: Path, max_size: int) -> Path:
    out = src.with_name(src.stem + "_small.jpg")
    side = 4096
    while side >= 256:
        _run([
            "-i", str(src),
            "-vf", f"scale='min(iw,{side})':'min(ih,{side})':force_original_aspect_ratio=decrease",
            "-q:v", "4", "-frames:v", "1",
            str(out),
        ])
        if out.stat().st_size <= max_size:
            break
        side //= 2
    else:
        raise CompressionError(f"Non è stato possibile ridurre {src.name} sotto {_mb(max_size)}.")
    src.unlink()
    return out.replace(src.with_suffix(".jpg"))


def fit(path: Path, max_size: int = MAX_SIZE) -> Path:
    """Restituisce un file non più grande di `max_size` byte: lo stesso file se
    è già abbastanza piccolo, altrimenti una versione compressa al suo posto."""
    if path.stat().st_size <= max_size:
        return path
    ext = path.suffix.lower()
    if ext in VIDEO_EXTS:
        return _compress_video(path, max_size)
    if ext in IMAGE_EXTS:
        return _compress_image(path, max_size)
    raise CompressionError(f"{path.name} supera {_mb(max_size)} e non è un video o un'immagine comprimibile.")
