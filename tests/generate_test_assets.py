#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2024-2026 ReSerendipity
# SPDX-License-Identifier: Apache-2.0
"""
Generate minimal test binary assets for Playwright E2E tests.

用途：CI 环境（GitHub Actions）在运行 E2E 测试前生成 test-assets 目录下的
测试用二进制文件（sample.jpg / sample.png / sample.mp4）。

设计说明（对应 .gitignore 中 "Test binary assets (regenerated / downloadable)"）：
- 这些文件被 .gitignore 有意排除，由本脚本在 CI 上重新生成；
- 本地开发可直接运行本脚本补齐文件，或使用仓库内已有的占位文件；
- 生成的是最小合法文件（JPEG/PNG 魔数正确、MP4 为合法 ftyp 容器），
  足够 Playwright setInputFiles + 前端文件类型/大小校验使用（后端接口在测试中被 mock）。

用法：
    python tests/generate-test-assets.py
"""

import os
import struct
import sys
import zlib

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGES_DIR = os.path.join(TESTS_DIR, "test-assets", "images")
VIDEOS_DIR = os.path.join(TESTS_DIR, "test-assets", "videos")

# 1x1 红色像素的最小合法 JPEG（SOI + APP0 + DQT + SOF0 + DHT + SOS + EOI）
MINIMAL_JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707070909080a0c"
    "140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c30313434341f27"
    "3d38323c2e333432ffc0000b080001000101011100ffc4001f00000105010101010101000000000000"
    "0000000102030405060708090a0bffc400b5100002010303020403050504040000017d010203000411"
    "05122131410613516107227114328191a1082342b1c11552d1f02433627282090a161718191a252627"
    "28292a3435363738393a434445464748494a535455565758595a636465666768696a73747576777879"
    "7a838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6"
    "c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9faffda000c030100"
    "02110311003f00f8ffc00011080001000103012200021101031101ffc4001f00000105010101010101"
    "00000000000000000102030405060708090a0bffc400b5100002010303020403050504040000017d01"
    "020300041105122131410613516107227114328191a1082342b1c11552d1f02433627282090a161718"
    "191a25262728292a3435363738393a434445464748494a535455565758595a636465666768696a7374"
    "75767778797a838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9ba"
    "c2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9faffda"
    "000c03010002110311003f00f8ffd9"
)


def make_png(width: int = 1, height: int = 1, rgba: tuple = (255, 0, 0, 255)) -> bytes:
    """构造最小合法 PNG（IHDR + IDAT + IEND）。"""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8-bit RGBA
    raw = b"\x00" + bytes(rgba)  # filter byte 0 + pixel
    idat = zlib.compress(raw)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def make_minimal_mp4() -> bytes:
    """构造最小 MP4 容器骨架（ftyp + free + mdat）。

    说明：完整可播放的 MP4 需要 moov/avc1 等轨道 box，生成成本高；
    这里生成 ftyp 魔数正确的骨架文件，满足上传测试（setInputFiles +
    前端扩展名/大小校验 + mock 后端接口）即可。
    """
    ftyp = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2avc1mp41"
    free = b"\x00\x00\x00\x08free"
    mdat = b"\x00\x00\x00\x18mdat" + b"\x00" * 16
    return ftyp + free + mdat


def main() -> int:
    os.makedirs(IMAGES_DIR, exist_ok=True)
    os.makedirs(VIDEOS_DIR, exist_ok=True)

    written = []

    jpg_path = os.path.join(IMAGES_DIR, "sample.jpg")
    with open(jpg_path, "wb") as f:
        f.write(MINIMAL_JPEG)
    written.append(jpg_path)

    png_path = os.path.join(IMAGES_DIR, "sample.png")
    with open(png_path, "wb") as f:
        f.write(make_png())
    written.append(png_path)

    mp4_path = os.path.join(VIDEOS_DIR, "sample.mp4")
    with open(mp4_path, "wb") as f:
        f.write(make_minimal_mp4())
    written.append(mp4_path)

    for p in written:
        print(f"generated: {p} ({os.path.getsize(p)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
