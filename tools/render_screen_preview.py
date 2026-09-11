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
#   2  BLE_conn_string[...]    Dialog_plain_16             ( 232,  20)
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
    # BLE indicator: epd.c:368 passes these literals straight to
    # obdWriteStringCustom() as (232, 20); they are not named constants there, so
    # fall back to the literals.  Promote them to #defines in epd.c and this will
    # pick the new values up automatically.
    bx = int(read_define('epd.c', 'EPD_BLE_IND_X', '232'))
    by = int(read_define('epd.c', 'EPD_BLE_IND_Y', '20'))

    px = bytearray(VDISP_W * VDISP_H)

    draw_string(px, *g16, 1, 17, 'ESL_140EC6 BWR213')      # 1 model line
    if with_ble:
        draw_string(px, *g16, bx, by, 'B')                 # 2 BLE indicator
    draw_string(px, *g60, 50, 65, '14:23')                 # 3 clock
    draw_string(px, *g30, 10, 95, "25'C")                  # 4 temperature
    draw_string(px, *g16, 10, 120, 'Battery 3600mV')       # 5 battery
    if with_badge:
        draw_string(px, *g16, vx, vy, ver)                 # 6 version badge
    return px, (vx, vy, ver), (bx, by)


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

    px, (vx, vy, ver), (bx, by) = render(with_badge=not args.no_badge,
                                         with_ble=not args.no_ble)
    os.makedirs(OUTDIR, exist_ok=True)

    tag = 'v9' if args.no_badge else 'v10'
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
        # same approximation verify_version_badge.py uses: 12 px advance, cap
        # height 12 sitting on the baseline
        bd2.rectangle([(bx - x0) * z - 4, (by - 12 - y0) * z - 4,
                       (bx + 12 - x0) * z + 4, (by + 2 - y0) * z + 4],
                      outline=(200, 30, 40), width=3)
    ble_png = os.path.join(OUTDIR, 'ble_ind_zoom%d.png' % z)
    box.save(ble_png)
    print('wrote %s  (%dx%d, red box = the "B" BLE indicator)'
          % (ble_png, box.width, box.height))

    print('badge at x=%d y=%d  text="%s"' % (vx, vy, ver))
    print('ble indicator at x=%d y=%d  text="%s"'
          % (bx, by, '' if args.no_ble else 'B'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
