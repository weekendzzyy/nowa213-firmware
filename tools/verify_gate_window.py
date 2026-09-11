#!/usr/bin/env python3
# =============================================================================
# verify_gate_window.py - offline check of the v7.0 SSD1680 gate-scan window
# -----------------------------------------------------------------------------
# v7.0 makes the per-minute refresh a REAL partial refresh on the driver that
# this tag actually runs: epd_bwr_213.c.  The panel controller is an SSD1680
# (the file's own header says "SSD1675 mixed with SSD1680"), which has NO
# partial-window command like the IL0373's 0x90 PTL.  Instead the driven gate
# range is selected by two registers, per the SSD1680 datasheet Rev 0.14:
#
#   0x01 Driver Output Control (p.34)
#        byte1 = MUX[7:0], byte2 = MUX[8], byte3 = GD,SM,TB
#        "MUX[8:0]: Specify number of lines for the driver: MUX[8:0] + 1.
#         Multiplex ratio (MUX ratio) from 16 MUX to 296 MUX."
#
#   0x0F Gate Scan Start Position (p.36)
#        byte1 = SCN[7:0], byte2 = SCN[8]
#        "determining the starting gate of display RAM by selecting a value from
#         0 to 295 ... Figure 8-2: with MUX ratio = 093h and Gate Start Position
#         = 04Ah the gates G0..G73 are '-' (NOT driven) and G74.. are driven,
#         G74 = ROW74, G75 = ROW75 ..."
#
# So with MUX[8:0] = N-1 and SCN = F the controller drives exactly the contiguous
# range G_F .. G_(F+N-1), and driven gate G_n reads RAM row n (identity mapping,
# which is what the driver's GD=0 / SM=0 setting selects -- see the GD/SM table
# on p.34).  Gates outside the range are simply not driven, so they keep the ink
# state from the previous full refresh.  That is precisely what we want: the
# clock digits are rewritten, everything else holds still.
#
# The geometry below is NOT guessed.  epd_bwr_213.c streams epd_buffer
# sequentially into the BW RAM, and epd_buffer is produced by FixBuffer() in
# epd.c:
#
#     FixBuffer():  epd_buffer[col*16 + byteY] = ~ucMirror[ obd[byteY][249-col] ]
#     write order:  index i = col*16 + byteY  ->  RAM X = byteY, RAM Y = 296 - col
#                   (0x11 = 0x01 -> X increments, Y decrements; 0x4F = 0x0128)
#
# therefore  col = 296 - RAM_Y  and, because FixBuffer mirrors x,
#            glass_x = 249 - col = RAM_Y - 47
# i.e.       RAM_Y = glass_x + 47
#
# This script recomputes the exact ink rectangle the clock can ever occupy from
# the REAL font metrics and asserts it is inside the driven gate range.
#
# Exit code 0 = window provably covers the clock; 1 = it does not.
# =============================================================================
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, '..', 'atc1441_src', 'Firmware', 'src')

# --- window constants, mirrored from epd_bwr_213.c --------------------------
WIN_GATE_FIRST = 101          # first DRIVEN gate  -> 0x0F
WIN_GATE_LAST = 237           # last  DRIVEN gate
WIN_GATES = WIN_GATE_LAST - WIN_GATE_FIRST + 1          # 137 lines -> MUX = 136

GLASS_X_TO_RAM_Y = 47         # RAM_Y = glass_x + 47   (see the header block)
CLOCK_X = 50                  # epd.c: obdWriteStringCustom(..., 50, 65, ...)
CLOCK_Y = 65                  # 65 is the BASELINE, not the top edge
FONT_NAME = 'DSEG14_Classic_Mini_Regular_40'

MUX_POR_MIN, MUX_POR_MAX = 16, 296    # SSD1680 p.34
SCN_MIN, SCN_MAX = 0, 295             # SSD1680 p.36


def load_glyphs():
    """Parse the GFXglyph table out of font_60.h.  The trailing comments carry
    the character, so they must be consumed with the numbers."""
    text = open(os.path.join(SRC, 'font_60.h'), encoding='utf-8', errors='ignore').read()
    m = re.search(r'const GFXglyph %sGlyphs\[\]\s*=\s*\{(.*?)\n\};' % FONT_NAME, text, re.S)
    if not m:
        sys.exit('could not find glyph table for ' + FONT_NAME)
    glyphs = {}
    for nums, ch in re.findall(r'\{\s*([-\d,\s]+?)\s*\}\s*,\s*//\s*\'(.)\'', m.group(1)):
        off, w, h, xadv, xoff, yoff = [int(v) for v in nums.split(',')]
        glyphs[ch] = dict(off=off, w=w, h=h, xadv=xadv, xoff=xoff, yoff=yoff)
    return glyphs


def ink_bbox_for(text, glyphs):
    """Mirror of obdWriteStringCustom(): pen x starts at CLOCK_X, every glyph is
    placed at (x + xOffset, y + yOffset) with y as the baseline."""
    x = CLOCK_X
    xs, ys = [], []
    for ch in text:
        g = glyphs[ch]
        dx = x + g['xoff']
        dy = CLOCK_Y + g['yoff']
        if g['w'] and g['h']:
            xs += [dx, dx + g['w'] - 1]
            ys += [dy, dy + g['h'] - 1]
        x += g['xadv']
    return min(xs), min(ys), max(xs), max(ys)


def main():
    glyphs = load_glyphs()
    print('loaded %d glyphs from font_60.h' % len(glyphs))

    gx0, gy0, gx1, gy1 = 10 ** 9, 10 ** 9, -10 ** 9, -10 ** 9
    worst = None
    for hh in range(24):
        for mm in range(60):
            t = '%02d:%02d' % (hh, mm)
            x0, y0, x1, y1 = ink_bbox_for(t, glyphs)
            if x0 < gx0:
                gx0 = x0
            if y0 < gy0:
                gy0 = y0
            if y1 > gy1:
                gy1 = y1
            if x1 > gx1:
                gx1 = x1
            if worst is None or x1 > worst[1]:
                worst = (t, x1)
    print('clock ink over all 1440 times: glass x [%d,%d]  y [%d,%d]' % (gx0, gx1, gy0, gy1))
    print('  widest time: %s (right edge %d)' % worst)

    ram_y0 = gx0 + GLASS_X_TO_RAM_Y
    ram_y1 = gx1 + GLASS_X_TO_RAM_Y
    print('  -> RAM rows (gate numbers) [%d,%d]' % (ram_y0, ram_y1))

    ok = True
    if not (WIN_GATE_FIRST <= ram_y0 and ram_y1 <= WIN_GATE_LAST):
        ok = False
        print('FAIL: clock ink sticks out of the driven gate range')

    if gy0 < 0 or gy1 > 127:
        ok = False
        print('FAIL: ink leaves the 128-pixel source range')
    ram_x0, ram_x1 = gy0 >> 3, gy1 >> 3
    if ram_x0 < 0 or ram_x1 > 15:
        ok = False
        print('FAIL: ink leaves RAM X 0..15')

    if not (MUX_POR_MIN <= WIN_GATES <= MUX_POR_MAX):
        ok = False
        print('FAIL: MUX ratio %d outside 16..296' % WIN_GATES)
    if not (SCN_MIN <= WIN_GATE_FIRST <= SCN_MAX):
        ok = False
        print('FAIL: gate start %d outside 0..295' % WIN_GATE_FIRST)
    if WIN_GATE_FIRST + WIN_GATES - 1 > 295:
        ok = False
        print('FAIL: driven gate range runs past 295')

    mux = WIN_GATES - 1
    b01 = [mux & 0xFF, (mux >> 8) & 0x01, 0x01]
    b0f = [WIN_GATE_FIRST & 0xFF, (WIN_GATE_FIRST >> 8) & 0x01]
    print('')
    print('driven gates      : G%d..G%d  (%d lines)' % (WIN_GATE_FIRST, WIN_GATE_LAST, WIN_GATES))
    print('0x01 (MUX)        : %s   (MUX[8:0] = %d -> %d lines)' %
          (' '.join('%02X' % b for b in b01), mux, mux + 1))
    print('0x0F (gate start) : %s   (SCN = %d)' % (' '.join('%02X' % b for b in b0f), WIN_GATE_FIRST))
    print('')
    print('scanned gates     : %d/296  (%.0f%% of a full refresh)'
          % (WIN_GATES, WIN_GATES * 100.0 / 296))
    print('source bytes      : 16/16 streamed (data path unchanged)')
    print('')
    print('RESULT: ' + ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
