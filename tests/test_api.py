import zipfile

import pytest
from fastapi.testclient import TestClient

from app import downloader
from app.downloader import DownloadError, validate_url
from app.main import app

client = TestClient(app)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.tiktok.com/@user/video/123",
        "https://vm.tiktok.com/abc/",
        "https://www.instagram.com/p/abc/",
        "https://www.facebook.com/watch/?v=1",
        "https://fb.watch/abc/",
    ],
)
def test_validate_url_accepts_supported_sites(url):
    assert validate_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "not a url",
        "ftp://www.tiktok.com/x",
        "https://www.youtube.com/watch?v=1",
        "https://eviltiktok.com/x",
        "https://tiktok.com.evil.com/x",
        "http://127.0.0.1:8000/",
    ],
)
def test_validate_url_rejects_others(url):
    with pytest.raises(DownloadError):
        validate_url(url)


def test_index_is_served():
    res = client.get("/")
    assert res.status_code == 200
    assert "Social Media Downloader" in res.text


def test_unsupported_url_returns_422():
    res = client.post("/api/download", json={"url": "https://example.com/x"})
    assert res.status_code == 422
    assert "TikTok" in res.json()["detail"]


def test_single_file_is_returned(monkeypatch):
    def fake_ytdlp(url, dest):
        (dest / "video.mp4").write_bytes(b"video")

    monkeypatch.setattr(downloader, "_download_with_ytdlp", fake_ytdlp)
    res = client.post("/api/download", json={"url": "https://www.tiktok.com/@u/video/1"})
    assert res.status_code == 200
    assert res.content == b"video"
    assert "video.mp4" in res.headers["content-disposition"]


def test_reduce_flag_compresses_each_file(monkeypatch):
    def fake_ytdlp(url, dest):
        (dest / "1.mp4").write_bytes(b"a")
        (dest / "2.mp4").write_bytes(b"b")

    calls = []

    def fake_fit(path, max_size):
        calls.append((path.name, max_size))
        return path

    monkeypatch.setattr(downloader, "_download_with_ytdlp", fake_ytdlp)
    monkeypatch.setattr(downloader.compress, "fit", fake_fit)
    res = client.post("/api/download", json={"url": "https://www.tiktok.com/@u/video/1", "reduce": True})
    assert res.status_code == 200
    assert calls == [("1.mp4", 9_900_000), ("2.mp4", 9_900_000)]


def test_without_reduce_flag_nothing_is_compressed(monkeypatch):
    def fake_ytdlp(url, dest):
        (dest / "video.mp4").write_bytes(b"video")

    def fail_fit(path, max_size):
        raise AssertionError("non doveva comprimere")

    monkeypatch.setattr(downloader, "_download_with_ytdlp", fake_ytdlp)
    monkeypatch.setattr(downloader.compress, "fit", fail_fit)
    res = client.post("/api/download", json={"url": "https://www.tiktok.com/@u/video/1"})
    assert res.status_code == 200


def test_fallback_to_gallerydl_and_zip(monkeypatch, tmp_path):
    def failing_ytdlp(url, dest):
        raise downloader.yt_dlp.utils.DownloadError("There is no video in this post")

    def fake_gallerydl(url, dest):
        (dest / "1.jpg").write_bytes(b"a")
        (dest / "2.jpg").write_bytes(b"b")

    monkeypatch.setattr(downloader, "_download_with_ytdlp", failing_ytdlp)
    monkeypatch.setattr(downloader, "_download_with_gallerydl", fake_gallerydl)
    res = client.post("/api/download", json={"url": "https://www.instagram.com/p/abc/"})
    assert res.status_code == 200
    archive = tmp_path / "out.zip"
    archive.write_bytes(res.content)
    with zipfile.ZipFile(archive) as zf:
        assert sorted(zf.namelist()) == ["1.jpg", "2.jpg"]


def test_both_downloaders_fail(monkeypatch):
    def failing(url, dest):
        raise DownloadError("Unsupported URL")

    monkeypatch.setattr(downloader, "_download_with_ytdlp", failing)
    monkeypatch.setattr(downloader, "_download_with_gallerydl", failing)
    res = client.post("/api/download", json={"url": "https://www.facebook.com/x"})
    assert res.status_code == 422
    assert "Unsupported URL" in res.json()["detail"]


def test_login_required_gets_friendly_message(monkeypatch):
    def failing(url, dest):
        raise DownloadError("TikTok is requiring login for access to this content")

    monkeypatch.setattr(downloader, "_download_with_ytdlp", failing)
    monkeypatch.setattr(downloader, "_download_with_gallerydl", failing)
    res = client.post("/api/download", json={"url": "https://www.tiktok.com/@u/video/1"})
    assert res.status_code == 422
    assert "richiede il login" in res.json()["detail"]
