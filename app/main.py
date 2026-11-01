import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.background import BackgroundTask

from app.downloader import DownloadError, download

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Social Media Downloader")


class DownloadRequest(BaseModel):
    url: str


@app.post("/api/download")
def api_download(req: DownloadRequest):
    tmp = Path(tempfile.mkdtemp(prefix="smd_"))
    try:
        file = download(req.url, tmp)
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


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
