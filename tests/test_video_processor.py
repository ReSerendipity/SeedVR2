"""视频处理模块测试 (video_processor.py) — mock subprocess 覆盖 FFmpegWrapper 路径。"""

import asyncio
import json
import subprocess
from unittest.mock import patch

import pytest

from bin.integrated_app.video_processor import (
    FFmpegWrapper,
    VideoInfo,
    VideoProcessor,
    rife_interpolate_video,
)


@pytest.fixture
def wrapper():
    return FFmpegWrapper(ffmpeg_path="ffmpeg", ffprobe_path="ffprobe")


class _Result:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


# ---------- is_available ----------


def test_is_available_success(wrapper):
    with patch("bin.integrated_app.video_processor.subprocess.run", return_value=_Result(0)):
        assert wrapper.is_available() is True


def test_is_available_failure(wrapper):
    with patch("bin.integrated_app.video_processor.subprocess.run", side_effect=OSError("no ffmpeg")):
        assert wrapper.is_available() is False


# ---------- get_video_info ----------


def _ffprobe_json():
    return json.dumps(
        {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                    "r_frame_rate": "30/1",
                    "nb_frames": "300",
                },
                {"codec_type": "audio", "codec_name": "aac"},
            ],
            "format": {"duration": "10.0"},
        }
    )


def test_get_video_info_success(wrapper, tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake")
    with patch("bin.integrated_app.video_processor.subprocess.run", return_value=_Result(0, _ffprobe_json())):
        info = wrapper.get_video_info(str(video))
    assert info is not None
    assert info.width == 1920 and info.height == 1080
    assert info.fps == 30.0
    assert info.frame_count == 300
    assert info.duration == 10.0
    assert info.has_audio is True
    assert info.audio_codec == "aac"


def test_get_video_info_missing_file(wrapper):
    assert wrapper.get_video_info("C:/nonexistent/xyz.mp4") is None


def test_get_video_info_ffprobe_fail(wrapper, tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake")
    with patch("bin.integrated_app.video_processor.subprocess.run", return_value=_Result(1, "", "boom")):
        assert wrapper.get_video_info(str(video)) is None


def test_get_video_info_no_video_stream(wrapper, tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake")
    bad = json.dumps({"streams": [{"codec_type": "audio"}], "format": {}})
    with patch("bin.integrated_app.video_processor.subprocess.run", return_value=_Result(0, bad)):
        assert wrapper.get_video_info(str(video)) is None


def test_get_video_info_fps_fraction_and_frame_count_fallback(wrapper, tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake")
    data = json.dumps(
        {
            "streams": [{"codec_type": "video", "r_frame_rate": "30000/1001", "nb_frames": "0"}],
            "format": {"duration": "10"},
        }
    )
    with patch("bin.integrated_app.video_processor.subprocess.run", return_value=_Result(0, data)):
        info = wrapper.get_video_info(str(video))
    assert info is not None
    assert info.fps == pytest.approx(29.97, rel=1e-2)
    assert info.frame_count == int(10 * 29.97)
    assert info.has_audio is False


def test_get_video_info_parse_error(wrapper, tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake")
    with patch("bin.integrated_app.video_processor.subprocess.run", return_value=_Result(0, "not json")):
        assert wrapper.get_video_info(str(video)) is None


# ---------- extract_frames ----------


def test_extract_frames_success(wrapper, tmp_path):
    out = tmp_path / "frames"
    out.mkdir()
    (out / "frame_000001.png").write_bytes(b"a")
    (out / "frame_000002.png").write_bytes(b"b")
    with patch("bin.integrated_app.video_processor.subprocess.run", return_value=_Result(0)):
        frames = wrapper.extract_frames("in.mp4", str(out))
    assert len(frames) == 2
    assert frames[0].endswith("frame_000001.png")


def test_extract_frames_fail(wrapper, tmp_path):
    out = tmp_path / "frames"
    out.mkdir()
    with patch("bin.integrated_app.video_processor.subprocess.run", return_value=_Result(1, "", "err")):
        assert wrapper.extract_frames("in.mp4", str(out)) == []


def test_extract_frames_timeout(wrapper, tmp_path):
    out = tmp_path / "frames"
    out.mkdir()
    with patch(
        "bin.integrated_app.video_processor.subprocess.run", side_effect=subprocess.TimeoutExpired("ffmpeg", 10)
    ):
        assert wrapper.extract_frames("in.mp4", str(out)) == []


# ---------- compose_video ----------


def test_compose_video_no_frames(wrapper, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert wrapper.compose_video(str(empty), str(tmp_path / "o.mp4")) is False


def test_compose_video_success(wrapper, tmp_path):
    frames = tmp_path / "frames"
    frames.mkdir()
    (frames / "frame_000001.png").write_bytes(b"a")
    with patch("bin.integrated_app.video_processor.subprocess.run", return_value=_Result(0)):
        assert wrapper.compose_video(str(frames), str(tmp_path / "o.mp4")) is True


def test_compose_video_with_audio(wrapper, tmp_path):
    frames = tmp_path / "frames"
    frames.mkdir()
    (frames / "frame_000001.png").write_bytes(b"a")
    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake")
    with patch(
        "bin.integrated_app.video_processor.subprocess.run", side_effect=[_Result(0, _ffprobe_json()), _Result(0)]
    ):
        assert wrapper.compose_video(str(frames), str(tmp_path / "o.mp4"), source_video=str(video)) is True


def test_compose_video_fail(wrapper, tmp_path):
    frames = tmp_path / "frames"
    frames.mkdir()
    (frames / "frame_000001.png").write_bytes(b"a")
    with patch("bin.integrated_app.video_processor.subprocess.run", return_value=_Result(1, "", "err")):
        assert wrapper.compose_video(str(frames), str(tmp_path / "o.mp4")) is False


# ---------- extract_audio / merge_audio_video ----------


def test_extract_audio_success(wrapper):
    with patch("bin.integrated_app.video_processor.subprocess.run", return_value=_Result(0)):
        assert wrapper.extract_audio("in.mp4", "out.aac") is True


def test_extract_audio_fail(wrapper):
    with patch("bin.integrated_app.video_processor.subprocess.run", side_effect=OSError("no")):
        assert wrapper.extract_audio("in.mp4", "out.aac") is False


def test_merge_audio_video_success(wrapper):
    with patch("bin.integrated_app.video_processor.subprocess.run", return_value=_Result(0)):
        assert wrapper.merge_audio_video("v.mp4", "a.aac", "o.mp4") is True


def test_merge_audio_video_fail(wrapper):
    with patch(
        "bin.integrated_app.video_processor.subprocess.run", side_effect=subprocess.TimeoutExpired("ffmpeg", 300)
    ):
        assert wrapper.merge_audio_video("v.mp4", "a.aac", "o.mp4") is False


# ---------- VideoProcessor (deprecated) ----------


def test_video_processor_deprecated():
    with pytest.warns(DeprecationWarning):
        vp = VideoProcessor()
    assert vp.max_segment_frames == 30


def test_video_processor_no_info(wrapper):
    with pytest.warns(DeprecationWarning):
        vp = VideoProcessor(ffmpeg=wrapper)
    with patch("bin.integrated_app.video_processor.FFmpegWrapper.get_video_info", return_value=None):
        ok, msg = asyncio.run(vp.process_video("x.mp4", "out", restore_func=lambda frames, **kw: frames))
    assert ok is False


def test_rife_interpolate_unavailable():
    assert rife_interpolate_video("in.mp4", "out.mp4") is False


# ---------------------------------------------------------------------------
# VideoInfo 数据类
# ---------------------------------------------------------------------------


class TestVideoInfo:
    """VideoInfo 数据类测试。"""

    def test_init(self):
        info = VideoInfo(
            path="test.mp4",
            width=1920,
            height=1080,
            fps=30.0,
            frame_count=100,
            duration=3.33,
            codec="h264",
            has_audio=True,
        )
        assert info.path == "test.mp4"
        assert info.width == 1920
        assert info.height == 1080
        assert info.fps == 30.0
        assert info.frame_count == 100
        assert info.duration == 3.33
        assert info.codec == "h264"
        assert info.has_audio is True
        assert info.audio_codec == ""

    def test_init_with_audio_codec(self):
        info = VideoInfo(
            path="test.mp4",
            width=1280,
            height=720,
            fps=25.0,
            frame_count=50,
            duration=2.0,
            codec="hevc",
            has_audio=True,
            audio_codec="aac",
        )
        assert info.audio_codec == "aac"

    def test_no_audio(self):
        info = VideoInfo(
            path="test.mp4",
            width=640,
            height=480,
            fps=24.0,
            frame_count=10,
            duration=0.416,
            codec="h264",
            has_audio=False,
        )
        assert info.has_audio is False
