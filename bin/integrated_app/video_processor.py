"""视频处理工具链 - FFmpeg 集成与视频分帧/合帧处理

提供基于 FFmpeg/FFprobe 命令行工具的视频处理能力:
1. FFmpegWrapper: FFmpeg/FFprobe 可执行文件封装，提供视频信息查询、帧提取、视频合成、音频提取/合并等功能
2. VideoProcessor: 已废弃的视频分段处理流水线（引擎直接使用 FFmpegWrapper）
3. rife_interpolate_video: RIFE 帧插值接口（可选功能）

特性:
- 自动查找 FFmpeg: 优先使用项目 bin 目录下的 FFmpeg，其次查找系统 PATH
- 多种视频编码: H.264 编码（libx264），CRF 18 高质量，yuv420p 兼容性好
- 音频处理: 支持从源视频提取并合并音轨，AAC 192k 编码
- 超时保护: 所有子进程调用设置超时，防止卡死

注意: 需要系统安装 FFmpeg 或将 ffmpeg.exe/ffprobe.exe 放置于项目 bin/ 目录。
"""

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class VideoInfo:
    """视频元信息数据类。

    由 FFprobe 解析视频文件得到的元数据。

    Attributes:
        path: 视频文件路径。
        width: 视频宽度（像素）。
        height: 视频高度（像素）。
        fps: 帧率（帧/秒）。
        frame_count: 总帧数。
        duration: 时长（秒）。
        codec: 视频编码名称（如 h264、hevc）。
        has_audio: 是否包含音频轨道。
        audio_codec: 音频编码名称（如 aac），无音频时为空字符串。
    """

    path: str
    width: int
    height: int
    fps: float
    frame_count: int
    duration: float
    codec: str
    has_audio: bool
    audio_codec: str = ""


class FFmpegWrapper:
    """FFmpeg/FFprobe 命令行工具封装类。

    封装对 ffmpeg 和 ffprobe 可执行文件的调用，提供视频元信息查询、
    帧提取、视频合成、音频提取/音视频合并等常用操作。

    可执行文件查找顺序:
    1. 项目根目录 bin/ 下的 ffmpeg.exe/ffprobe.exe（Windows）或 ffmpeg/ffprobe（Linux/macOS）
    2. 系统 PATH 中的 ffmpeg/ffprobe
    3. 返回默认名称（依赖 PATH 查找）

    Attributes:
        ffmpeg_path: ffmpeg 可执行文件路径。
        ffprobe_path: ffprobe 可执行文件路径。
    """

    def __init__(self, ffmpeg_path: str = "ffmpeg", ffprobe_path: str = "ffprobe"):
        """初始化 FFmpeg 封装，自动查找可执行文件路径。

        Args:
            ffmpeg_path: ffmpeg 可执行文件名称或路径，默认 "ffmpeg"。
            ffprobe_path: ffprobe 可执行文件名称或路径，默认 "ffprobe"。
        """
        self.ffmpeg_path = self._find_executable(ffmpeg_path, "ffmpeg")
        self.ffprobe_path = self._find_executable(ffprobe_path, "ffprobe")

    def _find_executable(self, name: str, base_name: str) -> str:
        """查找 FFmpeg/FFprobe 可执行文件路径。

        查找顺序:
        1. 项目根目录 bin/ 下的本地可执行文件（Windows 下带 .exe 后缀）
        2. 系统 PATH 环境变量中的可执行文件
        3. 都找不到时返回传入的默认名称（依赖运行时 PATH）

        Args:
            name: 用户传入的可执行文件名称或路径。
            base_name: 可执行文件基础名（"ffmpeg" 或 "ffprobe"），用于拼接 Windows 后缀。

        Returns:
            找到的可执行文件路径，找不到时返回 name 参数本身。
        """
        project_root = Path(__file__).parent.parent.parent.parent
        bin_dir = project_root / "bin"
        exe_name = f"{base_name}.exe" if sys.platform == "win32" else base_name

        local_path = bin_dir / exe_name
        if local_path.exists():
            return str(local_path)

        system_path = shutil.which(name)
        if system_path:
            return system_path

        return name

    def is_available(self) -> bool:
        """检查 FFmpeg 是否可用。

        通过执行 ``ffmpeg -version`` 验证可执行文件存在且可正常运行。

        Returns:
            FFmpeg 可用返回 True，否则返回 False。
        """
        try:
            result = subprocess.run([self.ffmpeg_path, "-version"], capture_output=True, text=True, timeout=10)
            return result.returncode == 0
        except Exception:
            return False

    def get_video_info(self, video_path: str) -> VideoInfo | None:
        """获取视频信息"""
        if not os.path.exists(video_path):
            logger.error(f"视频文件不存在: {video_path}")
            return None

        try:
            cmd = [
                self.ffprobe_path,
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                video_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            if result.returncode != 0:
                logger.error(f"ffprobe 执行失败: {result.stderr}")
                return None

            data = json.loads(result.stdout)

            # 查找视频流
            video_stream = None
            audio_stream = None
            for stream in data.get("streams", []):
                if stream.get("codec_type") == "video" and video_stream is None:
                    video_stream = stream
                elif stream.get("codec_type") == "audio" and audio_stream is None:
                    audio_stream = stream

            if not video_stream:
                logger.error("未找到视频流")
                return None

            # 解析帧率
            fps_str = video_stream.get("r_frame_rate", "30/1")
            if "/" in fps_str:
                num, den = fps_str.split("/")
                fps = float(num) / float(den) if float(den) > 0 else 30.0
            else:
                fps = float(fps_str)

            # 解析帧数
            frame_count = int(video_stream.get("nb_frames", 0))
            if frame_count == 0:
                duration = float(data.get("format", {}).get("duration", 0))
                frame_count = int(duration * fps)

            duration = float(data.get("format", {}).get("duration", 0))

            return VideoInfo(
                path=video_path,
                width=int(video_stream.get("width", 0)),
                height=int(video_stream.get("height", 0)),
                fps=fps,
                frame_count=frame_count,
                duration=duration,
                codec=video_stream.get("codec_name", "unknown"),
                has_audio=audio_stream is not None,
                audio_codec=audio_stream.get("codec_name", "") if audio_stream else "",
            )

        except Exception as e:
            logger.error(f"获取视频信息失败: {e}")
            return None

    def extract_frames(
        self,
        video_path: str,
        output_dir: str,
        fmt: str = "png",
        start_frame: int = 0,
        end_frame: int | None = None,
    ) -> list[str]:
        """从视频提取帧

        Returns:
            帧文件路径列表
        """
        os.makedirs(output_dir, exist_ok=True)

        cmd = [
            self.ffmpeg_path,
            "-i",
            video_path,
            "-start_number",
            str(start_frame),
        ]

        if end_frame is not None:
            cmd.extend(["-frames:v", str(end_frame - start_frame)])

        cmd.extend(["-q:v", "2" if fmt == "jpg" else "1", os.path.join(output_dir, f"frame_%06d.{fmt}")])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
            if result.returncode != 0:
                logger.error(f"帧提取失败: {result.stderr}")
                return []

            # 收集帧文件
            frames = sorted(
                [
                    os.path.join(output_dir, f)
                    for f in os.listdir(output_dir)
                    if f.startswith("frame_") and f.endswith(f".{fmt}")
                ]
            )
            logger.info(f"提取了 {len(frames)} 帧")
            return frames

        except subprocess.TimeoutExpired:
            logger.error("帧提取超时")
            return []
        except Exception as e:
            logger.error(f"帧提取失败: {e}")
            return []

    def compose_video(
        self,
        frames_dir: str,
        output_path: str,
        fps: float = 30.0,
        source_video: str | None = None,
        include_audio: bool = True,
    ) -> bool:
        """将帧合成为视频

        Args:
            frames_dir: 帧目录
            output_path: 输出视频路径
            fps: 帧率
            source_video: 源视频（用于提取音频）
            include_audio: 是否包含音频
        """
        # 检测帧格式
        frame_files = [f for f in os.listdir(frames_dir) if f.startswith("frame_")]
        if not frame_files:
            logger.error("未找到帧文件")
            return False

        ext = Path(frame_files[0]).suffix

        cmd = [
            self.ffmpeg_path,
            "-y",
            "-framerate",
            str(fps),
            "-i",
            os.path.join(frames_dir, f"frame_%06d{ext}"),
        ]

        # 添加音频
        if include_audio and source_video:
            info = self.get_video_info(source_video)
            if info and info.has_audio:
                cmd.extend(["-i", source_video])
                cmd.extend(["-map", "0:v", "-map", "1:a"])
                cmd.extend(["-c:a", "aac", "-b:a", "192k"])
            else:
                cmd.extend(["-c:a", "none"])

        cmd.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                output_path,
            ]
        )

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
            if result.returncode != 0:
                logger.error(f"视频合成失败: {result.stderr}")
                return False
            logger.info(f"视频合成完成: {output_path}")
            return True
        except subprocess.TimeoutExpired:
            logger.error("视频合成超时")
            return False
        except Exception as e:
            logger.error(f"视频合成失败: {e}")
            return False

    def extract_audio(self, video_path: str, output_path: str) -> bool:
        """从视频中提取音频轨道（直接复制流，不重新编码）。

        Args:
            video_path: 输入视频路径。
            output_path: 输出音频文件路径（推荐 .aac 格式）。

        Returns:
            提取成功返回 True，失败返回 False。
        """
        cmd = [self.ffmpeg_path, "-y", "-i", video_path, "-vn", "-acodec", "copy", output_path]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            return result.returncode == 0
        except Exception as e:
            logger.error(f"音频提取失败: {e}")
            return False

    def merge_audio_video(
        self,
        video_path: str,
        audio_path: str,
        output_path: str,
    ) -> bool:
        """合并视频和音频轨道。

        视频流直接复制（不重新编码），音频转码为 AAC 192kbps，
        使用 -shortest 标志以较短流的时长为准截断输出。

        Args:
            video_path: 输入视频文件路径（无音频）。
            audio_path: 输入音频文件路径。
            output_path: 输出合并后视频路径。

        Returns:
            合并成功返回 True，失败返回 False。
        """
        cmd = [
            self.ffmpeg_path,
            "-y",
            "-i",
            video_path,
            "-i",
            audio_path,
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            output_path,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            return result.returncode == 0
        except Exception as e:
            logger.error(f"音视频合并失败: {e}")
            return False


class VideoProcessor:
    """视频处理流水线 - 大视频分段处理避免 OOM

    .. deprecated::
        此类已废弃，引擎直接使用 FFmpegWrapper 进行视频处理。
        将在未来版本中移除。
    """

    def __init__(self, ffmpeg: FFmpegWrapper | None = None, max_segment_frames: int = 30):
        warnings.warn(
            "VideoProcessor 已废弃，请直接使用 FFmpegWrapper",
            DeprecationWarning,
            stacklevel=2,
        )
        self.ffmpeg = ffmpeg or FFmpegWrapper()
        self.max_segment_frames = max_segment_frames

    async def process_video(
        self,
        video_path: str,
        output_dir: str,
        restore_func: Callable,
        progress_callback: Callable | None = None,
        **kwargs,
    ) -> tuple[bool, str]:
        """处理视频的完整流水线

        Args:
            video_path: 输入视频路径
            output_dir: 输出目录
            restore_func: 修复函数，接收帧列表和参数，返回修复后的帧列表
            progress_callback: 进度回调
            **kwargs: 修复参数

        Returns:
            (success, output_path)
        """
        # 1. 获取视频信息
        info = self.ffmpeg.get_video_info(video_path)
        if not info:
            return False, "无法获取视频信息"

        logger.info(f"开始处理视频: {info.width}x{info.height}, {info.fps}fps, {info.frame_count}帧")

        # 2. 提取音频（如果有）
        audio_path = None
        if info.has_audio:
            audio_path = os.path.join(output_dir, "audio_track.aac")
            if not self.ffmpeg.extract_audio(video_path, audio_path):
                logger.warning("音频提取失败，将不包含音频")
                audio_path = None

        # 3. 分段提取帧并处理
        with tempfile.TemporaryDirectory() as temp_dir:
            all_restored_frames_dir = os.path.join(temp_dir, "restored")
            os.makedirs(all_restored_frames_dir, exist_ok=True)

            total_frames = info.frame_count
            segment_size = self.max_segment_frames
            frame_index = 0
            global_frame_index = 0

            while frame_index < total_frames:
                end_frame = min(frame_index + segment_size, total_frames)

                # 提取当前段的帧
                segment_dir = os.path.join(temp_dir, f"segment_{frame_index}")
                os.makedirs(segment_dir, exist_ok=True)

                frames = self.ffmpeg.extract_frames(
                    video_path,
                    segment_dir,
                    start_frame=frame_index,
                    end_frame=end_frame,
                )

                if not frames:
                    logger.error(f"帧提取失败: 帧 {frame_index}-{end_frame}")
                    return False, f"帧提取失败: 帧 {frame_index}-{end_frame}"

                # 修复当前段的帧
                import cv2

                frame_arrays = []
                for f in frames:
                    img = cv2.imread(f)
                    if img is not None:
                        frame_arrays.append(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))

                if frame_arrays:
                    restored = await restore_func(frame_arrays, **kwargs)

                    # 保存修复后的帧
                    for i, frame in enumerate(restored):
                        output_frame = os.path.join(
                            all_restored_frames_dir, f"frame_{global_frame_index + i + 1:06d}.png"
                        )
                        cv2.imwrite(output_frame, cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))

                global_frame_index += len(frame_arrays)
                frame_index = end_frame

                # 进度回调
                if progress_callback:
                    await progress_callback(
                        current_frame=global_frame_index,
                        total_frames=total_frames,
                        progress=global_frame_index / total_frames * 100,
                    )

            # 4. 合成视频
            output_filename = f"restored_{Path(video_path).stem}.mp4"
            output_path = os.path.join(output_dir, output_filename)

            temp_video = os.path.join(temp_dir, "temp_video.mp4")
            if not self.ffmpeg.compose_video(all_restored_frames_dir, temp_video, fps=info.fps, include_audio=False):
                return False, "视频合成失败"

            # 5. 合并音频
            if audio_path and os.path.exists(audio_path):
                if not self.ffmpeg.merge_audio_video(temp_video, audio_path, output_path):
                    # 合并失败，使用无音频版本
                    shutil.copy2(temp_video, output_path)
                    logger.warning("音频合并失败，输出视频不含音频")
            else:
                shutil.copy2(temp_video, output_path)

        logger.info(f"视频处理完成: {output_path}")
        return True, output_path


def rife_interpolate_video(input_path: str, output_path: str, multiplier: int = 2) -> bool:
    """使用 RIFE 算法进行视频帧率插值提升。

    通过在现有帧之间插入中间帧来提高视频帧率，使视频更流畅。
    需要安装 optimization.video_processing_enhance 模块中的 RIFEInterpolator。

    Args:
        input_path: 输入视频文件路径。
        output_path: 输出视频文件路径。
        multiplier: 帧率倍数，2 表示帧率翻倍（如 30fps -> 60fps）。

    Returns:
        插值成功返回 True，RIFE 不可用或处理失败返回 False。
    """
    try:
        # RIFEInterpolator 仅提供基于张量（[B, T, C, H, W]）的 interpolate_video 接口，
        # 尚未实现基于文件路径的插帧流水线（需先集成实际 RIFE 模型），
        # 因此此文件级入口目前不可用，返回 False。
        logger.debug("RIFE 文件级插帧尚未实现（RIFEInterpolator 仅提供张量接口）")
        return False
    except Exception as e:
        logger.debug(f"RIFE 插值不可用: {e}")
        return False
