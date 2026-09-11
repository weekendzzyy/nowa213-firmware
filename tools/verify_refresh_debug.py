#!/usr/bin/env python3
# =============================================================================
# verify_refresh_debug.py - assert the v12.0 on-glass refresh counters are
#                           enabled, readable, and COMPLETE
# -----------------------------------------------------------------------------
# v12.0 draws "H0 T0 B0 L0" next to the temperature, so one glance at the tag
# says which of the four full-refresh causes fired.  Nothing is hard-coded
# twice: the position and the format string are parsed out of epd.c, the counter
# names out of app.c/epd.h, the font metrics out of font16.h/font30.h, and the
# per-minute gate window out of verify_gate_window.py.
#
# Checks:
#   1. EPD_USE_REFRESH_DEBUG is on and the sprintf is where we think it is
#   2. the widest string the format can ever produce still fits on the glass and
#      clears the 6 off-screen storage rows at the bottom
#   3. it does not collide with the temperature ink on its left, and it sits on
#      the temperature's baseline (same row)
#   4. it does not collide with the battery / version-badge row below it
#   5. its whole ink span stays inside the per-minute gate window (glass
#      x 54..190), so it is repainted every tick and can never go stale
#   6. the four counters exist as extern in epd.h and as RAM uint8_t in app.c
#   7. ANTI-DRIFT: every `force_full = 1` in app.c is paired with a matching
#      `cause_* = 1`, every cause_* is tallied into its own dbg_* counter, and
#      every counter is drawn.  Add a fifth full-refresh cause and forget the
#      counter and this fails - otherwise the on-glass numbers would silently
#      under-report, which is worse than no instrument at all.
#
# Exit code 0 = all good, 1 = something drifted.
#
# Usage:
#   python tools/verify_refresh_debug.py
# =============================================================================

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from render_screen_preview import load_font, read_define, VDISP_W, SRC
from verify_gate_window import WIN_GATE_FIRST, WIN_GATE_LAST, GLASS_X_TO_RAM_Y

# The driven gates are the clock rectangle; x on the drawn side is derived from
# them by the same identity verify_gate_window.py asserts (glass_x = RAM_Y - 47).
GLASS_X_MIN = WIN_GATE_FIRST - GLASS_X_TO_RAM_Y          # 54
GLASS_X_MAX = WIN_GATE_LAST - GLASS_X_TO_RAM_Y           # 190
VISIBLE_H = 122                                          # bottom 6 rows are off-glass

COUNTERS = ['dbg_hour', 'dbg_temp', 'dbg_batt', 'dbg_ble']

failures = []


def check(ok, msg):
    print(('  ok    ' if ok else '  FAIL  ') + msg)
    if not ok:
        failures.append(msg)


def src(path):
    return open(os.path.join(SRC, path), encoding='utf-8', errors='ignore').read()


def ink_span(glyphs, x, y, text):
    """Ink box (x0, x1, y0, y1) of the string obdWriteStringCustom() draws."""
    pen, x0, x1, y0, y1 = x, 10 ** 9, -10 ** 9, 10 ** 9, -10 ** 9
    for ch in text:
        g = glyphs[ch]
        gx, gy = pen + g['xo'], y + g['yo']
        x0, x1 = min(x0, gx), max(x1, gx + g['w'] - 1)
        y0, y1 = min(y0, gy), max(y1, gy + g['h'] - 1)
        pen += g['adv']
    return x0, x1, y0, y1


def _find_debug_sprintf(text):
    """(format, argument list) of the one sprintf that has a slot per counter.

    epd.c holds several sprintf(buff, ...) calls.  The counters one is picked by
    ARITY, not by position, so reordering the draws in epd_display() cannot make
    this latch onto the temperature line by accident.
    """
    for m in re.finditer(r'sprintf\(buff,\s*"([^"]*)"\s*,([^;]*?)\);', text):
        if m.group(1).count('%d') == len(COUNTERS):
            return m.group(1), m.group(2)
    return None


def main():
    _, g16 = load_font('font16.h', 'Dialog_plain_16')
    _, g30 = load_font('font30.h', 'Special_Elite_Regular_30')
    e, a, h = src('epd.c'), src('app.c'), src('epd.h')

    # 1 ----------------------------------------------------------------- set up
    on = read_define('epd.c', 'EPD_USE_REFRESH_DEBUG', '0')
    check(on == '1', 'EPD_USE_REFRESH_DEBUG is %s' % on)

    x = int(read_define('epd.c', 'EPD_DEBUG_X'))
    y = int(read_define('epd.c', 'EPD_DEBUG_Y'))

    m = _find_debug_sprintf(e)
    check(m is not None, 'found the counter sprintf in epd.c')
    fmt = m[0] if m else 'H%d T%d B%d L%d'
    args = m[1] if m else ''
    check(fmt.count('%d') == len(COUNTERS),
          'format "%s" has %d slots for %d counters'
          % (fmt, fmt.count('%d'), len(COUNTERS)))

    # the counters saturate at 9, so replacing every %d with 9 is the widest
    # string the glass can ever be asked to draw
    widest = re.sub(r'%d', '9', fmt)
    x0, x1, y0, y1 = ink_span(g16, x, y, widest)
    print('debug string "%s" at (%d, %d) -> ink x %d..%d  y %d..%d'
          % (widest, x, y, x0, x1, y0, y1))
    print()

    # 2 ------------------------------------------------------- on the glass
    check(0 <= x0 and x1 <= VDISP_W - 1,
          'x spans %d..%d inside 0..%d' % (x0, x1, VDISP_W - 1))
    check(y1 <= VISIBLE_H - 1,
          'y bottom %d is above the off-glass rows %d..127' % (y1, VISIBLE_H))

    # 3 --------------------------------------------- clear of the temperature
    mt = re.search(r'&Special_Elite_Regular_30,\s*(\d+),\s*(\d+)', e)
    check(mt is not None, 'found the temperature draw in epd.c')
    tx, ty = int(mt.group(1)), int(mt.group(2))
    mtf = re.search(r'sprintf\(buff,\s*"([^"]*%d[^"]*)"[^;]*Special_Elite', e, re.S)
    tfmt = mtf.group(1) if mtf else "%d'C"
    # 99'C is the widest 2-digit reading Special_Elite_Regular_30 can produce
    tspan = ink_span(g30, tx, ty, re.sub(r'%d', '99', tfmt))
    print('temperature   "%s" at (%d, %d) -> ink x %d..%d'
          % (re.sub(r'%d', '99', tfmt), tx, ty, tspan[0], tspan[1]))
    check(y == ty, 'both sit on the same baseline (debug y=%d, temp y=%d)' % (y, ty))
    check(x0 > tspan[1],
          'debug starts at x=%d, temperature ink ends at x=%d' % (x0, tspan[1]))

    # 4 ------------------------------------- clear of the rows below (y=120)
    min_yo = min(g['yo'] for g in g16.values())
    rows_below = []
    mb = re.search(r'"Battery %dmV"[^;]*;\s*obdWriteStringCustom\(&obd,\s*'
                   r'\(GFXfont \*\)&Dialog_plain_16,\s*(\d+),\s*(\d+)', e, re.S)
    if mb:
        rows_below.append(('battery', int(mb.group(1)), int(mb.group(2))))
    rows_below.append(('version',
                       int(read_define('epd.c', 'EPD_VERSION_X', '199')),
                       int(read_define('epd.c', 'EPD_VERSION_Y', '120'))))
    top_below = min(by + min_yo for _, _, by in rows_below)
    check(y1 < top_below,
          'debug ink bottom y=%d clears the rows below (top y=%d: %s)'
          % (y1, top_below, ', '.join(n for n, _, _ in rows_below)))

    # 5 ------------------------------------- inside the per-minute gate window
    check(x0 >= GLASS_X_MIN and x1 <= GLASS_X_MAX,
          'ink x %d..%d inside the near-side window %d..%d (repainted each tick)'
          % (x0, x1, GLASS_X_MIN, GLASS_X_MAX))

    # 6 ------------------------------------------------- the counters exist
    for name in COUNTERS:
        check(re.search(r'extern uint8_t[^;]*\b%s\b' % name, h) is not None,
              'epd.h declares extern %s' % name)
        check(re.search(r'RAM uint8_t\s+%s\s*=' % name, a) is not None,
              'app.c defines RAM uint8_t %s' % name)

    # 7 -------------------------------------------------------------- coverage
    forces = re.findall(r'\bforce_full = 1;', a)
    causes = re.findall(r'\bcause_(\w+) = 1;', a)
    print()
    print('force_full sites: %d   cause_* sites: %s'
          % (len(forces), ', '.join(causes)))
    check(len(forces) == len(causes) and len(causes) == len(set(causes)),
          'every force_full = 1 is paired with its own cause_* = 1 (%d/%d)'
          % (len(forces), len(causes)))
    for suffix in causes:
        check(re.search(r'if \(cause_%s\)\s+DBG_BUMP\(dbg_%s\)' % (suffix, suffix), a)
              is not None,
              'cause_%s is tallied into dbg_%s' % (suffix, suffix))
        check(('dbg_%s' % suffix) in COUNTERS,
              'dbg_%s is one of the drawn counters' % suffix)
    for name in COUNTERS:
        check(re.search(r'DBG_BUMP\(%s\)' % name, a) is not None,
              '%s is incremented somewhere in the tick' % name)
        check(re.search(r'\b%s\b' % name, args) is not None,
              '%s reaches the glass (in the sprintf argument list)' % name)

    print()
    if failures:
        print('%d CHECK(S) FAILED' % len(failures))
        return 1
    print('all checks passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
