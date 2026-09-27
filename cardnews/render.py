"""카드뉴스 이미지(1080x1350, 4:5)를 그린다."""
import os
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1350
PAD = 90

BG = (15, 23, 42)
BG_COVER = (30, 41, 82)
FG = (241, 245, 249)
MUTED = (148, 163, 184)
ACCENT = (250, 204, 21)
DIVIDER = (51, 65, 85)

WEEKDAYS = "월화수목금토일"

# (경로, ttc 인덱스). 앞에서부터 처음 존재하는 폰트를 쓴다.
BOLD_FONTS = [
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 1),
    ("/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf", 0),
    ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0),
]
REGULAR_FONTS = [
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 1),
    ("/usr/share/fonts/truetype/nanum/NanumGothic.ttf", 0),
    ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0),
]


def _find_font(candidates, override):
    if override and os.path.exists(override):
        return override, 0
    for path, index in candidates:
        if os.path.exists(path):
            return path, index
    raise FileNotFoundError("한글 폰트를 찾을 수 없습니다. fonts-noto-cjk를 설치하거나 CARD_FONT_PATH를 지정하세요.")


class Fonts:
    def __init__(self, override=""):
        self.bold = _find_font(BOLD_FONTS, override)
        self.regular = _find_font(REGULAR_FONTS, os.environ.get("CARD_FONT_REGULAR_PATH", override))

    def get(self, size, bold=False):
        path, index = self.bold if bold else self.regular
        return ImageFont.truetype(path, size, index=index)


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
    return lines


def _draw_lines(draw, lines, xy, font, fill, spacing):
    x, y = xy
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += font.size + spacing
    return y


def _footer(draw, fonts, handle, page):
    f = fonts.get(30)
    draw.text((PAD, H - PAD - 30), handle, font=f, fill=MUTED)
    draw.text((W - PAD, H - PAD - 30), page, font=f, fill=MUTED, anchor="ra")


def render_cover(data, now, fonts, handle, total, label="정치 브리핑"):
    img = Image.new("RGB", (W, H), BG_COVER)
    d = ImageDraw.Draw(img)
    label = f"{now:%m.%d} ({WEEKDAYS[now.weekday()]}) {now:%H}시 {label}"
    d.rectangle((PAD, PAD, PAD + 12, PAD + 52), fill=ACCENT)
    d.text((PAD + 32, PAD + 4), label, font=fonts.get(38, bold=True), fill=ACCENT)

    title_font = fonts.get(88, bold=True)
    y = _draw_lines(d, wrap(d, data["headline"], title_font, W - 2 * PAD), (PAD, 260), title_font, FG, 24)

    y += 50
    d.line((PAD, y, W - PAD, y), fill=DIVIDER, width=3)
    y += 50
    item_font = fonts.get(40)
    for i, card in enumerate(data["cards"], 1):
        lines = wrap(d, card["title"], item_font, W - 2 * PAD - 70)
        if y + len(lines) * 56 > H - PAD - 90:
            break
        d.text((PAD, y), f"{i:02d}", font=fonts.get(40, bold=True), fill=ACCENT)
        y = _draw_lines(d, lines, (PAD + 70, y), item_font, FG, 16) + 20

    _footer(d, fonts, handle, f"1/{total}")
    return img


def render_card(card, index, total, sources, fonts, handle):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    tag_font = fonts.get(34, bold=True)
    tag_w = d.textlength(card["tag"], font=tag_font)
    d.rounded_rectangle((PAD, PAD, PAD + tag_w + 48, PAD + 64), radius=32, fill=ACCENT)
    d.text((PAD + 24, PAD + 32), card["tag"], font=tag_font, fill=BG, anchor="lm")
    d.text((W - PAD, PAD + 32), f"{index - 1:02d}", font=fonts.get(64, bold=True), fill=DIVIDER, anchor="rm")

    title_font = fonts.get(72, bold=True)
    y = _draw_lines(d, wrap(d, card["title"], title_font, W - 2 * PAD), (PAD, 230), title_font, FG, 20)
    y += 40
    d.rectangle((PAD, y, PAD + 80, y + 8), fill=ACCENT)
    y += 70

    body_font = fonts.get(44)
    y = _draw_lines(d, wrap(d, card["body"], body_font, W - 2 * PAD), (PAD, y), body_font, FG, 26)

    if sources:
        src_font = fonts.get(28)
        src_text = "출처: " + ", ".join(sources)
        src_lines = wrap(d, src_text, src_font, W - 2 * PAD)[:2]
        _draw_lines(d, src_lines, (PAD, H - PAD - 60 - len(src_lines) * 40), src_font, MUTED, 12)

    _footer(d, fonts, handle, f"{index}/{total}")
    return img


def render_all(data, articles, now: datetime, out_dir, handle, font_override="", label="정치 브리핑"):
    fonts = Fonts(font_override)
    os.makedirs(out_dir, exist_ok=True)
    total = len(data["cards"]) + 1
    paths = []
    images = [render_cover(data, now, fonts, handle, total, label)]
    for i, card in enumerate(data["cards"], 2):
        sources = sorted({articles[j - 1].source for j in card["source_ids"]})
        images.append(render_card(card, i, total, sources, fonts, handle))
    for i, img in enumerate(images, 1):
        path = os.path.join(out_dir, f"card_{i:02d}.jpg")
        img.save(path, "JPEG", quality=90)
        paths.append(path)
    return paths
