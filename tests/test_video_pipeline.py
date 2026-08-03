"""_VideoPipelineMixin 分段流式视频推理单元测试

覆盖:
- 分段大小对齐与内存估算辅助函数
- 内存保护: 单段内存超限时返回清晰错误
- 分段流式端到端推理 (mock 模型层, 真实 cv2 读取 + 帧写盘)
"""

import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from bin.integrated_app.engines._video_pipeline import _VideoPipelineMixin
from bin.integrated_app.video_processor import VideoInfo


class MockVideoEngine(_VideoPipelineMixin):
    """Mock 引擎: 重载模型相关方法, 复用分段流式主逻辑"""

    def __init__(self, video_info, *, config=None):
        self._loaded = True
        self.device = "cpu"
        self.config = config or {}
        self._progress_callback = None
        self._vram_monitor = None  # type: ignore[assignment]
        self._blockswap_active = False
        self.model_size = "3b"
        self.precision = "fp16"
        self._ffmpeg = MagicMock()
        self._ffmpeg.get_video_info.return_value = video_info
        self._ffmpeg.compose_video.return_value = True
        self.vae = MagicMock()
        self.dit = None
        self._vae_checkpoint_path = "fake_vae.safetensors"
        self._model_config = {}
        self._dit_model_size = "3b"
        self._dit_checkpoint_path = "fake_dit.safetensors"
        self._dit_precision = "fp16"
        self._inf = {
            "max_resolution": 0,
            "seed": 42,
            "cfg_scale": 1.0,
            "cfg_rescale": 0.0,
            "sample_steps": 1,
            "color_correction": "none",
            "input_noise_scale": 0.0,
            "latent_noise_scale": 0.0,
            "temporal_segment_size": 0,
            "temporal_segment_overlap": 8,
            "blocks_to_swap": 32,
            "swap_io_components": True,
            "offload_device": "cpu",
            "attention_mode": "sdpa",
            "restoration_guidance_scale": 0.0,
            "inference_mode": "distilled",
        }

    def _check_cancelled(self, stage):
        return None

    def _reset_cancel_token(self):
        return None

    def _cleanup_after_error(self):
        self.dit = None
        self.vae = None

    def _get_inference_config(self, **kwargs):
        inf = dict(self._inf)
        for k, v in kwargs.items():
            if v is not None:
                inf[k] = v
        return inf

    def _vae_encode(self, samples):
        return [samples[0]]

    def _vae_decode(self, latents):
        return [latents[0]]

    def _generation_step(self, **kwargs):
        return [kwargs["cond_latents"][0]]

    def _get_text_embeds(self):
        return {"texts_pos": [], "texts_neg": []}

    def _load_vae_model(self, **kwargs):
        self.vae = MagicMock()
        return self.vae

    def _load_dit_model(self, **kwargs):
        self.dit = SimpleNamespace()
        return self.dit

    def _destroy_dit(self):
        self.dit = None

    def _destroy_vae(self):
        self.vae = None


def _make_test_video(path, n_frames, w=64, h=64):
    """生成实帧测试视频 (cv2 MJPG/avi, 保证可回读)"""
    fourcc = cv2.VideoWriter_fourcc(*"MJPG")  # type: ignore[attr-defined]
    writer = cv2.VideoWriter(str(path), fourcc, 30.0, (w, h))
    for i in range(n_frames):
        frame = np.full((h, w, 3), (i * 3) % 256, dtype=np.uint8)
        writer.write(frame)
    writer.release()
    return path


def _make_video_info(path, frame_count, width=64, height=64):
    return VideoInfo(
        path=str(path),
        width=width,
        height=height,
        fps=30.0,
        frame_count=frame_count,
        duration=frame_count / 30.0,
        codec="mjpeg",
        has_audio=False,
    )


def _sorted_frame_names(frames_dir):
    return sorted(f for f in os.listdir(frames_dir) if f.startswith("frame_"))


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


class TestAlignSegmentSize:
    def test_aligned_value_unchanged(self):
        assert _VideoPipelineMixin._align_segment_size(25) == 25
        assert _VideoPipelineMixin._align_segment_size(9) == 9

    def test_unaligned_value_adjusted(self):
        # 26 -> 25, 24 -> 21, 27 -> 25
        assert _VideoPipelineMixin._align_segment_size(26) == 25
        assert _VideoPipelineMixin._align_segment_size(24) == 21
        assert _VideoPipelineMixin._align_segment_size(27) == 25

    def test_edge_values(self):
        assert _VideoPipelineMixin._align_segment_size(1) == 1
        assert _VideoPipelineMixin._align_segment_size(0) == 1


class TestEstimateSegmentMemory:
    def test_positive_estimate(self):
        engine = MockVideoEngine(_make_video_info("x.mp4", 10))
        gb = engine._estimate_segment_memory(25, 1080, 1920)
        assert gb > 0
        # 25 帧 1080p float32 的峰值应显著大于 1 帧
        assert gb > engine._estimate_segment_memory(1, 1080, 1920)

    def test_zero_resolution_guarded(self):
        engine = MockVideoEngine(_make_video_info("x.mp4", 10))
        assert engine._estimate_segment_memory(25, 0, 0) > 0


class TestChooseSegmentSize:
    def test_requested_size_preferred(self):
        engine = MockVideoEngine(_make_video_info("x.mp4", 100))
        with patch.object(engine, "_available_ram_gb", return_value=16.0):
            seg = engine._choose_segment_size(None, 1080, 1920, requested=25)
        assert seg == 25

    def test_default_size(self):
        engine = MockVideoEngine(_make_video_info("x.mp4", 100))
        with patch.object(engine, "_available_ram_gb", return_value=16.0):
            seg = engine._choose_segment_size(None, 1080, 1920, requested=0)
        assert seg == 25

    def test_capped_by_ram(self):
        engine = MockVideoEngine(_make_video_info("x.mp4", 100))
        # 可用内存极小 -> 段大小被压缩到 1
        with patch.object(engine, "_available_ram_gb", return_value=0.01):
            seg = engine._choose_segment_size(None, 1080, 1920, requested=0)
        assert seg == 1

    def test_always_4n_plus_1(self):
        engine = MockVideoEngine(_make_video_info("x.mp4", 100))
        with patch.object(engine, "_available_ram_gb", return_value=16.0):
            for requested in (1, 5, 9, 25, 100):
                seg = engine._choose_segment_size(None, 1080, 1920, requested=requested)
                assert seg >= 1
                assert (seg - 1) % 4 == 0


# ---------------------------------------------------------------------------
# 内存保护
# ---------------------------------------------------------------------------


class TestMemoryProtection:
    def test_insufficient_ram_rejects_cleanly(self, tmp_path):
        info = _make_video_info("x.mp4", 1000, width=7680, height=4320)
        engine = MockVideoEngine(info)
        with (
            patch.object(engine, "_available_ram_gb", return_value=0.05),
            patch("bin.integrated_app.engines._video_pipeline._check_memory", return_value=0.0),
            patch("bin.integrated_app.engines._video_pipeline._log_memory"),
        ):
            result = engine._infer_video_impl("x.mp4", str(tmp_path))
        assert not result.success
        assert result.error is not None
        assert "无法安全处理" in result.error

    def test_video_info_invalid_returns_error(self, tmp_path):
        info = _make_video_info("x.mp4", 0)  # frame_count=0
        engine = MockVideoEngine(info)
        with (
            patch("bin.integrated_app.engines._video_pipeline._check_memory", return_value=0.0),
            patch("bin.integrated_app.engines._video_pipeline._log_memory"),
        ):
            result = engine._infer_video_impl("x.mp4", str(tmp_path))
        assert not result.success


# ---------------------------------------------------------------------------
# 分段流式端到端
# ---------------------------------------------------------------------------


class TestSegmentedStreamingInference:
    def test_single_segment_short_video(self, tmp_path):
        video_path = _make_test_video(tmp_path / "input.mp4", 10, 64, 64)
        info = _make_video_info(video_path, 10, 64, 64)
        engine = MockVideoEngine(info)
        with (
            patch("bin.integrated_app.engines._video_pipeline._check_memory", return_value=0.0),
            patch("bin.integrated_app.engines._video_pipeline._log_memory"),
            patch("bin.integrated_app.engines._video_pipeline._cleanup_cuda_cache"),
            patch("bin.integrated_app.engines._video_pipeline.shutil.rmtree"),
        ):
            result = engine._infer_video_impl(str(video_path), str(tmp_path / "out"))
        assert result.success
        assert result.metadata["output_frames"] == 10
        assert result.metadata["num_segments"] == 1
        frames = _sorted_frame_names(tmp_path / "out" / "_frames")
        assert frames == [f"frame_{i:06d}.png" for i in range(10)]

    def test_multiple_segments_long_video(self, tmp_path):
        # 65 帧 > 25 帧/段 -> 触发分段 (overlap=8, stride=17, 4 段)
        video_path = _make_test_video(tmp_path / "input.mp4", 65, 64, 64)
        info = _make_video_info(video_path, 65, 64, 64)
        engine = MockVideoEngine(info)
        with (
            patch("bin.integrated_app.engines._video_pipeline._check_memory", return_value=0.0),
            patch("bin.integrated_app.engines._video_pipeline._log_memory"),
            patch("bin.integrated_app.engines._video_pipeline._cleanup_cuda_cache"),
            patch("bin.integrated_app.engines._video_pipeline.shutil.rmtree"),
        ):
            result = engine._infer_video_impl(str(video_path), str(tmp_path / "out"))
        assert result.success
        assert result.metadata["output_frames"] == 65
        assert result.metadata["num_segments"] == 4
        assert result.metadata["segment_size"] == 25
        assert result.metadata["segment_overlap"] == 8
        # 帧文件连续无缺口
        frames = _sorted_frame_names(tmp_path / "out" / "_frames")
        assert len(frames) == 65
        assert frames[0] == "frame_000000.png"
        assert frames[-1] == "frame_000064.png"
        # ffmpeg 合成被调用, 携带源视频用于音轨
        engine._ffmpeg.compose_video.assert_called_once()
        compose_kwargs = engine._ffmpeg.compose_video.call_args.kwargs
        assert compose_kwargs["source_video"] == str(video_path)
        assert compose_kwargs["include_audio"] is True
        assert compose_kwargs["fps"] == 30.0
        # 模型已销毁归还内存
        assert engine.vae is None
        assert engine.dit is None

    def test_models_destroyed_on_success(self, tmp_path):
        video_path = _make_test_video(tmp_path / "input.mp4", 10, 64, 64)
        info = _make_video_info(video_path, 10, 64, 64)
        engine = MockVideoEngine(info)
        assert engine.dit is None
        with (
            patch("bin.integrated_app.engines._video_pipeline._check_memory", return_value=0.0),
            patch("bin.integrated_app.engines._video_pipeline._log_memory"),
            patch("bin.integrated_app.engines._video_pipeline._cleanup_cuda_cache"),
            patch("bin.integrated_app.engines._video_pipeline.shutil.rmtree"),
        ):
            result = engine._infer_video_impl(str(video_path), str(tmp_path / "out"))
        assert result.success
        # DiT 被按需加载过 (首段时 dit 为 None)
        assert engine.dit is None
        assert engine.vae is None
        # 临时帧目录被清理
        engine._ffmpeg.compose_video.assert_called_once()

    def test_progress_callback_reported(self, tmp_path):
        video_path = _make_test_video(tmp_path / "input.mp4", 65, 64, 64)
        info = _make_video_info(video_path, 65, 64, 64)
        engine = MockVideoEngine(info)
        reports = []
        engine._progress_callback = lambda current_frame, total_frames, progress: reports.append(
            (current_frame, total_frames, progress)
        )
        with (
            patch("bin.integrated_app.engines._video_pipeline._check_memory", return_value=0.0),
            patch("bin.integrated_app.engines._video_pipeline._log_memory"),
            patch("bin.integrated_app.engines._video_pipeline._cleanup_cuda_cache"),
            patch("bin.integrated_app.engines._video_pipeline.shutil.rmtree"),
        ):
            result = engine._infer_video_impl(str(video_path), str(tmp_path / "out"))
        assert result.success
        # 每段结束后上报一次 (4 段)
        assert len(reports) == 4
        # 最后一段上报 100%
        assert reports[-1] == (65, 65, 100.0)
        # 单调递增
        frames = [r[0] for r in reports]
        assert frames == sorted(frames)
