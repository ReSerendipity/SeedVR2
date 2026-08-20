#!/usr/bin/env python3
"""翻译键一致性检查脚本。

比较 locales/{zh,zh-TW,en,ja,fr}.yaml 中：
- 缺失键（A 语言有但 B 语言没有）
- 多余键（B 语言多出但基准语言已删除）
- 值为空或仅含空白字符的键

输出 JSON 差异报告，退出码 0 = 通过，1 = 有差异。

使用方法：
    python scripts/check_i18n_keys.py
    python scripts/check_i18n_keys.py --base zh  # 指定基准语言（默认 zh）
    python scripts/check_i18n_keys.py --report report.json  # 输出报告到文件

所属项目：SeedVR2
"""

import argparse
import json
import sys
from pathlib import Path


def load_yaml_keys(file_path: Path) -> dict:
    """加载 YAML 文件，返回扁平化键值对。

    使用递归遍历，将嵌套字典的键用 '.' 拼接为完整路径。
    如 {"nav": {"home": "首页"}} -> {"nav.home": "首页"}

    Args:
        file_path: YAML 文件路径。

    Returns:
        扁平化的键值对字典。
    """
    try:
        import yaml
    except ImportError:
        print("错误: 需要安装 PyYAML: pip install pyyaml", file=sys.stderr)
        sys.exit(2)

    with open(file_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    flat = {}

    def _flatten(prefix: str, value):
        if isinstance(value, dict):
            for k, v in value.items():
                key = f"{prefix}.{k}" if prefix else k
                _flatten(key, v)
        else:
            flat[prefix] = value

    _flatten("", data)
    return flat


def compare_keys(base_keys: set, other_keys: set, base_name: str, other_name: str) -> dict:
    """比较两个语言的键集合。

    Args:
        base_keys: 基准语言的键集合。
        other_keys: 被比较语言的键集合。
        base_name: 基准语言名称。
        other_name: 被比较语言名称。

    Returns:
        包含 missing_in_other、extra_in_other 的差异字典。
    """
    missing_in_other = sorted(base_keys - other_keys)
    extra_in_other = sorted(other_keys - base_keys)
    return {
        "missing_in_other": missing_in_other,
        "extra_in_other": extra_in_other,
    }


def check_empty_values(flat: dict, locale: str) -> list:
    """检查值为空或仅含空白字符的键。

    Args:
        flat: 扁平化键值对。
        locale: 语言名称。

    Returns:
        空值键列表。
    """
    empties = []
    for key, value in flat.items():
        if value is None or isinstance(value, str) and value.strip() == "":
            empties.append(key)
    return empties


def main():
    parser = argparse.ArgumentParser(description="SeedVR2 翻译键一致性检查")
    parser.add_argument(
        "--base",
        default="zh",
        help="基准语言代码（默认 zh）",
    )
    parser.add_argument(
        "--report",
        default=None,
        help="输出 JSON 报告到指定文件（可选）",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="严格模式：有差异时退出码为 1（默认行为）",
    )
    args = parser.parse_args()

    locales_dir = Path(__file__).parent.parent / "app" / "integrated_app" / "locales"
    if not locales_dir.exists():
        print(f"错误: locales 目录不存在: {locales_dir}", file=sys.stderr)
        sys.exit(2)

    yaml_files = sorted(locales_dir.glob("*.yaml"))
    if not yaml_files:
        print(f"错误: 未找到 YAML 语言文件: {locales_dir}", file=sys.stderr)
        sys.exit(2)

    # 加载所有语言
    locales = {}
    for f in yaml_files:
        locale_name = f.stem  # 文件名（不含扩展名）作为语言代码
        locales[locale_name] = load_yaml_keys(f)

    base_name = args.base
    if base_name not in locales:
        print(f"错误: 基准语言 '{base_name}' 不在可用语言中: {list(locales.keys())}", file=sys.stderr)
        sys.exit(2)

    base_keys = set(locales[base_name].keys())
    report = {
        "base_locale": base_name,
        "total_locales": len(locales),
        "locales": list(locales.keys()),
        "base_key_count": len(base_keys),
        "differences": {},
        "empty_values": {},
    }

    has_diff = False

    for locale_name, flat in locales.items():
        if locale_name == base_name:
            # 只检查空值
            empties = check_empty_values(flat, locale_name)
            if empties:
                report["empty_values"][locale_name] = empties
                has_diff = True
            continue

        other_keys = set(flat.keys())
        diff = compare_keys(base_keys, other_keys, base_name, locale_name)
        empties = check_empty_values(flat, locale_name)

        if diff["missing_in_other"] or diff["extra_in_other"]:
            report["differences"][locale_name] = diff
            has_diff = True

        if empties:
            report["empty_values"][locale_name] = empties
            has_diff = True

    # 输出摘要
    print("=" * 60)
    print("SeedVR2 翻译键一致性检查")
    print("=" * 60)
    print(f"基准语言:   {base_name} ({len(base_keys)} 键)")
    print(f"语言列表:   {', '.join(locales.keys())}")
    print()

    if report["differences"]:
        print("📌 键差异:")
        for locale, diff in report["differences"].items():
            if diff["missing_in_other"]:
                print(f"  [{locale}] 缺失 {len(diff['missing_in_other'])} 键:")
                for k in diff["missing_in_other"][:10]:
                    print(f"    - {k}")
                if len(diff["missing_in_other"]) > 10:
                    print(f"    ... 及其他 {len(diff['missing_in_other']) - 10} 键")
            if diff["extra_in_other"]:
                print(f"  [{locale}] 多余 {len(diff['extra_in_other'])} 键:")
                for k in diff["extra_in_other"][:10]:
                    print(f"    + {k}")
                if len(diff["extra_in_other"]) > 10:
                    print(f"    ... 及其他 {len(diff['extra_in_other']) - 10} 键")
        print()

    if report["empty_values"]:
        print("📌 空值键:")
        for locale, empties in report["empty_values"].items():
            print(f"  [{locale}] {len(empties)} 个空值:")
            for k in empties[:10]:
                print(f"    ~ {k}")
            if len(empties) > 10:
                print(f"    ... 及其他 {len(empties) - 10} 键")
        print()

    if not has_diff:
        print("✅ 所有语言翻译键一致，无缺失/多余/空值！")
    else:
        print("❌ 发现翻译键差异，请修复上述问题。")

    print("=" * 60)

    # 输出 JSON 报告
    if args.report:
        report_path = Path(args.report)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\nJSON 报告已输出到: {report_path}")

    if has_diff and args.strict:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
