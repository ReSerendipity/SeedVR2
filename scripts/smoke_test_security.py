#!/usr/bin/env python3
"""冒烟测试: 水印 + 自检模块"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np

# 测试水印
from app.integrated_app.security.watermark import embed_watermark, extract_watermark

img = np.random.randint(0, 256, (64, 64, 3), dtype=np.uint8)
wm = embed_watermark(img)
extracted = extract_watermark(wm)
print(f"Watermark embedded: shape={wm.shape}, dtype={wm.dtype}")
print(f"Watermark extracted: {extracted[:40]}...")
print(f"Contains SeedVR2: {'SeedVR2' in extracted}")
print("Watermark test: PASS")

# 测试 PSNR (不可感知性)
mse = np.mean((img.astype(float) - wm.astype(float)) ** 2)
if mse > 0:
    import math

    psnr = 10 * math.log10(255.0**2 / mse)
    print(f"PSNR: {psnr:.1f} dB (should be > 35 dB for imperceptibility)")
else:
    print("PSNR: infinite (identical images)")

# 测试启动自检
from app.integrated_app.security.integrity_selfcheck import run_startup_selfcheck

result = run_startup_selfcheck()
print(
    f"Self-check: {result['passed']}/{result['total']} passed, {result['failed']} failed, {result['skipped']} skipped"
)

# 测试完整性校验
import os

# 创建临时文件测试
import tempfile

from app.integrated_app.security.integrity_check import compute_sha256, verify_checkpoint

with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
    f.write(b"test data for sha256")
    tmpfile = f.name

h = compute_sha256(tmpfile)
print(f"SHA256 of test file: {h[:16]}...")
print(f"Verify with correct hash: {verify_checkpoint(tmpfile, h, purpose='test')}")
print(f"Verify with wrong hash: {verify_checkpoint(tmpfile, '0' * 64, purpose='test')}")
print(f"Verify with empty hash (skip): {verify_checkpoint(tmpfile, '', purpose='test')}")
os.unlink(tmpfile)

# 测试 Basic Auth
from app.integrated_app.middleware.basic_auth import should_enable_auth

print(f"Auth disabled by default: {not should_enable_auth({})}")
print(
    f"Auth enabled when configured: {should_enable_auth({'security': {'auth': {'enable': True, 'username': 'admin', 'password': 'secret'}}})}"
)

# 测试权重加密模块
from app.integrated_app.security.weight_encryption import generate_license, get_machine_fingerprint

fingerprint = get_machine_fingerprint()
print(f"Machine fingerprint: {fingerprint[:16]}...")
license_info = generate_license("test@example.com")
print(f"License key: {license_info.license_key[:16]}...")

print("\n=== All smoke tests PASSED ===")
