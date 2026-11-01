"""Download di video e immagini da TikTok, Instagram, Facebook, Snapchat, Telegram e YouTube.

Strategia: prima yt-dlp (ottimo per i video), poi gallery-dl come ripiego
(gestisce i post con sole immagini, i caroselli e le slideshow di TikTok).
"""

import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp

from app import compress

ALLOWED_DOMAINS = (
    "tiktok.com", "instagram.com", "facebook.com", "fb.watch", "fb.com",
    "snapchat.com", "t.me", "telegram.me", "youtube.com", "youtu.be",
)

YOUTUBE_DOMAINS = ("youtube.com", "youtu.be")
YOUTUBE_SINGLE_VIDEO = re.compile(r"^/(watch|shorts/[\w-]+|live/[\w-]+)/?$")

TELEGRAM_DOMAINS = ("t.me", "telegram.me")
TELEGRAM_PHOTO = re.compile(r"tgme_widget_message_photo_wrap[^>]*?background-image:url\('([^']+)'\)")

GALLERY_DL_TIMEOUT = 300
HTTP_TIMEOUT = 30


class DownloadError(Exception):
    """Errore mostrabile all'utente."""


def validate_url(url: str) -> str:
    url = url.strip()
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or not host:
        raise DownloadError("Inserisci un indirizzo valido che inizi con http:// o https://")
    if not any(host == d or host.endswith("." + d) for d in ALLOWED_DOMAINS):
        raise DownloadError(
            "Sono supportati solo link di TikTok, Instagram, Facebook, Snapchat, Telegram e YouTube."
        )
    if _is_youtube(host) and not (host.endswith("youtu.be") or YOUTUBE_SINGLE_VIDEO.match(parsed.path)):
        raise DownloadError("Per YouTube incolla il link di un singolo video o Short, non di playlist o canali.")
    return url


def _is_youtube(host: str) -> bool:
    return any(host == d or host.endswith("." + d) for d in YOUTUBE_DOMAINS)


def _ffmpeg_location() -> str | None:
    if shutil.which("ffmpeg"):
        return None  # yt-dlp lo trova da solo nel PATH
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _deno_path() -> str | None:
    # YouTube richiede di risolvere una sfida JavaScript: yt-dlp usa Deno,
    # installato come pacchetto pip.
    try:
        import deno

        return deno.find_deno_bin()
    except Exception:
        return shutil.which("deno")


def _download_with_ytdlp(url: str, dest: Path) -> None:
    opts = {
        "outtmpl": str(dest / "%(extractor)s_%(id)s.%(ext)s"),
        "restrictfilenames": True,
        # Massimo 1080p: oltre i file diventano enormi senza vantaggi per i social.
        "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]/b",
        "merge_output_format": "mp4",
        # Su YouTube un link watch?v=...&list=... deve scaricare solo il video.
        "noplaylist": _is_youtube((urlparse(url).hostname or "").lower()),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "color": "no_color",
    }
    ffmpeg = _ffmpeg_location()
    if ffmpeg:
        opts["ffmpeg_location"] = ffmpeg
    deno_bin = _deno_path()
    if deno_bin:
        opts["js_runtimes"] = {"deno": {"path": deno_bin}}
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])


def _download_with_gallerydl(url: str, dest: Path) -> None:
    # Processo separato: la configurazione di gallery-dl è globale e non va
    # condivisa tra richieste concorrenti.
    result = subprocess.run(
        [sys.executable, "-m", "gallery_dl", "--quiet", "-D", str(dest), url],
        capture_output=True,
        text=True,
        timeout=GALLERY_DL_TIMEOUT,
    )
    if result.returncode != 0:
        raise DownloadError(result.stderr.strip() or "gallery-dl non è riuscito a scaricare il contenuto.")


def _download_telegram_photos(url: str, dest: Path) -> None:
    # yt-dlp prende solo i video di Telegram: le foto si leggono dal widget
    # pubblico di incorporamento del post.
    parsed = urlparse(url)
    if (parsed.hostname or "").lower() not in TELEGRAM_DOMAINS:
        return
    embed_url = f"https://t.me{parsed.path}?embed=1"
    with urllib.request.urlopen(embed_url, timeout=HTTP_TIMEOUT) as resp:
        html = resp.read().decode("utf-8", "replace")
    post_id = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    for n, photo_url in enumerate(TELEGRAM_PHOTO.findall(html), 1):
        if urlparse(photo_url).scheme != "https":
            continue
        with urllib.request.urlopen(photo_url, timeout=HTTP_TIMEOUT) as resp:
            (dest / f"telegram_{post_id}_{n}.jpg").write_bytes(resp.read())


def _media_files(dest: Path) -> list[Path]:
    return sorted(p for p in dest.rglob("*") if p.is_file() and not p.name.endswith((".part", ".ytdl")))


def download(url: str, dest: Path, max_size: int | None = None) -> Path:
    """Scarica il contenuto di `url` in `dest` e restituisce il file da inviare
    (il file singolo oppure uno ZIP se il post contiene più elementi).
    Con `max_size` ogni file viene compresso fino a stare in quel numero di byte."""
    url = validate_url(url)
    errors = []
    for fetch in (_download_with_ytdlp, _download_with_gallerydl, _download_telegram_photos):
        try:
            fetch(url, dest)
        except (yt_dlp.utils.DownloadError, DownloadError, subprocess.TimeoutExpired, OSError) as exc:
            errors.append(str(exc))
        files = _media_files(dest)
        if files:
            break
        if not errors:
            errors.append("nel post non c'è nessun video o immagine (forse è stato eliminato).")
    else:
        if any("login" in e.lower() for e in errors):
            raise DownloadError(
                "La piattaforma richiede il login per vedere questo contenuto, "
                "quindi senza accesso non è scaricabile."
            )
        detail = errors[0] if errors else "nessun file trovato"
        raise DownloadError(f"Impossibile scaricare il contenuto: {detail}")

    if max_size:
        try:
            files = [compress.fit(f, max_size) for f in files]
        except (compress.CompressionError, subprocess.TimeoutExpired) as exc:
            raise DownloadError(str(exc))

    if len(files) == 1:
        return files[0]

    archive = dest / "download.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for f in files:
            zf.write(f, f.name)
    return archive
