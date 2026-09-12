#!/usr/bin/env python3
# =============================================================================
# verify_partial_window.py - offline check of the v6.0 EPD partial window
# -----------------------------------------------------------------------------
# v6.0 makes the per-minute refresh a REAL partial refresh: epd_bw_213.c programs
# the IL0373 partial window (0x90 PTL) so the controller only scans/drives the
# rectangle that holds the clock digits.  If that rectangle is wrong the digits
# simply stop updating, so it must be provably big enough.
#
# This script recomputes, from the REAL font metrics, the exact ink rectangle the
# clock text can ever occupy, then converts the firmware's window constants into
# the bytes actually written to the controller and asserts containment.
#
# It reproduces two pieces of firmware logic exactly:
#   1. epd_display() in epd.c draws the clock with
#         obdWriteStringCustom(&obd, DSEG14_Classic_Mini_Regular_40, 50, 65, "HH:MM", 1)
#      and obdWriteStringCustom() (obd.inl) places each glyph at
#         dx = x + glyph.xOffset, dy = y + glyph.yOffset   (y = BASELINE)
#      with the glyph covering dx..dx+width-1, dy..dy+height-1, then x += xAdvance.
#      The OBD virtual screen maps 1:1 onto the glass (glass_x = obd x, glass_y = obd y).
#   2. epd_bw_213.c converts a glass rectangle into IL0373 PTL bytes:
#         HRST = (glass_y0) & 0xF8      (source axis, 8-pixel banks)
#         HRED = (glass_y1) & 0xF8
#         VRST = 249 - glass_x1         (gate axis; data group k lands at col 249-k)
#         VRED = 249 - glass_x0
#         PT_SCAN = 0                   (scan gates ONLY inside the window)
#
# Exit code 0 = window provably covers the clock; 1 = it does not.
# =============================================================================
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, '..', 'atc1441_src', 'Firmware', 'src')

# --- window constants, mirrored from epd_bw_213.c ---------------------------
WIN_SRC_START = 24    # glass row (source axis)
WIN_SRC_END = 71      # glass row
WIN_GLASS_X0 = 50     # glass column (gate axis)
WIN_GLASS_X1 = 194
CLOCK_X = 50          # epd.c: obdWriteStringCustom(..., 50, 65, ...)
CLOCK_Y = 65          # baseline
FONT_NAME = 'DSEG14_Classic_Mini_Regular_40'


def load_glyphs():
    """Parse the GFXglyph table out of font_60.h.  Comments carry the character,
    so strip them first (they contain digits that would corrupt the parse)."""
    text = open(os.path.join(SRC, 'font_60.h'), encoding='utf-8', errors='ignore').read()
    m = re.search(r'const GFXglyph %sGlyphs\[\]\s*=\s*\{(.*?)\n\};' % FONT_NAME,
                  text, re.S)
    if not m:
        sys.exit('could not find glyph table for ' + FONT_NAME)
    glyphs = {}
    for nums, ch in re.findall(r'\{\s*([-\d,\s]+?)\s*\}\s*,\s*//\s*\'(.)\'', m.group(1)):
        off, w, h, xadv, xoff, yoff = [int(v) for v in nums.split(',')]
        glyphs[ch] = dict(off=off, w=w, h=h, xadv=xadv, xoff=xoff, yoff=yoff)
    return glyphs


def ink_bbox_for(text, glyphs):
    """Reproduce obdWriteStringCustom()'s placement for one string."""
    x = CLOCK_X
    x0 = y0 = 1 << 30
    x1 = y1 = -(1 << 30)
    for ch in text:
        g = glyphs.get(ch)
        if g is None:
            continue
        dx = x + g['xoff']
        dy = CLOCK_Y + g['yoff']
        x0 = min(x0, dx)
        x1 = max(x1, dx + g['w'] - 1)
        y0 = min(y0, dy)
        y1 = max(y1, dy + g['h'] - 1)
        x += g['xadv']
    return x0, y0, x1, y1


def main():
    glyphs = load_glyphs()
    print('font       : %s (%d glyphs parsed)' % (FONT_NAME, len(glyphs)))

    # every time the tag can ever render
    worst = None
    for hh in range(24):
        for mm in range(60):
            bb = ink_bbox_for('%02d:%02d' % (hh, mm), glyphs)
            if worst is None:
                worst = list(bb)
            else:
                worst = [min(worst[0], bb[0]), min(worst[1], bb[1]),
                         max(worst[2], bb[2]), max(worst[3], bb[3])]
    x0, y0, x1, y1 = worst
    print('clock ink  : glass x in [%d,%d], y in [%d,%d]  (worst case over 1440 times)'
          % (x0, x1, y0, y1))

    # --- what the firmware programs -----------------------------------------
    hrst = WIN_SRC_START & 0xF8
    hred = WIN_SRC_END & 0xF8
    vrst = 249 - WIN_GLASS_X1
    vred = 249 - WIN_GLASS_X0
    print('window     : glass x in [%d,%d], y in [%d,%d]'
          % (WIN_GLASS_X0, WIN_GLASS_X1, WIN_SRC_START, WIN_SRC_END))
    print('PTL bytes  : 0x%02X 0x%02X 0x%02X 0x%02X 0x%02X 0x%02X 0x%02X'
          % (hrst, hred, (vrst >> 8) & 1, vrst & 0xFF, (vred >> 8) & 1, vred & 0xFF, 0))

    ok = True

    def check(name, cond, detail):
        nonlocal ok
        print('  [%s] %s%s' % ('OK' if cond else 'FAIL', name, detail))
        if not cond:
            ok = False

    # source (glass rows) window, in banks of 8 pixels
    bank_start, bank_end = hrst >> 3, hred >> 3
    check('HRST is bank-aligned', hrst % 8 == 0, '  (0x%02X -> bank %d)' % (hrst, bank_start))
    check('HRED is bank-aligned', hred % 8 == 0, '  (0x%02X -> bank %d)' % (hred, bank_end))
    check('HRED bank > HRST bank', bank_end > bank_start, '  (%d > %d)' % (bank_end, bank_start))
    check('glass rows covered',
          bank_start * 8 <= y0 and y1 <= bank_end * 8 + 7,
          '  ink [%d,%d] inside [%d,%d]' % (y0, y1, bank_start * 8, bank_end * 8 + 7))
    check('source banks <= 19 (IL0373 limit)', bank_end <= 0x13, '  (bank %d)' % bank_end)

    # gate (glass columns) window
    check('VRED > VRST', vred > vrst, '  (%d > %d)' % (vred, vrst))
    check('VRED <= 295 (IL0373 limit)', vred <= 295, '  (%d)' % vred)
    # gate k is shown at glass column 249-k, so the window must cover 249-x1..249-x0
    need_v0, need_v1 = 249 - x1, 249 - x0
    check('glass columns covered',
          vrst <= need_v0 and need_v1 <= vred,
          '  ink needs gates [%d,%d], window is [%d,%d]' % (need_v0, need_v1, vrst, vred))

    # how much smaller than the full panel the driven area now is
    full_src = 128 // 8 * 8
    src_now = (bank_end - bank_start + 1) * 8
    gate_now = vred - vrst + 1
    print('\ndriven area: %d/%d source rows, %d/%d gate lines'
          % (src_now, full_src, gate_now, 296))
    print('gate-line reduction: %.1f%% (energy scales with scanned gate lines)'
          % (100.0 * (1 - gate_now / 296.0)))
    frac_src = src_now / float(full_src)
    print('source x gate product reduction: %.1f%%   (%.2f x less drive per frame)'
          % (100.0 * (1 - frac_src * gate_now / 296.0), 1.0 / (frac_src * gate_now / 296.0)))

    print('\nRESULT:', 'PASS - window provably contains the clock' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
