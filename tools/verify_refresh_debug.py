#!/usr/bin/env python3
# =============================================================================
# verify_refresh_debug.py - assert the on-glass refresh counters are readable,
#                           COMPLETE, and still fit when re-armed
# -----------------------------------------------------------------------------
# app.c counts the four things that can raise `full` (the hourly refresh, the
# temperature dead band, the battery dead band, a BLE connect flip) and epd.c
# draws them next to the temperature as "H09T0B1L2".  The switch is
# EPD_USE_REFRESH_DEBUG: 1 = on the glass, 0 = off, which is what v13.0 ships.
# The counters keep counting either way, so flipping the switch back is the
# whole re-arm procedure - and that is exactly why this script has to keep
# passing while the flag is 0.  Nothing is hard-coded twice: the position and
# format string come out of epd.c, the counter names out of app.c/epd.h, the
# saturation caps out of app.c's DBG_BUMP* macros, the font metrics out of
# font16.h/font30.h, the night window out of app.c, and the per-minute gate
# window out of verify_gate_window.py.
#
# Checks:
#   1. EPD_USE_REFRESH_DEBUG is a real 0/1 switch, and the sprintf is where we
#      think it is (picked by ARITY, so reordering the draws cannot fool it)
#   2. every counter's saturation cap covers the geometry that was designed for
#      it: H must survive a whole day of hourly refreshes, because a cap that
#      pegs before the reading is taken reports nothing (that was the v12.0 bug)
#   3. the widest string the format + caps can ever produce still fits on the
#      glass and clears the 6 off-screen storage rows at the bottom
#   4. it does not collide with the temperature ink on its left, and it sits on
#      the temperature's baseline (same row)
#   5. it does not collide with the battery / version-badge row below it
#   6. its whole ink span stays inside the per-minute gate window (glass
#      x 54..190), so it is repainted every tick and can never go stale
#   7. the four counters exist as extern in epd.h and as RAM uint8_t in app.c
#   8. ANTI-DRIFT: every `force_full = 1` in app.c is paired with a matching
#      `cause_* = 1`, every cause_* is tallied into its own dbg_* counter, and
#      every counter appears in the sprintf in the SAME order.  Add a fifth
#      full-refresh cause and forget the counter and this fails - otherwise the
#      on-glass numbers would silently under-report, which is worse than no
#      instrument at all.
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
        if len(re.findall(r'%\d*d', m.group(1))) == len(COUNTERS):
            return m.group(1), m.group(2)
    return None


def _slots(fmt):
    """[(field width, raw spec)] per conversion, in format order."""
    return [(int(m.group(1)) if m.group(1) else 0, m.group(0))
            for m in re.finditer(r'%(\d*)d', fmt)]


def _caps(text):
    """{macro name: saturation cap} out of app.c's DBG_BUMP* defines.

    v12.0 hard-coded the cap of 9 here as well as in app.c, which meant the two
    could drift apart in silence.  Parsing it makes the widest-string
    computation below follow app.c instead of an assumption about it.
    """
    return {m.group(1): int(m.group(2))
            for m in re.finditer(
                r'#define\s+(DBG_BUMP\w*)\(c\)\s+do\s*\{\s*if\s*\(\(c\)\s*<\s*(\d+)\)',
                text)}


def _tally_macro(a, name):
    """The DBG_BUMP* macro that increments `name`, or None."""
    m = re.search(r'\b(DBG_BUMP\w*)\(%s\)' % name, a)
    return m.group(1) if m else None


def main():
    _, g16 = load_font('font16.h', 'Dialog_plain_16')
    _, g30 = load_font('font30.h', 'Special_Elite_Regular_30')
    e, a, h = src('epd.c'), src('app.c'), src('epd.h')

    # 1 ------------------------------------------------------- the switch
    on = read_define('epd.c', 'EPD_USE_REFRESH_DEBUG', '0')
    check(on in ('0', '1'), 'EPD_USE_REFRESH_DEBUG is %r (must be 0 or 1)' % on)
    print('        -> %s on the release glass; %s'
          % ('counters ARE' if on == '1' else 'counters are OFF',
             'this script then checks the live geometry'
             if on == '1' else
             'this script still checks the geometry they would need'))

    x = int(read_define('epd.c', 'EPD_DEBUG_X'))
    y = int(read_define('epd.c', 'EPD_DEBUG_Y'))

    m = _find_debug_sprintf(e)
    check(m is not None, 'found the counter sprintf in epd.c')
    fmt = m[0] if m else 'H%dT%dB%dL%d'
    args = m[1] if m else ''
    slots = _slots(fmt)
    check(len(slots) == len(COUNTERS),
          'format "%s" has %d slots for %d counters'
          % (fmt, len(slots), len(COUNTERS)))

    arg_list = [t.strip() for t in args.split(',')]
    caps = _caps(a)
    check(bool(caps), 'parsed the DBG_BUMP* saturation caps out of app.c: %s'
          % ', '.join('%s<%d' % kv for kv in sorted(caps.items())))

    # 2 ------------------------- each cap must outlast the geometry it serves
    # The tag full-refreshes once an hour while it is awake, and is silent
    # between NIGHT_START_HOUR and NIGHT_END_HOUR.  A counter is only read after
    # roughly a day, so a cap that a single day can reach is useless.
    ns = int(read_define('app.c', 'NIGHT_START_HOUR', '0'))
    ne = int(read_define('app.c', 'NIGHT_END_HOUR', '24'))
    night = (ne - ns) % 24
    hourly_per_day = 24 - night
    cap_h = caps.get(_tally_macro(a, 'dbg_hour') or '', 0)
    check(cap_h >= hourly_per_day,
          'dbg_hour cap %d survives a full day of %d hourly refreshes '
          '(night %02d:00-%02d:00 excluded)' % (cap_h, hourly_per_day, ns, ne))

    # 3 --------------------------------- the widest string, from the real caps
    # A cap of 99 printed through "%d" still widens the string to 2 glyphs, so
    # the widest rendering is max(digits in the cap, the format field width).
    widths = []
    for (width, _spec), argname in zip(slots, arg_list):
        cap = caps.get(_tally_macro(a, argname) or '', 0)
        widths.append(max(len(str(cap)), width))
    it = iter(widths)
    widest = re.sub(r'%\d*d', lambda _m: '9' * next(it), fmt)

    x0, x1, y0, y1 = ink_span(g16, x, y, widest)
    print()
    print('debug string "%s" at (%d, %d) -> ink x %d..%d  y %d..%d'
          % (widest, x, y, x0, x1, y0, y1))
    print()

    check(0 <= x0 and x1 <= VDISP_W - 1,
          'x spans %d..%d inside 0..%d' % (x0, x1, VDISP_W - 1))
    check(y1 <= VISIBLE_H - 1,
          'y bottom %d is above the off-glass rows %d..127' % (y1, VISIBLE_H))

    # 4 --------------------------------------------- clear of the temperature
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

    # 5 ------------------------------------- clear of the rows below (y=120)
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

    # 6 ------------------------------------- inside the per-minute gate window
    check(x0 >= GLASS_X_MIN and x1 <= GLASS_X_MAX,
          'ink x %d..%d inside the near-side window %d..%d (repainted each tick)'
          % (x0, x1, GLASS_X_MIN, GLASS_X_MAX))

    # 7 ------------------------------------------------- the counters exist
    for name in COUNTERS:
        check(re.search(r'extern uint8_t[^;]*\b%s\b' % name, h) is not None,
              'epd.h declares extern %s' % name)
        check(re.search(r'RAM uint8_t\s+%s\s*=' % name, a) is not None,
              'app.c defines RAM uint8_t %s' % name)

    # 8 -------------------------------------------------------------- coverage
    forces = re.findall(r'\bforce_full = 1;', a)
    causes = re.findall(r'\bcause_(\w+) = 1;', a)
    print()
    print('force_full sites: %d   cause_* sites: %s'
          % (len(forces), ', '.join(causes)))
    check(len(forces) == len(causes) and len(causes) == len(set(causes)),
          'every force_full = 1 is paired with its own cause_* = 1 (%d/%d)'
          % (len(forces), len(causes)))
    for suffix in causes:
        check(re.search(r'if \(cause_%s\)\s+DBG_BUMP\w*\(dbg_%s\)' % (suffix, suffix), a)
              is not None,
              'cause_%s is tallied into dbg_%s' % (suffix, suffix))
        check(('dbg_%s' % suffix) in COUNTERS,
              'dbg_%s is one of the drawn counters' % suffix)
    for name in COUNTERS:
        check(re.search(r'DBG_BUMP\w*\(%s\)' % name, a) is not None,
              '%s is incremented somewhere in the tick' % name)
    # positional: the sprintf argument list, the format slots and the caps all
    # have to line up, otherwise a counter would be printed under another label
    check(arg_list == COUNTERS,
          'sprintf arguments are %s (expected the declared order %s)'
          % (arg_list, COUNTERS))
    for (width, spec), name in zip(slots, arg_list):
        cap = caps.get(_tally_macro(a, name) or '', 0)
        check(width == 0 or width >= len(str(cap)),
              'slot %s renders up to %d digits and the field is "%s"'
              % (name, len(str(cap)), spec))

    print()
    if failures:
        print('%d CHECK(S) FAILED' % len(failures))
        return 1
    print('all checks passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
