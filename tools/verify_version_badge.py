#!/usr/bin/env python3
# =============================================================================
# verify_version_badge.py - offline geometry check of the bottom-right
# firmware-version badge added in v10.0.
# -----------------------------------------------------------------------------
# v10.0 draws FW_VERSION_STRING in the bottom-right corner of the clock screen,
# in the SAME font as the battery line (Dialog_plain_16) and on the same
# baseline.  Everything about that placement is arithmetic, so it is checked
# here against the REAL font metrics instead of by eyeballing the panel:
#
#   epd.c -> epd_display() draws, in this order:
#     1  "ESL_%02X%02X%02X %s"   Dialog_plain_16           (   1,  17)
#     2  BLE_conn_string[...]    Dialog_plain_16           ( 232,  20)
#     3  "%02d:%02d"             DSEG14_Classic_...40      (  50,  65)
#     4  "%d'C"                  Special_Elite_Regular_30  (  10,  95)
#     5  "Battery %dmV"          Dialog_plain_16           (  10, 120)
#     6  FW_VERSION_STRING       Dialog_plain_16           (EPD_VERSION_X, 120)
#
# `y` is a BASELINE, not a top edge: obdWriteStringCustom() places each glyph at
# (pen + xOffset, y + yOffset) and advances the pen by xAdvance, so the ink box
# of a string is derived from the glyph table in font16.h / font30.h.
#
# What is asserted:
#   A. EPD_VERSION_X in epd.c == 250 - MARGIN - width(FW_VERSION_STRING).
#      This is the anti-drift check: lengthening the version string (or the
#      value itself) without touching EPD_VERSION_X fails the script.
#   B. the badge's ink stays inside the 250x122 visible glass (x <= 249,
#      y <= 121) and inside the 250x128 storage buffer.
#   C. it does NOT overlap the battery line, which shares its baseline and is
#      the only other element on that row.
#   D. it does NOT overlap the temperature line in y (different baseline).
#   E. it falls OUTSIDE the v7.0 per-minute gate window, i.e. the badge adds
#      exactly zero cost to the minute refresh.  Being a compile-time constant
#      it only ever needs the full refresh, which is when it is redrawn anyway.
#
# Exit code 0 = all good, 1 = something drifted.
# =============================================================================
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, '..', 'atc1441_src', 'Firmware', 'src')

# --- panel / layout constants (epd.h, epd.c) --------------------------------
VDISP_W, VDISP_H = 250, 128        # virtual display that OneBitDisplay draws into
VISIBLE_H = 122                    # real glass height; y 0..121
RIGHT_MARGIN = 2                   # px kept free at the right edge

BATTERY_X, BATTERY_Y = 10, 120     # epd.c: battery line
TEMP_X, TEMP_Y = 10, 95            # epd.c: temperature line
GLASS_X_TO_RAM_Y = 47              # RAM_Y = glass_x + 47 (see verify_gate_window.py)

# v7.0 per-minute driven gate range, mirrored from epd_bwr_213.c
WIN_GATE_FIRST, WIN_GATE_LAST = 101, 237


def load_glyphs(header, font):
    """Parse a GFXglyph table out of one of the font headers.  The trailing
    comments carry the character, so they have to be consumed with the numbers."""
    path = os.path.join(SRC, header)
    text = open(path, encoding='utf-8', errors='ignore').read()
    # some headers write "Glyphs[] = {", others "Glyphs[] PROGMEM = {"
    m = re.search(r'const GFXglyph %sGlyphs\[\][^=]*=\s*\{(.*?)\n\};' % font, text, re.S)
    if not m:
        sys.exit('could not find glyph table for %s in %s' % (font, header))
    glyphs, first = {}, None
    for nums, ch in re.findall(r'\{\s*([-\d,\s]+?)\s*\}\s*,\s*//\s*\'(.)\'', m.group(1)):
        off, w, h, xadv, xoff, yoff = [int(v) for v in nums.split(',')]
        glyphs[ch] = dict(w=w, h=h, xadv=xadv, xoff=xoff, yoff=yoff)
    # the GFXfont struct at the bottom of the header names the first codepoint
    f = re.search(r'const GFXfont %s PROGMEM = \{[^}]*\}\s*,?\s*0x([0-9A-Fa-f]+)\s*,'
                  % font, text)
    if f:
        first = int(f.group(1), 16)
    else:  # fall back to the commented ' ' entry, which is codepoint 0x20
        first = 0x20
    # the regex above only captured commented rows; fill the rest by position
    rows = re.findall(r'\{\s*([-\d]+),\s*([-\d]+),\s*([-\d]+),\s*([-\d]+),'
                      r'\s*([-\d]+),\s*([-\d]+)\s*\}', m.group(1))
    if len(rows) != len(glyphs):
        glyphs = {}
        for i, r in enumerate(rows):
            off, w, h, xadv, xoff, yoff = [int(v) for v in r]
            glyphs[chr(first + i)] = dict(w=w, h=h, xadv=xadv, xoff=xoff, yoff=yoff)
    return glyphs


def text_width(text, glyphs):
    """Mirror of obdGetStringBox(): sum of xAdvance.  Characters outside the
    font are skipped by the real function too."""
    return sum(glyphs[c]['xadv'] for c in text if c in glyphs)


def ink_box(text, x, y, glyphs):
    """Mirror of obdWriteStringCustom() layout: glyph at (x + xoff, y + yoff),
    y is the baseline.  Returns (x0, y0, x1, y1) inclusive, or None if empty."""
    px = x
    xs, ys = [], []
    for ch in text:
        g = glyphs[ch]
        dx, dy = px + g['xoff'], y + g['yoff']
        if g['w'] and g['h']:
            xs += [dx, dx + g['w'] - 1]
            ys += [dy, dy + g['h'] - 1]
        px += g['xadv']
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def grep_source(pattern, path, default=None):
    text = open(os.path.join(SRC, path), encoding='utf-8', errors='ignore').read()
    m = re.search(pattern, text)
    return m.group(1) if m else default


def main():
    g16 = load_glyphs('font16.h', 'Dialog_plain_16')
    g30 = load_glyphs('font30.h', 'Special_Elite_Regular_30')
    print('fonts: Dialog_plain_16 %d glyphs, Special_Elite_Regular_30 %d glyphs'
          % (len(g16), len(g30)))

    ver = grep_source(r'#define\s+FW_VERSION_STRING\s+"([^"]*)"', 'app_config.h')
    vx = grep_source(r'#define\s+EPD_VERSION_X\s+(\d+)', 'epd.c')
    vy = grep_source(r'#define\s+EPD_VERSION_Y\s+(\d+)', 'epd.c')
    if ver is None or vx is None or vy is None:
        sys.exit('FAIL: could not read FW_VERSION_STRING / EPD_VERSION_X / '
                 'EPD_VERSION_Y from the sources')
    vx, vy = int(vx), int(vy)
    print('version string "%s"  -> EPD_VERSION_X=%d  EPD_VERSION_Y=%d' % (ver, vx, vy))

    ok = True

    # --- A. the badge is right-aligned for THIS string ------------------------
    w_ver = text_width(ver, g16)
    want_x = VDISP_W - RIGHT_MARGIN - w_ver
    print('\n[A] width("%s") = %d px  ->  right-aligned x = %d'
          % (ver, w_ver, want_x))
    ok &= _check('EPD_VERSION_X matches the font metrics', vx == want_x,
                 '%d vs %d' % (vx, want_x))
    ok &= _check('version string fits the 6-char budget of the badge',
                  len(ver) <= 6, '%d chars' % len(ver))

    box = ink_box(ver, vx, vy, g16)
    x0, y0, x1, y1 = box
    print('    badge ink: x [%d,%d]  y [%d,%d]' % (x0, x1, y0, y1))

    # --- B. inside the glass and inside the storage buffer -------------------
    ok &= _check('badge ink inside the visible glass (x 0..%d)' % (VDISP_W - 1),
                 0 <= x0 and x1 <= VDISP_W - 1, 'x [%d,%d]' % (x0, x1))
    ok &= _check('badge ink inside the visible glass (y 0..%d)' % (VISIBLE_H - 1),
                 0 <= y0 and y1 <= VISIBLE_H - 1, 'y [%d,%d]' % (y0, y1))
    ok &= _check('badge ink inside the %dx%d storage buffer' % (VDISP_W, VDISP_H),
                 0 <= y0 and y1 <= VDISP_H - 1, 'y [%d,%d]' % (y0, y1))

    # --- C. no clash with the battery line -----------------------------------
    # battery_mv is a uint16_t -> "Battery 65535mV" is the widest possible text
    bat = 'Battery 65535mV'
    bw = text_width(bat, g16)
    bx1 = BATTERY_X + bw - 1
    bbox = ink_box(bat, BATTERY_X, BATTERY_Y, g16)
    print('\n[C] widest battery line "%s": advance width %d -> x ends at %d'
          % (bat, bw, bx1))
    print('    battery ink: x [%d,%d]  y [%d,%d]'
          % (bbox[0], bbox[2], bbox[1], bbox[3]))
    ok &= _check('battery line and version badge do not overlap in x',
                 bbox[2] < x0, 'battery x1=%d < badge x0=%d' % (bbox[2], x0))
    print('    gap between them: %d px' % (x0 - bbox[2] - 1))
    if bbox[3] > VISIBLE_H - 1:
        print('    note: the battery line\'s "y" descender already reached y=%d, i.e.'
              % bbox[3])
        print('          %d px below the glass - pre-existing, not touched here '
              '(the badge has no descender)' % (bbox[3] - (VISIBLE_H - 1)))

    # --- D. no clash with the temperature line -------------------------------
    tbox = ink_box("-128'C", TEMP_X, TEMP_Y, g30)
    print('\n[D] temperature ink: x [%d,%d]  y [%d,%d]'
          % (tbox[0], tbox[2], tbox[1], tbox[3]))
    ok &= _check('temperature line and badge do not overlap in y',
                 tbox[3] < y0 or y1 < tbox[1], 'temp y [%d,%d] vs badge y [%d,%d]'
                 % (tbox[1], tbox[3], y0, y1))

    # --- E. does the badge cost anything in the per-minute refresh? ----------
    ram_y0, ram_y1 = x0 + GLASS_X_TO_RAM_Y, x1 + GLASS_X_TO_RAM_Y
    print('\n[E] badge ink at glass x [%d,%d] -> driven gates [%d,%d]'
          % (x0, x1, ram_y0, ram_y1))
    print('    v7.0 per-minute window  : gates %d..%d'
          % (WIN_GATE_FIRST, WIN_GATE_LAST))
    outside = ram_y0 > WIN_GATE_LAST or ram_y1 < WIN_GATE_FIRST
    partial = not outside and not (WIN_GATE_FIRST <= ram_y0 and ram_y1 <= WIN_GATE_LAST)
    ok &= _check('badge is outside the minute window (zero added cost)', outside,
                 'gates [%d,%d] vs window %d..%d' % (ram_y0, ram_y1,
                                                     WIN_GATE_FIRST, WIN_GATE_LAST))
    if partial:
        print('    WARNING: the badge straddles the window edge - harmless for a '
              'constant, but check that it is intentional')

    print('')
    print('RESULT: ' + ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


def _check(name, cond, detail=''):
    print('  %-58s %s %s' % (name, 'PASS' if cond else 'FAIL', detail))
    return bool(cond)


if __name__ == '__main__':
    sys.exit(main())
