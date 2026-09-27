"""카드뉴스 이미지(1080x1350, 4:5)를 그린다.

표지(어두운 그라데이션) → 이슈 카드(밝은 종이 톤) → 마무리 카드 순서로 만든다.
정당 색으로 읽히지 않도록 태그 색은 한 가지 강조색만 쓴다.
"""
import os
from datetime import datetime

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1080, 1350
PAD = 84

# 표지·마무리 (어두운 톤)
NAVY_TOP = (10, 17, 40)
NAVY_BOTTOM = (27, 38, 92)
ON_DARK = (248, 250, 252)
ON_DARK_MUTED = (160, 172, 204)

# 이슈 카드 (밝은 톤)
PAPER = (246, 243, 236)
PANEL = (255, 255, 255)
INK = (17, 24, 39)
INK_MUTED = (107, 114, 128)

ACCENT = (255, 94, 58)       # 태그·번호·포인트
HIGHLIGHT = (255, 224, 102)  # 형광펜

BRAND = "KOREA CARD NEWS"
WEEKDAYS = "월화수목금토일"

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(os.path.dirname(HERE), "fonts")

# 굵기별 후보 (경로, ttc 인덱스). 저장소의 Pretendard를 먼저 쓰고, 없으면 시스템 한글 폰트
FONT_CANDIDATES = {
    "extrabold": [(os.path.join(FONT_DIR, "Pretendard-ExtraBold.otf"), 0)],
    "bold": [(os.path.join(FONT_DIR, "Pretendard-Bold.otf"), 0)],
    "semibold": [(os.path.join(FONT_DIR, "Pretendard-SemiBold.otf"), 0)],
    "medium": [(os.path.join(FONT_DIR, "Pretendard-Medium.otf"), 0)],
}
SYSTEM_BOLD = [
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 1),
    ("/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf", 0),
    ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0),
]
SYSTEM_REGULAR = [
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 1),
    ("/usr/share/fonts/truetype/nanum/NanumGothic.ttf", 0),
    ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0),
]


class Fonts:
    def __init__(self, override=""):
        self.paths = {}
        for weight, candidates in FONT_CANDIDATES.items():
            fallback = SYSTEM_REGULAR if weight == "medium" else SYSTEM_BOLD
            chosen = None
            if override and os.path.exists(override):
                chosen = (override, 0)
            for path, index in candidates + fallback:
                if chosen:
                    break
                if os.path.exists(path):
                    chosen = (path, index)
            if not chosen:
                raise FileNotFoundError("한글 폰트를 찾을 수 없습니다. fonts/ 폴더를 확인하거나 CARD_FONT_PATH를 지정하세요.")
            self.paths[weight] = chosen
        self._cache = {}

    def get(self, size, weight="medium"):
        key = (size, weight)
        if key not in self._cache:
            path, index = self.paths[weight]
            self._cache[key] = ImageFont.truetype(path, size, index=index)
        return self._cache[key]


# ---------------------------------------------------------------- 그리기 도우미

def wrap(draw, text, font, max_width):
    """픽셀 폭 기준 줄바꿈. 가능하면 공백에서 끊고, 긴 어절은 글자 단위로 자른다."""
    lines = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split(" "):
            candidate = f"{line} {word}".strip()
            if draw.textlength(candidate, font=font) <= max_width:
                line = candidate
                continue
            if line:
                lines.append(line)
            line = ""
            for ch in word:
                if draw.textlength(line + ch, font=font) > max_width:
                    lines.append(line)
                    line = ""
                line += ch
        lines.append(line)
    return [l for l in lines if l]


def fit_text(draw, text, fonts, weight, sizes, max_width, max_lines):
    """max_lines 안에 들어가는 가장 큰 글자 크기를 고른다."""
    for size in sizes:
        font = fonts.get(size, weight)
        lines = wrap(draw, text, font, max_width)
        if len(lines) <= max_lines:
            return font, lines
    return font, lines[:max_lines]


def draw_lines(draw, lines, xy, font, fill, line_height):
    x, y = xy
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height
    return y


def spaced_text(draw, xy, text, font, fill, tracking):
    """자간을 넓힌 글자 (영문 브랜드 표기용)."""
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + tracking
    return x


def spaced_width(draw, text, font, tracking):
    return sum(draw.textlength(ch, font=font) + tracking for ch in text) - tracking


def vertical_gradient(top, bottom):
    mask = Image.linear_gradient("L").resize((W, H))
    return Image.composite(Image.new("RGB", (W, H), bottom), Image.new("RGB", (W, H), top), mask)


def glow(img, center, radius, color, strength):
    """부드러운 빛 번짐 원."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx, cy = center
    d.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=(*color, strength))
    layer = layer.filter(ImageFilter.GaussianBlur(radius // 2))
    img.alpha_composite(layer)


def pill(draw, xy, text, font, fill, text_fill, pad_x=26, height=62):
    x, y = xy
    w = draw.textlength(text, font=font) + pad_x * 2
    draw.rounded_rectangle((x, y, x + w, y + height), radius=height // 2, fill=fill)
    draw.text((x + pad_x, y + height / 2), text, font=font, fill=text_fill, anchor="lm")
    return x + w


def page_dots(draw, index, total, center_y, on_dark):
    """캐러셀 진행 표시 (현재 장은 길쭉한 막대)."""
    active = ACCENT
    idle = (255, 255, 255, 70) if on_dark else (17, 24, 39, 40)
    dot, gap, long = 12, 12, 40
    width = long + (total - 1) * dot + (total - 1) * gap
    x = W - PAD - width
    for i in range(1, total + 1):
        w = long if i == index else dot
        draw.rounded_rectangle((x, center_y - dot / 2, x + w, center_y + dot / 2), radius=dot / 2,
                               fill=active if i == index else idle)
        x += w + gap


def header(draw, fonts, left, right, on_dark):
    color = ON_DARK_MUTED if on_dark else INK_MUTED
    f = fonts.get(26, "bold")
    draw.rounded_rectangle((PAD, PAD + 4, PAD + 14, PAD + 18), radius=4, fill=ACCENT)
    spaced_text(draw, (PAD + 26, PAD), left, f, color, 4)
    draw.text((W - PAD, PAD), right, font=fonts.get(26, "semibold"), fill=color, anchor="ra")


def footer(draw, fonts, handle, index, total, on_dark):
    y = H - PAD - 10
    draw.text((PAD, y), handle, font=fonts.get(30, "bold"), fill=ON_DARK if on_dark else INK, anchor="lm")
    page_dots(draw, index, total, y, on_dark)


# ---------------------------------------------------------------- 카드 종류별

def render_cover(data, now, fonts, handle, total, label="정치 브리핑"):
    img = vertical_gradient(NAVY_TOP, NAVY_BOTTOM).convert("RGBA")
    glow(img, (W - 120, 260), 360, ACCENT, 110)
    glow(img, (80, H - 200), 300, (80, 110, 255), 90)
    img = img.convert("RGB")  # RGB 바탕에 RGBA로 그려야 반투명 색이 섞인다
    d = ImageDraw.Draw(img, "RGBA")

    slot = now.replace(minute=now.minute // 30 * 30)
    header(d, fonts, BRAND, f"{now:%Y.%m.%d} ({WEEKDAYS[now.weekday()]})", on_dark=True)

    y = 210
    x = pill(d, (PAD, y), label, fonts.get(32, "bold"), ACCENT, (255, 255, 255))
    d.text((x + 20, y + 31), f"{slot:%H:%M} 기준", font=fonts.get(30, "semibold"), fill=ON_DARK_MUTED, anchor="lm")

    title_font, lines = fit_text(d, data["headline"], fonts, "extrabold", (104, 96, 88, 80), W - 2 * PAD, 3)
    y = 320
    lh = int(title_font.size * 1.22)
    for i, line in enumerate(lines):
        if i == len(lines) - 1:  # 마지막 줄에 강조 밑줄
            lw = d.textlength(line, font=title_font)
            d.rectangle((PAD, y + title_font.size * 0.72, PAD + lw, y + title_font.size * 1.02), fill=(*ACCENT, 150))
        d.text((PAD, y), line, font=title_font, fill=ON_DARK)
        y += lh

    y += 50
    d.text((PAD, y), "이번 브리핑", font=fonts.get(28, "bold"), fill=ON_DARK_MUTED)
    y += 56
    item_font = fonts.get(38, "semibold")
    num_font = fonts.get(26, "extrabold")
    for i, card in enumerate(data["cards"], 1):
        lines = wrap(d, card["title"], item_font, W - 2 * PAD - 76)[:2]
        if y + len(lines) * 52 > H - PAD - 150:
            break
        d.ellipse((PAD, y + 2, PAD + 48, y + 50), fill=(255, 255, 255, 28), outline=(255, 255, 255, 90), width=2)
        d.text((PAD + 24, y + 26), str(i), font=num_font, fill=ON_DARK, anchor="mm")
        y = draw_lines(d, lines, (PAD + 76, y + 2), item_font, ON_DARK, 52) + 26

    d.text((W - PAD, H - PAD - 90), "옆으로 넘겨보세요  →", font=fonts.get(28, "semibold"),
           fill=ON_DARK_MUTED, anchor="rm")
    footer(d, fonts, handle, 1, total, on_dark=True)
    return img


def render_card(card, index, total, sources, fonts, handle, label="정치 브리핑"):
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img, "RGBA")
    number = index - 1
    header(d, fonts, BRAND, label, on_dark=False)

    # 번호 + 태그
    y = 196
    num_font = fonts.get(120, "extrabold")
    d.text((PAD - 4, y), f"{number:02d}", font=num_font, fill=ACCENT)
    num_w = d.textlength(f"{number:02d}", font=num_font)
    pill(d, (PAD + num_w + 28, y + 42), card["tag"], fonts.get(30, "bold"), INK, (255, 255, 255),
         pad_x=24, height=56)

    title_font, lines = fit_text(d, card["title"], fonts, "extrabold", (80, 74, 68, 62), W - 2 * PAD, 3)
    y += 190
    lh = int(title_font.size * 1.3)
    for line in lines:
        lw = d.textlength(line, font=title_font)
        d.rectangle((PAD - 6, y + title_font.size * 0.6, PAD + lw + 6, y + title_font.size * 1.1),
                    fill=(*HIGHLIGHT, 220))
        d.text((PAD, y), line, font=title_font, fill=INK)
        y += lh

    # 본문 패널 (글은 패널 안에서 세로 가운데 정렬)
    top = y + 40
    bottom = H - PAD - 150
    d.rounded_rectangle((PAD - 4, top + 10, W - PAD + 4, bottom + 10), radius=36, fill=(17, 24, 39, 10))
    d.rounded_rectangle((PAD - 4, top, W - PAD + 4, bottom), radius=36, fill=PANEL)
    inner_w = W - 2 * PAD - 110
    for size in (46, 43, 40, 37, 34):
        body_font = fonts.get(size, "medium")
        body_lines = wrap(d, card["body"], body_font, inner_w)
        line_h = int(size * 1.62)
        if len(body_lines) * line_h <= bottom - top - 96:
            break
    text_h = len(body_lines) * line_h - (line_h - body_font.size)
    text_top = top + (bottom - top - text_h) // 2 - 6
    d.rounded_rectangle((PAD + 40, text_top + 4, PAD + 48, text_top + 4 + min(text_h, 120)), radius=4, fill=ACCENT)
    draw_lines(d, body_lines, (PAD + 76, text_top), body_font, INK, line_h)

    if sources:
        src_font = fonts.get(26, "semibold")
        text = "출처  " + " · ".join(sources)
        line = wrap(d, text, src_font, W - 2 * PAD)[0]
        d.text((PAD, bottom + 34), line, font=src_font, fill=INK_MUTED)

    footer(d, fonts, handle, index, total, on_dark=False)
    return img


def render_outro(fonts, handle, total, label="정치 브리핑"):
    img = vertical_gradient(NAVY_BOTTOM, NAVY_TOP).convert("RGBA")
    glow(img, (W // 2, H // 2 - 80), 380, ACCENT, 70)
    img = img.convert("RGB")
    d = ImageDraw.Draw(img, "RGBA")
    header(d, fonts, BRAND, label, on_dark=True)

    cy = H // 2 - 160
    d.text((W // 2, cy), "핵심만 빠르게,", font=fonts.get(84, "extrabold"), fill=ON_DARK, anchor="mm")
    d.text((W // 2, cy + 110), "30분마다 정리합니다", font=fonts.get(84, "extrabold"), fill=ON_DARK, anchor="mm")

    f = fonts.get(40, "bold")
    text = f"팔로우  {handle}"
    tw = d.textlength(text, font=f)
    x0, y0 = (W - tw) / 2 - 44, cy + 250
    d.rounded_rectangle((x0, y0, x0 + tw + 88, y0 + 92), radius=46, fill=ACCENT)
    d.text((W // 2, y0 + 46), text, font=f, fill=(255, 255, 255), anchor="mm")

    d.text((W // 2, y0 + 170), "기사 원문 링크는 답글에서 확인하세요", font=fonts.get(32, "semibold"),
           fill=ON_DARK_MUTED, anchor="mm")
    d.text((W // 2, y0 + 220), "여러 언론 보도를 AI로 요약했습니다", font=fonts.get(28, "medium"),
           fill=ON_DARK_MUTED, anchor="mm")

    footer(d, fonts, handle, total, total, on_dark=True)
    return img


def render_all(data, articles, now: datetime, out_dir, handle, font_override="", label="정치 브리핑"):
    fonts = Fonts(font_override)
    os.makedirs(out_dir, exist_ok=True)
    total = len(data["cards"]) + 2  # 표지 + 이슈 카드 + 마무리
    images = [render_cover(data, now, fonts, handle, total, label)]
    for i, card in enumerate(data["cards"], 2):
        sources = sorted({articles[j - 1].source for j in card["source_ids"]})
        images.append(render_card(card, i, total, sources, fonts, handle, label))
    images.append(render_outro(fonts, handle, total, label))

    paths = []
    for i, img in enumerate(images, 1):
        path = os.path.join(out_dir, f"card_{i:02d}.jpg")
        img.save(path, "JPEG", quality=92)
        paths.append(path)
    return paths
