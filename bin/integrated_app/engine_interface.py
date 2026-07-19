"""推理引擎抽象接口

提供 RestoreEngine (ABC) 作为所有修复引擎的抽象基类，
SeedVR2Engine 继承自此类。

REFACTOR (A8): 移除未使用的死代码：
- RestoreEngineProtocol: 从未被任何代码引用，RestoreEngine ABC 已足够
- ControllableRestoreEngineProtocol: 从未被任何代码引用
- InMemoryEngineRegistry / engine_registry: 从未被任何代码引用，
  引擎类型通过 model_registry 直接管理，无需额外注册表
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class RestoreResult:
    """修复结果"""
    success: bool
    output_path: str | None = None
    error: str | None = None
    processing_time: float = 0.0
    metadata: dict = field(default_factory=dict)


class RestoreEngine(ABC):
    """修复引擎抽象基类

    所有修复引擎必须继承此类并实现所有 abstractmethod。
    """

    @abstractmethod
    async def load_model(self, model_size: str = "3b", device: str = "auto",
                         precision: str = None) -> bool:
        """加载模型"""
        pass

    @abstractmethod
    async def unload_model(self) -> bool:
        """卸载模型"""
        pass

    @abstractmethod
    async def infer_video(self, video_path: str, output_dir: str, **kwargs) -> RestoreResult:
        """视频修复推理"""
        pass

    @abstractmethod
    async def infer_image(self, image_path: str, output_dir: str, **kwargs) -> RestoreResult:
        """图像修复推理"""
        pass

    async def infer_batch(self, input_dir: str, output_dir: str, **kwargs) -> list[RestoreResult]:
        """批量图像修复 — 默认返回未实现错误，子类应覆盖此方法以支持批量处理"""
        return [RestoreResult(success=False, error="批量处理未实现")]

    @abstractmethod
    def is_loaded(self) -> bool:
        """模型是否已加载"""
        pass

    @abstractmethod
    def get_model_info(self) -> dict:
        """获取当前模型信息"""
        pass

    @abstractmethod
    def estimate_vram_required(self, model_size: str, resolution: tuple) -> int:
        """估算所需显存(MB)"""
        pass
