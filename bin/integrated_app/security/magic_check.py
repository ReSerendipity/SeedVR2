# SPDX-FileCopyrightText: Copyright (c) 2024-2026 ReSerendipity
# SPDX-License-Identifier: Apache-2.0
"""上传文件魔数（Magic Number）白名单校验模块。

通过读取文件头部字节判断文件实际类型，防止攻击者将恶意文件
伪装为合法扩展名上传（如将 .exe 改名为 .jpg）。

安全策略:
    - 读取文件前 32 字节作为魔数签名
    - 与已知白名单魔数前缀匹配
    - 仅当扩展名与实际魔数一致时才允许保存
    - 不匹配时返回详细错误信息

使用方式:
    from bin.integrated_app.security.magic_check import validate_upload_magic

    is_valid, detected_type, error = validate_upload_magic(contents, ".jpg")
    if not is_valid:
        raise HTTPException(status_code=400, detail=error)
"""

# 图片魔数白名单: {魔数前缀: 对应扩展名列表}
_IMG_MAGICS: list[tuple[bytes, frozenset[str]]] = [
    (b"\xff\xd8\xff", frozenset({".jpg", ".jpeg"})),
    (b"\x89PNG\r\n\x1a\n", frozenset({".png"})),
    (b"BM", frozenset({".bmp"})),
    (b"GIF87a", frozenset({".gif"})),
    (b"GIF89a", frozenset({".gif"})),
    (b"RIFF", frozenset({".webp"})),  # 需再校验 8-11 字节为 WEBP
    (b"II*\x00", frozenset({".tif", ".tiff"})),  # TIFF little-endian
    (b"MM\x00*", frozenset({".tif", ".tiff"})),  # TIFF big-endian
]

# 视频魔数白名单: {魔数前缀: 对应扩展名列表}
# 注意: MP4/MOV 等容器格式通过 _check_ftyp 通用检测处理，
# 此处仅列其他格式
_VID_MAGICS: list[tuple[bytes, frozenset[str]]] = [
    (b"RIFF", frozenset({".avi"})),  # AVI 也以 RIFF 开头，需区分
    (b"\x1aE\xdf\xa3", frozenset({".mkv", ".webm"})),  # Matroska/WebM
    (b"OggS", frozenset({".ogg"})),
    (b"FLV", frozenset({".flv"})),
    (b"\x30\x26\xB2\x75\x8E\x66\xCF\x11", frozenset({".wmv", ".avi"})),  # ASF/WMV
]

# 允许的图片/视频扩展名集合（与 common.py 保持一致）
_ALLOWED_IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tiff"})
_ALLOWED_VIDEO_EXTS = frozenset({".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv", ".wmv"})

# 读取的魔数字节数
_MAGIC_READ_SIZE = 32


def _check_webp(header: bytes) -> bool:
    """校验 RIFF 文件是否确实为 WebP（偏移 8-11 字节为 'WEBP'）。"""
    return len(header) >= 12 and header[8:12] == b"WEBP"


def _check_avi(header: bytes) -> bool:
    """校验 RIFF 文件是否确实为 AVI（偏移 8-11 字节为 'AVI '）。"""
    return len(header) >= 12 and header[8:12] == b"AVI "


def _check_ftyp(header: bytes) -> str | None:
    """检测 ISO BMFF ftyp box（MP4/MOV/3GP 等容器格式）。

    ftyp box 结构: [4字节box大小] 'ftyp' [4字节major_brand] ...
    """
    if len(header) < 8:
        return None
    # 检查偏移 4-7 是否为 'ftyp'
    if header[4:8] == b"ftyp":
        if len(header) >= 12:
            major_brand = header[8:12]
            if major_brand in (b"isom", b"mp42", b"mp41", b"avc1", b"M4V ", b"qt  ", b"MSNV"):
                return ".mp4"
            if major_brand in (b"qt  ",):
                return ".mov"
            # 默认归为 mp4
            return ".mp4"
        return ".mp4"
    return None


def validate_upload_magic(
    contents: bytes,
    file_ext: str,
) -> tuple[bool, str | None, str | None]:
    """校验上传文件的实际魔数是否与扩展名匹配。

    Args:
        contents: 文件二进制内容（至少前 32 字节）。
        file_ext: 文件扩展名（含点号，小写），如 ".jpg"、".mp4"。

    Returns:
        tuple[bool, str | None, str | None]:
            - is_valid: 校验是否通过
            - detected_type: 检测到的媒体类型 "image"/"video"/None
            - error_msg: 校验失败时的错误信息，成功时为 None

    Example:
        >>> is_valid, dtype, err = validate_upload_magic(b"\\x89PNG...", ".png")
        >>> assert is_valid and dtype == "image"
    """
    if not contents:
        return False, None, "文件内容为空"

    ext = file_ext.lower()
    header = contents[:_MAGIC_READ_SIZE]

    is_image_ext = ext in _ALLOWED_IMAGE_EXTS
    is_video_ext = ext in _ALLOWED_VIDEO_EXTS

    if not is_image_ext and not is_video_ext:
        return False, None, f"不支持的文件扩展名: {ext}"

    # --- 图片魔数校验 ---
    if is_image_ext:
        for magic, valid_exts in _IMG_MAGICS:
            if header.startswith(magic):
                # RIFF 可能是 WebP 或 AVI，需进一步区分
                if magic == b"RIFF":
                    if _check_webp(header) and ext in valid_exts:
                        return True, "image", None
                    continue
                if ext in valid_exts:
                    return True, "image", None

        return False, "image", (
            f"文件扩展名 {ext} 与实际文件内容不匹配（魔数校验失败）。"
            f"该文件可能已被伪装或损坏。"
        )

    # --- 视频魔数校验 ---
    if is_video_ext:
        # 先尝试 ftyp 通用检测（MP4/MOV 等）
        ftyp_ext = _check_ftyp(header)
        if ftyp_ext is not None:
            if ext in (".mp4", ".mov"):
                return True, "video", None
            # ftyp 检测到但扩展名不匹配
            return False, "video", (
                f"文件扩展名 {ext} 与实际文件内容不匹配"
                f"（检测到 {ftyp_ext} 格式）。该文件可能已被伪装。"
            )

        for magic, valid_exts in _VID_MAGICS:
            if header.startswith(magic):
                # RIFF 可能是 AVI
                if magic == b"RIFF":
                    if _check_avi(header) and ext in valid_exts:
                        return True, "video", None
                    continue
                # ASF/WMV 魔数
                if magic == b"\x30\x26\xB2\x75\x8E\x66\xCF\x11":
                    if ext in (".wmv",):
                        return True, "video", None
                    continue
                if ext in valid_exts:
                    return True, "video", None

        return False, "video", (
            f"文件扩展名 {ext} 与实际文件内容不匹配（魔数校验失败）。"
            f"该文件可能已被伪装或损坏。"
        )

    return False, None, f"无法识别的文件类型: {ext}"
