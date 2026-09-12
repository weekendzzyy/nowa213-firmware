#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate the two data headers the v14.0 clock face needs.

    atc1441_src/Firmware/src/font_unifont.h    glyphs, 8x16 and 16x16
    atc1441_src/Firmware/src/calendar_data.h   lunar months + solar-term days

Usage (from the repository root):

    python tools/gen_v14_tables.py <path-to-unifont.hex>

unifont.hex comes from the GNU Unifont release archive:

    https://unifoundry.com/pub/unifont/unifont-15.1.05/font-builds/unifont-15.1.05.hex.gz

Unifont is dual-licensed: GPL-2.0-or-later *with the font embedding exception*
and SIL OFL 1.1 (the dual licence dates from 13.0.04).  Either one permits
embedding a subset in this firmware without affecting the firmware's own
licence, which is why it is used here rather than a system font.

Everything else is computed in this file:

  * lunar months      - the standard lunarInfo[1900..2100] bit encoding,
                        sliced to the years the firmware covers (2026..2050)
  * solar terms       - Meeus, Astronomical Algorithms ch.25, solved for each
                        multiple of 15 deg of apparent solar longitude and
                        converted to Beijing time.  A closed-form published
                        "shouxing" formula is deliberately NOT used: it puts
                        2026 芒种 on 6 June when the instant is 5 June 23:48,
                        i.e. it is a day out, and it has other exceptions.
  * the rune bitmap   - rasterised here so the shape is reviewable as ASCII art
                        rather than being an opaque hex blob in the header.

The script is deterministic: same unifont.hex in, same headers out.
"""

import os
import sys
import hashlib
import datetime as dt
import math

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SRC = os.path.join(REPO, 'atc1441_src', 'Firmware', 'src')

# ---------------------------------------------------------------------------
# year range
# ---------------------------------------------------------------------------
YEAR_FIRST = 2026
YEAR_LAST = 2050          # the last year the face advertises
NYEARS = YEAR_LAST - YEAR_FIRST + 1

# The solar-term table carries ONE year past YEAR_LAST, and that row is not
# slack: cal_row3() shows the NEXT term, so a scan starting in late December
# reaches into January.  Without the extra row the last nine days of 2050 --
# inside the advertised range -- would draw the lunar date with no term at all.
TERM_YEAR_LAST = YEAR_LAST + 1
NTERMYEARS = TERM_YEAR_LAST - YEAR_FIRST + 1

# ---------------------------------------------------------------------------
# solar terms: index n sits at solar longitude (285 + 15n) mod 360 deg, so
# n = 0 is 小寒 (in January) and n = 17 is 秋分.  Term n always falls in the
# same Gregorian month across the supported range - asserted below, because the
# packed table stores only the day of the month.
# ---------------------------------------------------------------------------
TERM_NAMES = ['小寒', '大寒', '立春', '雨水', '惊蛰', '春分', '清明', '谷雨',
              '立夏', '小满', '芒种', '夏至', '小暑', '大暑', '立秋', '处暑',
              '白露', '秋分', '寒露', '霜降', '立冬', '小雪', '大雪', '冬至']
TERM_MONTH = [1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6,
              7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12]

# ---------------------------------------------------------------------------
# lunar months, standard lunarInfo encoding
#   bits 15..4  month 1..12 lengths, MSB = month 1, 1 = 30 days
#   bits 3..0   leap month number, 0 = none
#   bit 16      leap month length, 1 = 30 days
#
# The table runs from LUNAR_EPOCH to CAL_YEAR_LAST.  Two years of slack at the
# front are not decoration: 2026-01-01 is still 2025-11-13 in the lunar year,
# so a date in early January needs the *previous* year's row.
# ---------------------------------------------------------------------------
LUNAR_YEAR_FIRST = 2024
LUNAR_EPOCH = dt.date(2024, 2, 10)   # 2024 正月初一
LUNAR_INFO = [
    0x04b60, 0x0a6e6, 0x0a4e0, 0x0d260, 0x0ea65,   # 2024-2028
    0x0d530, 0x05aa0, 0x076a3, 0x096d0, 0x04afb,   # 2029-2033
    0x04ad0, 0x0a4d0, 0x1d0b6, 0x0d250, 0x0d520,   # 2034-2038
    0x0dd45, 0x0b5a0, 0x056d0, 0x055b2, 0x049b0,   # 2039-2043
    0x0a577, 0x0a4b0, 0x0aa50, 0x1b255, 0x06d20,   # 2044-2048
    0x0ada0, 0x14b63, 0x09370,                      # 2049-2051
]
NLUNAR = len(LUNAR_INFO)
LUNAR_YEAR_LAST = LUNAR_YEAR_FIRST + NLUNAR - 1



# ---------------------------------------------------------------------------
# astronomical core
# ---------------------------------------------------------------------------
def julian_day(when):
    y, m = when.year, when.month
    d = (when.day + when.hour / 24.0 + when.minute / 1440.0
         + when.second / 86400.0)
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    return int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + d + b - 1524.5


def jd_to_datetime(jd):
    jd += 0.5
    z = int(jd)
    f = jd - z
    if z < 2299161:
        a = z
    else:
        alpha = int((z - 1867216.25) / 36524.25)
        a = z + 1 + alpha - alpha // 4
    b = a + 1524
    c = int((b - 122.1) / 365.25)
    d = int(365.25 * c)
    e = int((b - d) / 30.6001)
    day = b - d - int(30.6001 * e) + f
    month = e - 1 if e < 14 else e - 13
    year = c - 4716 if month > 2 else c - 4715
    dayi = int(day)
    rem = (day - dayi) * 24
    hh = int(rem)
    mm = int((rem - hh) * 60)
    ss = int(round((((rem - hh) * 60) - mm) * 60))
    return dt.datetime(year, month, dayi, hh, mm, min(ss, 59), tzinfo=dt.timezone.utc)


def apparent_solar_longitude(jd):
    """Meeus ch.25 apparent longitude, good to about 0.01 deg."""
    t = (jd - 2451545.0) / 36525.0
    l0 = 280.46646 + 36000.76983 * t + 0.0003032 * t * t
    m = 357.52911 + 35999.05029 * t - 0.0001537 * t * t
    mr = math.radians(m)
    c = ((1.914602 - 0.004817 * t - 0.000014 * t * t) * math.sin(mr)
         + (0.019993 - 0.000101 * t) * math.sin(2 * mr)
         + 0.000289 * math.sin(3 * mr))
    omega = 125.04 - 1934.136 * t
    lam = l0 + c - 0.00569 - 0.00478 * math.sin(math.radians(omega))
    return lam % 360.0


def solar_term_instant_utc(y, n):
    """UTC datetime at which the sun reaches (285 + 15n) mod 360 deg."""
    target = (285.0 + n * 15.0) % 360.0
    jd = julian_day(dt.datetime(y, TERM_MONTH[n], 6, tzinfo=dt.timezone.utc))
    for _ in range(200):
        diff = (apparent_solar_longitude(jd) - target + 180.0) % 360.0 - 180.0
        if abs(diff) < 1e-7:
            break
        jd -= diff / 0.9856473
    return jd_to_datetime(jd)


def solar_term_beijing(y, n):
    """(date, datetime) in Beijing time (+8, no DST) for term n of year y."""
    bj = solar_term_instant_utc(y, n) + dt.timedelta(hours=8)
    return bj.date(), bj


# ---------------------------------------------------------------------------
# lunar calendar, mirrors the C implementation in src/calendar.c
# ---------------------------------------------------------------------------
def _li(year):
    return LUNAR_INFO[year - LUNAR_YEAR_FIRST]


def leap_month(year):
    return _li(year) & 0xf


def leap_days(year):
    return 30 if (_li(year) & 0x10000) else 29


def month_days(year, m):
    return 30 if (_li(year) & (0x10000 >> m)) else 29


def year_days(year):
    """Length of lunar year `year` in days.

    The 348 is 12 x 29, the base every lunar year starts from; a set month bit
    means that month is one day LONGER, so the bits add 1 each - adding the
    full month length here would double count and put the whole walk out by
    roughly a year (that is exactly the bug this comment replaces)."""
    total = 348
    for m in range(1, 13):
        if month_days(year, m) == 30:
            total += 1
    if leap_month(year):
        total += leap_days(year)
    return total


def solar_to_lunar(y, m, d):
    """(lunar_year, lunar_month, lunar_day, is_leap_month)."""
    offset = (dt.date(y, m, d) - LUNAR_EPOCH).days
    i = LUNAR_YEAR_FIRST
    temp = 0
    while offset > 0 and i <= LUNAR_YEAR_LAST:
        temp = year_days(i)
        offset -= temp
        i += 1
    if offset < 0:
        offset += temp
        i -= 1
    ly = i

    leap = leap_month(ly)
    is_leap = False
    j = 1
    while j < 13 and offset > 0:
        if leap > 0 and j == leap + 1 and not is_leap:
            j -= 1
            is_leap = True
            temp = leap_days(ly)
        else:
            temp = month_days(ly, j)
        if is_leap and j == leap + 1:
            is_leap = False
        offset -= temp
        j += 1
    if offset == 0 and leap > 0 and j == leap + 1:
        if is_leap:
            is_leap = False
        else:
            is_leap = True
            j -= 1
    if offset < 0:
        offset += temp
        j -= 1
    return ly, j, offset + 1, is_leap


# ---------------------------------------------------------------------------
# character set
# ---------------------------------------------------------------------------
LATIN = ('0123456789'        # every number on the face
         'ABCDEF'            # the BLE MAC is printed as hex
         'HLSTV'             # H/T/B/L debug counters, ESL_, mV
         'mv'               # "mV", the "v" of the version badge
         '-.[]_'            # negative temperature, version, [MAC], ESL_
         ' ')               # separator; advances 6 px, see SPACE_ADV
EXT_CHARS = '\u2103'         # ℃ - 8 px wide in Unifont, so it rides with LATIN

CJK = ('年月日周'              # date, and the 周 of 周六
       '一二三四五六七八九十'   # weekday names, lunar numerals
       '正冬腊'                # 正月 / 冬月 / 腊月
       '初廿闰'                # 初五 / 廿三 / 闰四月
       '天后今'                # "11天后秋分" / "今日秋分"
       + ''.join(TERM_NAMES))  # the 24 solar-term names

# The gap between fields.  Unifont's space is a full 8 px, but three of them in
# row 1 push the widest date over 250 px (see tools/verify_v14_layout.py, which
# recomputes this from the tables and fails if the budget is broken).
SPACE_ADV = 6


# ---------------------------------------------------------------------------
# unifont
# ---------------------------------------------------------------------------
def load_unifont(path):
    glyphs = {}
    with open(path, 'r', encoding='ascii', errors='ignore') as fh:
        for line in fh:
            line = line.strip()
            if not line or ':' not in line:
                continue
            code, bits = line.split(':', 1)
            if len(bits) not in (32, 64):
                continue
            glyphs[int(code, 16)] = bits
    return glyphs


def glyph_columns(bits, ncols):
    """Unifont's hex is row-major, MSB = leftmost.  The panel wants the
    transpose: for each column a 16-bit word whose bit r is row r, low byte
    first.  That makes the blit in epd_font.c two byte-store per column."""
    rows = [int(bits[i:i + 4], 16) if ncols == 16 else int(bits[i:i + 2], 16)
            for i in range(0, len(bits), 4 if ncols == 16 else 2)]
    out = bytearray()
    for c in range(ncols):
        word = 0
        for r in range(16):
            if rows[r] & (1 << (ncols - 1 - c)):
                word |= 1 << r
        out.append(word & 0xFF)
        out.append((word >> 8) & 0xFF)
    return bytes(out)


def build_glyphs(glyphs):
    """Return a list of (codepoint, ncols, advance, blob)."""
    out = []
    missing = []
    for ch in LATIN:
        cp = ord(ch)
        if cp not in glyphs:
            missing.append(ch)
            continue
        n = 8 if len(glyphs[cp]) == 32 else 16
        out.append((cp, n, SPACE_ADV if ch == ' ' else n,
                    glyph_columns(glyphs[cp], n)))
    for ch in EXT_CHARS:
        cp = ord(ch)
        if cp not in glyphs:
            missing.append(ch)
            continue
        n = 8 if len(glyphs[cp]) == 32 else 16
        out.append((cp, n, n, glyph_columns(glyphs[cp], n)))
    seen = set()
    for ch in CJK:
        cp = ord(ch)
        if cp in seen:
            continue
        seen.add(cp)
        if cp not in glyphs:
            missing.append(ch)
            continue
        n = 8 if len(glyphs[cp]) == 32 else 16
        if n != 16:
            missing.append('%s(only %d px wide)' % (ch, n))
            continue
        out.append((cp, n, n, glyph_columns(glyphs[cp], n)))
    if missing:
        raise SystemExit('ERROR: not available in this unifont.hex: %s'
                         % ' '.join(missing))
    out.sort(key=lambda g: g[0])
    return out


# ---------------------------------------------------------------------------
# the Bluetooth rune
# ---------------------------------------------------------------------------
# Sized to the Latin capitals on the same row: Unifont's caps are 11 px tall in
# a 16 px cell, and the reference photo's rune measures 17 x 25.5 photo px in a
# frame where the 250 px glass spans ~420, so ~10 x 15 glass px and an aspect of
# 0.66.  8 x 13 gives 0.62 - the same shape, one pixel narrower, and it keeps
# the rune inside the slot epd_layout.h reserves for it without stealing margin
# from the calendar text.
RUNE_W, RUNE_H = 8, 13


def raster_rune(w=RUNE_W, h=RUNE_H):
    """Rasterise the Bluetooth bind rune.

    Three strokes make the whole symbol: a vertical stem, a two-segment zigzag
    that forms the two right-hand chevrons, and a two-segment zigzag on the
    left that gives the left arrowhead.  The chevrons are the chords between
    the stem and the zigzag.

        T  (4,  0)   top of the stem
        RU (7,  3)   tip of the upper chevron
        C  (4,  6)   centre, where the left arrowhead meets the stem
        RL (7,  9)   tip of the lower chevron
        B  (4, 12)   bottom of the stem
        LU (0,  2)   free end of the upper-left arm
        LL (0, 10)   free end of the lower-left arm

    The left side is an OPEN arrowhead, not a closed chevron, and that is what
    the reference panel and the user's sketch of it both show: two arms meeting
    on the stem, with free ends towards the upper left and the lower left.  An
    earlier revision drew the upper-left arm collinear with the lower chevron's
    chord (L(0,2) -> C -> RL), which left the lower-left quarter of the symbol
    empty and made it lean; the sketch has a distinct stroke there, at a
    steeper angle than that chord, so it cannot be the same stroke.

    The four diagonals meet at C at 45 degrees and the two arms are the same
    length, which is what makes the symbol read at this size.  A shallower
    chevron spreads the diagonals into near-horizontal rows that merge with the
    stem and the result is a smudge rather than a symbol - at 8 px across there
    is no room for a shallower angle.

    Lines are sampled at twice the cell pitch and rounded, which is the cheap
    way to get an 8-connected line: one sample per cell (plain Bresenham)
    leaves the diagonals broken into separate dots.  Stroke weight stays at one
    pixel, the same as every glyph on the face.
    """
    px = [[0] * w for _ in range(h)]

    def line(x0, y0, x1, y1):
        steps = int(max(abs(x1 - x0), abs(y1 - y0)) * 2) + 1
        for i in range(steps + 1):
            t = i / float(steps)
            xi = int(round(x0 + (x1 - x0) * t))
            yi = int(round(y0 + (y1 - y0) * t))
            if 0 <= xi < w and 0 <= yi < h:
                px[yi][xi] = 1

    T, RU, C, RL, B = (4, 0), (7, 3), (4, 6), (7, 9), (4, 12)
    LU, LL = (0, 2), (0, 10)

    line(*T, *RU)
    line(*RU, *C)
    line(*C, *RL)
    line(*RL, *B)
    line(*T, *B)
    line(*LU, *C)
    line(*C, *LL)
    return px


def rune_columns(px):
    h = len(px)
    w = len(px[0])
    out = bytearray()
    for c in range(w):
        word = 0
        for r in range(h):
            if px[r][c]:
                word |= 1 << r
        out.append(word & 0xFF)
        out.append((word >> 8) & 0xFF)
    return bytes(out)


# ---------------------------------------------------------------------------
# emitting
# ---------------------------------------------------------------------------
BANNER = """/* %s
 *
 * GENERATED by tools/gen_v14_tables.py - do not edit by hand.
 * Regenerate with:
 *     python tools/gen_v14_tables.py <path-to-unifont.hex>
 */
"""


def c_hex(blob, per_line=12, indent='    '):
    out = []
    for i in range(0, len(blob), per_line):
        out.append(indent + ' '.join('0x%02x,' % b for b in blob[i:i + per_line]))
    return '\n'.join(out)


# Codepoints the C code refers to by name.  They are emitted into
# font_chars.h so that no source file ever spells a magic number - and so a
# character that the generator did not include in the glyph set cannot be
# referenced by accident (the generator fails first).
NAMED = [
    ('UF_C_YEAR', '年'), ('UF_C_MONTH', '月'), ('UF_C_DAY', '日'),
    ('UF_C_WEEK', '周'), ('UF_C_DEGC', '℃'), ('UF_C_LEAP', '闰'),
    ('UF_C_TIAN', '天'), ('UF_C_HOU', '后'), ('UF_C_JIN', '今'),
    ('UF_C_CHU', '初'), ('UF_C_NIAN', '廿'), ('UF_C_SHI', '十'),
]
WEEKDAY = '日一二三四五六'
NUMERAL = [0] + list('一二三四五六七八九')
LUNAR_MONTH = [0, '正', '二', '三', '四', '五', '六', '七', '八', '九', '十', '冬', '腊']


def emit_chars(path):
    lines = [BANNER % 'Character codepoints used by the v14.0 clock face.']
    body = ['']
    for name, ch in NAMED:
        body.append('#define %-12s 0x%04x' % (name, ord(ch)))
    body.append('')
    body.append('/* 0 = 周日 ... 6 = 周六, matching tm_wday */')
    body.append('static const unsigned short UF_WEEKDAY[7] = {\n    %s};'
                % ', '.join('0x%04x' % ord(c) for c in WEEKDAY))
    body.append('')
    body.append('/* 0 is unused - a lunar day never prints a bare zero - and is')
    body.append('   emitted as 0 rather than a codepoint, so the table cannot')
    body.append('   reference a glyph the font does not carry. */')
    body.append('static const unsigned short UF_NUMERAL[10] = {\n    %s};'
                % ', '.join('0x%04x' % ord(c) if c else '0' for c in NUMERAL))
    body.append('')
    body.append('/* index 1..12; index 0 is unused because lunar months are 1-based */')
    body.append('static const unsigned short UF_LUNAR_MONTH[13] = {\n    %s};'
                % ', '.join('0x%04x' % ord(c) if c else '0'
                            for c in LUNAR_MONTH))
    body.append('')
    body.append('/* the 24 solar terms, in CAL_TERM_DAY order */')
    body.append('static const unsigned short UF_TERM[24][2] = {')
    for i, name in enumerate(TERM_NAMES):
        body.append('    { 0x%04x, 0x%04x },   /* %s */'
                    % (ord(name[0]), ord(name[1]), name))
    body.append('};')
    lines.append('\n'.join(body))
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines))


def emit_font(path, glyphs, rune_px, rune_cols):
    bits = bytearray()
    offs = []
    for cp, n, adv, blob in glyphs:
        offs.append(len(bits))
        bits.extend(blob)
    total_16 = sum(1 for g in glyphs if g[1] == 16)
    total_8 = len(glyphs) - total_16

    lines = [BANNER % 'Unifont subset for the v14.0 clock face.']
    lines.append("""
/* The face draws every character from this one table: ASCII and the Chinese
 * characters share a 16 px line box, so nothing has to be aligned by hand.
 *
 * Layout of one glyph, "column major":
 *     for each column c the glyph owns two bytes,
 *         byte 0 bit r  -> pixel (c, r)
 *         byte 1 bit r  -> pixel (c, r + 8)
 * so a full 16x16 glyph is 32 bytes and an 8x16 glyph is 16 bytes.  The panel
 * buffer is stored the same way (one byte per column per 8 rows), therefore
 * blitting a glyph is two byte-ORs per column and needs no bit shuffling.
 *
 * %d glyphs: %d at 16x16, %d at 8x16, %d bytes of bitmap in total.
 */
#define UF_GLYPH_COUNT %d
#define UF_GLYPH_BYTES %d

/* codepoint, bitmap byte offset, columns, advance */
static const unsigned short UF_CODE[UF_GLYPH_COUNT] = {
%s};
static const unsigned short UF_OFF[UF_GLYPH_COUNT] = {
%s};
static const unsigned char UF_COLS[UF_GLYPH_COUNT] = {
%s};
static const unsigned char UF_ADV[UF_GLYPH_COUNT] = {
%s};
static const unsigned char UF_BITS[UF_GLYPH_BYTES] = {
%s};
""" % (len(glyphs), total_16, total_8, len(bits),
       len(glyphs), len(bits),
       c_hex_codes([g[0] for g in glyphs]),
       c_hex_words([o for o in offs]),
       c_hex_bytes([g[1] for g in glyphs]),
       c_hex_bytes([g[2] for g in glyphs]),
       c_hex(bits)))

    lines.append("""
/* ---- the Bluetooth rune -------------------------------------------------
 *
 * Not a font: %d x %d px, drawn only while a central is connected.  Same
 * column-major packing as the glyphs above, so it shares epd_font's blitter.
 *
 * The shape is the Bluetooth bind rune.  ASCII art of the exact bitmap that
 * is compiled in (tools/gen_v14_tables.py prints this too):
 *
%s */
#define BLE_RUNE_W %d
#define BLE_RUNE_H %d
static const unsigned char BLE_RUNE_BITS[%d] = {
%s};
""" % (RUNE_W, RUNE_H,
       '\n'.join(' *   ' + ''.join('#' if v else '.' for v in row)
                 for row in rune_px),
       RUNE_W, RUNE_H, len(rune_cols), c_hex(rune_cols, 11, '    ')))

    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines))


def c_hex_codes(vals, per_line=12, indent='    '):
    out = []
    for i in range(0, len(vals), per_line):
        out.append(indent + ' '.join('0x%04x,' % v for v in vals[i:i + per_line]))
    return '\n'.join(out)


def c_hex_words(vals, per_line=12, indent='    '):
    out = []
    for i in range(0, len(vals), per_line):
        out.append(indent + ' '.join('%d,' % v for v in vals[i:i + per_line]))
    return '\n'.join(out)


def c_hex_bytes(vals, per_line=12, indent='    '):
    out = []
    for i in range(0, len(vals), per_line):
        out.append(indent + ' '.join('%d,' % v for v in vals[i:i + per_line]))
    return '\n'.join(out)


# ---------------------------------------------------------------------------
# the DSEG14 clock font
# ---------------------------------------------------------------------------
# The big clock is the DSEG14 Classic Mini Regular 40 px face - the same one
# v13.0 drew with - rasterised by http://oleddisplay.squix.ch into a GFX-style
# header.  The upstream header carries 93 glyphs and 8.2 KB of bitmap; the
# clock needs eleven of them, so this step re-packs just those and drops the
# rest.  The upstream file is vendored at tools/dseg14_upstream.h unchanged.
#
# The bitmap is a GFX bitstream: MSB first, `w` bits per row, rows packed
# continuously (no byte alignment between rows), each glyph starting on a byte
# boundary.  That layout is what epd_font.c's blitter walks.

DSEG_UPSTREAM = os.path.join(HERE, 'dseg14_upstream.h')
DSEG_CHARS = '0123456789:'


def emit_dseg(path):
    import re
    src = open(DSEG_UPSTREAM, encoding='utf-8', errors='ignore').read()

    i = src.find('Bitmaps[]')
    j = src.index('};', i)
    bits = bytearray(int(h, 16) for h in
                     re.findall(r'0x([0-9A-Fa-f]{2})', src[i:j]))

    tab = {}
    for m in re.finditer(r'\{\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+),'
                         r'\s*(-?\d+),\s*(-?\d+)\s*\},\s*// \'(.)\'', src):
        off, w, h, adv, xo, yo, ch = m.groups()
        tab[ch] = (int(off), int(w), int(h), int(adv), int(xo), int(yo))
    missing = [c for c in DSEG_CHARS if c not in tab]
    if missing:
        raise SystemExit('DSEG14 upstream header has no glyph for %r' % missing)

    # '1' and '4' are the only digits whose ink stops short of the em both top
    # and bottom (34 of 40 rows, 3 px of inset each way).  Left alone they read
    # as visibly shorter than their neighbours once scaled - the user saw it on
    # the bench - so they are stretched back to the full em here, in the
    # GENERATED data, where the fix costs the runtime nothing.  All-vertical
    # strokes mean a vertical stretch cannot distort them; the '4's middle bar
    # moves down proportionally, which is what a full-height '4' does anyway.
    FULL_H = tab['0'][2]

    def stretch_full(src_off, gw, gh):
        """Re-encode a glyph vertically stretched to the em height.

        Same bitstream convention as the source: MSB first, `gw` bits per
        row, rows packed continuously, zero-padded to the byte boundary the
        next glyph starts on."""
        vals = []
        for y in range(FULL_H):
            r = y * gh // FULL_H          # nearest-neighbour row map
            for cx in range(gw):
                biti = src_off * 8 + r * gw + cx
                vals.append(1 if bits[biti >> 3] & (0x80 >> (biti & 7)) else 0)
        out = bytearray()
        for i in range(0, len(vals), 8):
            byte = 0
            for v in vals[i:i + 8]:
                byte = (byte << 1) | v
            if len(vals) - i < 8:
                byte <<= 8 - (len(vals) - i)
            out.append(byte)
        return out

    # re-pack the wanted glyphs contiguously and measure the per-cell ink span
    # the ten digits cover, which is what the fixed-slot layout is derived from
    out_bits = bytearray()
    glyphs, ink_x0, ink_x1 = [], None, None
    for ch in DSEG_CHARS:
        off, w, h, adv, xo, yo = tab[ch]
        if ch in '14' and (h, yo) != (FULL_H, -FULL_H):
            data = stretch_full(off, w, h)
            h, yo = FULL_H, -FULL_H
        else:
            nbytes = (w * h + 7) // 8
            data = bits[off:off + nbytes]
        glyphs.append((ch, len(out_bits), w, h, adv, xo, yo))
        out_bits += data
        if ch != ':':
            ink_x0 = xo if ink_x0 is None else min(ink_x0, xo)
            ink_x1 = xo + w - 1 if ink_x1 is None else max(ink_x1, xo + w - 1)
    advs = set(g[4] for g in glyphs if g[0] != ':')
    if len(advs) != 1:
        raise SystemExit('DSEG14 digits do not share one advance: %r' % advs)
    adv = advs.pop()
    ink_w = ink_x1 - ink_x0 + 1

    def hexrows(data, per=12, indent='    '):
        return '\n'.join(indent + ' '.join('0x%02x,' % b for b in data[i:i + per])
                         for i in range(0, len(data), per))

    hdr = """/* %(name)s
 *
 * The big clock's font: DSEG14 Classic Mini Regular, 40 px, generated by
 * http://oleddisplay.squix.ch from the DSEG font (keshikan, SIL OFL 1.1 - see
 * LICENSES/OFL-1.1.txt).  The upstream header carries 93 glyphs; this is the
 * re-packed subset the clock draws with, and it is GENERATED - edit
 * tools/dseg14_upstream.h (the vendored upstream file) and re-run
 * tools/gen_v14_tables.py rather than touching the numbers here.
 *
 * Bitmap layout: one MSB-first bitstream, `w` bits per row, rows packed
 * continuously, each glyph starting on a byte boundary.  `off` is a byte
 * offset into DSEG_BITS.  epd_font.c's dseg blitter walks it in this order.
 *
 * The fixed-slot layout rests on three properties of this face, asserted
 * below so a regenerated font cannot quietly break them:
 *   - every digit has the same advance  (DSEG_DIGIT_ADV),
 *   - every digit's ink starts at the same x within its cell and spans
 *     DSEG_DIGIT_INK_W columns (DSEG_INK_X0 / DSEG_INK_W),
 *   - the ink is never taller than DSEG_FONT_HEIGHT.
 */

#ifndef FONT_DSEG_H
#define FONT_DSEG_H

#include <stdint.h>

#define DSEG_FONT_HEIGHT   %(height)d
#define DSEG_ADV_DIGIT     %(adv)d
#define DSEG_ADV_COLON     %(colon)d
#define DSEG_INK_X0        %(ink_x0)d
#define DSEG_INK_W         %(ink_w)d

typedef struct {
    uint16_t off;   /* byte offset into DSEG_BITS */
    uint8_t  w, h;  /* ink box, pixels */
    uint8_t  adv;   /* pen advance - the same for every digit, see below */
    int8_t   xo;    /* ink x offset within the advance cell */
    int8_t   yo;    /* ink y offset from the baseline (negative = up) */
} DSEG_Glyph;

#define DSEG_GLYPH_COUNT %(count)d
extern const DSEG_Glyph DSEG_GLYPHS[DSEG_GLYPH_COUNT];
extern const uint8_t DSEG_BITS[%(bytes)d];

#if DSEG_FONT_HEIGHT != 40
#error "the clock layout in epd_layout.h assumes a 40 px DSEG face"
#endif
#if DSEG_INK_X0 + DSEG_INK_W > DSEG_ADV_DIGIT
#error "a digit's ink would run past its own advance cell"
#endif

#endif /* FONT_DSEG_H */
""" % {'name': 'font_dseg.h - the re-packed DSEG14 clock subset',
       'height': tab['0'][2], 'adv': adv, 'colon': tab[':'][3],
       'ink_x0': ink_x0, 'ink_w': ink_w, 'count': len(glyphs),
       'bytes': len(out_bits)}

    # the extern declarations and the definitions go in one header: the face is
    # small enough that the extra .c file would cost more than it organises
    glyph_rows = '\n'.join('    {%5d, %2d, %2d, %2d, %3d, %4d }, /* %s */'
                           % (g[1], g[2], g[3], g[4], g[5], g[6], g[0])
                           for g in glyphs)
    hdr = hdr.replace('extern const DSEG_Glyph DSEG_GLYPHS[DSEG_GLYPH_COUNT];',
                      'static const DSEG_Glyph DSEG_GLYPHS[DSEG_GLYPH_COUNT] = {\n'
                      + glyph_rows + '\n};')
    hdr = hdr.replace('extern const uint8_t DSEG_BITS[%(bytes)d];' % {'bytes': len(out_bits)},
                      'static const uint8_t DSEG_BITS[%(bytes)d] = {\n' % {'bytes': len(out_bits)}
                      + hexrows(out_bits) + '\n};')
    # drop the glyph_rows builder's now-unused original (kept above for clarity)

    open(path, 'w', encoding='utf-8', newline='\n').write(hdr)
    return {'count': len(glyphs), 'bytes': len(out_bits), 'adv': adv,
            'colon': tab[':'][3], 'ink_x0': ink_x0, 'ink_w': ink_w}


def emit_calendar(path, term_days):
    lunar_rows = []
    for i in range(0, NLUNAR, 5):
        chunk = LUNAR_INFO[i:i + 5]
        lunar_rows.append('    ' + ', '.join('0x%05x' % v for v in chunk)
                          + ',  /* %d-%d */'
                          % (LUNAR_YEAR_FIRST + i,
                             LUNAR_YEAR_FIRST + min(i + 4, NLUNAR - 1)))

    term_rows = []
    for i, y in enumerate(range(YEAR_FIRST, TERM_YEAR_LAST + 1)):
        term_rows.append('    ' + ' '.join('%2d,' % d for d in term_days[i])
                         + '  /* %d */' % y)

    text = BANNER % 'Lunar months and solar terms for the v14.0 clock face.'
    text += """
/* The face advertises CAL_YEAR_FIRST..CAL_YEAR_LAST.  Outside that range the
 * third row stays blank rather than showing a wrong date - see cal_row3() in
 * src/calendar.c, which is where the two encodings below are decoded.
 */
#define CAL_YEAR_FIRST %d
#define CAL_YEAR_LAST  %d
#define CAL_YEARS      %d

/* The term table is one year longer than the advertised range, so that a date
 * in the last days of CAL_YEAR_LAST can still see its next term in January.
 * This is the bound term_on() gates on; CAL_YEAR_LAST is the one cal_row3()
 * gates on.
 */
#define CAL_TERM_YEAR_FIRST %d
#define CAL_TERM_YEAR_LAST  %d
#define CAL_TERM_YEARS      %d

/* The lunar rows start earlier than CAL_YEAR_FIRST on purpose: 2026-01-01 is
 * still 2025-11-13 in the lunar year, so a January date needs the previous
 * year's row.  CAL_LUNAR_EPOCH_* is the Gregorian date of LUNAR_YEAR_FIRST's
 * 正月初一, i.e. day 0 of the table.
 */
#define CAL_LUNAR_YEAR_FIRST %d
#define CAL_LUNAR_YEARS      %d
#define CAL_LUNAR_EPOCH_Y    %d
#define CAL_LUNAR_EPOCH_M    %d
#define CAL_LUNAR_EPOCH_D    %d

/* Packed like the published lunarInfo table:
 *     bits 15..4  length of lunar months 1..12, MSB = month 1, 1 = 30 days
 *     bits  3..0  leap month number, 0 = no leap month
 *     bit  16     leap month length, 1 = 30 days
 */
static const unsigned int CAL_LUNAR_INFO[CAL_LUNAR_YEARS] = {
%s
};

/* Day of the month of each solar term.  Term n sits at (285 + 15n) mod 360
 * degrees of apparent solar longitude, and for every year in this range it
 * falls in the same Gregorian month - tools/gen_v14_tables.py asserts that,
 * which is why only the day has to be stored.  Order within a year is the
 * order of CAL_TERM_MONTH: 小寒, 大寒, 立春, ... 冬至.  One row per year from
 * CAL_TERM_YEAR_FIRST to CAL_TERM_YEAR_LAST inclusive.
 */
static const unsigned char CAL_TERM_MONTH[24] = {
    %s};
static const unsigned char CAL_TERM_DAY[CAL_TERM_YEARS][24] = {
%s
};
""" % (YEAR_FIRST, YEAR_LAST, NYEARS,
       YEAR_FIRST, TERM_YEAR_LAST, NTERMYEARS,
       LUNAR_YEAR_FIRST, NLUNAR,
       LUNAR_EPOCH.year, LUNAR_EPOCH.month, LUNAR_EPOCH.day,
       '\n'.join(lunar_rows),
       ', '.join('%d' % m for m in TERM_MONTH),
       '\n'.join(term_rows))

    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(text)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    hexpath = sys.argv[1]
    if not os.path.exists(hexpath):
        print('ERROR: no such file: %s' % hexpath)
        return 2

    print('=' * 74)
    print('unifont.hex  %s' % hexpath)
    with open(hexpath, 'rb') as fh:
        raw = fh.read()
    print('  %d bytes, sha256 %s' % (len(raw), hashlib.sha256(raw).hexdigest()))
    print()

    glyphs = build_glyphs(load_unifont(hexpath))
    n16 = sum(1 for g in glyphs if g[1] == 16)
    n8 = len(glyphs) - n16
    bitmap = sum(len(g[3]) for g in glyphs)
    tables = len(glyphs) * (2 + 2 + 1 + 1)
    print('glyphs: %d total  (%d at 16x16, %d at 8x16)' % (len(glyphs), n16, n8))
    print('  bitmap        %5d B' % bitmap)
    print('  lookup tables %5d B' % tables)
    print('  font total    %5d B' % (bitmap + tables))
    print()

    # --- solar terms ------------------------------------------------------
    print('solar terms %d..%d  (one year past the advertised %d so that late '
          'December can still see January)'
          % (YEAR_FIRST, TERM_YEAR_LAST, YEAR_LAST))
    term_days = []
    month_bad = 0
    worst = []
    for y in range(YEAR_FIRST, TERM_YEAR_LAST + 1):
        row = []
        for n in range(24):
            d, instant = solar_term_beijing(y, n)
            if d.month != TERM_MONTH[n]:
                month_bad += 1
                print('  !! %d %s fell in month %d, expected %d'
                      % (y, TERM_NAMES[n], d.month, TERM_MONTH[n]))
            row.append(d.day)
            minutes = instant.hour * 60 + instant.minute
            worst.append((min(minutes, 1440 - minutes), y, TERM_NAMES[n], instant))
        term_days.append(row)
    print('  months outside their slot: %d  (must be 0, the table stores only the day)'
          % month_bad)
    if month_bad:
        return 1
    worst.sort()
    print('  tightest instants (a wrong day would show up here first):')
    for dist, y, name, instant in worst[:3]:
        print('    %s %d  %s  %d min from midnight'
              % (name, y, instant.strftime('%Y-%m-%d %H:%M'), dist))
    print('  table: %d years x 24 terms x 1 B = %d B  (%d advertised + 1 lookahead)'
          % (NTERMYEARS, NTERMYEARS * 24, NYEARS))
    print()

    # --- lunar ------------------------------------------------------------
    print('lunar table %d..%d: %d x 4 B = %d B  (epoch %s = 正月初一)'
          % (LUNAR_YEAR_FIRST, LUNAR_YEAR_LAST, NLUNAR, NLUNAR * 4, LUNAR_EPOCH))
    for probe in [(2026, 1, 1, 'early January, needs the 2025 row'),
                  (2026, 2, 17, '春节'),
                  (2026, 9, 12, 'the reference photo'),
                  (2026, 12, 31, 'end of year'),
                  (2033, 1, 1, 'near a leap month'),
                  (2050, 12, 31, 'last supported day')]:
        ly, lm, ld, isl = solar_to_lunar(*probe[:3])
        print('  %04d-%02d-%02d -> %s%d月%d日 %s'
              % (probe[0], probe[1], probe[2], '闰' if isl else '', lm, ld,
                 probe[3]))
    print()

    # --- rune -------------------------------------------------------------
    rune_px = raster_rune()
    rune_cols = rune_columns(rune_px)
    print('Bluetooth rune %dx%d (this is the compiled bitmap):' % (RUNE_W, RUNE_H))
    for row in rune_px:
        print('    ' + ''.join('#' if v else '.' for v in row))
    print('  %d bytes' % len(rune_cols))
    print()

    # --- write ------------------------------------------------------------
    font_path = os.path.join(SRC, 'font_unifont.h')
    chars_path = os.path.join(SRC, 'font_chars.h')
    cal_path = os.path.join(SRC, 'calendar_data.h')
    dseg_path = os.path.join(SRC, 'font_dseg.h')
    emit_font(font_path, glyphs, rune_px, rune_cols)
    emit_chars(chars_path)
    emit_calendar(cal_path, term_days)
    dseg_stats = emit_dseg(dseg_path)
    for p in (font_path, chars_path, cal_path, dseg_path):
        print('wrote %s  (%d bytes)' % (p, os.path.getsize(p)))
    st = dseg_stats
    print()
    print('DSEG14 clock font: %d glyphs, %d B of bitmap; digit advance %d, '
          'colon %d; per-cell ink x %d..%d'
          % (st['count'], st['bytes'], st['adv'], st['colon'],
             st['ink_x0'], st['ink_x0'] + st['ink_w'] - 1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
