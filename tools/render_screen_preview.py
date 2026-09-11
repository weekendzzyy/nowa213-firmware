#!/usr/bin/env python3
# =============================================================================
# render_screen_preview.py - offline renderer for the clock screen
# -----------------------------------------------------------------------------
# Reproduces epd.c -> epd_display() pixel for pixel on a 250x122 canvas, so any
# layout change can be SEEN before flashing the tag.  It parses the real font
# headers (bitmaps + glyph tables) and mirrors OneBitDisplay's layout rules:
#
#   obdWriteStringCustom(pOBD, pFont, x, y, msg, color)
#     - y is a BASELINE, not a top edge
#     - each glyph is stamped at (pen + xOffset, y + yOffset)
#     - pen += xAdvance
#     - the bitmap is a CONTINUOUS MSB-first bit stream; rows are NOT re-aligned
#       to byte boundaries (obd.inl carries iBitOff across the row loop)
#
# Elements drawn, in the order epd_display() draws them:
#   1  "ESL_xxxxxx MODEL"      Dialog_plain_16             (   1,  17)
#   2  BLE rune (v11.0)        BLE_ICON_BITS[13] in epd.c  ( 233,   8)
#   3  "HH:MM"                 DSEG14_Classic_Mini_...40   (  50,  65)
#   4  "NN'C"                  Special_Elite_Regular_30    (  10,  95)
#   5  "Battery NNNNmV"        Dialog_plain_16             (  10, 120)
#   6  FW_VERSION_STRING       Dialog_plain_16             (EPD_VERSION_X, 120)
#
# Usage:
#   python tools/render_screen_preview.py                  # v10.0 default
#   python tools/render_screen_preview.py --no-badge       # what v9.0 looked like
#   python tools/render_screen_preview.py --zoom 4
# =============================================================================
import argparse
import os
import re
import sys

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..'))
SRC = os.path.join(ROOT, 'atc1441_src', 'Firmware', 'src')
OUTDIR = os.path.join(ROOT, 'previews')

VDISP_W, VDISP_H = 250, 128
GLASS_H = 122

PAPER = (246, 245, 240)      # e-paper white
INK = (24, 24, 26)           # e-paper black


# ---------------------------------------------------------------------------
# font parsing
# ---------------------------------------------------------------------------
def _strip_comments(body):
    return re.sub(r'//[^\n]*', '', body)


def load_font(header, font):
    """Return (bitmap_bytes, glyphs).  Glyph keys are the printable characters
    taken from the trailing comments of the glyph table."""
    path = os.path.join(SRC, header)
    text = open(path, encoding='utf-8', errors='ignore').read()

    m = re.search(r'const uint8_t %sBitmaps\[\][^=]*=\s*\{(.*?)\n\};' % font, text, re.S)
    if not m:
        sys.exit('no bitmap table for %s in %s' % (font, header))
    data = bytes(int(v, 0) for v in re.findall(r'0x[0-9a-fA-F]+', _strip_comments(m.group(1))))

    m = re.search(r'const GFXglyph %sGlyphs\[\][^=]*=\s*\{(.*?)\n\};' % font, text, re.S)
    if not m:
        sys.exit('no glyph table for %s in %s' % (font, header))
    body = m.group(1)
    glyphs = {}
    rows = re.findall(r'\{\s*([-\d]+)\s*,\s*([-\d]+)\s*,\s*([-\d]+)\s*,\s*([-\d]+)\s*,'
                      r'\s*([-\d]+)\s*,\s*([-\d]+)\s*\}', body)
    ff = re.search(r'const GFXfont %s [^=]*= \{[^}]*\}\s*,?\s*0x([0-9a-fA-F]+)\s*,' % font, text)
    first = int(ff.group(1), 16) if ff else 0x20
    for i, r in enumerate(rows):
        off, w, h, adv, xo, yo = [int(v) for v in r]
        glyphs[chr(first + i)] = dict(off=off, w=w, h=h, adv=adv, xo=xo, yo=yo)
    return data, glyphs


# ---------------------------------------------------------------------------
# drawing
# ---------------------------------------------------------------------------
def draw_string(px, data, glyphs, x, y, text):
    """Mirror of obdWriteStringCustom().  px is a bytearray of VDISP_W*VDISP_H,
    row major, 1 = ink."""
    pen = x
    for ch in text:
        g = glyphs.get(ch)
        if g is None:
            continue
        nbits = g['w'] * g['h']
        for k in range(nbits):
            byte = data[g['off'] + (k >> 3)]
            if not (byte >> (7 - (k & 7))) & 1:
                continue
            cx = pen + g['xo'] + (k % g['w'])
            cy = y + g['yo'] + (k // g['w'])
            if 0 <= cx < VDISP_W and 0 <= cy < VDISP_H:
                px[cy * VDISP_W + cx] = 1
        pen += g['adv']
    return pen


def load_ble_icon():
    """v11.0: parse the Bluetooth rune straight out of epd.c, so the preview can
    never drift from what the firmware actually draws.  Returns (x, y, w, h, rows)."""
    text = open(os.path.join(SRC, 'epd.c'), encoding='utf-8', errors='ignore').read()

    def num(name, default):
        m = re.search(r'#define\s+%s\s+(\d+)' % name, text)
        return int(m.group(1)) if m else default

    m = re.search(r'BLE_ICON_BITS\s*\[[^\]]*\]\s*=\s*\{(.*?)\};', text, re.S)
    if not m:
        sys.exit('no BLE_ICON_BITS[] table in epd.c')
    rows = [int(v, 0) for v in re.findall(r'0x[0-9a-fA-F]+', m.group(1))]
    return (num('BLE_ICON_X', 233), num('BLE_ICON_Y', 8),
            num('BLE_ICON_W', 7), num('BLE_ICON_H', 13), rows)


def draw_ble_icon(px, x, y, w, h, rows):
    """Mirror of epd_draw_ble_icon(): bit n of a row -> pixel (x + n, y + row)."""
    for r in range(h):
        for c in range(w):
            if rows[r] & (1 << c):
                cx, cy = x + c, y + r
                if 0 <= cx < VDISP_W and 0 <= cy < VDISP_H:
                    px[cy * VDISP_W + cx] = 1


def read_define(path, name, default=None):
    text = open(os.path.join(SRC, path), encoding='utf-8', errors='ignore').read()
    m = re.search(r'#define\s+%s\s+"?([^"\n]+)"?' % name, text)
    return m.group(1).strip() if m else default


def render(with_badge=True, with_ble=True):
    g16 = load_font('font16.h', 'Dialog_plain_16')
    g30 = load_font('font30.h', 'Special_Elite_Regular_30')
    g60 = load_font('font_60.h', 'DSEG14_Classic_Mini_Regular_40')

    ver = read_define('app_config.h', 'FW_VERSION_STRING', 'v0.0')
    vx = int(read_define('epd.c', 'EPD_VERSION_X', '199'))
    vy = int(read_define('epd.c', 'EPD_VERSION_Y', '120'))
    # v11.0 BLE indicator: the bare letter "B" was replaced by a drawn rune.
    # Both its geometry and its bitmap are parsed out of epd.c, so editing the
    # icon there is reflected here with no second place to keep in sync.
    bx, by, bw, bh, brows = load_ble_icon()
    use_icon = read_define('epd.c', 'EPD_USE_BLE_ICON', '1') == '1'

    px = bytearray(VDISP_W * VDISP_H)

    draw_string(px, *g16, 1, 17, 'ESL_140EC6 BWR213')      # 1 model line
    if with_ble:
        if use_icon:
            draw_ble_icon(px, bx, by, bw, bh, brows)       # 2a BLE rune (v11.0)
        else:
            draw_string(px, *g16, 232, 20, 'B')            # 2b legacy letter
    draw_string(px, *g60, 50, 65, '14:23')                 # 3 clock
    draw_string(px, *g30, 10, 95, "25'C")                  # 4 temperature
    draw_string(px, *g16, 10, 120, 'Battery 3600mV')       # 5 battery
    if with_badge:
        draw_string(px, *g16, vx, vy, ver)                 # 6 version badge
    return px, (vx, vy, ver), (bx, by, bw, bh, use_icon)


def to_image(px, zoom, glass_only=False):
    h = GLASS_H if glass_only else VDISP_H
    img = Image.new('RGB', (VDISP_W, h), PAPER)
    d = ImageDraw.Draw(img)
    for y in range(h):
        for x in range(VDISP_W):
            if px[y * VDISP_W + x]:
                d.point((x, y), fill=INK)
    return img.resize((VDISP_W * zoom, h * zoom), Image.NEAREST)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--no-badge', action='store_true', help='render without the version badge')
    ap.add_argument('--no-ble', action='store_true',
                    help='render the disconnected state (no "B" indicator)')
    ap.add_argument('--zoom', type=int, default=3)
    args = ap.parse_args()

    px, (vx, vy, ver), (bx, by, bw, bh, use_icon) = render(
        with_badge=not args.no_badge, with_ble=not args.no_ble)
    os.makedirs(OUTDIR, exist_ok=True)

    tag = 'v10' if args.no_badge else 'v11'
    main_png = os.path.join(OUTDIR, 'screen_%s_zoom%d.png' % (tag, args.zoom))
    to_image(px, args.zoom).save(main_png)
    print('wrote %s  (%dx%d)' % (main_png, VDISP_W * args.zoom, GLASS_H * args.zoom))

    # right-bottom close-up, so the badge and its spacing can be judged
    if not args.no_badge:
        z = 6
        x0, y0 = 150, 98     # keep the tail of "mV" visible as a reference
        box = Image.new('RGB', (VDISP_W - x0, VDISP_H - y0), PAPER)
        bd = ImageDraw.Draw(box)
        for y in range(y0, VDISP_H):
            for x in range(x0, VDISP_W):
                if px[y * VDISP_W + x]:
                    bd.point((x - x0, y - y0), fill=INK)
        box = box.resize(((VDISP_W - x0) * z, (VDISP_H - y0) * z), Image.NEAREST)
        # outline the badge, 4 px outside the box the string occupies
        bd2 = ImageDraw.Draw(box)
        bx0 = max(0, (vx - x0) * z - 4)
        by0 = max(0, (vy - 20 - y0) * z - 4)
        bx1 = min(box.width - 1, (vx + 52 - x0) * z + 4)
        by1 = min(box.height - 1, (vy + 2 - y0) * z + 4)
        bd2.rectangle([bx0, by0, bx1, by1], outline=(200, 30, 40), width=3)
        zoom_png = os.path.join(OUTDIR, 'badge_zoom%d.png' % z)
        box.save(zoom_png)
        print('wrote %s  (%dx%d, red box = badge ink area)'
              % (zoom_png, box.width, box.height))

    # top-right close-up, so the BLE indicator (and the tail of the model line)
    # can be told apart at a glance
    z = 8
    x0, y0 = 200, 0
    x1, y1 = VDISP_W, 34
    box = Image.new('RGB', (x1 - x0, y1 - y0), PAPER)
    bd = ImageDraw.Draw(box)
    for y in range(y0, y1):
        for x in range(x0, x1):
            if px[y * VDISP_W + x]:
                bd.point((x - x0, y - y0), fill=INK)
    box = box.resize(((x1 - x0) * z, (y1 - y0) * z), Image.NEAREST)
    if not args.no_ble:
        bd2 = ImageDraw.Draw(box)
        # v11.0 draws a real bitmap, so the box is exact.  The legacy letter is
        # still boxed with the old approximation (12 px advance, cap height 12).
        if use_icon:
            bx0, by0, bw0, bh0 = bx, by, bw, bh
        else:
            bx0, by0, bw0, bh0 = bx, by - 12, 12, 14
        bd2.rectangle([(bx0 - x0) * z - 4, (by0 - y0) * z - 4,
                       (bx0 + bw0 - x0) * z + 4, (by0 + bh0 - y0) * z + 4],
                      outline=(200, 30, 40), width=3)
    ble_png = os.path.join(OUTDIR, 'ble_ind_zoom%d.png' % z)
    box.save(ble_png)
    print('wrote %s  (%dx%d, red box = the BLE indicator)'
          % (ble_png, box.width, box.height))

    print('badge at x=%d y=%d  text="%s"' % (vx, vy, ver))
    if args.no_ble:
        print('ble indicator: not drawn (disconnected state)')
    elif use_icon:
        print('ble rune at x=%d y=%d  %dx%d bitmap'
              % (bx, by, bw, bh))
    else:
        print('ble indicator at x=%d y=%d  legacy letter "B"' % (bx, by))
    return 0


if __name__ == '__main__':
    sys.exit(main())
