import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.background import BackgroundTask

from app import folder
from app.compress import MAX_SIZE
from app.downloader import DownloadError, bundle, download

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Social Media Downloader")


@app.middleware("http")
async def reject_cross_site(request: Request, call_next):
    # L'API scrive file sul PC: accetta solo richieste dalla pagina dell'app,
    # non da altri siti aperti nel browser.
    if request.url.path.startswith("/api/") and request.headers.get("sec-fetch-site") == "cross-site":
        return JSONResponse({"detail": "Richiesta da un altro sito rifiutata."}, status_code=403)
    return await call_next(request)


class DownloadRequest(BaseModel):
    url: str
    reduce: bool = False


@app.post("/api/download")
def api_download(req: DownloadRequest):
    tmp = Path(tempfile.mkdtemp(prefix="smd_"))
    try:
        files = download(req.url, tmp, MAX_SIZE if req.reduce else None)
        target_dir = folder.get_download_dir()
        if target_dir:
            saved = folder.save_files(files, target_dir)
            shutil.rmtree(tmp, ignore_errors=True)
            return {"folder": str(target_dir), "saved": [p.name for p in saved]}
        file = bundle(files, tmp)
    except DownloadError as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return FileResponse(
        file,
        filename=file.name,
        background=BackgroundTask(shutil.rmtree, tmp, ignore_errors=True),
    )


@app.get("/api/folder")
def api_get_folder():
    target_dir = folder.get_download_dir()
    return {"folder": str(target_dir) if target_dir else None}


@app.post("/api/folder/pick")
def api_pick_folder():
    try:
        chosen = folder.pick_download_dir()
    except folder.FolderError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if chosen:
        folder.set_download_dir(chosen)
    return api_get_folder()


@app.delete("/api/folder")
def api_reset_folder():
    folder.set_download_dir(None)
    return api_get_folder()


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
