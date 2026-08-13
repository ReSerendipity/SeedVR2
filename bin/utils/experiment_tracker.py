"""
WandB 实验追踪集成
"""

import os
import json
from typing import Dict, Any, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# 检查 wandb 是否可用
try:
    import wandb
    WANDB_AVAILABLE = True
except ImportError:
    WANDB_AVAILABLE = False
    logger.warning("wandb 未安装，使用本地追踪模式")


class ExperimentTracker:
    """实验追踪器 - 支持 WandB 和本地回退"""
    
    def __init__(
        self,
        project_name: str = "seedvr2-experiments",
        experiment_name: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        use_wandb: bool = True,
        local_log_dir: str = "./experiments/logs"
    ):
        self.use_wandb = use_wandb and WANDB_AVAILABLE
        self.local_log_dir = local_log_dir
        os.makedirs(local_log_dir, exist_ok=True)
        
        # 生成本地实验 ID
        self.exp_id = experiment_name or f"exp_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.local_log_path = os.path.join(local_log_dir, f"{self.exp_id}.jsonl")
        
        if self.use_wandb:
            try:
                wandb.init(
                    project=project_name,
                    name=self.exp_id,
                    config=config or {}
                )
                logger.info(f"✅ WandB 实验已初始化: {self.exp_id}")
            except Exception as e:
                logger.error(f"WandB 初始化失败: {e}")
                self.use_wandb = False
        
        # 本地日志文件
        self._log_file = open(self.local_log_path, 'a', encoding='utf-8')
        logger.info(f"📝 本地日志: {self.local_log_path}")
    
    def log_metrics(self, metrics: Dict[str, Any], step: Optional[int] = None):
        """记录指标"""
        record = {
            'timestamp': datetime.now().isoformat(),
            'step': step,
            **metrics
        }
        
        # 写入本地
        self._log_file.write(json.dumps(record) + '\n')
        self._log_file.flush()
        
        # 上传 WandB
        if self.use_wandb:
            try:
                wandb.log(metrics, step=step)
            except Exception as e:
                logger.error(f"WandB log failed: {e}")
    
    def log_hyperparameters(self, config: Dict[str, Any]):
        """记录超参数"""
        if self.use_wandb:
            wandb.config.update(config)
        self.log_metrics({'hyperparameters': config}, step=0)
    
    def log_model(self, model_path: str, alias: str = 'latest'):
        """记录模型文件"""
        if self.use_wandb:
            wandb.save(model_path)
        self.log_metrics({'model_saved': model_path, 'alias': alias})
    
    def log_image(self, image_path: str, caption: Optional[str] = None):
        """记录图像"""
        if self.use_wandb:
            wandb.log({'image': wandb.Image(image_path, caption=caption)})
    
    def finish(self):
        """结束实验"""
        if self.use_wandb:
            wandb.finish()
        if self._log_file:
            self._log_file.close()
        logger.info(f"实验 {self.exp_id} 已结束")


# 全局追踪器
_tracker: Optional[ExperimentTracker] = None

def get_tracker() -> Optional[ExperimentTracker]:
    """获取全局追踪器"""
    return _tracker

def init_tracker(**kwargs) -> ExperimentTracker:
    """初始化全局追踪器"""
    global _tracker
    _tracker = ExperimentTracker(**kwargs)
    return _tracker
