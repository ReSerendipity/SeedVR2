#!/usr/bin/env python3
"""
render_pages.py — 将 Jinja2 模板渲染为静态 HTML，供前端 smoke 测试读取。

参考 MiniMax-H3-lite/scripts/render_pages.py 模式。
SeedVR2 前端由 FastAPI + Jinja2 单端口直出，jsdom smoke 测试无法执行
Jinja2 模板，因此先由本脚本把关键页面渲染到 tests/frontend/_rendered/，
smoke.js 再读取。

用法: python scripts/render_pages.py
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "app" / "integrated_app" / "templates"
OUTPUT_DIR = PROJECT_ROOT / "tests" / "frontend" / "_rendered"

# 关键页面：restore（工作台主页面）、index（首页）、history（历史记录）、settings（设置）
PAGES = ["restore", "index", "history", "settings"]


def main() -> None:
    import sys

    sys.path.insert(0, str(PROJECT_ROOT))

    from jinja2 import Environment, FileSystemLoader, select_autoescape

    from app.integrated_app.i18n import I18n

    # 加载中文翻译
    locales_dir = str(PROJECT_ROOT / "app" / "integrated_app" / "locales")
    i18n = I18n(locales_dir=locales_dir, default_locale="zh")
    locales = [{"code": code, "name": i18n.get_locale_name(code)} for code in i18n.available_locales]

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for name in PAGES:
        try:
            template = env.get_template(f"{name}.html")
            html = template.render(
                request=None,
                t=i18n.t,
                active_page=name,
                current_locale=i18n.current_locale,
                locale_name=i18n.get_locale_name(i18n.current_locale),
                locales=locales,
            )
            (OUTPUT_DIR / f"{name}.html").write_text(html, encoding="utf-8")
            print(f"[OK] 渲染 {name}.html ({len(html)} 字节) -> tests/frontend/_rendered/")
        except Exception as e:
            print(f"[FAIL] 渲染 {name}.html 失败: {e}")


if __name__ == "__main__":
    main()
