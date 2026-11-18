import subprocess
import zipfile

import pytest
from fastapi.testclient import TestClient

from app import downloader, folder
from app.downloader import DownloadError, validate_url
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    # I test non devono dipendere da cookie, variabili o cartella scelta sul PC di chi li lancia.
    monkeypatch.delenv("SMD_COOKIES_FILE", raising=False)
    monkeypatch.delenv("SMD_COOKIES_FROM_BROWSER", raising=False)
    monkeypatch.setattr(downloader, "DEFAULT_COOKIES_FILE", tmp_path / "assente.txt")
    monkeypatch.setattr(folder, "SETTINGS_FILE", tmp_path / "settings.local.json")


@pytest.mark.parametrize(
    "url",
    [
        "https://www.tiktok.com/@user/video/123",
        "https://vm.tiktok.com/abc/",
        "https://www.instagram.com/p/abc/",
        "https://www.facebook.com/watch/?v=1",
        "https://fb.watch/abc/",
        "https://www.snapchat.com/spotlight/abc",
        "https://t.me/channel/613",
        "https://www.youtube.com/watch?v=Yil32mThG04",
        "https://www.youtube.com/watch?v=Yil32mThG04&list=PLx",
        "https://m.youtube.com/watch?v=Yil32mThG04",
        "https://www.youtube.com/shorts/abc123",
        "https://youtu.be/Yil32mThG04",
    ],
)
def test_validate_url_accepts_supported_sites(url):
    assert validate_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "not a url",
        "ftp://www.tiktok.com/x",
        "https://vimeo.com/123",
        "https://eviltiktok.com/x",
        "https://tiktok.com.evil.com/x",
        "https://www.threads.com/@user/post/abc",
        "https://evilt.me/x",
        "https://www.youtube.com/@YouTube/videos",
        "https://www.youtube.com/playlist?list=PLx",
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


def test_telegram_photos_from_embed_widget(monkeypatch, tmp_path):
    embed = (
        "<a class=\"tgme_widget_message_photo_wrap 1\" style=\"width:800px;"
        "background-image:url('https://cdn4.telesco.pe/file/a.jpg')\"></a>"
        "<a class=\"tgme_widget_message_photo_wrap 2\" style=\"background-image:url('https://cdn4.telesco.pe/file/b.jpg')\"></a>"
    )
    responses = {
        "https://t.me/canale/605?embed=1": embed.encode(),
        "https://cdn4.telesco.pe/file/a.jpg": b"A",
        "https://cdn4.telesco.pe/file/b.jpg": b"B",
    }

    class FakeResponse:
        def __init__(self, body):
            self.body = body

        def read(self):
            return self.body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(downloader.urllib.request, "urlopen", lambda url, timeout: FakeResponse(responses[url]))
    downloader._download_telegram_photos("https://t.me/canale/605", tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["telegram_605_1.jpg", "telegram_605_2.jpg"]


def test_telegram_photos_ignores_other_sites(tmp_path):
    downloader._download_telegram_photos("https://www.instagram.com/p/abc/", tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_folder_defaults_to_browser_downloads():
    assert client.get("/api/folder").json() == {"folder": None}


def test_chosen_folder_receives_files_without_overwriting(monkeypatch, tmp_path):
    target = tmp_path / "scaricati"
    target.mkdir()
    (target / "video.mp4").write_bytes(b"vecchio")
    monkeypatch.setattr(folder, "pick_download_dir", lambda: target)
    assert client.post("/api/folder/pick").json() == {"folder": str(target)}

    def fake_ytdlp(url, dest):
        (dest / "video.mp4").write_bytes(b"nuovo")

    monkeypatch.setattr(downloader, "_download_with_ytdlp", fake_ytdlp)
    res = client.post("/api/download", json={"url": "https://www.tiktok.com/@u/video/1"})
    assert res.json() == {"folder": str(target), "saved": ["video (1).mp4"]}
    assert (target / "video.mp4").read_bytes() == b"vecchio"
    assert (target / "video (1).mp4").read_bytes() == b"nuovo"


def test_cancelled_picker_keeps_current_folder(monkeypatch, tmp_path):
    folder.set_download_dir(tmp_path)
    monkeypatch.setattr(folder, "pick_download_dir", lambda: None)
    assert client.post("/api/folder/pick").json() == {"folder": str(tmp_path)}


def test_reset_and_missing_folder_fall_back_to_browser(tmp_path):
    folder.set_download_dir(tmp_path)
    assert client.delete("/api/folder").json() == {"folder": None}
    folder.set_download_dir(tmp_path / "cancellata")
    assert folder.get_download_dir() is None


def test_cross_site_requests_are_rejected():
    res = client.post("/api/folder/pick", headers={"Sec-Fetch-Site": "cross-site"})
    assert res.status_code == 403


def test_cookies_disabled_by_default():
    assert downloader._cookies() == (None, None)


def test_cookies_file_beats_browser(monkeypatch, tmp_path):
    default = tmp_path / "cookies.txt"
    default.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setattr(downloader, "DEFAULT_COOKIES_FILE", default)
    monkeypatch.setenv("SMD_COOKIES_FROM_BROWSER", "firefox")
    assert downloader._cookies() == (str(default), None)
    monkeypatch.setenv("SMD_COOKIES_FILE", "altro.txt")
    assert downloader._cookies() == ("altro.txt", None)


def test_cookies_reach_both_downloaders(monkeypatch, tmp_path):
    monkeypatch.setenv("SMD_COOKIES_FROM_BROWSER", "Firefox")
    captured = {}

    class FakeYDL:
        def __init__(self, opts):
            captured["opts"] = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def download(self, urls):
            pass

    def fake_run(args, **kwargs):
        captured["args"] = args
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", FakeYDL)
    monkeypatch.setattr(downloader.subprocess, "run", fake_run)
    downloader._download_with_ytdlp("https://www.instagram.com/p/abc/", tmp_path)
    downloader._download_with_gallerydl("https://www.instagram.com/p/abc/", tmp_path)
    assert captured["opts"]["cookiesfrombrowser"] == ("firefox",)
    assert captured["args"][captured["args"].index("--cookies-from-browser") + 1] == "firefox"


def test_unreadable_browser_cookies_get_clear_message(monkeypatch):
    def failing(url, dest):
        raise DownloadError("ERROR: Could not copy Chrome cookie database.")

    monkeypatch.setattr(downloader, "_download_with_ytdlp", failing)
    monkeypatch.setattr(downloader, "_download_with_gallerydl", failing)
    res = client.post("/api/download", json={"url": "https://www.instagram.com/p/abc/"})
    assert res.status_code == 422
    assert "cookies.txt" in res.json()["detail"]


def test_login_required_gets_friendly_message(monkeypatch):
    def failing(url, dest):
        raise DownloadError("TikTok is requiring login for access to this content")

    monkeypatch.setattr(downloader, "_download_with_ytdlp", failing)
    monkeypatch.setattr(downloader, "_download_with_gallerydl", failing)
    res = client.post("/api/download", json={"url": "https://www.tiktok.com/@u/video/1"})
    assert res.status_code == 422
    assert "richiede il login" in res.json()["detail"]
