# -*- coding: utf-8 -*-
"""生成 SeedVR2 水印签名密钥（仅本机持有，切勿提交仓库或随便携包分发）。

用法:
    python scripts/init_watermark_key.py
"""
from pathlib import Path
import secrets

KEY_FILE = Path(__file__).resolve().parent.parent / ".watermark_key"


def main() -> None:
    if KEY_FILE.exists():
        existing = KEY_FILE.read_text(encoding="utf-8").strip()
        if existing:
            print(f"密钥已存在: {KEY_FILE}（如需重置请先手动删除该文件）")
            return
    KEY_FILE.write_text(secrets.token_hex(32) + "\n", encoding="utf-8")
    print(f"水印签名密钥已生成: {KEY_FILE}")
    print("注意:")
    print("  1. 该文件已被 .gitignore 忽略，请离线备份（密钥遗失后旧水印将无法验证）;")
    print("  2. 打包便携包时务必排除该文件，密钥只应存在于您的开发/签发机器。")


if __name__ == "__main__":
    main()
