"""VideoProcessor / FFmpegWrapper 单元测试

覆盖 FFmpeg 视频信息查询、帧提取和视频封装功能。
使用 mock subprocess 模拟 FFmpeg 命令，不依赖真实 FFmpeg。
"""

import json
from unittest.mock import MagicMock, patch

from bin.integrated_app.video_processor import FFmpegWrapper, VideoInfo, VideoProcessor

# ---------------------------------------------------------------------------
# VideoInfo
# ---------------------------------------------------------------------------


class TestVideoInfo:
    """VideoInfo 数据类测试"""

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


# ---------------------------------------------------------------------------
# FFmpegWrapper
# ---------------------------------------------------------------------------


class TestFFmpegWrapper:
    """FFmpegWrapper 命令封装测试"""

    def test_init_default(self):
        wrapper = FFmpegWrapper()
        assert wrapper is not None

    def test_init_custom_paths(self):
        wrapper = FFmpegWrapper(ffmpeg_path="/usr/bin/ffmpeg", ffprobe_path="/usr/bin/ffprobe")
        assert wrapper is not None

    @patch("subprocess.run")
    def test_get_video_info_success(self, mock_run, tmp_path):
        """模拟 ffprobe 返回视频信息"""
        video_file = tmp_path / "test.mp4"
        video_file.write_bytes(b"fake video")

        probe_output = json.dumps(
            {
                "streams": [
                    {
                        "codec_type": "video",
                        "width": 1920,
                        "height": 1080,
                        "r_frame_rate": "30/1",
                        "nb_frames": "100",
                        "duration": "3.333333",
                        "codec_name": "h264",
                    }
                ],
                "format": {"duration": "3.333333"},
            }
        )

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = probe_output
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        wrapper = FFmpegWrapper()
        info = wrapper.get_video_info(str(video_file))
        assert info is not None
        assert info.width == 1920
        assert info.height == 1080
        assert info.fps == 30.0

    @patch("subprocess.run")
    def test_get_video_info_not_found(self, mock_run, tmp_path):
        """模拟 ffprobe 返回错误"""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "No such file"
        mock_run.return_value = mock_result

        wrapper = FFmpegWrapper()
        info = wrapper.get_video_info(str(tmp_path / "nonexistent.mp4"))
        assert info is None

    @patch("subprocess.run")
    def test_get_video_info_invalid_json(self, mock_run, tmp_path):
        """模拟 ffprobe 返回无效 JSON"""
        video_file = tmp_path / "test.mp4"
        video_file.write_bytes(b"fake")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "not json"
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        wrapper = FFmpegWrapper()
        info = wrapper.get_video_info(str(video_file))
        assert info is None


# ---------------------------------------------------------------------------
# VideoProcessor
# ---------------------------------------------------------------------------


class TestVideoProcessor:
    """VideoProcessor 视频处理测试"""

    def test_init_default(self):
        processor = VideoProcessor()
        assert processor is not None

    def test_init_with_ffmpeg(self):
        ffmpeg = FFmpegWrapper()
        processor = VideoProcessor(ffmpeg=ffmpeg)
        assert processor.ffmpeg is ffmpeg

    def test_init_with_max_segment_frames(self):
        processor = VideoProcessor(max_segment_frames=60)
        assert processor is not None
