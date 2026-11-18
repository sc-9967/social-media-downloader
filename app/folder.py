"""Cartella dei download scelta dall'utente e salvata sul PC.

Il percorso arriva solo dalla finestra nativa di scelta cartella, aperta sul PC
dove gira l'app, mai dal contenuto di una richiesta: così una pagina web estranea
non può far scrivere file in una cartella decisa da lei.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SETTINGS_FILE = Path(__file__).resolve().parent.parent / "settings.local.json"
PICKER_TIMEOUT = 600

PICKER_SCRIPT = """
import tkinter, tkinter.filedialog
root = tkinter.Tk()
root.withdraw()
root.attributes("-topmost", True)
print(tkinter.filedialog.askdirectory(title="Cartella dei download", mustexist=True) or "")
"""


class FolderError(Exception):
    """Errore mostrabile all'utente."""


def get_download_dir() -> Path | None:
    """La cartella scelta, oppure None se non è impostata o non esiste più."""
    try:
        folder = json.loads(SETTINGS_FILE.read_text(encoding="utf-8")).get("download_dir")
    except (OSError, ValueError):
        return None
    return Path(folder) if folder and Path(folder).is_dir() else None


def set_download_dir(folder: Path | None) -> None:
    SETTINGS_FILE.write_text(
        json.dumps({"download_dir": str(folder) if folder else None}, ensure_ascii=False),
        encoding="utf-8",
    )


def pick_download_dir() -> Path | None:
    """Apre la finestra di scelta cartella e restituisce la cartella scelta,
    oppure None se l'utente annulla."""
    try:
        result = subprocess.run(
            [sys.executable, "-c", PICKER_SCRIPT],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            timeout=PICKER_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise FolderError("Nessuna cartella scelta in tempo.")
    if result.returncode != 0:
        raise FolderError("Non riesco ad aprire la finestra per scegliere la cartella su questo PC.")
    chosen = result.stdout.strip()
    return Path(chosen) if chosen else None


def save_files(files: list[Path], folder: Path) -> list[Path]:
    """Sposta i file nella cartella senza sovrascrivere quelli che ci sono già."""
    saved = []
    for f in files:
        target = folder / f.name
        n = 1
        while target.exists():
            target = folder / f"{f.stem} ({n}){f.suffix}"
            n += 1
        shutil.move(f, target)
        saved.append(target)
    return saved
