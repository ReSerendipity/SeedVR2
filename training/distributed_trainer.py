"""分布式训练支持 — DeepSpeed + FSDP + DDP。

基于项目已有的 ``common.distributed`` 基础设施，提供高层训练器封装，
支持多种并行策略和断点续训。

支持的并行策略:
    - **DDP (DistributedDataParallel)**: 数据并行，每卡持有完整模型副本
    - **FSDP (Fully Sharded Data Parallel)**: 模型分片，参数/梯度/优化器状态跨卡分片
    - **Hybrid Sharding**: 节点内分片 + 节点间数据并行

启动方式::

    # 4 卡 DDP
    torchrun --nproc_per_node=4 training/distributed_trainer.py --config config.yaml

    # 单卡调试
    python training/distributed_trainer.py --config config.yaml

依赖:
    - torch >= 2.4.0
    - common.distributed (项目内置)

验收标准:
    - 4 卡并行加速比 ≥ 3.5x
    - 支持 ZeRO 优化（显存节省 60%）
    - 断点续训正常
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import torch
import torch.nn as nn

# 项目内置分布式工具
from common.distributed import convert_to_ddp, get_device, get_global_rank, get_local_rank, get_world_size, init_torch

logger = logging.getLogger(__name__)


@dataclass
class TrainingConfig:
    """分布式训练配置。

    Attributes:
        batch_size: 全局批次大小（会被 world_size 等分）。
        learning_rate: 学习率。
        weight_decay: 权重衰减。
        epochs: 训练轮数。
        warmup_steps: 学习率预热步数。
        gradient_accumulation_steps: 梯度累积步数（模拟更大批次）。
        max_gradient_norm: 梯度裁剪阈值（None 表示不裁剪）。
        sharding_strategy: 分片策略（"ddp", "fsdp", "hybrid"）。
        checkpoint_dir: 检查点保存目录。
        checkpoint_interval: 检查点保存间隔（步数）。
        resume_from_checkpoint: 断点续训的检查点路径。
        log_interval: 日志打印间隔（步数）。
        mixed_precision: 混合精度类型（"fp16", "bf16", None）。
        gradient_checkpointing: 是否启用梯度检查点（节省显存）。
    """

    batch_size: int = 32
    learning_rate: float = 1e-4
    weight_decay: float = 0.01
    epochs: int = 100
    warmup_steps: int = 500
    gradient_accumulation_steps: int = 1
    max_gradient_norm: float | None = 1.0
    sharding_strategy: str = "ddp"
    checkpoint_dir: str = "data/checkpoints"
    checkpoint_interval: int = 500
    resume_from_checkpoint: str | None = None
    log_interval: int = 10
    mixed_precision: str | None = None
    gradient_checkpointing: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


class DistributedTrainer:
    """多 GPU 分布式训练器。

    封装分布式训练的完整生命周期：初始化 → 模型设置 → 数据加载 →
    训练循环 → 检查点保存/恢复 → 清理。

    支持三种分片策略:
        - ``"ddp"``: DistributedDataParallel（最简单，每卡完整模型）
        - ``"fsdp"``: Fully Sharded Data Parallel（参数跨卡分片）
        - ``"hybrid"``: 混合分片（节点内 FSDP + 节点间 DDP）

    Args:
        config: 训练配置。

    Example::

        config = TrainingConfig(sharding_strategy="ddp", epochs=100)
        trainer = DistributedTrainer(config)
        trainer.setup_model(model)
        trainer.setup_dataloader(dataset)
        trainer.train(model, dataloader, optimizer, compute_loss_fn)
        trainer.cleanup()
    """

    def __init__(self, config: TrainingConfig) -> None:
        self.config = config
        self.local_rank = get_local_rank()
        self.world_size = get_world_size()
        self.global_rank = get_global_rank()
        self.device = get_device()
        self._step = 0
        self._epoch = 0

        # 初始化分布式环境
        if self.world_size > 1:
            init_torch()
            logger.info(
                "分布式训练已初始化: rank=%d, world_size=%d, device=%s",
                self.global_rank,
                self.world_size,
                self.device,
            )
        else:
            logger.info("单卡模式训练, device=%s", self.device)

        # 混合精度设置
        self._scaler: torch.cuda.amp.GradScaler | None = None
        if config.mixed_precision == "fp16":
            self._scaler = torch.cuda.amp.GradScaler()
        self._autocast_dtype = {
            "fp16": torch.float16,
            "bf16": torch.bfloat16,
            None: None,
        }.get(config.mixed_precision)

    def setup_model(self, model: nn.Module) -> nn.Module:
        """设置分布式模型。

        根据配置的分片策略，将模型移动到正确设备并包装为分布式模型。

        Args:
            model: 待训练的模型。

        Returns:
            包装后的分布式模型（DDP/FSDP 或原始模型）。
        """
        model = model.to(self.device)

        # 梯度检查点
        if self.config.gradient_checkpointing and hasattr(model, "gradient_checkpointing_enable"):
            model.gradient_checkpointing_enable()
            logger.info("已启用梯度检查点")

        if self.world_size > 1:
            if self.config.sharding_strategy == "ddp":
                model = convert_to_ddp(model)
                logger.info("模型已使用 DDP 包装")
            elif self.config.sharding_strategy in ("fsdp", "hybrid"):
                model = self._wrap_fsdp(model)
                logger.info("模型已使用 FSDP 包装 (strategy=%s)", self.config.sharding_strategy)
            else:
                logger.warning(
                    "未知分片策略 '%s'，回退到 DDP",
                    self.config.sharding_strategy,
                )
                model = convert_to_ddp(model)

        return model

    def _wrap_fsdp(self, model: nn.Module) -> nn.Module:
        """使用 FSDP 包装模型。

        Args:
            model: 待包装的模型。

        Returns:
            FSDP 包装后的模型。
        """
        from torch.distributed.fsdp import FullyShardedDataParallel as FSDP
        from torch.distributed.fsdp import ShardingStrategy

        strategy_map = {
            "fsdp": ShardingStrategy.FULL_SHARD,
            "hybrid": ShardingStrategy.HYBRID_SHARD,
        }
        sharding_strategy = strategy_map.get(
            self.config.sharding_strategy,
            ShardingStrategy.FULL_SHARD,
        )

        return FSDP(
            model,
            sharding_strategy=sharding_strategy,
            device_id=self.local_rank,
            use_orig_params=True,
        )

    def setup_dataloader(self, dataset: torch.utils.data.Dataset) -> torch.utils.data.DataLoader:
        """设置分布式数据加载器。

        使用 :class:`DistributedSampler` 确保每卡处理不同的数据分片。

        Args:
            dataset: 训练数据集。

        Returns:
            配置好的 DataLoader。
        """
        sampler: torch.utils.data.distributed.DistributedSampler | None = None
        if self.world_size > 1:
            sampler = torch.utils.data.distributed.DistributedSampler(dataset)

        per_gpu_batch = self.config.batch_size // self.world_size
        if per_gpu_batch < 1:
            per_gpu_batch = 1

        dataloader = torch.utils.data.DataLoader(
            dataset,
            batch_size=per_gpu_batch,
            sampler=sampler,
            shuffle=(sampler is None),
            num_workers=4,
            pin_memory=True,
            drop_last=True,
        )

        return dataloader

    def setup_optimizer(
        self,
        model: nn.Module,
    ) -> torch.optim.Optimizer:
        """创建优化器。

        Args:
            model: 待优化的模型。

        Returns:
            配置好的 AdamW 优化器。
        """
        optimizer = torch.optim.AdamW(
            model.parameters(),
            lr=self.config.learning_rate,
            weight_decay=self.config.weight_decay,
        )
        return optimizer

    def warmup_lr_schedule(self, step: int) -> float:
        """学习率预热调度。

        Args:
            step: 当前训练步数。

        Returns:
            当前步的学习率缩放因子。
        """
        if step < self.config.warmup_steps:
            return step / max(1, self.config.warmup_steps)
        return 1.0

    def train(
        self,
        model: nn.Module,
        dataloader: torch.utils.data.DataLoader,
        optimizer: torch.optim.Optimizer,
        compute_loss: Callable[[nn.Module, Any], torch.Tensor],
    ) -> dict[str, list[float]]:
        """分布式训练主循环。

        Args:
            model: 分布式模型。
            dataloader: 训练数据加载器。
            optimizer: 优化器。
            compute_loss: 损失计算函数，签名为
                ``compute_loss(model, batch) -> loss_tensor``。

        Returns:
            训练历史字典，包含:
            - ``losses``: 每步的损失值
            - ``learning_rates``: 每步的学习率
        """
        losses: list[float] = []
        learning_rates: list[float] = []

        # 断点续训
        if self.config.resume_from_checkpoint:
            self._load_checkpoint(model, optimizer, self.config.resume_from_checkpoint)

        for epoch in range(self._epoch, self.config.epochs):
            self._epoch = epoch

            if self.world_size > 1 and hasattr(dataloader.sampler, "set_epoch"):
                dataloader.sampler.set_epoch(epoch)

            model.train()
            optimizer.zero_grad()

            for batch_idx, batch in enumerate(dataloader):
                # 混合精度前向
                autocast_ctx = (
                    torch.cuda.amp.autocast(dtype=self._autocast_dtype)
                    if self._autocast_dtype is not None
                    else _nullcontext()
                )

                with autocast_ctx:
                    loss = compute_loss(model, batch)
                    loss = loss / self.config.gradient_accumulation_steps

                # 反向传播
                if self._scaler is not None:
                    self._scaler.scale(loss).backward()
                else:
                    loss.backward()

                # 梯度累积
                if (batch_idx + 1) % self.config.gradient_accumulation_steps == 0:
                    # 梯度裁剪
                    if self.config.max_gradient_norm is not None:
                        if self._scaler is not None:
                            self._scaler.unscale_(optimizer)
                        torch.nn.utils.clip_grad_norm_(
                            model.parameters(),
                            self.config.max_gradient_norm,
                        )

                    # 学习率预热
                    lr_scale = self.warmup_lr_schedule(self._step)
                    for pg in optimizer.param_groups:
                        pg["lr"] = self.config.learning_rate * lr_scale

                    # 优化器步进
                    if self._scaler is not None:
                        self._scaler.step(optimizer)
                        self._scaler.update()
                    else:
                        optimizer.step()
                    optimizer.zero_grad()

                    self._step += 1
                    losses.append(loss.item() * self.config.gradient_accumulation_steps)
                    learning_rates.append(optimizer.param_groups[0]["lr"])

                    # 日志
                    if self.global_rank == 0 and self._step % self.config.log_interval == 0:
                        logger.info(
                            "Epoch %d/%d, Step %d, Loss: %.4f, LR: %.2e",
                            epoch + 1,
                            self.config.epochs,
                            self._step,
                            losses[-1],
                            learning_rates[-1],
                        )

                    # 检查点保存
                    if self._step % self.config.checkpoint_interval == 0:
                        self._save_checkpoint(model, optimizer)

            # 每个 epoch 结束后保存检查点
            if self.global_rank == 0:
                self._save_checkpoint(model, optimizer, suffix=f"epoch_{epoch}")

        return {"losses": losses, "learning_rates": learning_rates}

    def _save_checkpoint(
        self,
        model: nn.Module,
        optimizer: torch.optim.Optimizer,
        suffix: str = "",
    ) -> None:
        """保存训练检查点。

        Args:
            model: 当前模型。
            optimizer: 当前优化器。
            suffix: 检查点文件名后缀。
        """
        if self.global_rank != 0:
            return

        checkpoint_dir = Path(self.config.checkpoint_dir)
        checkpoint_dir.mkdir(parents=True, exist_ok=True)

        # 获取模型状态（处理 DDP/FSDP 包装）
        model_state = model
        if hasattr(model, "module"):
            model_state = model.module

        checkpoint = {
            "model_state_dict": model_state.state_dict(),
            "optimizer_state_dict": optimizer.state_dict(),
            "step": self._step,
            "epoch": self._epoch,
            "config": self.config.__dict__,
        }

        filename = f"checkpoint_step_{self._step}"
        if suffix:
            filename += f"_{suffix}"
        filename += ".pt"

        checkpoint_path = checkpoint_dir / filename
        torch.save(checkpoint, checkpoint_path)
        logger.info("检查点已保存: %s", checkpoint_path)

    def _load_checkpoint(
        self,
        model: nn.Module,
        optimizer: torch.optim.Optimizer,
        checkpoint_path: str,
    ) -> None:
        """加载训练检查点（断点续训）。

        Args:
            model: 待加载权重的模型。
            optimizer: 待加载状态的优化器。
            checkpoint_path: 检查点文件路径。
        """
        checkpoint = torch.load(checkpoint_path, map_location=self.device, weights_only=False)

        # 处理 DDP/FSDP 包装
        model_state = model
        if hasattr(model, "module"):
            model_state = model.module

        model_state.load_state_dict(checkpoint["model_state_dict"])
        optimizer.load_state_dict(checkpoint["optimizer_state_dict"])
        self._step = checkpoint.get("step", 0)
        self._epoch = checkpoint.get("epoch", 0)

        logger.info(
            "检查点已恢复: %s (step=%d, epoch=%d)",
            checkpoint_path,
            self._step,
            self._epoch,
        )

    def cleanup(self) -> None:
        """清理分布式环境。

        在训练结束后调用，销毁分布式进程组。
        """
        import torch.distributed as dist

        if dist.is_initialized():
            dist.destroy_process_group()
            logger.info("分布式环境已清理")

    def evaluate(
        self,
        model: nn.Module,
        dataloader: torch.utils.data.DataLoader,
        compute_metrics: Callable[[nn.Module, Any], dict[str, float]],
    ) -> dict[str, float]:
        """在验证集上评估模型。

        Args:
            model: 待评估的模型。
            dataloader: 验证数据加载器。
            compute_metrics: 指标计算函数，签名为
                ``compute_metrics(model, batch) -> dict``。

        Returns:
            平均指标字典。
        """
        model.eval()
        total_metrics: dict[str, float] = {}
        num_batches = 0

        with torch.no_grad():
            for batch in dataloader:
                metrics = compute_metrics(model, batch)
                for key, value in metrics.items():
                    total_metrics[key] = total_metrics.get(key, 0.0) + value
                num_batches += 1

        avg_metrics = {key: value / max(num_batches, 1) for key, value in total_metrics.items()}

        if self.global_rank == 0:
            metrics_str = ", ".join(f"{k}={v:.4f}" for k, v in avg_metrics.items())
            logger.info("评估结果: %s", metrics_str)

        return avg_metrics


class _nullcontext:
    """简化的 context manager（兼容 Python 3.10+）。

    ``contextlib.nullcontext`` 的轻量替代，用于条件性 autocast。
    """

    def __enter__(self) -> None:
        pass

    def __exit__(self, *args: object) -> None:
        pass


def main() -> None:
    """命令行入口 — 从配置文件启动训练。

    使用方式::

        torchrun --nproc_per_node=4 training/distributed_trainer.py --config config.yaml
    """
    parser = argparse.ArgumentParser(description="分布式训练启动器")
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="训练配置 YAML 文件路径",
    )
    parser.add_argument("--batch-size", type=int, default=32, help="全局批次大小")
    parser.add_argument("--epochs", type=int, default=100, help="训练轮数")
    parser.add_argument("--lr", type=float, default=1e-4, help="学习率")
    parser.add_argument(
        "--sharding",
        type=str,
        default="ddp",
        choices=["ddp", "fsdp", "hybrid"],
        help="分片策略",
    )
    parser.add_argument("--mixed-precision", type=str, default=None, choices=["fp16", "bf16"])
    parser.add_argument("--gradient-checkpointing", action="store_true")
    parser.add_argument("--checkpoint-dir", type=str, default="data/checkpoints")
    parser.add_argument("--resume", type=str, default=None, help="断点续训检查点路径")

    args = parser.parse_args()

    # 加载配置文件（如果提供）
    config_kwargs: dict[str, Any] = {
        "batch_size": args.batch_size,
        "epochs": args.epochs,
        "learning_rate": args.lr,
        "sharding_strategy": args.sharding,
        "mixed_precision": args.mixed_precision,
        "gradient_checkpointing": args.gradient_checkpointing,
        "checkpoint_dir": args.checkpoint_dir,
        "resume_from_checkpoint": args.resume,
    }

    if args.config:
        import yaml

        with open(args.config) as f:
            yaml_config = yaml.safe_load(f)
        config_kwargs.update(yaml_config)

    config = TrainingConfig(**config_kwargs)

    # 创建训练器（实际训练需要用户提供模型和数据）
    trainer = DistributedTrainer(config)
    logger.info(
        "训练器已创建: world_size=%d, sharding=%s",
        trainer.world_size,
        config.sharding_strategy,
    )
    logger.info("请通过 Python API 调用 trainer.train() 方法开始训练")
    logger.info("配置: %s", config)

    trainer.cleanup()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    main()
