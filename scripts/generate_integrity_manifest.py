#!/usr/bin/env python3
"""生成核心模块完整性清单 (integrity_manifest.json)

用于启动时核心模块 SHA256 完整性自检 (CWE-912 防御)。

用法:
    python scripts/generate_integrity_manifest.py
"""

import hashlib
import json
from datetime import datetime
from pathlib import Path

# 核心安全模块清单 (相对于 bin/integrated_app/)
_CORE_MODULES = [
    "app_server.py",
    "config.py",
    "model_manager.py",
    "security/path_guard.py",
    "security/integrity_check.py",
    "security/watermark.py",
    "security/integrity_selfcheck.py",
    "middleware/csrf.py",
    "middleware/basic_auth.py",
    "engines/seedvr2_engine.py",
]


def compute_sha256(filepath: Path) -> str:
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(8 * 1024 * 1024)
            if not chunk:
                break
            sha256.update(chunk)
    return sha256.hexdigest()


def main():
    project_root = Path(__file__).parent.parent
    app_dir = project_root / "bin" / "integrated_app"
    manifest_path = app_dir / "security" / "integrity_manifest.json"

    files = {}
    for module_rel in _CORE_MODULES:
        module_path = app_dir / module_rel
        if module_path.exists():
            files[module_rel] = compute_sha256(module_path)
            print(f"  ✓ {module_rel}: {files[module_rel][:16]}...")
        else:
            print(f"  ✗ {module_rel}: NOT FOUND")

    manifest = {
        "generated_at": datetime.now().isoformat(),
        "generator": "scripts/generate_integrity_manifest.py",
        "description": "核心安全模块 SHA256 完整性清单，用于启动时自检",
        "files": files,
    }

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"\n已生成: {manifest_path} ({len(files)} 个模块)")


if __name__ == "__main__":
    main()
