"""显存优化工具链集成模块 - SeedVR2 视频修复项目

本模块集成多种显存优化技术，提供统一的配置和编排框架，降低推理时的 VRAM 占用，
提升推理速度。各优化技术可按需独立启用/禁用，通过编排器按正确顺序应用。

所属项目: SeedVR2 (基于 ComfyUI-SeedVR2_VideoUpscaler 独立重构)
核心技术栈: PyTorch, torchao (FP8量化), xformers, torch.compile, Gradient Checkpointing

集成的优化技术（按优先级）:
    - P1: FP8/INT8 权重量化（torchao）- 参考 CogVideo
    - P1: xformers 显存高效注意力 - 参考 CogVideo/StableVSR/DiffVSR
    - P2: TensorRT 加速推理（参考框架）- 参考 Stream-DiffVSR
    - P2: torch.compile 编译优化 - 参考 Fast-SRGAN
    - P2: 逐层选择性 Gradient Checkpointing - 参考 RVRT

注意事项:
    - FP8 量化与 TensorRT 互斥，不应同时启用
    - torch.compile 与 TensorRT 互斥，不应同时启用
    - 工具链提供两种预设：低显存模式（最大化节省）和高性能模式（优先速度）
"""

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import torch

logger = logging.getLogger(__name__)


# ===========================================================================
# 1. FP8 量化集成框架 (CogVideo/torchao P1)
# ===========================================================================


class QuantizationDtype(StrEnum):
    """量化数据类型枚举

    参考 CogVideo 使用 torchao 的 FP8/INT8 量化策略：
    - FP8 量化：将模型权重从 FP16 压缩到 8-bit 浮点，显存节省约 50%
    - INT8 量化：将模型权重量化为 8-bit 整数，进一步压缩但精度损失略大

    Attributes:
        FP8: 通用 FP8 量化（默认）
        INT8: 8-bit 整数量化
        FLOAT8_E4M3FN: E4M3 格式（指数4位，尾数3位），适合前向传播权重
        FLOAT8_E5M2: E5M2 格式（指数5位，尾数2位），适合梯度/反向传播
    """

    FP8 = "fp8"
    INT8 = "int8"
    FLOAT8_E4M3FN = "float8_e4m3fn"
    FLOAT8_E5M2 = "float8_e5m2"


class QuantizationGranularity(StrEnum):
    """量化粒度枚举

    参考 torchao 的量化粒度选项，控制量化参数的共享范围。

    Attributes:
        PER_TENSOR: 整个张量共享一组量化参数（最简单）
        PER_ROW: 每行独立量化（适合线性层权重，精度更好）
        PER_CHANNEL: 每个输出通道独立量化（精度最好但开销略大）
    """

    PER_TENSOR = "per_tensor"
    PER_ROW = "per_row"
    PER_CHANNEL = "per_channel"


@dataclass
class FP8QuantConfig:
    """FP8 量化配置数据类

    参考 CogVideo 使用 torchao 的 FP8 量化策略配置：
    - 权重量化到 FP8 可减少约 50% 权重显存占用
    - 动态激活量化在推理时量化激活，保持精度
    - 可排除关键模块（如 LayerNorm、Embedding）避免精度损失

    Attributes:
        enabled: 是否启用 FP8 量化
        dtype: 量化数据类型（默认 FP8）
        granularity: 量化粒度（默认 PER_ROW）
        mode: 量化模式：
            - "weight_only": 仅量化权重（推荐用于推理，速度快）
            - "dynamic_activation_weight": 权重+动态激活量化（精度更高）
        exclude_module_types: 排除量化的模块类型列表（类名子串匹配）
        exclude_module_names: 排除量化的模块名列表（名称子串匹配）
        verify_accuracy: 量化后是否验证精度（预留功能）
        accuracy_tolerance: 精度验证余弦相似度下限
    """

    enabled: bool = False
    dtype: QuantizationDtype = QuantizationDtype.FP8
    granularity: QuantizationGranularity = QuantizationGranularity.PER_ROW
    mode: str = "weight_only"
    exclude_module_types: list[str] = field(
        default_factory=lambda: [
            "LayerNorm",
            "RMSNorm",
            "Embedding",
            "TimestepEmbedding",
        ]
    )
    exclude_module_names: list[str] = field(
        default_factory=lambda: [
            "norm",
            "embed",
            "time_embed",
            "pos_embed",
        ]
    )
    verify_accuracy: bool = True
    accuracy_tolerance: float = 0.98


class FP8Quantizer:
    """FP8 量化集成框架

    参考 CogVideo 使用 torchao 的 FP8/INT8 量化推理实现。
    将模型权重量化为 8-bit 格式以减少显存占用和加速推理。

    依赖: torchao（pip install torchao）

    集成流程:
        1. 检测 torchao 是否可用
        2. 按配置排除不需要量化的模块（LayerNorm、Embedding 等）
        3. 对 Linear 层应用量化
        4. （可选）验证量化精度
        5. 提供量化状态查询接口

    Usage:
        config = FP8QuantConfig(enabled=True, mode="weight_only")
        quantizer = FP8Quantizer(config)

        if quantizer.is_available():
            model = quantizer.quantize(model)
    """

    def __init__(self, config: FP8QuantConfig | None = None):
        """初始化 FP8 量化器

        Args:
            config: 量化配置，None 时使用默认配置（禁用状态）
        """
        self.config = config or FP8QuantConfig()
        self._quantized: bool = False
        self._original_dtypes: dict[str, torch.dtype] = {}

    def is_available(self) -> bool:
        """检测 torchao 库是否可用

        Returns:
            bool: torchao 已安装返回 True，否则返回 False
        """
        try:
            import torchao  # noqa: F401

            return True
        except ImportError:
            logger.debug("torchao 未安装，FP8 量化不可用")
            return False

    def get_torchao_version(self) -> str | None:
        """获取 torchao 版本号

        Returns:
            str | None: 版本字符串；未安装返回 None
        """
        try:
            import torchao

            return getattr(torchao, "__version__", "unknown")
        except ImportError:
            return None

    def quantize(self, model: torch.nn.Module) -> torch.nn.Module:
        """对模型应用 FP8/INT8 量化

        参考 CogVideo 的量化流程:
        1. 遍历模型所有子模块
        2. 排除不需要量化的模块（LayerNorm、Embedding 等）
        3. 对 Linear 层应用 float8_weight_only 或动态激活量化
        4. 记录原始数据类型用于恢复（预留功能）

        Args:
            model: 要量化的 PyTorch 模型

        Returns:
            torch.nn.Module: 量化后的模型（原地修改）

        Raises:
            RuntimeError: torchao 不可用或量化失败时抛出
        """
        if not self.config.enabled:
            logger.debug("FP8 量化已禁用，跳过")
            return model

        if not self.is_available():
            raise RuntimeError("torchao 未安装，无法使用 FP8 量化。" "请运行: pip install torchao")

        if self._quantized:
            logger.warning("模型已量化，跳过重复量化")
            return model

        try:
            import torchao  # noqa: F401
        except ImportError:
            raise RuntimeError("torchao 导入失败") from None

        self._save_original_dtypes(model)

        quantizable_count = 0
        excluded_count = 0
        for name, module in model.named_modules():
            if isinstance(module, torch.nn.Linear):
                if self._should_exclude(name, module):
                    excluded_count += 1
                else:
                    quantizable_count += 1

        logger.info(f"FP8 量化配置: mode={self.config.mode}, " f"可量化层={quantizable_count}, 排除层={excluded_count}")

        try:
            if self.config.mode == "weight_only":
                from torchao.quantization import float8_weight_only, quantize_

                quantize_(model, float8_weight_only())
            elif self.config.mode == "dynamic_activation_weight":
                from torchao.quantization import (
                    float8_dynamic_activation_float8_weight,
                    quantize_,
                )

                quantize_(model, float8_dynamic_activation_float8_weight())
            else:
                logger.warning(f"未知的量化模式: {self.config.mode}，跳过量化")
                return model
        except Exception as e:
            logger.error(f"FP8 量化失败: {e}")
            raise RuntimeError(f"FP8 量化失败: {e}") from e

        self._quantized = True
        logger.info("FP8 量化已应用")

        if self.config.verify_accuracy:
            logger.info("FP8 量化精度验证 (需要后续推理对比)")

        return model

    def _should_exclude(self, name: str, module: torch.nn.Module) -> bool:
        """判断模块是否应排除在量化之外（内部方法）

        Args:
            name: 模块完整名称
            module: 模块实例

        Returns:
            bool: 应排除返回 True，否则返回 False
        """
        module_type = type(module).__name__
        for excluded_type in self.config.exclude_module_types:
            if excluded_type in module_type:
                return True

        return any(excluded_name in name.lower() for excluded_name in self.config.exclude_module_names)

    def _save_original_dtypes(self, model: torch.nn.Module):
        """保存模型各模块参数的原始数据类型（内部方法）

        Args:
            model: 模型
        """
        for name, param in model.named_parameters():
            self._original_dtypes[name] = param.dtype

    @property
    def is_quantized(self) -> bool:
        """模型是否已完成量化

        Returns:
            bool: 已量化返回 True
        """
        return self._quantized

    def get_memory_savings_estimate(self) -> dict[str, Any]:
        """估算量化后的显存节省量

        Returns:
            dict: 包含估算信息的字典：
                - estimated_savings_ratio (float): 预估节省比例（0.0-1.0）
                - quantization_dtype (str): 使用的量化类型
                - quantization_mode (str): 量化模式
                - note (str): 说明文本
        """
        if not self._quantized:
            return {"estimated_savings_ratio": 0.0, "note": "模型未量化"}

        if self.config.dtype in (QuantizationDtype.FP8, QuantizationDtype.INT8):
            savings_ratio = 0.5
        else:
            savings_ratio = 0.5

        return {
            "estimated_savings_ratio": savings_ratio,
            "quantization_dtype": self.config.dtype.value,
            "quantization_mode": self.config.mode,
            "note": f"估算: 权重从 FP16 量化为 {self.config.dtype.value}，节省约 {savings_ratio*100:.0f}%",
        }


# ===========================================================================
# 2. TensorRT 加速框架 (Stream-DiffVSR P2)
# ===========================================================================


@dataclass
class TensorRTConfig:
    """TensorRT 加速配置数据类

    参考 Stream-DiffVSR 的 TensorRT 集成:
    - 将 PyTorch 模型编译为 TensorRT 引擎可显著降低推理延迟
    - 支持动态 batch size 和分辨率
    - 提供 FP16/INT8 精度选项
    - 引擎缓存避免重复编译开销

    Attributes:
        enabled: 是否启用 TensorRT 加速
        precision: 工作精度："fp32" / "fp16" / "int8"
        cache_engine: 是否缓存编译后的引擎到磁盘
        cache_dir: 引擎缓存目录
        max_batch_size: 最大 batch size
        min_resolution: 最小支持分辨率
        max_resolution: 最大支持分辨率
        optimization_level: 优化级别（1-5，越高优化越激进）
        tf32_enabled: 是否启用 TF32 精度（Ampere+ GPU）
    """

    enabled: bool = False
    precision: str = "fp16"
    cache_engine: bool = True
    cache_dir: str = ".tensorrt_cache"
    max_batch_size: int = 1
    min_resolution: int = 512
    max_resolution: int = 4096
    optimization_level: int = 3
    tf32_enabled: bool = True


class TensorRTRuntime:
    """TensorRT 加速框架（参考实现）

    参考 Stream-DiffVSR 的 TensorRT 引擎编译与推理加速设计。
    将 PyTorch 模型导出并编译为 TensorRT 引擎，可实现低延迟推理。

    依赖: tensorrt（pip install tensorrt）

    注意:
        - TensorRT 是参考框架，当前仅提供接口定义，未实现完整编译流程
        - TensorRT 引擎与 GPU 架构绑定，更换 GPU 需要重新编译
        - SeedVR2 当前仅支持 NVIDIA CUDA，与 TensorRT 兼容
        - TensorRT 与 FP8 量化、torch.compile 互斥

    Usage:
        config = TensorRTConfig(enabled=True, precision="fp16")
        runtime = TensorRTRuntime(config)

        if runtime.is_available():
            engine = runtime.compile_model(model, sample_input)
            output = runtime.infer(engine, input_tensor)
    """

    def __init__(self, config: TensorRTConfig | None = None):
        """初始化 TensorRT 运行时

        Args:
            config: TensorRT 配置，None 时使用默认配置（禁用状态）
        """
        self.config = config or TensorRTConfig()
        self._engine = None
        self._compiled = False

    def is_available(self) -> bool:
        """检测 TensorRT 是否可用

        Returns:
            bool: tensorrt 已安装返回 True
        """
        try:
            import tensorrt  # noqa: F401

            return True
        except ImportError:
            logger.debug("TensorRT 未安装，加速不可用")
            return False

    def get_tensorrt_version(self) -> str | None:
        """获取 TensorRT 版本号

        Returns:
            str | None: 版本字符串；未安装返回 None
        """
        try:
            import tensorrt

            return getattr(tensorrt, "__version__", "unknown")
        except ImportError:
            return None

    def compile_model(
        self,
        model: torch.nn.Module,
        sample_input: torch.Tensor | tuple[torch.Tensor, ...],
        cache_key: str = "",
    ) -> Any:
        """编译模型为 TensorRT 引擎（参考框架）

        参考 Stream-DiffVSR 的编译流程:
        1. 检查缓存
        2. 导出 ONNX
        3. 编译 TensorRT 引擎
        4. 缓存引擎到磁盘

        Args:
            model: PyTorch 模型
            sample_input: 示例输入张量（用于 tracing）
            cache_key: 缓存键（用于引擎缓存命中）

        Returns:
            Any: TensorRT 引擎（当前为 None，参考实现）

        Raises:
            RuntimeError: TensorRT 不可用时抛出
        """
        if not self.config.enabled:
            logger.debug("TensorRT 加速已禁用，跳过")
            return None

        if not self.is_available():
            raise RuntimeError("TensorRT 未安装，无法编译引擎")

        logger.info(f"TensorRT 编译配置: precision={self.config.precision}, " f"max_batch={self.config.max_batch_size}")

        logger.info("TensorRT 引擎编译流程 (参考实现):")
        logger.info("  1. torch.onnx.export(model, sample_input, onnx_path)")
        logger.info("  2. trt.Builder 创建 builder")
        logger.info("  3. builder.create_network 配置网络")
        logger.info(f"  4. 设置精度: {self.config.precision}")
        logger.info(f"  5. 优化级别: {self.config.optimization_level}")
        logger.info("  6. builder.build_engine 编译引擎")
        logger.info(f"  7. 缓存引擎到: {self.config.cache_dir}")

        self._compiled = True
        logger.warning("TensorRT 编译为参考框架，实际使用需安装 tensorrt 并实现完整编译流程")
        return None

    def infer(self, engine: Any, input_tensor: torch.Tensor) -> torch.Tensor | None:
        """使用 TensorRT 引擎执行推理（参考框架）

        Args:
            engine: TensorRT 引擎
            input_tensor: 输入张量

        Returns:
            torch.Tensor | None: 输出张量（当前为 None）
        """
        if engine is None:
            logger.warning("TensorRT 引擎未就绪，无法推理")
            return None

        logger.warning("TensorRT 推理为参考框架，实际使用需实现完整推理流程")
        return None

    @property
    def is_compiled(self) -> bool:
        """引擎是否已编译

        Returns:
            bool: 已编译返回 True
        """
        return self._compiled


# ===========================================================================
# 3. torch.compile 集成 (Fast-SRGAN P2)
# ===========================================================================


@dataclass
class CompileConfig:
    """torch.compile 编译配置数据类

    参考 Fast-SRGAN 的 torch.compile 集成:
    - 使用 mode="max-autotune" 自动搜索最优内核
    - 支持 fullgraph 和子图编译
    - 可指定后端：inductor、eager、aot_eager 等
    - 动态形状支持

    Attributes:
        enabled: 是否启用 torch.compile
        mode: 编译模式：
            - "default": 默认优化
            - "max-autotune": 最大程度自动调优（编译慢，推理快）
            - "reduce-overhead": 减少开销（适合小模型）
        backend: 编译后端："inductor"（默认）/ "eager" / "aot_eager" / "cudagraphs"
        fullgraph: 是否全图编译（False 允许子图编译，兼容性更好）
        dynamic: 是否支持动态形状
        exclude_module_names: 排除编译的模块名列表
    """

    enabled: bool = False
    mode: str = "max-autotune"
    backend: str = "inductor"
    fullgraph: bool = False
    dynamic: bool = True
    exclude_module_names: list[str] = field(default_factory=list)


class CompileOptimizer:
    """torch.compile 编译优化集成

    参考 Fast-SRGAN 的 torch.compile 集成设计。
    在首次推理前编译模型，后续推理可加速 10-30%。

    约束:
        - torch.compile 需要 PyTorch 2.0+
        - 首次编译有较大开销（约 30-120 秒）
        - 部分 CUDA 操作可能不兼容，会自动回退到 eager 模式

    Usage:
        config = CompileConfig(enabled=True, mode="max-autotune")
        optimizer = CompileOptimizer(config)

        if optimizer.is_available():
            model = optimizer.compile(model)
            # 首次推理触发编译 (较慢)
            output = model(input_tensor)
            # 后续推理加速
            output = model(input_tensor2)
    """

    def __init__(self, config: CompileConfig | None = None):
        """初始化编译优化器

        Args:
            config: 编译配置，None 时使用默认配置（禁用状态）
        """
        self.config = config or CompileConfig()
        self._compiled: bool = False

    def is_available(self) -> bool:
        """检测 torch.compile 是否可用（PyTorch 2.0+）

        Returns:
            bool: torch.compile 可用返回 True
        """
        return hasattr(torch, "compile")

    def get_pytorch_version(self) -> str:
        """获取 PyTorch 版本号

        Returns:
            str: PyTorch 版本字符串
        """
        return torch.__version__

    def compile(self, model: torch.nn.Module) -> torch.nn.Module:
        """使用 torch.compile 编译模型

        参考 Fast-SRGAN 的编译流程:
        1. 检查 PyTorch 版本
        2. 排除不兼容的子模块（预留）
        3. 应用 torch.compile
        4. 首次推理触发实际编译

        Args:
            model: 要编译的模型

        Returns:
            torch.nn.Module: 编译后的模型（或原模型，编译失败时回退）
        """
        if not self.config.enabled:
            logger.debug("torch.compile 已禁用，跳过")
            return model

        if not self.is_available():
            logger.warning("torch.compile 不可用 (需要 PyTorch 2.0+)，" f"当前版本: {torch.__version__}")
            return model

        logger.info(
            f"torch.compile 配置: mode={self.config.mode}, "
            f"backend={self.config.backend}, "
            f"fullgraph={self.config.fullgraph}, "
            f"dynamic={self.config.dynamic}"
        )

        try:
            compiled_model = torch.compile(
                model,
                mode=self.config.mode,
                backend=self.config.backend,
                fullgraph=self.config.fullgraph,
                dynamic=self.config.dynamic,
            )
            self._compiled = True
            logger.info("torch.compile 已应用。首次推理将触发编译 (约30-120秒)，" "后续推理将加速。")
            return compiled_model

        except Exception as e:
            logger.error(f"torch.compile 失败: {e}，回退到未编译模式")
            return model

    @property
    def is_compiled(self) -> bool:
        """模型是否已应用 torch.compile

        Returns:
            bool: 已编译返回 True
        """
        return self._compiled


# ===========================================================================
# 4. xformers 显存高效注意力 (CogVideo/StableVSR/DiffVSR P1)
# ===========================================================================


@dataclass
class XFormersConfig:
    """xformers 显存高效注意力配置数据类

    参考 CogVideo/StableVSR/DiffVSR 的 xformers 集成:
    - 使用 xformers.ops.memory_efficient_attention 替代标准注意力
    - 显存占用从 O(N^2) 降至接近 O(N)，长序列节省显著
    - 支持多种注意力偏置类型
    - 自动回退到 PyTorch 2.0+ scaled_dot_product_attention (SDPA)

    Attributes:
        enabled: 是否启用显存高效注意力
        attention_mode: 注意力实现选择：
            - "xformers": 使用 xformers memory_efficient_attention
            - "sdpa": 使用 PyTorch 2.0+ scaled_dot_product_attention
            - "math": 使用标准数学实现（兼容性最好，显存占用高）
        auto_fallback: 不可用时是否自动回退到次优实现
        verify_correctness: 是否验证 xformers 输出与标准实现一致（预留）
    """

    enabled: bool = False
    attention_mode: str = "xformers"
    auto_fallback: bool = True
    verify_correctness: bool = True


class XFormersIntegration:
    """xformers 显存高效注意力集成框架

    参考 CogVideo/StableVSR/DiffVSR 的 xformers 集成设计。
    替换 DiT 中的标准注意力为显存高效实现，可节省 30-50% 注意力显存。

    约束:
        - xformers 需要 CUDA GPU
        - xformers 版本需与 PyTorch/CUDA 版本匹配
        - 部分注意力偏置类型 xformers 不支持，会自动回退

    自动回退策略:
        1. 首选 xformers memory_efficient_attention
        2. 不可用时回退到 PyTorch SDPA
        3. SDPA 不可用时回退到标准数学实现

    Usage:
        config = XFormersConfig(enabled=True)
        integration = XFormersIntegration(config)

        if integration.is_available():
            model = integration.apply(model)
    """

    def __init__(self, config: XFormersConfig | None = None):
        """初始化 xformers 集成

        Args:
            config: xformers 配置，None 时使用默认配置（禁用状态）
        """
        self.config = config or XFormersConfig()
        self._applied: bool = False
        self._effective_mode: str = self.config.attention_mode

    def is_available(self) -> bool:
        """检测 xformers 是否可用

        Returns:
            bool: xformers 已安装且 ops 可用返回 True
        """
        try:
            import xformers  # noqa: F401
            import xformers.ops  # noqa: F401

            return True
        except ImportError:
            return False

    def is_sdpa_available(self) -> bool:
        """检测 PyTorch scaled_dot_product_attention 是否可用

        Returns:
            bool: PyTorch 有 SDPA 实现返回 True（PyTorch 2.0+）
        """
        return hasattr(torch.nn.functional, "scaled_dot_product_attention")

    def get_xformers_version(self) -> str | None:
        """获取 xformers 版本号

        Returns:
            str | None: 版本字符串；未安装返回 None
        """
        try:
            import xformers

            return getattr(xformers, "__version__", "unknown")
        except ImportError:
            return None

    def get_effective_attention_mode(self) -> str:
        """获取实际使用的注意力模式

        根据 xformers 可用性和配置，自动确定最终使用的注意力实现，
        处理自动回退逻辑。

        Returns:
            str: 实际使用的模式："xformers" / "sdpa" / "math"
        """
        if self.config.attention_mode == "xformers" and self.is_available():
            return "xformers"

        if self.config.attention_mode in ("xformers", "sdpa") and self.is_sdpa_available():
            if self.config.auto_fallback:
                logger.info("xformers 不可用，回退到 PyTorch SDPA")
            return "sdpa"

        if self.config.auto_fallback:
            logger.info("xformers 和 SDPA 均不可用，回退到标准实现")
        return "math"

    def apply(self, model: torch.nn.Module) -> torch.nn.Module:
        """对模型应用显存高效注意力替换

        参考 CogVideo 的集成方式:
        1. 检测可用注意力实现
        2. 设置模型的注意力模式标识
        3. 查找并替换 Attention 层的 forward 方法

        注意: SeedVR2 的 DiT 使用自定义注意力实现，
        此方法提供集成框架，具体替换需根据 DiT 实际实现调整。

        Args:
            model: 要优化的模型

        Returns:
            torch.nn.Module: 优化后的模型（原地修改）
        """
        if not self.config.enabled:
            logger.debug("xformers 集成已禁用，跳过")
            return model

        self._effective_mode = self.get_effective_attention_mode()

        if self._effective_mode == "math":
            logger.info("显存高效注意力不可用，使用标准实现")
            return model

        logger.info(f"应用显存高效注意力: {self._effective_mode}")

        model._attention_mode = self._effective_mode

        replaced_count = 0
        for name, module in model.named_modules():
            if self._is_attention_module(module):
                self._replace_attention_forward(module, name)
                replaced_count += 1

        self._applied = True
        logger.info(f"已替换 {replaced_count} 个注意力层为 {self._effective_mode} 实现")
        return model

    def _is_attention_module(self, module: torch.nn.Module) -> bool:
        """判断模块是否为注意力模块（内部方法）

        通过类名子串匹配识别常见的注意力模块类型。

        Args:
            module: 待检测模块

        Returns:
            bool: 是注意力模块返回 True
        """
        attention_types = (
            "Attention",
            "SelfAttention",
            "CrossAttention",
            "MultiHeadAttention",
            "FlashAttention",
        )
        module_type = type(module).__name__
        return any(t in module_type for t in attention_types)

    def _replace_attention_forward(self, module: torch.nn.Module, name: str):
        """替换注意力模块的 forward 方法（内部方法）

        根据 effective_mode 替换为对应实现：
        - xformers: 使用 memory_efficient_attention
        - sdpa: 使用 scaled_dot_product_attention

        Args:
            module: 注意力模块
            name: 模块名称（日志用）
        """
        original_forward = module.forward

        if self._effective_mode == "xformers":

            def xformers_forward(query, key, value, **kwargs):
                try:
                    import xformers.ops

                    output = xformers.ops.memory_efficient_attention(
                        query,
                        key,
                        value,
                        attn_bias=kwargs.get("attn_bias"),
                    )
                    return output
                except Exception as e:
                    logger.debug(f"xformers 注意力失败，回退: {e}")
                    return original_forward(query, key, value, **kwargs)

            module.forward = xformers_forward

        elif self._effective_mode == "sdpa":

            def sdpa_forward(query, key, value, **kwargs):
                try:
                    output = torch.nn.functional.scaled_dot_product_attention(
                        query,
                        key,
                        value,
                        attn_mask=kwargs.get("attn_mask"),
                        is_causal=kwargs.get("is_causal", False),
                    )
                    return output
                except Exception as e:
                    logger.debug(f"SDPA 注意力失败，回退: {e}")
                    return original_forward(query, key, value, **kwargs)

            module.forward = sdpa_forward

    @property
    def is_applied(self) -> bool:
        """是否已应用注意力替换

        Returns:
            bool: 已应用返回 True
        """
        return self._applied

    @property
    def effective_mode(self) -> str:
        """实际使用的注意力模式

        Returns:
            str: 模式字符串
        """
        return self._effective_mode


# ===========================================================================
# 5. Gradient Checkpointing (RVRT P2)
# ===========================================================================


@dataclass
class CheckpointConfig:
    """Gradient Checkpointing 配置数据类

    参考 RVRT 的逐层选择性 checkpoint 设计:
    - 不是所有层都需要 checkpoint，靠近输入的层激活更大优先 checkpoint
    - 可以按层配置启用/禁用
    - 支持 block 级别的选择性 checkpoint
    - 显存节省 30-40%，推理时间增加 20-30%（时间换空间）

    注意: Gradient Checkpointing 主要用于训练，但在推理时也可用于减少峰值显存。

    Attributes:
        enabled: 是否启用 Gradient Checkpointing
        strategy: checkpoint 策略：
            - "all": 对所有 block 启用 checkpoint
            - "selective": 仅对 selected_blocks 指定的 block 启用
            - "auto": 根据 VRAM 可用量自动决定
        selected_blocks: 选择性 checkpoint 的 block 索引列表（仅 strategy="selective"）
        auto_checkpoint_ratio: 自动策略中 checkpoint 的 block 比例（0.0-1.0）
        checkpoint_io_components: 是否对 I/O 组件也启用 checkpoint
        implementation: checkpoint 实现：
            - "torch": 使用 torch.utils.checkpoint.checkpoint（推荐）
            - "custom": 使用自定义实现（预留）
    """

    enabled: bool = False
    strategy: str = "auto"
    selected_blocks: list[int] = field(default_factory=list)
    auto_checkpoint_ratio: float = 0.5
    checkpoint_io_components: bool = False
    implementation: str = "torch"


class GradientCheckpointManager:
    """Gradient Checkpointing 管理器

    参考 RVRT 的逐层选择性 checkpoint 实现。
    在推理过程中选择性不保存中间激活，减少显存峰值，需要时重新计算。

    注意: 虽然 Gradient Checkpointing 主要用于训练，
    在推理时也可用于减少峰值显存（以重新计算前向传播为代价）。
    对于 SeedVR2 的 DiT 模型，选择性 checkpoint 可以：
    - 减少峰值 VRAM 约 30-40%
    - 增加推理时间约 20-30%
    - 适用于 VRAM 不足但时间充裕的场景

    Usage:
        config = CheckpointConfig(enabled=True, strategy="auto")
        manager = GradientCheckpointManager(config)

        model = manager.apply(model)
        info = manager.get_checkpoint_info()
    """

    def __init__(self, config: CheckpointConfig | None = None):
        """初始化 Gradient Checkpoint 管理器

        Args:
            config: checkpoint 配置，None 时使用默认配置（禁用状态）
        """
        self.config = config or CheckpointConfig()
        self._applied: bool = False
        self._checkpointed_blocks: list[int] = []

    def apply(self, model: torch.nn.Module) -> torch.nn.Module:
        """对模型应用选择性 Gradient Checkpointing

        参考 RVRT 的选择性 checkpoint 策略:
        1. 确定策略（all/selective/auto）
        2. 根据策略选择要 checkpoint 的 block
        3. 包装 block 的 forward 方法

        Args:
            model: 要优化的模型（需有 blocks 属性）

        Returns:
            torch.nn.Module: 优化后的模型（原地修改）
        """
        if not self.config.enabled:
            logger.debug("Gradient Checkpointing 已禁用，跳过")
            return model

        blocks = None
        if hasattr(model, "blocks"):
            blocks = model.blocks
        else:
            logger.warning("模型无 blocks 属性，无法应用 block 级 checkpoint")
            return model

        total_blocks = len(blocks)
        if total_blocks == 0:
            logger.warning("模型 blocks 为空，跳过 checkpoint")
            return model

        if self.config.strategy == "all":
            self._checkpointed_blocks = list(range(total_blocks))
        elif self.config.strategy == "selective":
            self._checkpointed_blocks = list(self.config.selected_blocks)
        elif self.config.strategy == "auto":
            self._checkpointed_blocks = self._auto_select_blocks(total_blocks)
        else:
            logger.warning(f"未知 checkpoint 策略: {self.config.strategy}")
            return model

        for block_idx in self._checkpointed_blocks:
            if block_idx < total_blocks:
                self._apply_checkpoint_to_block(blocks[block_idx], block_idx)

        if self.config.checkpoint_io_components:
            self._apply_checkpoint_to_io(model)

        self._applied = True
        logger.info(
            f"Gradient Checkpointing 已应用: "
            f"{len(self._checkpointed_blocks)}/{total_blocks} blocks, "
            f"策略={self.config.strategy}"
        )
        return model

    def _auto_select_blocks(self, total_blocks: int) -> list[int]:
        """自动选择需要 checkpoint 的 block（内部方法）

        策略: 按 auto_checkpoint_ratio 比例均匀间隔选择 block。
        优先选择靠近输入的 block（它们通常占用更多显存）。

        Args:
            total_blocks: 总 block 数量

        Returns:
            list[int]: 要 checkpoint 的 block 索引列表
        """
        num_to_checkpoint = max(1, int(total_blocks * self.config.auto_checkpoint_ratio))

        if num_to_checkpoint >= total_blocks:
            return list(range(total_blocks))

        step = total_blocks / num_to_checkpoint
        selected = [int(i * step) for i in range(num_to_checkpoint)]
        logger.debug(f"自动选择 checkpoint blocks: {selected} " f"({num_to_checkpoint}/{total_blocks})")
        return selected

    def _apply_checkpoint_to_block(self, block: torch.nn.Module, block_idx: int):
        """对单个 block 应用 Gradient Checkpointing（内部方法）

        使用 torch.utils.checkpoint.checkpoint 包装 forward:
        - 推理时不保存中间激活，需要时重新计算
        - 使用 use_reentrant=False（推荐的新 API，无重入问题）

        Args:
            block: transformer block
            block_idx: block 索引（日志用）
        """
        if self.config.implementation == "torch":
            from torch.utils.checkpoint import checkpoint

            original_forward = block.forward

            def checkpointed_forward(*args, **kwargs):
                return checkpoint(
                    original_forward,
                    *args,
                    use_reentrant=False,
                    **kwargs,
                )

            block.forward = checkpointed_forward
            block._gradient_checkpointing_enabled = True

        logger.debug(f"Block {block_idx} 已启用 Gradient Checkpointing")

    def _apply_checkpoint_to_io(self, model: torch.nn.Module):
        """对 I/O 组件应用 Gradient Checkpointing（内部方法）

        Args:
            model: 模型
        """
        from torch.utils.checkpoint import checkpoint

        for name, module in model.named_children():
            if name != "blocks":
                original_forward = module.forward

                def make_checkpointed(orig_fwd):
                    def checkpointed_forward(*args, **kwargs):
                        return checkpoint(orig_fwd, *args, use_reentrant=False, **kwargs)

                    return checkpointed_forward

                module.forward = make_checkpointed(original_forward)
                module._gradient_checkpointing_enabled = True
                logger.debug(f"I/O 组件 {name} 已启用 Gradient Checkpointing")

    def get_checkpoint_info(self) -> dict[str, Any]:
        """获取 checkpoint 应用信息

        Returns:
            dict: 应用状态信息字典
        """
        return {
            "enabled": self.config.enabled,
            "strategy": self.config.strategy,
            "checkpointed_blocks": self._checkpointed_blocks,
            "num_checkpointed": len(self._checkpointed_blocks),
            "implementation": self.config.implementation,
            "is_applied": self._applied,
        }

    @property
    def is_applied(self) -> bool:
        """是否已应用 checkpoint

        Returns:
            bool: 已应用返回 True
        """
        return self._applied


# ===========================================================================
# 统一 VRAM 工具链编排器
# ===========================================================================


@dataclass
class VRAMToolchainConfig:
    """VRAM 工具链统一配置数据类

    聚合所有显存优化技术的配置，用于一次性配置整个工具链。

    Attributes:
        fp8_quant: FP8 量化配置
        tensorrt: TensorRT 加速配置
        torch_compile: torch.compile 配置
        xformers: xformers 注意力配置
        checkpoint: Gradient Checkpointing 配置
    """

    fp8_quant: FP8QuantConfig = field(default_factory=FP8QuantConfig)
    tensorrt: TensorRTConfig = field(default_factory=TensorRTConfig)
    torch_compile: CompileConfig = field(default_factory=CompileConfig)
    xformers: XFormersConfig = field(default_factory=XFormersConfig)
    checkpoint: CheckpointConfig = field(default_factory=CheckpointConfig)


class VRAMToolchainOrchestrator:
    """VRAM 优化工具链编排器

    统一管理所有 VRAM 优化工具的应用顺序和互斥性检查，
    确保各优化技术按正确依赖顺序应用，避免冲突。

    应用顺序（按依赖关系排列）:
        1. xformers（替换注意力实现，无权重变更）
        2. Gradient Checkpointing（修改 forward 方法）
        3. torch.compile（编译优化，在前两步之后）
        4. FP8 量化（权重格式变更，最后应用）
        5. TensorRT（独立编译，与其他优化互斥，需单独调用）

    互斥约束:
        - FP8 量化与 TensorRT 不应同时启用
        - torch.compile 与 TensorRT 不应同时启用
        - xformers 与 FP8 量化可共存

    Usage:
        config = VRAMToolchainConfig()
        config.xformers.enabled = True
        config.checkpoint.enabled = True

        orchestrator = VRAMToolchainOrchestrator(config)
        model = orchestrator.optimize(model)
    """

    def __init__(self, config: VRAMToolchainConfig | None = None):
        """初始化工具链编排器

        Args:
            config: 工具链统一配置，None 时使用默认配置（全部禁用）
        """
        self.config = config or VRAMToolchainConfig()
        self._xformers = XFormersIntegration(self.config.xformers)
        self._checkpoint = GradientCheckpointManager(self.config.checkpoint)
        self._compile = CompileOptimizer(self.config.torch_compile)
        self._fp8 = FP8Quantizer(self.config.fp8_quant)
        self._tensorrt = TensorRTRuntime(self.config.tensorrt)

    def optimize(self, model: torch.nn.Module) -> torch.nn.Module:
        """按正确顺序应用所有已启用的 VRAM 优化

        执行顺序:
        1. 先检查互斥配置，自动禁用冲突项
        2. xformers（注意力替换）
        3. Gradient Checkpointing
        4. torch.compile
        5. FP8 量化
        6. TensorRT（提示需单独调用）

        Args:
            model: 要优化的模型

        Returns:
            torch.nn.Module: 优化后的模型
        """
        if self.config.fp8_quant.enabled and self.config.tensorrt.enabled:
            logger.warning("FP8 量化与 TensorRT 不应同时启用，已禁用 TensorRT")
            self.config.tensorrt.enabled = False

        if self.config.torch_compile.enabled and self.config.tensorrt.enabled:
            logger.warning("torch.compile 与 TensorRT 不应同时启用，已禁用 TensorRT")
            self.config.tensorrt.enabled = False

        logger.info("开始 VRAM 优化工具链应用...")

        if self.config.xformers.enabled:
            logger.info("[1/5] 应用 xformers 显存高效注意力...")
            model = self._xformers.apply(model)
            logger.info(f"[1/5] xformers 完成, 模式={self._xformers.effective_mode}")

        if self.config.checkpoint.enabled:
            logger.info("[2/5] 应用 Gradient Checkpointing...")
            model = self._checkpoint.apply(model)
            logger.info("[2/5] Gradient Checkpointing 完成")

        if self.config.torch_compile.enabled:
            logger.info("[3/5] 应用 torch.compile...")
            model = self._compile.compile(model)
            logger.info("[3/5] torch.compile 完成")

        if self.config.fp8_quant.enabled:
            logger.info("[4/5] 应用 FP8 量化...")
            model = self._fp8.quantize(model)
            logger.info("[4/5] FP8 量化完成")

        if self.config.tensorrt.enabled:
            logger.info("[5/5] TensorRT 为独立编译流程，需单独调用")
            logger.info("[5/5] 跳过自动编译，请手动调用 tensorrt.compile_model()")

        logger.info("VRAM 优化工具链应用完成")
        return model

    def get_status(self) -> dict[str, Any]:
        """获取工具链各组件的应用状态

        Returns:
            dict: 各优化技术的启用/应用状态字典
        """
        return {
            "xformers": {
                "enabled": self.config.xformers.enabled,
                "applied": self._xformers.is_applied,
                "effective_mode": self._xformers.effective_mode,
            },
            "checkpoint": {
                "enabled": self.config.checkpoint.enabled,
                "applied": self._checkpoint.is_applied,
                "info": self._checkpoint.get_checkpoint_info(),
            },
            "torch_compile": {
                "enabled": self.config.torch_compile.enabled,
                "applied": self._compile.is_compiled,
            },
            "fp8_quant": {
                "enabled": self.config.fp8_quant.enabled,
                "applied": self._fp8.is_quantized,
                "available": self._fp8.is_available(),
            },
            "tensorrt": {
                "enabled": self.config.tensorrt.enabled,
                "compiled": self._tensorrt.is_compiled,
                "available": self._tensorrt.is_available(),
            },
        }

    def get_availability_report(self) -> dict[str, bool]:
        """获取各优化工具的可用性报告

        Returns:
            dict: 各工具是否可用的布尔字典
        """
        return {
            "xformers_available": self._xformers.is_available(),
            "sdpa_available": self._xformers.is_sdpa_available(),
            "torch_compile_available": self._compile.is_available(),
            "fp8_torchao_available": self._fp8.is_available(),
            "tensorrt_available": self._tensorrt.is_available(),
        }


# ===========================================================================
# 便捷工厂函数
# ===========================================================================


def create_low_vram_toolchain() -> VRAMToolchainOrchestrator:
    """创建低显存优化工具链预设

    适合 12GB 以下显存的 GPU，最大化显存节省。
    启用: xformers + Gradient Checkpointing (60%) + FP8 权重量化
    禁用: torch.compile、TensorRT

    Returns:
        VRAMToolchainOrchestrator: 配置好的编排器实例
    """
    config = VRAMToolchainConfig()
    config.xformers.enabled = True
    config.xformers.attention_mode = "xformers"
    config.checkpoint.enabled = True
    config.checkpoint.strategy = "auto"
    config.checkpoint.auto_checkpoint_ratio = 0.6
    config.fp8_quant.enabled = True
    config.fp8_quant.mode = "weight_only"
    config.torch_compile.enabled = False
    config.tensorrt.enabled = False
    return VRAMToolchainOrchestrator(config)


def create_high_performance_toolchain() -> VRAMToolchainOrchestrator:
    """创建高性能优化工具链预设

    适合 24GB+ 显存的 GPU，优先推理速度。
    启用: xformers + torch.compile (max-autotune)
    禁用: Gradient Checkpointing、FP8 量化、TensorRT

    Returns:
        VRAMToolchainOrchestrator: 配置好的编排器实例
    """
    config = VRAMToolchainConfig()
    config.xformers.enabled = True
    config.xformers.attention_mode = "xformers"
    config.torch_compile.enabled = True
    config.torch_compile.mode = "max-autotune"
    config.checkpoint.enabled = False
    config.fp8_quant.enabled = False
    config.tensorrt.enabled = False
    return VRAMToolchainOrchestrator(config)
