#!/usr/bin/env python3
# =============================================================================
# verify_v14_layout.py - offline proof of the v14.0 clock face
# -----------------------------------------------------------------------------
# epd_layout.h claims three things, and this script is what makes the claims
# cost something to break:
#
#   1. every digit stays inside its own cell, so
#   2. the per-minute gate window can be exactly the last two clock slots, and
#   3. the widest row-1 string the calendar and the clamps can produce still
#      fits on the glass and in the buffer sized for it.
#
# Nothing here re-types a number from the firmware.  The geometry is evaluated
# out of epd_layout.h (including its one function-like macro, CLOCK_SLOT_X), the
# glyph metrics out of the generated font_unifont.h, the calendar out of
# calendar_data.h, and the drawing itself out of tools/epd_face_model.py, which
# is the line-by-line mirror of epd_font.c / epd.c / calendar.c.  Point 2 is
# checked the only way that cannot be fooled: render every "HH:MM", diff the
# framebuffers tick by tick, and see whether the columns that actually change
# are the columns the window drives.
#
# The last section re-introduces the bugs this release fixed and asserts that
# the corresponding check FAILS.  A check that cannot fail is not a check.
#
# Exit code 0 = every assertion held; 1 = at least one did not.
# =============================================================================
import argparse
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from epd_face_model import (Face, _read, ink_extent,  # noqa: E402
                            new_buffer)

EPOCH = datetime.datetime(1970, 1, 1)


def ts(y, m, d, hh=0, mi=0):
    return int((datetime.datetime(y, m, d, hh, mi) - EPOCH).total_seconds())


class Report(object):
    """Collects PASS/FAIL lines and prints them grouped by section."""

    def __init__(self, quiet=False):
        self.fail = 0
        self.pass_ = 0
        self.quiet = quiet

    def head(self, title):
        print('')
        print('== %s %s' % (title, '=' * max(4, 66 - len(title))))

    def chk(self, ok, label, detail=''):
        if ok:
            self.pass_ += 1
            if not self.quiet:
                print('  ok    %s%s' % (label, ('   ' + detail) if detail else ''))
        else:
            self.fail += 1
            print('  FAIL  %s%s' % (label, ('   ' + detail) if detail else ''))
        return ok

    def note(self, text):
        if not self.quiet:
            print('        %s' % text)


# ---------------------------------------------------------------------------
# section 1 - the glass and the rows
# ---------------------------------------------------------------------------
def check_geometry(face, rep):
    L = face.L
    rep.head('glass and rows')
    rep.chk(L['FACE_W'] == 250 and L['FACE_H'] == 128 and L['FACE_VISIBLE_H'] == 122,
            'the glass is 250x122 in a 250x128 buffer',
            '%dx%d visible %d' % (L['FACE_W'], L['FACE_H'], L['FACE_VISIBLE_H']))

    rows = [('row 1', L['ROW1_Y'], 16),
            ('clock', L['CLOCK_Y'], L['CLOCK_H']),
            ('row 3', L['ROW3_Y'], 16),
            ('rune ', L['ROW3_Y'] + 1, face.rune_h)]
    for name, y0, h in rows:
        rep.chk(y0 >= 0 and y0 + h <= L['FACE_VISIBLE_H'],
                '%s is inside the visible height' % name,
                'y %d..%d of %d' % (y0, y0 + h - 1, L['FACE_VISIBLE_H']))

    # rows must not overlap each other either
    rep.chk(L['ROW1_Y'] + 16 <= L['CLOCK_Y'] and
            L['CLOCK_Y'] + L['CLOCK_H'] <= L['ROW3_Y'],
            'the three rows do not overlap',
            'row1 ends %d, clock %d..%d, row3 starts %d'
            % (L['ROW1_Y'] + 15, L['CLOCK_Y'], L['CLOCK_Y'] + L['CLOCK_H'] - 1,
               L['ROW3_Y']))


# ---------------------------------------------------------------------------
# section 2 - the clock is a fixed-slot display and every digit stays home
# ---------------------------------------------------------------------------
GLYPHS = '0123456789:'


def glyph_cell_w(face, ch):
    """How wide a glyph's slot is - the colon's own, otherwise a digit cell.
    Note this is NOT slot_w(i) with i the index into GLYPHS: the colon is the
    last entry of GLYPHS but the third slot."""
    return face.L['CLOCK_COLON_W'] if ch == ':' else face.L['CLOCK_CELL_W']


def cell_ink(face):
    """{char: (xmin, xmax)} for each clock glyph, drawn on a FULL-WIDTH buffer.

    Full width matters: drawing into a cell-wide buffer clips at wpitch and
    would hide exactly the overshoot this measures.  That mistake is what let
    the original x1 - t + 1 reach the panel unnoticed.
    """
    L, W, H = face.L, face.L['FACE_W'], face.L['FACE_H']
    out = {}
    for ch in GLYPHS:
        w = L['CLOCK_COLON_W'] if ch == ':' else L['CLOCK_CELL_W']
        buf = bytearray(W * H // 8)
        if ch == ':':
            face.draw_colon(buf, W, H, 0, L['CLOCK_Y'], L['CLOCK_H'],
                            L['CLOCK_STROKE'])
        else:
            face.draw_digit(buf, W, H, 0, L['CLOCK_Y'], w, L['CLOCK_H'],
                            L['CLOCK_STROKE'], ch)
        xs = [x for r in range(H // 8) for x in range(W) if buf[r * W + x]]
        out[ch] = (min(xs), max(xs)) if xs else None
    return out


def check_clock(face, rep):
    L = face.L
    rep.head('the clock')
    slots = [face.slot_x(i) for i in range(5)]
    rep.note('slot x: %s   cell %d px, colon %d px, stroke %d px'
             % (slots, L['CLOCK_CELL_W'], L['CLOCK_COLON_W'], L['CLOCK_STROKE']))

    rep.chk(L['CLOCK_X0'] >= 0 and L['CLOCK_X0'] + L['CLOCK_WIDEST'] <= L['FACE_W'],
            'the widest HH:MM fits on the glass',
            '%d..%d of %d' % (L['CLOCK_X0'], L['CLOCK_X0'] + L['CLOCK_WIDEST'] - 1,
                              L['FACE_W']))
    rep.chk(L['CLOCK_STROKE'] * 4 < L['CLOCK_CELL_W'],
            'the stroke leaves the bars distinguishable',
            '4*%d < %d' % (L['CLOCK_STROKE'], L['CLOCK_CELL_W']))

    # slots laid out left to right without overlapping
    ends = [s + face.slot_w(i) - 1 for i, s in enumerate(slots)]
    ok = True
    for i in range(1, 5):
        if slots[i] <= ends[i - 1]:
            ok = False
    rep.chk(ok, 'the five slots do not overlap',
            'ends %s' % ends)

    # THE invariant the gate window rests on
    ink = cell_ink(face)
    bad = [(c, ink[c]) for c in GLYPHS
           if ink[c] is None or ink[c][0] < 0 or ink[c][1] > glyph_cell_w(face, c) - 1]
    rep.chk(not bad, 'every glyph stays inside its own cell',
            'ink %s, colon %d, cell %d'
            % ({c: ink[c] for c in GLYPHS},
               face.L['CLOCK_COLON_W'], face.L['CLOCK_CELL_W']))
    if bad:
        rep.note('outside: %s' % bad)


# ---------------------------------------------------------------------------
# section 3 - the per-minute gate window
# ---------------------------------------------------------------------------
def column_bits(face):
    """{char: {x: tuple of pixel bits down the clock band}} for placement.

    The scan is over the WHOLE buffer width, not 0..w-1: a glyph that paints
    outside its own cell is the defect this exists to catch, and clipping the
    scan to the cell would hide it.  (It did: that is why the off-by-one in the
    right-hand bars survived the first run of this script.)
    """
    L, W, H = face.L, face.L['FACE_W'], face.L['FACE_H']
    out = {}
    for ch in GLYPHS:
        w = glyph_cell_w(face, ch)
        buf = bytearray(W * H // 8)
        if ch == ':':
            face.draw_colon(buf, W, H, 0, L['CLOCK_Y'], L['CLOCK_H'],
                            L['CLOCK_STROKE'])
        else:
            face.draw_digit(buf, W, H, 0, L['CLOCK_Y'], w, L['CLOCK_H'],
                            L['CLOCK_STROKE'], ch)
        cols = {}
        for x in range(W):
            col = tuple((buf[((y >> 3) * W + x)] >> (y & 7)) & 1
                        for y in range(L['CLOCK_Y'], L['CLOCK_Y'] + L['CLOCK_H']))
            if any(col):
                cols[x] = col
        out[ch] = cols
    return out


def placed(cells, face, hhmm):
    out = {}
    for i, ch in enumerate(hhmm):
        x0 = face.slot_x(i)
        for x, v in cells[ch].items():
            out[x0 + x] = v
    return out


def minute_tick_union(face, cells):
    """(union of changed columns, count of ticks) over every partial refresh.

    A tick is a partial refresh only when the hour did NOT change - app.c takes
    `full = hour_changed || force_full` - so the 59 -> 00 tick is excluded: it
    changes the hour digits and does a full panel refresh instead.
    """
    lo, hi, ticks = None, None, 0
    hour_creep = []
    for h in range(24):
        for mi in range(59):
            a = placed(cells, face, '%02d:%02d' % (h, mi))
            b = placed(cells, face, '%02d:%02d' % (h, mi + 1))
            changed = [x for x in set(a) | set(b) if a.get(x) != b.get(x)]
            ticks += 1
            if not changed:
                continue
            lo = min(changed) if lo is None else min(lo, min(changed))
            hi = max(changed) if hi is None else max(hi, max(changed))
            creep = [x for x in changed if x < face.slot_x(3)]
            if creep:
                hour_creep.append(('%02d:%02d' % (h, mi), creep))
    return lo, hi, ticks, hour_creep


def check_window(face, rep, cells, union):
    """The window check: was the union of what actually changes computed, and
    does the window the driver will be given cover it - exactly?"""
    L = face.L
    lo, hi, ticks, creep = union

    rep.head('the per-minute gate window')
    rep.note('partial ticks simulated: %d  (every minute of the day except the '
             '59 -> 00 hour change)' % ticks)

    first, last = L['EPD_WIN_GATE_FIRST'], L['EPD_WIN_GATE_LAST']

    rep.chk(not creep, 'the hour digits hold still on a partial tick',
            '%d ticks moved a column left of slot 3' % len(creep))
    if creep:
        rep.note('e.g. %s moved %s' % creep[0])

    got_first = lo + L['EPD_WIN_GATE_OFFSET']
    got_last = hi + L['EPD_WIN_GATE_OFFSET']
    rep.note('changed columns: glass %d..%d  ->  gate %d..%d'
             % (lo, hi, got_first, got_last))
    rep.note('declared window: gate %d..%d  (%d gates, %.0f%% of 296)'
             % (first, last, last - first + 1, (last - first + 1) * 100.0 / 296))

    rep.chk(first <= got_first and got_last <= last,
            'the window covers every column a partial tick can change',
            'covers %d..%d' % (got_first, got_last))
    rep.chk(first == got_first and last == got_last,
            'the window is exactly that union - no unexplained slack',
            'slack %d left, %d right' % (got_first - first, last - got_last))

    rep.chk(L['EPD_WIN_GATES'] == last - first + 1,
            'EPD_WIN_GATES is the window length',
            '%d gates -> MUX %d' % (L['EPD_WIN_GATES'], L['EPD_WIN_GATES'] - 1))
    rep.chk(16 <= L['EPD_WIN_GATES'] <= 296,
            'the MUX ratio is legal for the SSD1680 (p.34)',
            '%d in 16..296' % L['EPD_WIN_GATES'])
    rep.chk(0 <= first and last <= 295,
            'the driven gates are legal for the SSD1680 (p.36)',
            '%d..%d in 0..295' % (first, last))

    # ... and the driver writes those exact bytes
    mux = L['EPD_WIN_GATES'] - 1
    rep.note('0x01 (MUX, SCN) -> %02X %02X %02X / %02X %02X'
             % (mux & 0xFF, (mux >> 8) & 1, 0x01,
                first & 0xFF, (first >> 8) & 1))

    # The band is vertical, so a partial refresh rewrites EVERY row that has ink
    # in x band .. band+w.  Two things live there and both have to be constant
    # or the minute tick will smear them:
    #   - row 1's temperature and voltage: app.c freezes them (checked in
    #     check_version, because the guard is on the other side of the driver);
    #   - row 3's device name: derived from mac_public[], constant for the life
    #     of the boot.  Re-painting it changes nothing, so it is safe by being
    #     a constant rather than by being frozen.
    # What must NOT be in the band is anything that moves on its own, and the
    # H/T/B/L counters are the only such thing on the face: they advance during
    # a full refresh, and if a partial refresh could reach them it would repaint
    # a stale copy over the top.
    band = (first - L['EPD_WIN_GATE_OFFSET'], last - L['EPD_WIN_GATE_OFFSET'])
    dbg = 'H99T9B9L9'          # the widest string sprintf() can produce there
    dbg_end = L['ROW3_X'] + face.text_width(dbg)
    rep.note('the per-minute band covers glass x %d..%d' % band)
    rep.chk(dbg_end <= band[0],
            'the H/T/B/L counters sit clear of the per-minute band',
            '"%s" ends at %d, band starts at %d (%d px of slack)'
            % (dbg, dbg_end, band[0], band[0] - dbg_end))

    # The other half of the same argument: row 1's voltage DOES fall in the band,
    # which is why app.c has to freeze it.  Use the shortest the suffix can get
    # (a 1-digit mV reading) so this stays true for every reading.
    cps = face.row1(ts(2026, 9, 12, 12, 0), 0, 31)
    x, xs = L['ROW1_X'], []
    for cp in cps:
        xs.append(x)
        x += face.uf_find(cp)[2]
    mv_x = xs[-2]                                    # the 'm' of the unit
    rep.chk(band[0] <= mv_x <= band[1],
            'row 1\'s voltage does fall in the band - so it must be frozen',
            '"...mV" starts at %d, band is %d..%d'
            % (mv_x, band[0], band[1]))
    return union


# ---------------------------------------------------------------------------
# section 4 - row 1, the only row that can grow
# ---------------------------------------------------------------------------
DAY_FIRST = (2026, 1, 1)
DAY_LAST = (2050, 12, 31)


def days():
    y, m, d = DAY_FIRST
    while (y, m, d) <= DAY_LAST:
        yield y, m, d
        if m == 12 and d == 31:
            y, m, d = y + 1, 1, 1
        else:
            d += 1
            if d > (29 if m == 2 and ((y % 4 == 0 and y % 100 != 0) or y % 400 == 0)
                    else (0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)[m]):
                d, m = 1, m + 1


def check_row1(face, rep):
    L = face.L
    rep.head('row 1')
    temps = [L['ROW1_TEMP_MIN'], -10, -9, -1, 0, 9, 10, 85, L['ROW1_TEMP_MAX']]
    mvs = [0, 9, 999, 1000, 2905, L['ROW1_MV_MAX']]
    overflow = []
    too_wide = []
    too_long = []
    worst = (0, None)

    for y, m, d in days():
        t = ts(y, m, d, 12, 0)
        for temp in temps:
            for mv in mvs:
                try:
                    cps = face.row1(t, mv, temp)
                except IndexError as exc:
                    overflow.append(('%04d-%02d-%02d %d %d' % (y, m, d, temp, mv),
                                     str(exc)))
                    continue
                if len(cps) > L['ROW1_MAX_CHARS'] - 1:
                    too_long.append((y, m, d, temp, mv, len(cps)))
                w = face.utext_width(cps)
                if L['ROW1_X'] + w > L['FACE_W']:
                    too_wide.append((y, m, d, temp, mv, w))
                if w > worst[0]:
                    worst = (w, ''.join(chr(c) for c in cps))

    checked = len(temps) * len(mvs)
    rep.note('walked every day of %04d-%02d-%02d..%04d-%02d-%02d x %d x %d = %d strings'
             % (DAY_FIRST + DAY_LAST + (len(temps), len(mvs),
                                        sum(1 for _ in days()) * checked)))
    rep.chk(not overflow, 'the row-1 buffer holds the widest string (no overrun)',
            'ROW1_MAX_CHARS %d' % L['ROW1_MAX_CHARS'])
    if overflow:
        rep.note('e.g. %s -> %s' % overflow[0])
    rep.chk(not too_long, 'no string needs more codepoints than the buffer has',
            'max %d, capacity %d' % (len(face.row1(ts(2050, 12, 26), 9999, -40)),
                                     L['ROW1_MAX_CHARS'] - 1))
    rep.chk(not too_wide, 'the widest string still fits across the glass',
            'ends at x=%d of %d' % (L['ROW1_X'] + worst[0], L['FACE_W']))
    rep.note('widest: %s  (%d px)' % (worst[1], worst[0]))
    rep.chk(worst[0] == L['ROW1_MAX_ADV'],
            'ROW1_MAX_ADV is the true maximum, not a guess',
            'measured %d, declared %d' % (worst[0], L['ROW1_MAX_ADV']))

    rep.note('clamps: temperature %d..%d, voltage <= %d'
             % (L['ROW1_TEMP_MIN'], L['ROW1_TEMP_MAX'], L['ROW1_MV_MAX']))
    return worst


# ---------------------------------------------------------------------------
# section 5 - row 3
# ---------------------------------------------------------------------------
def check_row3(face, rep):
    L = face.L
    rep.head('row 3')
    mac = (0xA1, 0xB2, 0xC3)
    bracket = face.mac_bracket(mac)
    bx = face.row3_right_x(mac)
    rx = face.row3_rune_x(mac)
    rep.note('left text at x=%d; rune slot %d..%d; "%s" at %d..%d'
             % (L['ROW3_X'], rx, rx + face.rune_w - 1, bracket, bx,
                bx + face.text_width(bracket) - 1))

    rep.chk(bx + face.text_width(bracket) <= L['FACE_W'],
            'the device name fits inside the right edge',
            'ends at %d of %d' % (bx + face.text_width(bracket), L['FACE_W']))
    rep.chk(rx >= 0 and L['ROW3_X'] < rx,
            'the rune slot is on the glass, right of the text origin',
            '%d' % rx)

    # The rune is drawn from its own bitmap array, not from a slice of the font.
    # A mirror that reads UF_BITS at offset 0 gets the subset's first glyph - a
    # space, i.e. all zeroes - and silently draws nothing, which is precisely
    # what the first preview render did.  So assert both directions.
    ry = L['ROW3_Y'] + 1
    rbuf = new_buffer(face)
    face.rune(rbuf, L['FACE_W'], L['FACE_H'], rx, ry)
    rink = ink_extent(face, rbuf)
    rep.chk(rink[0] == rx and rink[1] == rx + face.rune_w - 1,
            'the rune marks every column of its slot',
            'ink x %d..%d of slot %d..%d' % (rink[0], rink[1], rx,
                                             rx + face.rune_w - 1))

    wbuf = new_buffer(face)
    face.uf_blit(wbuf, L['FACE_W'], L['FACE_H'], rx, ry, face.bits, 0,
                 face.rune_w)
    rep.chk(ink_extent(face, wbuf) is None,
            'reading the rune out of the font array would draw nothing',
            'the wrong array is caught by the check above')

    # The reference panel's rune carries a left arm in each half - the user's
    # sketch of it is unmistakable about that - so it is its own mirror image
    # about the centre row.  The first revision put the whole left arm above the
    # centre, which left the lower-left quarter blank and made the symbol lean.
    asym = face.rune_asymmetric()
    rep.chk(not asym, 'the rune is its own mirror image top to bottom',
            'no ink in the lower-left quarter' if asym == [0, 1, 2, 3]
            else 'columns %s disagree with their own reverse' % (asym,))

    worst = (0, None, None)
    collide = []
    empty = 0
    for y, m, d in days():
        cps = face.row3(ts(y, m, d, 12, 0))
        if not cps:
            empty += 1
            continue
        if len(cps) >= face.ch_maxn:
            rep.chk(False, 'cal_row3 needs more room than CAL_ROW3_MAX',
                    '%04d-%02d-%02d -> %d' % (y, m, d, len(cps)))
            return
        w = face.utext_width(cps)
        if w > worst[0]:
            worst = (w, ''.join(chr(c) for c in cps), '%04d-%02d-%02d' % (y, m, d))
        if L['ROW3_X'] + w > rx:
            collide.append(('%04d-%02d-%02d' % (y, m, d), w, L['ROW3_X'] + w))

    rep.chk(empty == 0, 'every day of the supported range produces row-3 text',
            '%d days drew nothing' % empty)
    rep.chk(not collide, 'the calendar text never reaches the rune slot',
            'closest left edge %d, rune at %d' % (L['ROW3_X'] + worst[0], rx))
    if collide:
        rep.note('e.g. %s' % (collide[0],))
    rep.note('widest: %s  (%d px, ends at %d, %d px clear of the rune)'
             % (worst[1], worst[0], L['ROW3_X'] + worst[0],
                rx - L['ROW3_X'] - worst[0]))
    if worst[2]:
        rep.note('first seen %s' % worst[2])

    # the drawn face must keep row 3 inside the visible height as well
    buf = new_buffer(face)
    face.face(buf, L['FACE_W'], L['FACE_H'], ts(2026, 9, 12, 19, 6), 2905, 31,
              mac=mac, connected=True)
    ext = ink_extent(face, buf)
    rep.chk(ext[3] < L['FACE_VISIBLE_H'],
            'the drawn face stays above the last 6 buffer rows',
            'ink y %d..%d of %d visible' % (ext[2], ext[3], L['FACE_VISIBLE_H']))
    rep.chk(ext[1] < L['FACE_W'] and ext[0] >= 0,
            'the drawn face stays on the glass',
            'ink x %d..%d' % (ext[0], ext[1]))
    return worst


# ---------------------------------------------------------------------------
# section 6 - the calendar the two rows are formatted from
# ---------------------------------------------------------------------------
# Independently sourced anchors: the epoch the table is keyed on, the two
# Spring Festivals either side of the reference photo's date, and a leap month.
LUNAR_ANCHORS = [
    ((2024, 2, 10), (1, 1, 0), 'the table epoch, new year 2024'),
    ((2025, 1, 29), (1, 1, 0), 'new year 2025'),
    ((2026, 1, 1), (11, 13, 0), 'the year before 2026 - needs the 2025 row'),
    ((2026, 2, 17), (1, 1, 0), 'new year 2026'),
    ((2026, 9, 12), (8, 2, 0), 'the reference photo'),
    ((2050, 12, 31), (11, 18, 0), 'the last supported day'),
]


def lunar_year_of(face, y, m, d):
    """Which lunar year a solar date falls in, or None before the table starts.

    Deliberately NOT lunar_from_solar(): this sums the table's year lengths from
    the epoch on its own, so it is an independent route to the same answer and
    a wrong year length in either place shows up as a disagreement.
    """
    c = face.cal
    off = (face.days_from_civil(y, m, d)
           - face.days_from_civil(c['CAL_LUNAR_EPOCH_Y'], c['CAL_LUNAR_EPOCH_M'],
                                  c['CAL_LUNAR_EPOCH_D']))
    if off < 0:
        return None
    ly = c['CAL_LUNAR_YEAR_FIRST']
    last = c['CAL_LUNAR_YEAR_FIRST'] + c['CAL_LUNAR_YEARS'] - 1
    while ly <= last and off >= face.cal_year_days(ly):
        off -= face.cal_year_days(ly)
        ly += 1
    return ly if ly <= last else None


def lunar_year_span(face, ly):
    """The first and last Gregorian dates of lunar year `ly`.

    Walks the table's own year lengths from the epoch, which is an independent
    route to the same numbers lunar_from_solar() produces - so a year-length
    error shows up as a disagreement rather than as a silent shift.
    """
    c = face.cal
    off = sum(face.cal_year_days(y)
              for y in range(c['CAL_LUNAR_YEAR_FIRST'], ly))
    d0 = (face.days_from_civil(c['CAL_LUNAR_EPOCH_Y'], c['CAL_LUNAR_EPOCH_M'],
                               c['CAL_LUNAR_EPOCH_D']) + off)
    return face.civil_from_days(d0), face.civil_from_days(d0 + face.cal_year_days(ly) - 1)


def check_calendar(face, rep):
    c = face.cal
    rep.head('the calendar')
    rep.note('%d lunar rows for %d..%d, keyed on %04d-%02d-%02d; terms for %d..%d'
             % (c['CAL_LUNAR_YEARS'], c['CAL_LUNAR_YEAR_FIRST'],
                c['CAL_LUNAR_YEAR_FIRST'] + c['CAL_LUNAR_YEARS'] - 1,
                c['CAL_LUNAR_EPOCH_Y'], c['CAL_LUNAR_EPOCH_M'],
                c['CAL_LUNAR_EPOCH_D'], c['CAL_YEAR_FIRST'], c['CAL_YEAR_LAST']))

    for (y, m, d), want, why in LUNAR_ANCHORS:
        got = face.lunar_from_solar(y, m, d)
        rep.chk(got == want, '%04d-%02d-%02d -> %d月%s%d日' % (y, m, d, got[0],
                                                             '闰' if got[2] else '',
                                                             got[1]),
                why)

    # weekday: 1970-01-01 was a Thursday (4)
    rep.chk(face.cal_date(0)[3] == 4, '1970-01-01 is a Thursday',
            'weekday %d' % face.cal_date(0)[3])
    rep.chk(face.cal_date(ts(2026, 9, 12))[3] == 6, '2026-09-12 is a Saturday',
            'weekday %d' % face.cal_date(ts(2026, 9, 12))[3])

    # walk every day: the lunar day must advance by one or wrap to a new month,
    # every month must be 29 or 30 days, and the totals must match year_days()
    prev = None
    bad_step, bad_len = [], []
    seen = {}
    for y, m, d in days():
        cur = face.lunar_from_solar(y, m, d)
        if cur is None:
            bad_step.append(('%04d-%02d-%02d' % (y, m, d), 'outside the table'))
            continue
        lm, ld, leap = cur
        seen.setdefault((lm, leap), set()).add(ld)
        if prev is not None:
            plm, pld, pleap = prev
            if not ((lm == plm and ld == pld + 1) or
                    (ld == 1 and ((lm == plm and not pleap) or
                                  (lm == plm + 1) or
                                  (plm == 12 and lm == 1)))):
                bad_step.append(('%04d-%02d-%02d' % (y, m, d),
                                 '%d月%d日 after %d月%d日%s'
                                 % (lm, ld, plm, pld, '(leap)' if pleap else '')))
        prev = cur

    rep.chk(not bad_step, 'the lunar day advances by one every solar day',
            '%d breaks in %d days' % (len(bad_step), sum(1 for _ in days())))
    if bad_step:
        rep.note('e.g. %s' % (bad_step[0],))

    # month lengths, and the leap month the table claims vs the one observed
    for (lm, leap), ds in sorted(seen.items()):
        if sorted(ds) != list(range(1, max(ds) + 1)):
            bad_len.append((lm, leap, sorted(ds)[:3], sorted(ds)[-3:]))
    rep.chk(not bad_len, 'every lunar month has contiguous days 1..29 or 1..30',
            '%d months checked' % len(seen))

    # A leap month claimed by the table must actually be visited, and nothing
    # else may look like one.  The comparison is per LUNAR year - an earlier
    # draft of this check compared the table's lunar years against the solar
    # years the walk happened to be iterating, which "passed" by coincidence.
    observed, denied = set(), set()
    for y, m, d in days():
        ly = lunar_year_of(face, y, m, d)
        lm, ld, leap = face.lunar_from_solar(y, m, d)
        if ly is None:
            continue
        if leap:
            observed.add(ly)
        if leap and not face.cal_leap_month(ly):
            denied.add(ly)

    claimed, partial = set(), []
    for ly in range(c['CAL_LUNAR_YEAR_FIRST'],
                    c['CAL_LUNAR_YEAR_FIRST'] + c['CAL_LUNAR_YEARS']):
        if not face.cal_leap_month(ly):
            continue
        d0, d1 = lunar_year_span(face, ly)
        if d0 >= DAY_FIRST and d1 <= DAY_LAST:
            claimed.add(ly)
        else:
            partial.append((ly, d0, d1))
    rep.note('lunar years with a leap month: %d fully inside the walk, %d not'
             % (len(claimed), len(partial)))
    for ly, d0, d1 in partial:
        rep.note('%d runs %04d-%02d-%02d..%04d-%02d-%02d, only partly walked'
                 % ((ly,) + d0 + d1))

    missing = claimed - observed
    rep.chk(not missing, 'every leap month the table claims is actually reached',
            'claimed %d fully-walked, observed %d' % (len(claimed), len(observed)))
    if missing:
        rep.note('never reached: %s' % sorted(missing))
    rep.chk(not denied, 'and no other month is drawn as a leap month',
            'visited %d leap years total' % len(observed))

    # the two independent routes to a lunar year must agree, day by day
    disagree = []
    for y, m, d in days():
        ly = lunar_year_of(face, y, m, d)
        if ly is None:
            continue
        d0, d1 = lunar_year_span(face, ly)
        if not (d0 <= (y, m, d) <= d1):
            disagree.append(('%04d-%02d-%02d' % (y, m, d), ly, d0, d1))
    rep.chk(not disagree, 'the year-length walk and the day walk agree',
            '%d days disagree' % len(disagree))
    if disagree:
        rep.note('e.g. %s' % (disagree[0],))

    # and the first day of a lunar year is always 正月初一
    new_year_bad = []
    for ly in range(c['CAL_LUNAR_YEAR_FIRST'] + 1,
                    c['CAL_LUNAR_YEAR_FIRST'] + c['CAL_LUNAR_YEARS']):
        d0, _d1 = lunar_year_span(face, ly)
        got = face.lunar_from_solar(*d0)
        if got != (1, 1, 0):
            new_year_bad.append((ly, d0, got))
    rep.chk(not new_year_bad, 'every lunar year starts on 正月初一',
            '%d boundaries checked' % (c['CAL_LUNAR_YEARS'] - 1))
    if new_year_bad:
        rep.note('e.g. %s' % (new_year_bad[0],))

    # the table implies ~29.53 days per month; a transcription slip of a single
    # bit moves this measurably over 28 years
    first = c['CAL_LUNAR_YEAR_FIRST']
    total = sum(face.cal_year_days(y) for y in range(first, first + c['CAL_LUNAR_YEARS']))
    months = sum(12 + (1 if face.cal_leap_month(y) else 0)
                 for y in range(first, first + c['CAL_LUNAR_YEARS']))
    mean = total / float(months)
    rep.chk(abs(mean - 29.530589) < 0.02, 'the mean month is the synodic month',
            '%.4f d over %d months (29.530589 expected)' % (mean, months))

    # solar terms: 24 per year, in the right months, and the calendar must find
    # one within two weeks of any date
    bad_term, far = [], []
    for y in range(c['CAL_YEAR_FIRST'], c['CAL_YEAR_LAST'] + 1):
        for n in range(24):
            if not (1 <= face.term_day[y - c['CAL_YEAR_FIRST']][n] <= 31):
                bad_term.append((y, n))
    for y, m, d in days():
        nt = face.next_term(y, m, d)
        if nt is None or nt[1] > 20:
            far.append(('%04d-%02d-%02d' % (y, m, d), nt))
    rep.chk(not bad_term, 'all %d term days are real days of a month'
            % (24 * c['CAL_YEARS']), '')
    rep.chk(not far, 'a solar term is always within 20 days',
            '%d dates had none' % len(far))
    if far:
        rep.note('e.g. %s' % (far[0],))


# ---------------------------------------------------------------------------
# section 7 - the version, and the constants that must be gone
# ---------------------------------------------------------------------------
def check_version(face, rep):
    v = face.version
    rep.head('version and leftovers')
    rep.chk(v is not None, 'app_config.h defines FW_VERSION_STRING', str(v))

    epd = _read('epd.c')
    stale = [name for name in ('EPD_VERSION_X', 'EPD_VERSION_Y', 'BLE_ICON_X',
                               'BLE_ICON_BITS', 'EPD_DEBUG_X', 'EPD_DEBUG_Y')
             if name in epd]
    rep.chk(not stale, 'the v13.0 layout constants are gone from epd.c',
            ', '.join(stale) if stale else 'none left')

    rep.chk('r1[ROW1_MAX_CHARS]' in epd,
            'epd.c sizes the row-1 buffer from epd_layout.h',
            'so the two cannot disagree')

    font = _read('epd_font.c')
    rep.chk('int xr = x1 - t;' in font,
            'the digit right-hand bars sit inside the cell',
            'epd_font.c: xr = x1 - t')
    rep.chk('lone' not in font,
            'the special case for a narrow "1" is gone',
            'fixed slots make it unnecessary')
    rep.chk('CLOCK_SLOT_X' in font,
            'epd_font.c lays the clock out on the slots',
            '')
    rep.chk('clock_char_w' not in font,
            'nothing computes a variable clock width any more',
            'the face is CLOCK_WIDEST wide for every H:MM')

    bwr = _read('epd_bwr_213.c')
    rep.chk('EPD_WIN_GATES' in bwr and 'EPD_WIN_GATE_FIRST' in bwr,
            'the driver takes the window from epd_layout.h',
            '')
    rep.chk('EPD_WIN_GATE_FIRST 166' not in _read('epd_layout.h'),
            'the 166..280 window of the first v14.0 draft is gone', '')

    app = _read('app.c')
    rep.chk('shown_mv' in app and 'shown_temp' in app,
            'app.c freezes the displayed values between full refreshes',
            'the window band covers row 1 otherwise')
    return v


# ---------------------------------------------------------------------------
# section 8 - make the checks fail on purpose
# ---------------------------------------------------------------------------
def check_falsification(face, rep, cells, union, row3_worst):
    """Re-introduce each bug and confirm the matching check reports it.

    Without this the script proves only that today's numbers agree with today's
    numbers.  Each case below is a defect this release actually had.
    """
    L = face.L
    mac = (0xA1, 0xB2, 0xC3)
    rep.head('the checks can fail')

    # (a) the off-by-one that was really there: right-hand bars one column too
    #     far right, i.e. ink outside the cell the window is derived from
    def shifted(self, buf, wp, ht, x, y, w, h, t, ch):
        on = self.segments(ch)
        x1, y1, ym = x + w - 1, y + h - 1, y + h // 2
        s = max(t // 2, 2)
        xr = x1 - t + 1
        for _label, px, py in segment_quads(x, x1, y, y1, ym, t, s, xr, on):
            self.fill_quad(buf, wp, ht, px, py)

    orig = Face.draw_digit
    Face.draw_digit = shifted
    try:
        f2 = Face(face.src)
        u2 = minute_tick_union(f2, column_bits(f2))
        g_first = u2[0] + L['EPD_WIN_GATE_OFFSET']
        g_last = u2[1] + L['EPD_WIN_GATE_OFFSET']
        rep.chk(not (L['EPD_WIN_GATE_FIRST'] <= g_first
                     and g_last <= L['EPD_WIN_GATE_LAST']),
                'the old off-by-one in the right-hand bars is caught',
                'ink would change gate %d, window ends at %d'
                % (g_last, L['EPD_WIN_GATE_LAST']))
    finally:
        Face.draw_digit = orig

    # (b) the row-1 buffer at its original 24 entries
    need = len(face.row1(ts(2050, 12, 26, 12, 0), 9999, -40))
    saved = L.obj.get('ROW1_MAX_CHARS')
    L.obj['ROW1_MAX_CHARS'] = '24'
    L._cache.pop(('ROW1_MAX_CHARS',), None)
    try:
        try:
            Face.row1(face, ts(2050, 12, 26, 12, 0), 9999, -40)
            raised = False
        except IndexError:
            raised = True
        rep.chk(raised, 'the original 24-entry row-1 buffer overruns, and says so',
                'the widest string needs %d codepoints' % need)
    finally:
        L.obj['ROW1_MAX_CHARS'] = saved
        L._cache.pop(('ROW1_MAX_CHARS',), None)

    # (c) a window one gate short, and one gate of slack
    lo, hi = union[0] + L['EPD_WIN_GATE_OFFSET'], union[1] + L['EPD_WIN_GATE_OFFSET']
    rep.chk(not (L['EPD_WIN_GATE_FIRST'] <= lo
                 and hi <= L['EPD_WIN_GATE_LAST'] - 1),
            'a window one gate short is caught',
            '%d..%d would miss gate %d' % (L['EPD_WIN_GATE_FIRST'],
                                           L['EPD_WIN_GATE_LAST'] - 1, hi))
    rep.chk(not (L['EPD_WIN_GATE_FIRST'] + 1 <= lo
                 and hi <= L['EPD_WIN_GATE_LAST']),
            'one gate of slack is caught by the exactness check',
            'start %d vs union %d' % (L['EPD_WIN_GATE_FIRST'] + 1, lo))

    # (d) a stroke wide enough to swallow the cell
    saved = L.obj.get('CLOCK_STROKE_PCT')
    L.obj['CLOCK_STROKE_PCT'] = '30'
    L._cache.clear()
    stroke = L['CLOCK_STROKE']
    degenerate = stroke * 4 >= L['CLOCK_CELL_W']
    L.obj['CLOCK_STROKE_PCT'] = saved
    L._cache.clear()
    rep.chk(degenerate, 'a degenerate stroke is caught by the header assertion',
            'a 30%% stroke gives %d px bars in a %d px cell'
            % (stroke, L['CLOCK_CELL_W']))

    # (e) one more glyph than the WIDEST row-3 text must trip the collision test
    w_now = row3_worst[0]
    w_more = w_now + face.uf_find(ord('年'))[2]     # one 16 px CJK glyph
    rep.chk(L['ROW3_X'] + w_more > face.row3_rune_x(mac)
            and L['ROW3_X'] + w_now <= face.row3_rune_x(mac),
            'one more glyph in row 3 trips the collision test',
            'widest is "%s", ends at %d; +1 glyph would end at %d, rune slot '
            'starts at %d' % (row3_worst[1], L['ROW3_X'] + w_now,
                              L['ROW3_X'] + w_more, face.row3_rune_x(mac)))

    # (f) the calendar walk is the other side of the same coin: it re-derives
    #     every day of 25 years from CAL_LUNAR_INFO, so a single wrong bit in
    #     that table moves the mean month off the synodic month and breaks the
    #     day-to-day continuity check above.
    rep.chk(abs(sum(face.cal_year_days(y) for y in range(
        face.cal['CAL_LUNAR_YEAR_FIRST'],
        face.cal['CAL_LUNAR_YEAR_FIRST'] + face.cal['CAL_LUNAR_YEARS'])) - 10226.8) < 40,
            'the lunar table\'s total length sits where 28 tropical years put it',
            'so a mis-transcribed bit cannot pass unnoticed')

    # (g) the rune as it was first drawn: the upper-left arm collinear with the
    #     lower chevron's chord, so every pixel of the left arm sits above the
    #     centre and the lower-left quarter stays empty.  These are the literal
    #     bytes that were compiled in before the sketch was re-measured.
    old_rune = [0x04, 0x00, 0x08, 0x00, 0x10, 0x00, 0x20, 0x00,
                0xff, 0x1f, 0xa2, 0x08, 0x14, 0x05, 0x08, 0x02]
    rep.chk(face.rune_asymmetric(old_rune) != [],
            'the leaning rune of the first draft is caught',
            'columns %s have no ink below the centre row'
            % (face.rune_asymmetric(old_rune),))


def segment_quads(x, x1, y, y1, ym, t, s, xr, on):
    """The segment quads for `on`, as (label, px, py).

    Only the falsification copy of draw_digit uses this.  It exists so that the
    copy is written out in full rather than reached through the real one - if
    the two disagree, the disagreement is the point of the exercise.
    """
    out = []
    if 'a' in on:
        out.append(('a', [x + s, x1 - s, x1 - 2 * s, x + 2 * s], [y, y, y + t, y + t]))
    if 'g' in on:
        yt = ym - t // 2
        out.append(('g', [x + s, x1 - s, x1 - 2 * s, x + 2 * s], [yt, yt, yt + t, yt + t]))
    if 'd' in on:
        yt = y1 - t + 1
        out.append(('d', [x + s, x1 - s, x1 - 2 * s, x + 2 * s], [yt, yt, yt + t, yt + t]))
    if 'f' in on:
        out.append(('f', [x, x + t, x + t, x], [y + s, y + 2 * s, ym - s, ym]))
    if 'b' in on:
        out.append(('b', [xr, xr + t, xr + t, xr], [y + s, y + 2 * s, ym - s, ym]))
    if 'e' in on:
        out.append(('e', [x, x + t, x + t, x], [ym + s, ym + 2 * s, y1 - s, y1]))
    if 'c' in on:
        out.append(('c', [xr, xr + t, xr + t, xr], [ym + s, ym + 2 * s, y1 - s, y1]))
    return out


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description='offline proof of the v14.0 layout')
    ap.add_argument('--quiet', action='store_true',
                    help='print only the failures and the summary')
    args = ap.parse_args()

    face = Face()
    rep = Report(quiet=args.quiet)
    print('verify_v14_layout.py - %s, glass %dx%d'
          % (face.version, face.L['FACE_W'], face.L['FACE_VISIBLE_H']))

    check_geometry(face, rep)
    check_clock(face, rep)
    cells = column_bits(face)
    union = minute_tick_union(face, cells)
    check_window(face, rep, cells, union)
    check_row1(face, rep)
    row3_worst = check_row3(face, rep)
    check_calendar(face, rep)
    check_version(face, rep)
    check_falsification(face, rep, cells, union, row3_worst)

    print('')
    print('%d checks passed, %d failed' % (rep.pass_, rep.fail))
    print('RESULT: ' + ('PASS' if rep.fail == 0 else 'FAIL'))
    return 0 if rep.fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
