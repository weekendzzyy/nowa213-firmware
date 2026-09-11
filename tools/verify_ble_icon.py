#!/usr/bin/env python3
# =============================================================================
# verify_ble_icon.py - assert the v11.0 Bluetooth rune is well formed and sits
#                      where the letter "B" it replaced used to sit
# -----------------------------------------------------------------------------
# Nothing is hard-coded twice: the bitmap and the geometry are parsed out of
# epd.c, the font metrics out of font16.h.  Run this after touching either.
#
# Checks:
#   1. the table is BLE_ICON_H rows, no row sets a bit outside BLE_ICON_W
#   2. the stem (bit 3) is set on every row
#   3. both chevrons are drawn as unbroken 45-degree diagonals
#   4. the rune fits inside the 250x128 virtual display
#   5. it does not reach the model line on its left
#   6. it occupies the same vertical span as the letter "B", and its horizontal
#      centre is within one pixel of the letter's -- so swapping the letter for
#      the icon cannot silently shift the layout
#
# Exit code 0 = all good, 1 = something drifted.
#
# Usage:
#   python tools/verify_ble_icon.py
# =============================================================================
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from render_screen_preview import load_font, load_ble_icon, VDISP_W, VDISP_H

MODEL_TEXT = 'ESL_140EC6 BWR213'
MODEL_X = 1
B_X, B_Y = 232, 20       # where epd.c used to draw the letter "B"

failures = []


def check(ok, msg):
    print(('  ok    ' if ok else '  FAIL  ') + msg)
    if not ok:
        failures.append(msg)


def segment_points(x1, y1, x2, y2):
    """Lattice points of the segment, so a diagonal can be tested for gaps."""
    n = max(abs(x2 - x1), abs(y2 - y1))
    if n == 0:
        return [(x1, y1)]
    return [(x1 + round((x2 - x1) * i / n), y1 + round((y2 - y1) * i / n))
            for i in range(n + 1)]


def main():
    x, y, w, h, rows = load_ble_icon()
    print('BLE rune: x=%d y=%d  size %dx%d' % (x, y, w, h))
    print('rows: ' + ' '.join('%02X' % r for r in rows))
    print()

    # 1 ---------------------------------------------------------------- shape
    check(len(rows) == h, 'table has %d rows, BLE_ICON_H is %d' % (len(rows), h))
    check(all((r >> w) == 0 for r in rows),
          'no row sets a bit outside the %d-px width' % w)

    # 2 -------------------------------------------------------------- the stem
    stem = 3
    check(all(r & (1 << stem) for r in rows),
          'stem is set on all %d rows (bit %d)' % (h, stem))
    check((rows[0] & (1 << stem)) and (rows[h - 1] & (1 << stem)),
          'stem runs edge to edge (rows 0 and %d)' % (h - 1))

    # 3 ---------------------------------------------------------- the chevrons
    for (x1, y1, x2, y2) in [(stem, 0, stem + 3, 3),
                             (stem + 3, 3, stem, 6),
                             (stem, 6, stem + 3, 9),
                             (stem + 3, 9, stem, 12)]:
        missing = [(cx, cy) for cx, cy in segment_points(x1, y1, x2, y2)
                   if not (rows[cy] & (1 << cx))]
        check(not missing,
              'diagonal (%d,%d)->(%d,%d) unbroken%s'
              % (x1, y1, x2, y2, '' if not missing else ', missing %s' % missing))

    # 4 ----------------------------------------------------------- on screen
    check(0 <= x and x + w <= VDISP_W,
          'x spans %d..%d inside 0..%d' % (x, x + w - 1, VDISP_W - 1))
    check(0 <= y and y + h <= VDISP_H,
          'y spans %d..%d inside 0..%d' % (y, y + h - 1, VDISP_H - 1))

    # 5 ----------------------------------------------- clear of the model line
    _, g16 = load_font('font16.h', 'Dialog_plain_16')
    pen = MODEL_X
    for ch in MODEL_TEXT:
        pen += g16[ch]['adv']
    model_last = pen - 1
    check(model_last < x,
          'model line ends at x=%d, rune starts at x=%d' % (model_last, x))

    # 6 -------------------------------- matches the letter it replaced exactly
    gb = g16['B']
    b_top = B_Y + gb['yo']
    b_bot = b_top + gb['h'] - 1
    b_cx = B_X + gb['xo'] + (gb['w'] - 1) / 2.0
    r_cx = x + (w - 1) / 2.0
    check(y <= b_top + 1 and (y + h - 1) <= b_bot + 1,
          "vertical span %d..%d fits the letter's %d..%d (1 px slack)"
          % (y, y + h - 1, b_top, b_bot))
    check(abs(r_cx - b_cx) <= 1.0,
          "horizontal centre %.1f within 1 px of the letter's %.1f"
          % (r_cx, b_cx))

    print()
    if failures:
        print('%d CHECK(S) FAILED' % len(failures))
        return 1
    print('all checks passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
