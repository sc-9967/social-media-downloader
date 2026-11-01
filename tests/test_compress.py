import re
import subprocess

import pytest

from app import compress
from app.compress import CompressionError, fit


def ffmpeg(*args):
    subprocess.run([compress._ffmpeg(), "-hide_banner", "-y", *args], check=True, capture_output=True)


@pytest.fixture
def big_video(tmp_path):
    path = tmp_path / "clip.mp4"
    ffmpeg(
        "-f", "lavfi", "-i", "testsrc2=size=720x1280:rate=30:duration=4",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
        "-c:v", "libx264", "-b:v", "4M", "-c:a", "aac", "-pix_fmt", "yuv420p",
        str(path),
    )
    return path


def test_small_file_is_untouched(tmp_path):
    path = tmp_path / "a.mp4"
    path.write_bytes(b"x" * 100)
    assert fit(path, 1000) == path
    assert path.read_bytes() == b"x" * 100


def test_video_is_reduced_under_limit(big_video):
    limit = 400_000
    assert big_video.stat().st_size > limit
    result = fit(big_video, limit)
    assert result.suffix == ".mp4"
    assert result.stat().st_size <= limit
    assert compress._duration(result) == pytest.approx(4, abs=0.3)


def test_vertical_video_keeps_orientation(big_video):
    result = fit(big_video, 400_000)
    stderr = subprocess.run(
        [compress._ffmpeg(), "-hide_banner", "-i", str(result)], capture_output=True, text=True
    ).stderr
    width, height = map(int, re.search(r", (\d+)x(\d+)", stderr).groups())
    assert height > width


def test_video_too_long_for_limit(big_video):
    with pytest.raises(CompressionError, match="troppo lungo"):
        fit(big_video, 20_000)


def test_image_is_reduced_under_limit(tmp_path):
    path = tmp_path / "photo.png"
    ffmpeg("-f", "lavfi", "-i", "nullsrc=size=3000x3000,geq=random(1)*255:128:128", "-frames:v", "1", str(path))
    limit = 300_000
    assert path.stat().st_size > limit
    result = fit(path, limit)
    assert result.name == "photo.jpg"
    assert result.stat().st_size <= limit
    assert not path.exists()


def test_other_files_over_limit_are_rejected(tmp_path):
    path = tmp_path / "a.txt"
    path.write_bytes(b"x" * 2000)
    with pytest.raises(CompressionError):
        fit(path, 1000)
