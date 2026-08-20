"""为 SeedVR2 视频封面叠加中文品牌排版"""
import os

from PIL import Image, ImageDraw, ImageFont


def find_chinese_font():
    """按优先级找一个可用的中文字体路径"""
    candidates = [
        r"C:\Windows\Fonts\msyhbd.ttc",  # 微软雅黑 Bold
        r"C:\Windows\Fonts\msyh.ttc",  # 微软雅黑
        r"C:\Windows\Fonts\simhei.ttf",  # 黑体
        r"C:\Windows\Fonts\simkai.ttf",  # 楷体
        r"C:\Windows\Fonts\simsun.ttc",  # 宋体
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def draw_text_with_shadow(draw, xy, text, font, fill, shadow=(0, 0, 0, 220), offset=(4, 4)):
    """带阴影的文字绘制"""
    x, y = xy
    draw.text((x + offset[0], y + offset[1]), text, font=font, fill=shadow)
    draw.text((x, y), text, font=font, fill=fill)


def add_left_gradient(overlay, w, h, width_ratio=0.45, max_alpha=140):
    """在画面左侧叠加一道由深到浅的暗色渐变，便于放白字"""
    grad = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    end_x = int(w * width_ratio)
    for x in range(0, end_x):
        a = int(max_alpha * (1 - x / end_x))
        gd.line([(x, 0), (x, h)], fill=(0, 0, 0, a))
    return Image.alpha_composite(overlay, grad)


def add_top_gradient(overlay, w, h, height_ratio=0.20, max_alpha=150):
    """在画面顶部叠加一道由深到浅的暗色渐变"""
    grad = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    end_y = int(h * height_ratio)
    for y in range(0, end_y):
        a = int(max_alpha * (1 - y / end_y))
        gd.line([(0, y), (w, y)], fill=(0, 0, 0, a))
    return Image.alpha_composite(overlay, grad)


def make_cover_16x9(input_path, output_path):
    img = Image.open(input_path).convert("RGBA")
    w, h = img.size
    print(f"[16:9] 输入尺寸: {w}x{h}")

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    overlay = add_left_gradient(overlay, w, h, width_ratio=0.42, max_alpha=130)
    draw = ImageDraw.Draw(overlay)

    font_path = find_chinese_font()
    if not font_path:
        raise RuntimeError("找不到任何中文字体")

    # 字号按高度算
    title_size = int(h * 0.115)        # ~ 350px @ 3072
    sub_size = int(h * 0.044)          # ~ 135px
    tag_size = int(h * 0.028)          # ~ 85px
    badge_size = int(h * 0.030)        # ~ 90px

    title_font = ImageFont.truetype(font_path, title_size)
    sub_font = ImageFont.truetype(font_path, sub_size)
    tag_font = ImageFont.truetype(font_path, tag_size)
    badge_font = ImageFont.truetype(font_path, badge_size)

    white = (255, 250, 240, 255)
    soft_white = (245, 245, 250, 245)
    gold = (255, 200, 120, 255)
    shadow = (0, 0, 0, 220)

    # 主标题 SeedVR2
    draw_text_with_shadow(
        draw,
        (int(w * 0.05), int(h * 0.08)),
        "SeedVR2",
        title_font,
        white,
        shadow,
        (6, 6),
    )

    # 副标题
    draw_text_with_shadow(
        draw,
        (int(w * 0.052), int(h * 0.235)),
        "AI 视频 / 图片超分实战",
        sub_font,
        soft_white,
        shadow,
        (4, 4),
    )

    # 标签行
    draw_text_with_shadow(
        draw,
        (int(w * 0.052), int(h * 0.305)),
        "参数详解   ·   效果对比   ·   8K 修复",
        tag_font,
        gold,
        shadow,
        (3, 3),
    )

    # 右上角 8K 徽章
    badge_text = "8K ULTRA HD"
    bb = draw.textbbox((0, 0), badge_text, font=badge_font)
    bw = bb[2] - bb[0]
    bh = bb[3] - bb[1]
    pad_x, pad_y = 28, 18
    bx2 = w - int(w * 0.05)
    by = int(h * 0.085)
    bx1 = bx2 - bw - pad_x * 2
    by2 = by + bh + pad_y * 2
    draw.rounded_rectangle(
        [bx1, by, bx2, by2],
        radius=20,
        fill=(15, 18, 30, 200),
        outline=(255, 200, 120, 255),
        width=3,
    )
    draw.text((bx1 + pad_x, by + pad_y), badge_text, font=badge_font, fill=gold)

    # 合成并保存
    result = Image.alpha_composite(img, overlay)
    result.convert("RGB").save(output_path, "PNG", quality=95)
    print(f"[16:9] 已保存: {output_path}")


def make_cover_3x4(input_path, output_path):
    img = Image.open(input_path).convert("RGBA")
    w, h = img.size
    print(f"[3:4] 输入尺寸: {w}x{h}")

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    overlay = add_top_gradient(overlay, w, h, height_ratio=0.18, max_alpha=150)
    # 底部也加一点渐变
    grad = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for y in range(int(h * 0.93), h):
        a = int(160 * (y - h * 0.93) / (h * 0.07))
        gd.line([(0, y), (w, y)], fill=(0, 0, 0, a))
    overlay = Image.alpha_composite(overlay, grad)
    draw = ImageDraw.Draw(overlay)

    font_path = find_chinese_font()
    if not font_path:
        raise RuntimeError("找不到任何中文字体")

    # 3:4 的画幅比 16:9 窄很多，字号按宽度算时务必更克制
    title_size = int(w * 0.075)        # ~ 270px @ 3584（之前 0.16 太大）
    sub_size = int(w * 0.030)          # ~ 108px
    tag_size = int(w * 0.020)          # ~ 72px
    bottom_size = int(w * 0.018)       # ~ 65px

    title_font = ImageFont.truetype(font_path, title_size)
    sub_font = ImageFont.truetype(font_path, sub_size)
    tag_font = ImageFont.truetype(font_path, tag_size)
    bottom_font = ImageFont.truetype(font_path, bottom_size)

    white = (255, 250, 240, 255)
    soft_white = (245, 245, 250, 245)
    gold = (255, 200, 120, 255)
    shadow = (0, 0, 0, 220)

    # 主标题（居中，靠顶部，避开月亮）
    title_text = "SeedVR2"
    bb = draw.textbbox((0, 0), title_text, font=title_font)
    tw = bb[2] - bb[0]
    draw_text_with_shadow(
        draw,
        ((w - tw) // 2, int(h * 0.028)),
        title_text,
        title_font,
        white,
        shadow,
        (5, 5),
    )

    # 副标题
    sub_text = "AI 视频 / 图片超分实战"
    bb = draw.textbbox((0, 0), sub_text, font=sub_font)
    sw = bb[2] - bb[0]
    draw_text_with_shadow(
        draw,
        ((w - sw) // 2, int(h * 0.105)),
        sub_text,
        sub_font,
        soft_white,
        shadow,
        (3, 3),
    )

    # 标签
    tag_text = "参数详解  ·  效果对比  ·  8K 修复"
    bb = draw.textbbox((0, 0), tag_text, font=tag_font)
    tw2 = bb[2] - bb[0]
    draw_text_with_shadow(
        draw,
        ((w - tw2) // 2, int(h * 0.135)),
        tag_text,
        tag_font,
        gold,
        shadow,
        (3, 3),
    )

    # 底部签名（带浅色 ribbon 背景，提高对比）
    bot_text = "SeedVR2  ·  AI 超分引擎"
    bb = draw.textbbox((0, 0), bot_text, font=bottom_font)
    bw3 = bb[2] - bb[0]
    bh3 = bb[3] - bb[1]
    bx = (w - bw3) // 2
    by = int(h * 0.945)
    # ribbon 背景
    draw.rounded_rectangle(
        [bx - 40, by - 10, bx + bw3 + 40, by + bh3 + 18],
        radius=24,
        fill=(10, 12, 20, 170),
        outline=(255, 200, 120, 200),
        width=2,
    )
    draw.text((bx + 3, by + 3), bot_text, font=bottom_font, fill=(0, 0, 0, 220))
    draw.text((bx, by), bot_text, font=bottom_font, fill=gold)

    # 合成并保存
    result = Image.alpha_composite(img, overlay)
    result.convert("RGB").save(output_path, "PNG", quality=95)
    print(f"[3:4] 已保存: {output_path}")


def make_cover_4x3(input_path, output_path):
    """4:3 横版：与 3:4 手机版排版完全一致——顶部居中标题 + 底部 ribbon，去掉徽章。"""
    img = Image.open(input_path).convert("RGBA")
    w, h = img.size
    print(f"[4:3] 输入尺寸: {w}x{h}")

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    overlay = add_top_gradient(overlay, w, h, height_ratio=0.20, max_alpha=150)
    # 底部渐变
    grad = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for y in range(int(h * 0.90), h):
        a = int(160 * (y - h * 0.90) / (h * 0.10))
        gd.line([(0, y), (w, y)], fill=(0, 0, 0, a))
    overlay = Image.alpha_composite(overlay, grad)
    draw = ImageDraw.Draw(overlay)

    font_path = find_chinese_font()
    if not font_path:
        raise RuntimeError("找不到任何中文字体")

    # 4:3 比 3:4 矮，按高度算字号视觉更稳
    title_size = int(h * 0.095)        # ~ 295px @ 3104 高
    sub_size = int(h * 0.040)          # ~ 125px
    tag_size = int(h * 0.026)          # ~ 80px
    bottom_size = int(h * 0.024)       # ~ 75px

    title_font = ImageFont.truetype(font_path, title_size)
    sub_font = ImageFont.truetype(font_path, sub_size)
    tag_font = ImageFont.truetype(font_path, tag_size)
    bottom_font = ImageFont.truetype(font_path, bottom_size)

    white = (255, 250, 240, 255)
    soft_white = (245, 245, 245, 245)
    gold = (255, 200, 120, 255)
    shadow = (0, 0, 0, 220)

    # 主标题（顶部居中）
    title_text = "SeedVR2"
    bb = draw.textbbox((0, 0), title_text, font=title_font)
    tw = bb[2] - bb[0]
    draw_text_with_shadow(
        draw,
        ((w - tw) // 2, int(h * 0.030)),
        title_text,
        title_font,
        white,
        shadow,
        (5, 5),
    )

    # 副标题
    sub_text = "AI 视频 / 图片超分实战"
    bb = draw.textbbox((0, 0), sub_text, font=sub_font)
    sw = bb[2] - bb[0]
    draw_text_with_shadow(
        draw,
        ((w - sw) // 2, int(h * 0.140)),
        sub_text,
        sub_font,
        soft_white,
        shadow,
        (3, 3),
    )

    # 标签
    tag_text = "参数详解  ·  效果对比  ·  8K 修复"
    bb = draw.textbbox((0, 0), tag_text, font=tag_font)
    tw2 = bb[2] - bb[0]
    draw_text_with_shadow(
        draw,
        ((w - tw2) // 2, int(h * 0.185)),
        tag_text,
        tag_font,
        gold,
        shadow,
        (3, 3),
    )

    # 底部签名 ribbon
    bot_text = "SeedVR2  ·  AI 超分引擎"
    bb = draw.textbbox((0, 0), bot_text, font=bottom_font)
    bw3 = bb[2] - bb[0]
    bh3 = bb[3] - bb[1]
    bx = (w - bw3) // 2
    by = int(h * 0.935)
    draw.rounded_rectangle(
        [bx - 40, by - 10, bx + bw3 + 40, by + bh3 + 18],
        radius=24,
        fill=(10, 12, 20, 170),
        outline=(255, 200, 120, 200),
        width=2,
    )
    draw.text((bx + 3, by + 3), bot_text, font=bottom_font, fill=(0, 0, 0, 220))
    draw.text((bx, by), bot_text, font=bottom_font, fill=gold)

    # 合成并保存
    result = Image.alpha_composite(img, overlay)
    result.convert("RGB").save(output_path, "PNG", quality=95)
    print(f"[4:3] 已保存: {output_path}")


if __name__ == "__main__":
    base_dir = r"C:\Users\Doro\SeedVR2-lite\assets\covers"
    make_cover_16x9(
        os.path.join(base_dir, "cover_16x9_base.png"),
        os.path.join(base_dir, "cover_16x9_final.png"),
    )
    make_cover_3x4(
        os.path.join(base_dir, "cover_3x4.png"),
        os.path.join(base_dir, "cover_3x4_final.png"),
    )
    make_cover_4x3(
        os.path.join(base_dir, "cover_4x3_base.png"),
        os.path.join(base_dir, "cover_4x3_final.png"),
    )
    print("all done")
