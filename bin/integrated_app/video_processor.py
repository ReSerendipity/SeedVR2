"""视频处理工具链 - FFmpeg 集成与视频分帧处理"""
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
    """视频信息"""
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
    """FFmpeg 命令行封装"""

    def __init__(self, ffmpeg_path: str = "ffmpeg", ffprobe_path: str = "ffprobe"):
        self.ffmpeg_path = self._find_executable(ffmpeg_path, "ffmpeg")
        self.ffprobe_path = self._find_executable(ffprobe_path, "ffprobe")

    def _find_executable(self, name: str, base_name: str) -> str:
        """查找可执行文件"""
        # 1. 检查项目 bin 目录
        project_root = Path(__file__).parent.parent.parent.parent
        bin_dir = project_root / "bin"
        exe_name = f"{base_name}.exe" if sys.platform == "win32" else base_name

        local_path = bin_dir / exe_name
        if local_path.exists():
            return str(local_path)

        # 2. 检查系统 PATH
        system_path = shutil.which(name)
        if system_path:
            return system_path

        # 3. 返回默认名称（依赖 PATH）
        return name

    def is_available(self) -> bool:
        """检查 FFmpeg 是否可用"""
        try:
            result = subprocess.run(
                [self.ffmpeg_path, "-version"],
                capture_output=True, text=True, timeout=10
            )
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
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                video_path
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
            "-i", video_path,
            "-start_number", str(start_frame),
        ]

        if end_frame is not None:
            cmd.extend(["-frames:v", str(end_frame - start_frame)])

        cmd.extend([
            "-q:v", "2" if fmt == "jpg" else "1",
            os.path.join(output_dir, f"frame_%06d.{fmt}")
        ])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
            if result.returncode != 0:
                logger.error(f"帧提取失败: {result.stderr}")
                return []

            # 收集帧文件
            frames = sorted([
                os.path.join(output_dir, f)
                for f in os.listdir(output_dir)
                if f.startswith("frame_") and f.endswith(f".{fmt}")
            ])
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
            "-framerate", str(fps),
            "-i", os.path.join(frames_dir, f"frame_%06d{ext}"),
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

        cmd.extend([
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            output_path
        ])

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
        """从视频提取音频轨道"""
        cmd = [
            self.ffmpeg_path,
            "-y",
            "-i", video_path,
            "-vn",
            "-acodec", "copy",
            output_path
        ]
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
        """合并音频和视频"""
        cmd = [
            self.ffmpeg_path,
            "-y",
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            output_path
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

    def __init__(self, ffmpeg: FFmpegWrapper = None, max_segment_frames: int = 30):
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
        **kwargs
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
                    video_path, segment_dir,
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
                            all_restored_frames_dir,
                            f"frame_{global_frame_index + i + 1:06d}.png"
                        )
                        cv2.imwrite(output_frame, cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))

                global_frame_index += len(frame_arrays)
                frame_index = end_frame

                # 进度回调
                if progress_callback:
                    await progress_callback(
                        current_frame=global_frame_index,
                        total_frames=total_frames,
                        progress=global_frame_index / total_frames * 100
                    )

            # 4. 合成视频
            output_filename = f"restored_{Path(video_path).stem}.mp4"
            output_path = os.path.join(output_dir, output_filename)

            temp_video = os.path.join(temp_dir, "temp_video.mp4")
            if not self.ffmpeg.compose_video(
                all_restored_frames_dir, temp_video,
                fps=info.fps,
                include_audio=False
            ):
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


# RIFE frame interpolation reference (CogVideo inspired)
def rife_interpolate_video(input_path: str, output_path: str, multiplier: int = 2) -> bool:
    """Attempt RIFE-based frame interpolation for video rate enhancement.
    
    Args:
        input_path: Input video path
        output_path: Output video path  
        multiplier: Frame rate multiplier (2 = double fps)
    
    Returns:
        True if interpolation succeeded, False otherwise
    """
    try:
        from bin.integrated_app.optimization.video_processing_enhance import RIFEInterpolator
        interpolator = RIFEInterpolator()
        return interpolator.interpolate_file(input_path, output_path, multiplier)
    except Exception as e:
        import logging
        logging.getLogger(__name__).debug(f"RIFE interpolation not available: {e}")
        return False
