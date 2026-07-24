"""WebUI / 用户交互增强模块

参考多个竞品项目的 WebUI 设计最佳实践，提供交互增强的框架与模式参考。
本模块为设计参考与框架实现，不直接绑定具体前端框架，可按需对接 Gradio 等。

竞品来源:
- SUPIR: Gradio WebUI 逐步执行 + 参数面板设计 (P1)
- Waifu2x-Extension-GUI: 文件列表管理 + 进度上报 (P1)
- clarity-upscaler: CFG Scale/Randomness/Denoising Strength 参数面板 (P1)
- DiffBIR: Accordion 分组设计 (Basic/Condition/Sampler) (P2)
- Waifu2x-Extension-GUI: 设置持久化 (P2)
- upscayl: 文件拖放支持 (P2)

Key Features:
- Gradio WebUI 设计参考: 逐步执行、参数面板、滑块对比 UI
- 文件列表管理: 表格视图状态机 + 实时进度上报
- 参数面板优化: CFG Scale/Randomness/Denoising Strength 组合设计
- Accordion 分组设计: Basic/Condition/Sampler 三组折叠面板
- 设置持久化: 用户偏好保存/加载 (config.yaml)
- 文件拖放支持: 图片/文件夹拖放添加模式
"""

import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Gradio WebUI 设计参考 (SUPIR P1)
# ---------------------------------------------------------------------------

@dataclass
class StepExecutionConfig:
    """逐步执行配置

    参考 SUPIR 的 step-by-step 执行模式:
    将复杂推理流程拆分为可独立触发、可中断的步骤，
    用户可在每步之间检查中间结果并调整参数。

    SUPIR 的核心设计:
    - Step 1: Load Image (加载输入)
    - Step 2: Stage 1 - Restoration (粗修复)
    - Step 3: Stage 2 - Enhancement (精细增强)
    - 每步可独立执行，支持"执行到此步"的交互模式

    SeedVR2 对应步骤:
    - Step 1: Load/Input (加载输入图片/视频)
    - Step 2: Preprocess (预处理: 分帧/缩放/颜色空间转换)
    - Step 3: Restore (DiT 推理修复)
    - Step 4: Postprocess (后处理: 合帧/颜色校正)
    - Step 5: Output (输出保存)
    """
    enabled: bool = True
    # 步骤定义列表
    steps: list[dict[str, Any]] = field(default_factory=lambda: [
        {"id": "load", "name": "加载输入", "description": "加载图片或视频文件"},
        {"id": "preprocess", "name": "预处理", "description": "分帧、缩放、颜色空间转换"},
        {"id": "restore", "name": "推理修复", "description": "DiT 模型推理"},
        {"id": "postprocess", "name": "后处理", "description": "合帧、颜色校正"},
        {"id": "output", "name": "输出保存", "description": "保存修复结果"},
    ])
    # 是否允许从任意步骤重新开始
    allow_restart_from_any_step: bool = True
    # 是否在每步完成后自动暂停等待用户确认
    pause_between_steps: bool = False


@dataclass
class ParameterPanelConfig:
    """参数面板配置

    参考 SUPIR 的参数面板设计:
    - 主要参数突出显示，次要参数折叠
    - 参数分组排列，逻辑清晰
    - 实时参数预览/提示
    - 参数间的联动与约束 (如 resolution 限制 denoising_strength)

    SUPIR 的面板结构:
    - Sampling Settings: 采样步数、CFG Scale、sampler
    - Stage 2 Settings: edition/starting/ending 控制图像风格
    - Restoration Settings: restoration fix 控制修复程度
    """
    # 参数分组定义
    groups: list[dict[str, Any]] = field(default_factory=lambda: [
        {
            "id": "basic",
            "name": "基本设置",
            "priority": 0,
            "default_expanded": True,
            "params": ["resolution", "seed", "sampler"],
        },
        {
            "id": "sampling",
            "name": "采样设置",
            "priority": 1,
            "default_expanded": True,
            "params": ["cfg_scale", "steps", "denoising_strength"],
        },
        {
            "id": "advanced",
            "name": "高级设置",
            "priority": 2,
            "default_expanded": False,
            "params": ["restoration_guidance", "blockswap", "vae_tiling"],
        },
    ])
    # 参数间的联动约束 (参数A变化时影响参数B的范围)
    constraints: list[dict[str, Any]] = field(default_factory=lambda: [
        {
            "source": "resolution",
            "target": "denoising_strength",
            "rule": "resolution > 2048 时建议 denoising_strength >= 0.5",
        },
        {
            "source": "blockswap",
            "target": "steps",
            "rule": "blockswap 启用时建议 steps <= 30 以避免超时",
        },
    ])


@dataclass
class SliderComparisonConfig:
    """滑块对比 UI 配置

    参考 SUPIR 的 Before/After 滑块对比设计:
    - 同一视图中拖动滑块对比修复前后
    - 支持水平/垂直分割线
    - 支持缩放查看细节
    - 适配图片和视频帧

    典型实现: Gradio ImageSlider / ImageComparison 组件
    """
    enabled: bool = True
    # 分割线方向: "horizontal" | "vertical"
    direction: str = "horizontal"
    # 默认分割位置 (0.0-1.0)
    default_position: float = 0.5
    # 是否支持缩放
    zoom_enabled: bool = True
    # 标签
    before_label: str = "修复前"
    after_label: str = "修复后"


class WebUIDesignReference:
    """Gradio WebUI 设计参考集合

    整合 SUPIR 风格的 WebUI 设计模式，作为前端实现的参考。

    Usage:
        ref = WebUIDesignReference()
        step_config = ref.step_execution
        panel_config = ref.parameter_panel
        slider_config = ref.slider_comparison
    """

    def __init__(
        self,
        step_execution: StepExecutionConfig | None = None,
        parameter_panel: ParameterPanelConfig | None = None,
        slider_comparison: SliderComparisonConfig | None = None,
    ):
        self.step_execution = step_execution or StepExecutionConfig()
        self.parameter_panel = parameter_panel or ParameterPanelConfig()
        self.slider_comparison = slider_comparison or SliderComparisonConfig()
        logger.debug("WebUI 设计参考已初始化")


# ---------------------------------------------------------------------------
# 2. 文件列表管理 + 进度上报 (Waifu2x-Extension-GUI P1)
# ---------------------------------------------------------------------------

class FileItemStatus(str, Enum):
    """文件项处理状态

    参考 Waifu2x-Extension-GUI 的文件处理状态机:
    - Pending: 等待处理
    - Processing: 正在处理
    - Done: 处理完成
    - Failed: 处理失败
    - Skipped: 跳过 (用户取消或不满足条件)
    - Cancelled: 取消
    """
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


@dataclass
class FileItem:
    """文件列表中单个文件条目

    参考 Waifu2x-Extension-GUI 的文件表格视图:
    每个文件项包含路径、状态、进度、耗时等信息，
    支持表格视图中实时更新。

    Attributes:
        path: 文件路径
        name: 文件名
        status: 当前处理状态
        progress: 处理进度 (0.0-1.0)
        current_step: 当前步骤描述
        error_message: 错误信息 (失败时)
        start_time: 开始处理时间戳
        end_time: 结束处理时间戳
        output_path: 输出文件路径 (完成时)
        file_size_mb: 文件大小 (MB)
    """
    path: str
    name: str
    status: FileItemStatus = FileItemStatus.PENDING
    progress: float = 0.0
    current_step: str = ""
    error_message: str = ""
    start_time: float = 0.0
    end_time: float = 0.0
    output_path: str = ""
    file_size_mb: float = 0.0

    @property
    def elapsed_seconds(self) -> float:
        """已用时间 (秒)"""
        if self.start_time == 0:
            return 0.0
        end = self.end_time if self.end_time > 0 else time.time()
        return end - self.start_time

    def to_dict(self) -> dict[str, Any]:
        """转换为前端友好的字典格式"""
        return {
            "path": self.path,
            "name": self.name,
            "status": self.status.value,
            "progress": round(self.progress, 3),
            "current_step": self.current_step,
            "error_message": self.error_message,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "output_path": self.output_path,
            "file_size_mb": round(self.file_size_mb, 2),
        }


@dataclass
class FileListProgress:
    """文件列表整体进度

    参考 Waifu2x-Extension-GUI 的批量进度上报:
    - 总文件数 / 已完成 / 失败 / 处理中
    - 整体进度百分比
    - 预估剩余时间
    """
    total: int = 0
    done: int = 0
    failed: int = 0
    processing: int = 0
    pending: int = 0
    skipped: int = 0

    @property
    def overall_progress(self) -> float:
        """整体进度 (0.0-1.0)"""
        if self.total == 0:
            return 0.0
        completed = self.done + self.failed + self.skipped
        return completed / self.total

    @property
    def is_complete(self) -> bool:
        """是否全部处理完毕"""
        return self.total > 0 and (self.done + self.failed + self.skipped) == self.total

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "done": self.done,
            "failed": self.failed,
            "processing": self.processing,
            "pending": self.pending,
            "skipped": self.skipped,
            "overall_progress": round(self.overall_progress, 3),
            "is_complete": self.is_complete,
        }


class FileListManager:
    """文件列表管理器

    参考 Waifu2x-Extension-GUI 的文件列表状态机:
    - 表格视图管理多个文件的修复状态
    - 实时进度上报 (单文件进度 + 整体进度)
    - 支持添加/移除/重新排队文件
    - 状态变更回调通知

    Usage:
        manager = FileListManager()

        # 添加文件
        manager.add_file("/path/to/image.png")

        # 更新进度
        manager.update_progress("/path/to/image.png", progress=0.5, step="DiT 采样")

        # 标记完成
        manager.mark_done("/path/to/image.png", output_path="/path/to/output.png")

        # 获取整体进度
        progress = manager.get_overall_progress()
    """

    def __init__(self):
        self._files: dict[str, FileItem] = {}
        self._order: list[str] = []  # 保持插入顺序
        self._callbacks: list[callable] = []

    def add_file(self, file_path: str) -> FileItem:
        """添加文件到列表

        Args:
            file_path: 文件路径

        Returns:
            创建的 FileItem
        """
        path = str(file_path)
        if path in self._files:
            logger.debug(f"文件已存在，跳过: {path}")
            return self._files[path]

        name = os.path.basename(path)
        file_size_mb = 0.0
        try:
            if os.path.exists(path):
                file_size_mb = os.path.getsize(path) / (1024 * 1024)
        except OSError:
            pass

        item = FileItem(path=path, name=name, file_size_mb=file_size_mb)
        self._files[path] = item
        self._order.append(path)
        logger.debug(f"文件已添加: {name} ({file_size_mb:.2f}MB)")
        self._notify_callbacks(item)
        return item

    def add_files(self, file_paths: list[str]) -> list[FileItem]:
        """批量添加文件"""
        return [self.add_file(p) for p in file_paths]

    def remove_file(self, file_path: str) -> bool:
        """从列表中移除文件

        Args:
            file_path: 文件路径

        Returns:
            是否成功移除
        """
        path = str(file_path)
        if path not in self._files:
            return False

        item = self._files[path]
        # 不允许移除正在处理中的文件
        if item.status == FileItemStatus.PROCESSING:
            logger.warning(f"无法移除正在处理的文件: {path}")
            return False

        del self._files[path]
        self._order.remove(path)
        logger.debug(f"文件已移除: {path}")
        return True

    def update_progress(
        self,
        file_path: str,
        progress: float | None = None,
        step: str | None = None,
    ) -> bool:
        """更新文件处理进度

        Args:
            file_path: 文件路径
            progress: 进度值 (0.0-1.0)
            step: 当前步骤描述

        Returns:
            是否成功更新
        """
        path = str(file_path)
        if path not in self._files:
            return False

        item = self._files[path]
        if item.status == FileItemStatus.PENDING:
            item.status = FileItemStatus.PROCESSING
            item.start_time = time.time()

        if progress is not None:
            item.progress = max(0.0, min(1.0, progress))
        if step is not None:
            item.current_step = step

        self._notify_callbacks(item)
        return True

    def mark_done(self, file_path: str, output_path: str = "") -> bool:
        """标记文件处理完成"""
        path = str(file_path)
        if path not in self._files:
            return False

        item = self._files[path]
        item.status = FileItemStatus.DONE
        item.progress = 1.0
        item.end_time = time.time()
        item.output_path = output_path
        item.current_step = "完成"
        logger.info(f"文件处理完成: {item.name} ({item.elapsed_seconds:.1f}s)")
        self._notify_callbacks(item)
        return True

    def mark_failed(self, file_path: str, error_message: str = "") -> bool:
        """标记文件处理失败"""
        path = str(file_path)
        if path not in self._files:
            return False

        item = self._files[path]
        item.status = FileItemStatus.FAILED
        item.end_time = time.time()
        item.error_message = error_message
        item.current_step = "失败"
        logger.error(f"文件处理失败: {item.name} - {error_message}")
        self._notify_callbacks(item)
        return True

    def mark_skipped(self, file_path: str, reason: str = "") -> bool:
        """标记文件跳过"""
        path = str(file_path)
        if path not in self._files:
            return False

        item = self._files[path]
        item.status = FileItemStatus.SKIPPED
        item.current_step = f"跳过: {reason}" if reason else "跳过"
        logger.debug(f"文件已跳过: {item.name} - {reason}")
        self._notify_callbacks(item)
        return True

    def cancel_file(self, file_path: str) -> bool:
        """取消文件处理"""
        path = str(file_path)
        if path not in self._files:
            return False

        item = self._files[path]
        if item.status not in (FileItemStatus.PENDING, FileItemStatus.PROCESSING):
            return False

        item.status = FileItemStatus.CANCELLED
        item.end_time = time.time()
        item.current_step = "已取消"
        logger.debug(f"文件已取消: {item.name}")
        self._notify_callbacks(item)
        return True

    def retry_file(self, file_path: str) -> bool:
        """重新排队失败/取消的文件"""
        path = str(file_path)
        if path not in self._files:
            return False

        item = self._files[path]
        if item.status not in (FileItemStatus.FAILED, FileItemStatus.CANCELLED):
            return False

        item.status = FileItemStatus.PENDING
        item.progress = 0.0
        item.current_step = ""
        item.error_message = ""
        item.start_time = 0.0
        item.end_time = 0.0
        item.output_path = ""
        logger.debug(f"文件已重新排队: {item.name}")
        self._notify_callbacks(item)
        return True

    def get_file(self, file_path: str) -> FileItem | None:
        """获取文件条目"""
        return self._files.get(str(file_path))

    def get_all_files(self) -> list[FileItem]:
        """获取所有文件条目 (按添加顺序)"""
        return [self._files[p] for p in self._order if p in self._files]

    def get_overall_progress(self) -> FileListProgress:
        """获取整体进度统计"""
        progress = FileListProgress()
        progress.total = len(self._files)
        for item in self._files.values():
            if item.status == FileItemStatus.DONE:
                progress.done += 1
            elif item.status == FileItemStatus.FAILED:
                progress.failed += 1
            elif item.status == FileItemStatus.PROCESSING:
                progress.processing += 1
            elif item.status == FileItemStatus.PENDING:
                progress.pending += 1
            elif item.status == FileItemStatus.SKIPPED:
                progress.skipped += 1
            elif item.status == FileItemStatus.CANCELLED:
                progress.skipped += 1
        return progress

    def get_next_pending(self) -> FileItem | None:
        """获取下一个待处理文件"""
        for p in self._order:
            item = self._files.get(p)
            if item and item.status == FileItemStatus.PENDING:
                return item
        return None

    def clear(self):
        """清空文件列表"""
        self._files.clear()
        self._order.clear()

    def on_change(self, callback: callable):
        """注册状态变更回调

        Args:
            callback: 回调函数，接收 FileItem 参数
        """
        self._callbacks.append(callback)

    def _notify_callbacks(self, item: FileItem):
        """通知所有回调"""
        for cb in self._callbacks:
            try:
                cb(item)
            except Exception as e:
                logger.debug(f"文件列表回调异常: {e}")


# ---------------------------------------------------------------------------
# 3. 参数面板优化 (clarity-upscaler P1)
# ---------------------------------------------------------------------------

@dataclass
class ParameterDefinition:
    """参数定义

    参考 clarity-upscaler 的参数面板设计:
    每个参数有明确的类型、范围、默认值和联动关系。
    """
    id: str
    name: str
    param_type: str  # "slider" | "number" | "select" | "checkbox" | "text"
    default: Any = None
    min_value: float | None = None
    max_value: float | None = None
    step: float | None = None
    choices: list[str] | None = None
    description: str = ""
    group: str = "basic"
    # 是否为高级参数 (默认折叠)
    advanced: bool = False


@dataclass
class ParameterComboRule:
    """参数组合规则

    参考 clarity-upscaler 的 CFG Scale / Randomness / Denoising Strength 组合设计:
    - 三者之间存在最优组合区间
    - 不同任务类型推荐不同参数组合
    - 参数变化时实时提示推荐值

    典型组合:
    - 照片修复: CFG=3.0, Randomness=0.3, Denoising=0.6
    - 艺术增强: CFG=5.0, Randomness=0.7, Denoising=0.8
    - 轻度去噪: CFG=2.0, Randomness=0.1, Denoising=0.3
    """
    name: str
    description: str
    preset_values: dict[str, Any]
    # 推荐的参数范围约束
    recommended_ranges: dict[str, tuple[float, float]] = field(default_factory=dict)
    # 适用场景描述
    use_case: str = ""


class ParameterPanelOptimizer:
    """参数面板优化器

    参考 clarity-upscaler 的参数面板组合设计:
    - 定义参数间的联动规则
    - 提供预设组合 (Preset)
    - 根据参数值实时推荐最优组合

    Usage:
        optimizer = ParameterPanelOptimizer()

        # 添加参数定义
        optimizer.add_param(ParameterDefinition(
            id="cfg_scale", name="CFG Scale", param_type="slider",
            default=3.0, min_value=1.0, max_value=10.0, step=0.5,
        ))

        # 添加预设组合
        optimizer.add_preset(ParameterComboRule(
            name="照片修复", description="适合真实照片修复",
            preset_values={"cfg_scale": 3.0, "denoising_strength": 0.6},
            recommended_ranges={"cfg_scale": (2.0, 5.0), "denoising_strength": (0.4, 0.8)},
            use_case="真实照片修复",
        ))

        # 获取推荐组合
        recommendations = optimizer.get_recommendations(cfg_scale=3.0)
    """

    def __init__(self):
        self._params: dict[str, ParameterDefinition] = {}
        self._presets: list[ParameterComboRule] = []

    def add_param(self, param: ParameterDefinition):
        """添加参数定义"""
        self._params[param.id] = param
        logger.debug(f"参数已注册: {param.id} ({param.name})")

    def add_preset(self, preset: ParameterComboRule):
        """添加预设组合"""
        self._presets.append(preset)
        logger.debug(f"预设已添加: {preset.name}")

    def get_param(self, param_id: str) -> ParameterDefinition | None:
        """获取参数定义"""
        return self._params.get(param_id)

    def get_all_params(self) -> list[ParameterDefinition]:
        """获取所有参数定义"""
        return list(self._params.values())

    def get_presets(self) -> list[ParameterComboRule]:
        """获取所有预设组合"""
        return list(self._presets)

    def get_recommendations(self, **current_values) -> list[dict[str, Any]]:
        """根据当前参数值获取推荐预设

        Args:
            **current_values: 当前参数值

        Returns:
            匹配度排序的推荐列表
        """
        recommendations = []
        for preset in self._presets:
            # 计算当前值与预设值的匹配度
            match_score = 0.0
            total_params = 0
            for key, preset_val in preset.preset_values.items():
                if key in current_values:
                    current_val = current_values[key]
                    if isinstance(current_val, (int, float)) and isinstance(preset_val, (int, float)):
                        # 数值参数: 距离越近匹配度越高
                        param_def = self._params.get(key)
                        if param_def and param_def.min_value is not None and param_def.max_value is not None:
                            range_size = param_def.max_value - param_def.min_value
                            if range_size > 0:
                                distance = abs(current_val - preset_val) / range_size
                                match_score += 1.0 - min(distance, 1.0)
                                total_params += 1
                    elif current_val == preset_val:
                        match_score += 1.0
                        total_params += 1

            if total_params > 0:
                match_ratio = match_score / total_params
            else:
                match_ratio = 0.0

            recommendations.append({
                "preset": preset,
                "match_score": round(match_ratio, 3),
                "use_case": preset.use_case,
            })

        recommendations.sort(key=lambda x: x["match_score"], reverse=True)
        return recommendations

    def validate_values(self, values: dict[str, Any]) -> dict[str, list[str]]:
        """验证参数值是否在合法范围内

        Args:
            values: 参数值字典

        Returns:
            参数ID到错误信息列表的映射
        """
        errors: dict[str, list[str]] = {}
        for key, value in values.items():
            param = self._params.get(key)
            if param is None:
                continue
            param_errors = []
            if param.min_value is not None and isinstance(value, (int, float)):
                if value < param.min_value:
                    param_errors.append(f"值 {value} 小于最小值 {param.min_value}")
            if param.max_value is not None and isinstance(value, (int, float)):
                if value > param.max_value:
                    param_errors.append(f"值 {value} 大于最大值 {param.max_value}")
            if param.choices is not None and value not in param.choices:
                param_errors.append(f"值 '{value}' 不在可选范围 {param.choices} 中")
            if param_errors:
                errors[key] = param_errors
        return errors


# ---------------------------------------------------------------------------
# 4. Accordion 分组设计 (DiffBIR P2)
# ---------------------------------------------------------------------------

@dataclass
class AccordionGroup:
    """折叠面板分组

    参考 DiffBIR 的三组折叠面板设计:
    - Basic: 基础参数 (分辨率、种子、采样器等)
    - Condition: 条件控制参数 (CFG Scale、引导、提示词等)
    - Sampler: 采样器参数 (步数、调度器、去噪强度等)

    每组可独立展开/折叠，减少界面信息过载。
    """
    id: str
    name: str
    description: str = ""
    default_expanded: bool = True
    priority: int = 0  # 显示顺序，数字越小越靠前
    param_ids: list[str] = field(default_factory=list)


class AccordionLayoutManager:
    """折叠面板布局管理器

    参考 DiffBIR 的 Accordion 分组设计模式:
    将参数按功能分组，每组可折叠，减少界面复杂度。
    默认三组: Basic / Condition / Sampler。

    Usage:
        manager = AccordionLayoutManager()

        # 使用默认分组
        groups = manager.get_layout()

        # 自定义分组
        manager.add_group(AccordionGroup(
            id="custom", name="自定义参数", default_expanded=False, priority=10,
        ))

        # 按布局顺序获取所有分组
        layout = manager.get_layout()
    """

    def __init__(self):
        self._groups: dict[str, AccordionGroup] = {}
        self._setup_default_groups()

    def _setup_default_groups(self):
        """设置默认三组折叠面板 (DiffBIR 风格)"""
        self.add_group(AccordionGroup(
            id="basic",
            name="基本设置",
            description="分辨率、种子等基础参数",
            default_expanded=True,
            priority=0,
        ))
        self.add_group(AccordionGroup(
            id="condition",
            name="条件控制",
            description="CFG Scale、引导强度、提示词等条件参数",
            default_expanded=True,
            priority=1,
        ))
        self.add_group(AccordionGroup(
            id="sampler",
            name="采样器",
            description="采样步数、调度器、去噪强度等采样参数",
            default_expanded=False,
            priority=2,
        ))

    def add_group(self, group: AccordionGroup):
        """添加折叠面板分组"""
        self._groups[group.id] = group
        logger.debug(f"折叠面板分组已添加: {group.name} (优先级={group.priority})")

    def remove_group(self, group_id: str) -> bool:
        """移除折叠面板分组"""
        if group_id in self._groups:
            del self._groups[group_id]
            return True
        return False

    def get_group(self, group_id: str) -> AccordionGroup | None:
        """获取指定分组"""
        return self._groups.get(group_id)

    def get_layout(self) -> list[AccordionGroup]:
        """获取按优先级排序的布局"""
        return sorted(self._groups.values(), key=lambda g: g.priority)

    def assign_param(self, group_id: str, param_id: str) -> bool:
        """将参数分配到指定分组

        Args:
            group_id: 分组ID
            param_id: 参数ID

        Returns:
            是否成功分配
        """
        group = self._groups.get(group_id)
        if group is None:
            logger.warning(f"分组不存在: {group_id}")
            return False
        if param_id not in group.param_ids:
            group.param_ids.append(param_id)
        return True


# ---------------------------------------------------------------------------
# 5. 设置持久化 (Waifu2x-Extension-GUI P2)
# ---------------------------------------------------------------------------

@dataclass
class UserPreferences:
    """用户偏好设置

    参考 Waifu2x-Extension-GUI 的设置持久化:
    将用户在 WebUI 中调整的参数偏好保存到 config.yaml，
    下次启动时自动恢复。

    持久化的设置包括:
    - 推理参数默认值 (分辨率、CFG Scale、步数等)
    - UI 偏好 (折叠面板状态、主题等)
    - 输出偏好 (格式、路径模板等)
    - 性能偏好 (BlockSwap 开关、VAE 分块大小等)
    """
    # 推理参数默认值
    default_resolution: int = 2048
    default_cfg_scale: float = 3.0
    default_steps: int = 20
    default_denoising_strength: float = 0.6
    default_sampler: str = "dpmpp_2m_sde"
    default_seed: int = -1  # -1 表示随机

    # UI 偏好
    accordion_expanded_groups: list[str] = field(default_factory=lambda: ["basic", "condition"])
    slider_comparison_enabled: bool = True
    step_execution_enabled: bool = False

    # 输出偏好
    output_format: str = "png"  # "png" | "jpg" | "webp"
    output_quality: int = 95  # jpg/webp 质量
    output_path_template: str = "{input_dir}/restored/{input_name}{ext}"

    # 性能偏好
    blockswap_enabled: bool = False
    blocks_to_swap: int = 0
    vae_tiling_enabled: bool = False
    vae_tile_size: int = 512

    # 最近使用的模型路径
    recent_model_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        """转换为字典 (用于序列化)"""
        return {
            "default_resolution": self.default_resolution,
            "default_cfg_scale": self.default_cfg_scale,
            "default_steps": self.default_steps,
            "default_denoising_strength": self.default_denoising_strength,
            "default_sampler": self.default_sampler,
            "default_seed": self.default_seed,
            "accordion_expanded_groups": self.accordion_expanded_groups,
            "slider_comparison_enabled": self.slider_comparison_enabled,
            "step_execution_enabled": self.step_execution_enabled,
            "output_format": self.output_format,
            "output_quality": self.output_quality,
            "output_path_template": self.output_path_template,
            "blockswap_enabled": self.blockswap_enabled,
            "blocks_to_swap": self.blocks_to_swap,
            "vae_tiling_enabled": self.vae_tiling_enabled,
            "vae_tile_size": self.vae_tile_size,
            "recent_model_path": self.recent_model_path,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UserPreferences":
        """从字典创建 (用于反序列化)"""
        prefs = cls()
        for key, value in data.items():
            if hasattr(prefs, key):
                setattr(prefs, key, value)
        return prefs


class SettingsPersistence:
    """设置持久化管理器

    参考 Waifu2x-Extension-GUI 的设置保存/加载:
    将用户偏好保存到 config.yaml 的 user_preferences 段，
    支持读取、保存和重置操作。

    约束: 与项目现有 config.yaml 集成，不覆盖其他配置段。

    Usage:
        persistence = SettingsPersistence(config_path="config.yaml")

        # 加载用户偏好
        prefs = persistence.load()

        # 修改并保存
        prefs.default_cfg_scale = 5.0
        persistence.save(prefs)

        # 重置为默认
        persistence.reset()
    """

    # config.yaml 中的偏好设置段键名
    PREFERENCES_KEY = "user_preferences"

    def __init__(self, config_path: str | None = None):
        """初始化设置持久化管理器

        Args:
            config_path: config.yaml 路径，None 则使用项目默认路径
        """
        if config_path is None:
            # 默认路径: 项目根目录/config.yaml
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))
            )))
            config_path = os.path.join(project_root, "config.yaml")

        self._config_path = config_path
        self._prefs: UserPreferences | None = None
        logger.debug(f"设置持久化管理器已初始化: {config_path}")

    def load(self) -> UserPreferences:
        """从 config.yaml 加载用户偏好

        Returns:
            UserPreferences 实例 (加载失败时返回默认值)
        """
        if not os.path.exists(self._config_path):
            logger.debug(f"配置文件不存在，使用默认偏好: {self._config_path}")
            self._prefs = UserPreferences()
            return self._prefs

        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}

            prefs_data = config.get(self.PREFERENCES_KEY, {})
            if prefs_data:
                self._prefs = UserPreferences.from_dict(prefs_data)
                logger.info(f"用户偏好已加载: {len(prefs_data)} 项设置")
            else:
                self._prefs = UserPreferences()
                logger.debug("配置文件中无用户偏好段，使用默认值")

        except Exception as e:
            logger.warning(f"加载用户偏好失败: {e}，使用默认值")
            self._prefs = UserPreferences()

        return self._prefs

    def save(self, prefs: UserPreferences) -> bool:
        """保存用户偏好到 config.yaml

        只更新 user_preferences 段，不影响其他配置。

        Args:
            prefs: 要保存的用户偏好

        Returns:
            是否保存成功
        """
        try:
            # 读取现有配置
            config: dict[str, Any] = {}
            if os.path.exists(self._config_path):
                with open(self._config_path, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f) or {}

            # 更新偏好段
            config[self.PREFERENCES_KEY] = prefs.to_dict()

            # 写回文件
            with open(self._config_path, "w", encoding="utf-8") as f:
                yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

            self._prefs = prefs
            logger.info(f"用户偏好已保存: {self._config_path}")
            return True

        except Exception as e:
            logger.error(f"保存用户偏好失败: {e}")
            return False

    def reset(self) -> UserPreferences:
        """重置用户偏好为默认值

        Returns:
            重置后的默认偏好
        """
        self._prefs = UserPreferences()
        self.save(self._prefs)
        logger.info("用户偏好已重置为默认值")
        return self._prefs

    @property
    def current(self) -> UserPreferences:
        """获取当前偏好 (未加载则自动加载)"""
        if self._prefs is None:
            return self.load()
        return self._prefs


# ---------------------------------------------------------------------------
# 6. 文件拖放支持 (upscayl P2)
# ---------------------------------------------------------------------------

@dataclass
class DropTarget:
    """拖放目标区域定义

    参考 upscayl 的拖放交互设计:
    - 支持图片和文件夹拖放
    - 拖放区域视觉反馈 (高亮/动画)
    - 文件类型过滤
    - 递归扫描文件夹
    """
    # 目标区域标识
    id: str
    # 接受的文件扩展名 (空列表表示接受所有)
    accepted_extensions: list[str] = field(default_factory=list)
    # 是否接受文件夹拖放
    accept_folders: bool = True
    # 是否递归扫描子文件夹
    recursive_scan: bool = False
    # 最大文件大小限制 (MB, 0 = 无限制)
    max_file_size_mb: float = 0.0
    # 最大文件数量限制 (0 = 无限制)
    max_file_count: int = 0


@dataclass
class DropResult:
    """拖放操作结果"""
    accepted_files: list[str] = field(default_factory=list)
    rejected_files: list[dict[str, str]] = field(default_factory=list)
    # 被拒绝的原因: "extension" | "size" | "count"
    rejection_reasons: dict[str, str] = field(default_factory=dict)


class FileDropHandler:
    """文件拖放处理器

    参考 upscayl 的拖放交互模式:
    - 验证拖入的文件类型和大小
    - 递归扫描文件夹
    - 与 FileListManager 集成
    - 提供拖放事件的回调接口

    此类处理后端逻辑，前端交互由 UI 框架实现。

    Usage:
        handler = FileDropHandler()

        # 定义目标区域
        handler.add_target(DropTarget(
            id="image_drop",
            accepted_extensions=[".png", ".jpg", ".jpeg", ".webp", ".bmp"],
            accept_folders=True,
        ))

        # 处理拖放
        result = handler.handle_drop("image_drop", ["/path/to/image.png", "/path/to/folder"])

        # 获取接受的文件列表
        print(result.accepted_files)
    """

    # 支持的图片扩展名
    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"}
    # 支持的视频扩展名
    VIDEO_EXTENSIONS = {".mp4", ".avi", ".mkv", ".mov", ".webm", ".flv", ".wmv"}

    def __init__(self, file_list_manager: FileListManager | None = None):
        """初始化拖放处理器

        Args:
            file_list_manager: 可选的 FileListManager，自动将接受的文件添加到列表
        """
        self._targets: dict[str, DropTarget] = {}
        self._file_list_manager = file_list_manager

    def add_target(self, target: DropTarget):
        """添加拖放目标区域"""
        self._targets[target.id] = target
        logger.debug(f"拖放目标已添加: {target.id}")

    def get_target(self, target_id: str) -> DropTarget | None:
        """获取拖放目标"""
        return self._targets.get(target_id)

    def handle_drop(self, target_id: str, paths: list[str]) -> DropResult:
        """处理拖放操作

        验证拖入的路径列表，过滤无效文件，返回接受/拒绝结果。

        Args:
            target_id: 拖放目标区域ID
            paths: 拖入的文件/文件夹路径列表

        Returns:
            DropResult 包含接受的文件和被拒绝的文件
        """
        target = self._targets.get(target_id)
        if target is None:
            logger.warning(f"未知的拖放目标: {target_id}")
            return DropResult()

        accepted: list[str] = []
        rejected: list[dict[str, str]] = []
        rejection_reasons: dict[str, str] = {}

        # 收集所有文件路径 (展开文件夹)
        all_files: list[str] = []
        for path in paths:
            path_obj = Path(path)
            if path_obj.is_file():
                all_files.append(str(path_obj.resolve()))
            elif path_obj.is_dir() and target.accept_folders:
                scanned = self._scan_folder(path_obj, target.recursive_scan)
                all_files.extend(scanned)
            else:
                rejected.append({"path": path, "reason": "不是文件或文件夹"})
                rejection_reasons[path] = "invalid_path"

        # 过滤文件
        current_count = len(accepted)
        for file_path in all_files:
            # 检查扩展名
            if target.accepted_extensions:
                ext = Path(file_path).suffix.lower()
                if ext not in target.accepted_extensions:
                    rejected.append({"path": file_path, "reason": f"不支持的文件类型: {ext}"})
                    rejection_reasons[file_path] = "extension"
                    continue

            # 检查文件大小
            if target.max_file_size_mb > 0:
                try:
                    size_mb = os.path.getsize(file_path) / (1024 * 1024)
                    if size_mb > target.max_file_size_mb:
                        rejected.append({
                            "path": file_path,
                            "reason": f"文件过大: {size_mb:.1f}MB > {target.max_file_size_mb:.1f}MB",
                        })
                        rejection_reasons[file_path] = "size"
                        continue
                except OSError:
                    rejected.append({"path": file_path, "reason": "无法读取文件大小"})
                    rejection_reasons[file_path] = "size"
                    continue

            # 检查文件数量
            if target.max_file_count > 0 and current_count >= target.max_file_count:
                rejected.append({"path": file_path, "reason": f"超过最大文件数: {target.max_file_count}"})
                rejection_reasons[file_path] = "count"
                continue

            accepted.append(file_path)
            current_count += 1

        # 自动添加到 FileListManager
        if self._file_list_manager is not None:
            self._file_list_manager.add_files(accepted)

        logger.debug(
            f"拖放处理完成: 接受 {len(accepted)} 个文件, "
            f"拒绝 {len(rejected)} 个文件"
        )
        return DropResult(
            accepted_files=accepted,
            rejected_files=rejected,
            rejection_reasons=rejection_reasons,
        )

    def _scan_folder(self, folder: Path, recursive: bool = False) -> list[str]:
        """扫描文件夹中的文件

        Args:
            folder: 文件夹路径
            recursive: 是否递归扫描子文件夹

        Returns:
            文件路径列表
        """
        files: list[str] = []
        try:
            if recursive:
                for root, _dirs, filenames in os.walk(folder):
                    for filename in filenames:
                        files.append(str(Path(root) / filename))
            else:
                for item in folder.iterdir():
                    if item.is_file():
                        files.append(str(item))
        except OSError as e:
            logger.warning(f"扫描文件夹失败: {folder} - {e}")

        return files


# ---------------------------------------------------------------------------
# 便捷工厂函数
# ---------------------------------------------------------------------------

def create_default_webui_reference() -> WebUIDesignReference:
    """创建默认 WebUI 设计参考"""
    return WebUIDesignReference()


def create_default_file_list_manager() -> FileListManager:
    """创建默认文件列表管理器"""
    return FileListManager()


def create_default_parameter_panel() -> ParameterPanelOptimizer:
    """创建默认参数面板优化器 (含 SeedVR2 预设)"""
    optimizer = ParameterPanelOptimizer()

    # 注册 SeedVR2 核心参数
    optimizer.add_param(ParameterDefinition(
        id="cfg_scale", name="CFG Scale", param_type="slider",
        default=3.0, min_value=1.0, max_value=10.0, step=0.5,
        description="Classifier-Free Guidance 缩放系数",
        group="condition",
    ))
    optimizer.add_param(ParameterDefinition(
        id="denoising_strength", name="去噪强度", param_type="slider",
        default=0.6, min_value=0.1, max_value=1.0, step=0.05,
        description="去噪强度，越高修复越激进",
        group="sampler",
    ))
    optimizer.add_param(ParameterDefinition(
        id="steps", name="采样步数", param_type="slider",
        default=20, min_value=5, max_value=100, step=1,
        description="扩散采样步数",
        group="sampler",
    ))
    optimizer.add_param(ParameterDefinition(
        id="resolution", name="目标分辨率", param_type="number",
        default=2048, min_value=512, max_value=8192, step=256,
        description="输出目标分辨率 (长边)",
        group="basic",
    ))
    optimizer.add_param(ParameterDefinition(
        id="seed", name="随机种子", param_type="number",
        default=-1, description="-1 为随机种子",
        group="basic",
    ))

    # 添加预设组合
    optimizer.add_preset(ParameterComboRule(
        name="照片修复", description="适合真实照片修复，保留细节",
        preset_values={"cfg_scale": 3.0, "denoising_strength": 0.6, "steps": 20},
        recommended_ranges={"cfg_scale": (2.0, 5.0), "denoising_strength": (0.4, 0.8)},
        use_case="真实照片修复",
    ))
    optimizer.add_preset(ParameterComboRule(
        name="艺术增强", description="更强的创造力，适合艺术化处理",
        preset_values={"cfg_scale": 5.0, "denoising_strength": 0.8, "steps": 30},
        recommended_ranges={"cfg_scale": (4.0, 8.0), "denoising_strength": (0.6, 1.0)},
        use_case="艺术化增强",
    ))
    optimizer.add_preset(ParameterComboRule(
        name="轻度去噪", description="最小干预，保持原始风格",
        preset_values={"cfg_scale": 2.0, "denoising_strength": 0.3, "steps": 15},
        recommended_ranges={"cfg_scale": (1.5, 3.0), "denoising_strength": (0.1, 0.4)},
        use_case="轻度去噪/风格保留",
    ))

    return optimizer
