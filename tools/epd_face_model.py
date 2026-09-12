#!/usr/bin/env python3
# =============================================================================
# epd_face_model.py - the v14.0 clock face, mirrored in Python
# -----------------------------------------------------------------------------
# One mirror, shared by tools/verify_v14_layout.py (which asserts things about
# it) and tools/render_screen_preview.py (which draws it).  Two hand-written
# copies of the same geometry is how a preview starts lying about the firmware.
#
# Every number comes out of the real sources - nothing is typed twice:
#
#   epd_layout.h    all coordinates, the clock metrics, the gate window
#   font_unifont.h  the glyph table the firmware blits (codepoint, bitmap,
#                   columns, advance) and the Bluetooth rune bitmap
#   font_chars.h    the codepoints row 1 and row 3 are composed from
#   calendar_data.h the lunar table and the solar term day numbers
#   app_config.h    the firmware version string
#
# The functions below are line-for-line mirrors of:
#   epd_font.c   uf_find uf_blit epd_glyph epd_text epd_utext
#                epd_text_width epd_utext_width epd_rune
#                plot fill_quad draw_digit draw_colon clock_char_w
#                epd_clock_width epd_clock
#   epd.c        put_num epd_face
#   calendar.c   days_from_civil civil_from_days next_day cal_date
#                cal_li cal_leap_month cal_leap_days cal_month_days
#                cal_year_days lunar_from_solar term_on next_term
#                put_lunar_day cal_row3
#
# Byte-exactness notes that matter:
#   * the panel buffer holds one byte per column per 8 rows, bit (y & 7),
#     byte at (y >> 3) * wpitch + x - see obdSetPixel() in OneBitDisplay
#   * C integer division truncates toward zero and C's % keeps the sign of the
#     dividend; Python floors.  _cdiv / _cmod are used wherever the C could see
#     a negative operand, which is everywhere the calendar can.
# =============================================================================
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..'))
SRC = os.path.join(ROOT, 'atc1441_src', 'Firmware', 'src')


# ---------------------------------------------------------------------------
# C arithmetic
# ---------------------------------------------------------------------------
def _cdiv(a, b):
    """C's integer '/' - truncate toward zero."""
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def _cmod(a, b):
    """C's integer '%' - result takes the sign of the dividend."""
    return a - _cdiv(a, b) * b


class Arr(object):
    """A fixed-length array that raises on a write past the end.

    The C composes each row into a stack array of a fixed size, and the whole
    point of ROW1_MAX_CHARS is that the widest string fits.  Python lists grow
    silently, so mirroring the C with a list would hide exactly the failure this
    module exists to catch - Arr keeps the C's capacity and its overrun.
    """

    __slots__ = ('a', 'n')

    def __init__(self, n):
        self.a = [0] * n
        self.n = n

    def __setitem__(self, i, v):
        if i < 0 or i >= self.n:
            raise IndexError('write to index %d of a %d-element row buffer'
                             % (i, self.n))
        self.a[i] = v

    def __getitem__(self, i):
        return self.a[i]

    def __len__(self):
        return self.n

    def slice(self, upto):
        """The first `upto` entries, as a plain list."""
        return self.a[:upto]


# ---------------------------------------------------------------------------
# source parsing
# ---------------------------------------------------------------------------
def _read(name):
    with open(os.path.join(SRC, name), encoding='utf-8', errors='ignore') as fh:
        return fh.read()


def _strip_comments(text):
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    return re.sub(r'//[^\n]*', '', text)


def _top_level_qc(seg):
    """(index of '?', index of its ':') at paren depth 0 inside seg, or (None, None)."""
    depth, q = 0, None
    for i, ch in enumerate(seg):
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif ch == '?' and depth == 0:
            q = i
            break
    if q is None:
        return None, None
    depth = 0
    for j in range(q + 1, len(seg)):
        ch = seg[j]
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif ch == ':' and depth == 0:
            return q, j
    return None, None


def _convert_ternaries(expr):
    """Rewrite every C ?: into a Python conditional, innermost group first.

    A macro author naturally writes `(A < 6 ? 6 : (A))`, so the ternary sits
    inside a parenthesised group rather than at the top level; the search is
    therefore for the DEEPEST group that has a '?' at its own top level, which
    handles the nesting without needing a full expression parser.
    """
    while '?' in expr:
        stack, groups = [], []
        for i, ch in enumerate(expr):
            if ch == '(':
                stack.append(i)
            elif ch == ')' and stack:
                groups.append((stack.pop(), i, len(stack)))
        picked = None
        for start, end, depth in sorted(groups, key=lambda g: -g[2]):
            q, c = _top_level_qc(expr[start + 1:end])
            if q is not None:
                picked = (start, end, q, c)
                break
        if picked is None:
            raise ValueError('unbalanced ?: in %r' % expr)
        start, end, q, c = picked
        seg = expr[start + 1:end]
        expr = (expr[:start] + '(' + seg[q + 1:c].strip() + ' if '
                + seg[:q].strip() + ' else ' + seg[c + 1:].strip() + ')'
                + expr[end + 1:])
    return expr


def _eval_expr(expr, table):
    """Evaluate one macro body: C ternary to Python, '/' to '//', calls and
    identifiers expanded from `table`, then eval."""
    expr = _convert_ternaries(expr).replace('/', '//')

    def sub_call(mm):
        """NAME(arg, ...) -> its value.  The `if`/`else` of a converted ternary
        match the same shape and must be left alone."""
        name, argtext = mm.group(1), mm.group(2)
        if name in ('if', 'else'):
            return mm.group(0)
        args = [int(_eval_expr(a, table)) for a in argtext.split(',')]
        return str(table.call(name, *args))

    expr = re.sub(r'\b([A-Za-z_]\w*)\s*\(([^()]*)\)', sub_call, expr)

    def sub_name(mm):
        name = mm.group(1)
        if name in ('if', 'else'):
            return name
        return str(table[name])

    return eval(re.sub(r'\b([A-Za-z_]\w*)\b', sub_name, expr),
                {'__builtins__': {}}, {})


class Macros(object):
    """The integer #define table of one header.

    Supports both object-like macros (MACROS['CLOCK_CELL_W']) and, because
    epd_layout.h derives the clock slots with one, function-like macros
    (MACROS.call('CLOCK_SLOT_X', 3)).  So the window and the slot positions in
    the verify script are evaluated FROM the C text rather than retyped.
    """

    def __init__(self, text):
        body = _strip_comments(text)
        # join backslash continuations first: CLOCK_SLOT_X is written across two
        # lines, and a macro body that keeps its trailing '\' is not an
        # expression the evaluate step can handle
        body = re.sub(r'\\\s*\n', ' ', body)
        self.obj = {}
        self.fn = {}
        for m in re.finditer(r'^#define\s+(\w+)(\([^)]*\))?\s+([^\n]+)$', body, re.M):
            name, params, expr = m.group(1), m.group(2), m.group(3).strip()
            if expr.startswith('"') or expr.startswith("'"):
                continue
            if params is None:
                self.obj[name] = expr
            else:
                self.fn[name] = ([p.strip() for p in params[1:-1].split(',')],
                                 expr)
        self._cache = {}

    def merge(self, other):
        """Fold another header's defines in - epd_layout.h #includes
        font_dseg.h and derives the clock layout from its metrics, so the
        mirror has to see both files as one namespace."""
        self.obj.update(other.obj)
        self.fn.update(other.fn)
        self._cache = {}

    def __getitem__(self, name):
        return self.call(name)

    def __contains__(self, name):
        return name in self.obj or name in self.fn

    def get(self, name, default=None):
        try:
            return self.call(name)
        except KeyError:
            return default

    def call(self, name, *args):
        key = (name,) + args
        if key in self._cache:
            return self._cache[key]
        if name in self.fn:
            params, expr = self.fn[name]
            if len(args) != len(params):
                raise TypeError('%s takes %d arguments' % (name, len(params)))
            for p, a in zip(params, args):
                expr = re.sub(r'\b%s\b' % re.escape(p), '(%d)' % a, expr)
        elif name in self.obj:
            expr = self.obj[name]
        else:
            raise KeyError(name)
        v = _eval_expr(expr, self)
        self._cache[key] = v
        return v


def parse_defines(text, want=None):
    """The integer #define table of a header, as a Macros.

    `want` is accepted and ignored - it survives from an earlier version that
    parsed only a named subset, and every caller now wants the whole table
    (a macro's meaning depends on its neighbours).
    """
    return Macros(text)


def parse_int_array(text, name):
    """Flatten one integer initialiser list, hex or decimal."""
    m = re.search(r'\b%s\s*\[[^\]]*\]\s*=\s*\{(.*?)\};' % re.escape(name),
                  text, re.S)
    if not m:
        raise KeyError('no array %s' % name)
    body = _strip_comments(m.group(1))
    return [int(t, 0) for t in re.findall(r'0x[0-9a-fA-F]+|\d+', body)]


def parse_2d_array(text, name, rows):
    """The [r][c] form, e.g. CAL_TERM_DAY[25][24]."""
    m = re.search(r'\b%s\s*\[[^\]]*\]\[[^\]]*\]\s*=\s*\{(.*?)\};' % re.escape(name),
                  text, re.S)
    if not m:
        raise KeyError('no 2d array %s' % name)
    body = _strip_comments(m.group(1))
    flat = [int(t, 0) for t in re.findall(r'0x[0-9a-fA-F]+|\d+', body)]
    if len(flat) % rows:
        raise ValueError('%s: %d values is not a multiple of %d rows'
                         % (name, len(flat), rows))
    w = len(flat) // rows
    return [flat[i * w:(i + 1) * w] for i in range(rows)]


# ---------------------------------------------------------------------------
# the model
# ---------------------------------------------------------------------------
class Face(object):
    def __init__(self, src=SRC):
        self.src = src
        lay = parse_defines(_read('epd_layout.h'))
        # epd_layout.h #includes font_dseg.h and derives the clock layout from
        # its metrics, so the mirror merges the same two files
        lay.merge(parse_defines(_read('font_dseg.h')))
        self.L = lay

        font = _read('font_unifont.h')
        self.code = parse_int_array(font, 'UF_CODE')
        self.off = parse_int_array(font, 'UF_OFF')
        self.cols = parse_int_array(font, 'UF_COLS')
        self.adv = parse_int_array(font, 'UF_ADV')
        self.bits = parse_int_array(font, 'UF_BITS')
        self.rune_bits = parse_int_array(font, 'BLE_RUNE_BITS')
        self.rune_w = parse_defines(font).get('BLE_RUNE_W')
        self.rune_h = parse_defines(font).get('BLE_RUNE_H')
        self._by_cp = {c: i for i, c in enumerate(self.code)}

        ch = _read('font_chars.h')
        self.ch = parse_defines(ch)
        self.weekday = parse_int_array(ch, 'UF_WEEKDAY')
        self.numeral = parse_int_array(ch, 'UF_NUMERAL')
        self.lunar_month = parse_int_array(ch, 'UF_LUNAR_MONTH')
        self.term = parse_2d_array(ch, 'UF_TERM', 24)

        cal = _read('calendar_data.h')
        self.cal = parse_defines(cal)
        self.lunar_info = parse_int_array(cal, 'CAL_LUNAR_INFO')
        self.term_month = parse_int_array(cal, 'CAL_TERM_MONTH')
        self.term_day = parse_2d_array(cal, 'CAL_TERM_DAY', self.cal['CAL_TERM_YEARS'])

        # the DSEG14 clock font: glyph table + bitmap + a codepoint index
        dseg = _read('font_dseg.h')
        self.dseg_glyphs = []
        for m in re.finditer(r'\{\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+),'
                             r'\s*(-?\d+),\s*(-?\d+)\s*\},\s*/\* (\S+) \*/', dseg):
            self.dseg_glyphs.append(tuple(int(v) for v in m.groups()[:6])
                                    + (m.group(7),))
        self.dseg_index = {g[6]: i for i, g in enumerate(self.dseg_glyphs)}
        self.dseg_bits = parse_int_array(dseg, 'DSEG_BITS')
        self.dseg_define = parse_defines(dseg)

        # cal_row3()'s scratch array, and the buffer epd_face() hands it
        self.ch_maxn = parse_defines(_read('calendar.h'))['CAL_ROW3_MAX']

        self.version = self._version()

    def _version(self):
        m = re.search(r'#define\s+FW_VERSION_STRING\s+"([^"]*)"',
                      _read('app_config.h'))
        return m.group(1) if m else None

    # -- font ---------------------------------------------------------------
    def uf_find(self, cp):
        """Mirror of uf_find(): (blob_offset or None, columns, advance)."""
        i = self._by_cp.get(cp)
        if i is None:
            return None, 0, (16 if cp >= 0x2E80 else 8)
        return self.off[i], self.cols[i], self.adv[i]

    def uf_blit(self, buf, wpitch, height, x, ytop, data, blob, ncols):
        """Mirror of uf_blit() - including its bounds guard, so a glyph placed
        off the glass draws nothing here either.

        `data` is the byte array the C pointer refers to, and `blob` the offset
        into it.  It has to be a parameter: the firmware calls uf_blit with
        BLE_RUNE_BITS, a different array from UF_BITS, and a mirror that always
        read UF_BITS drew an empty glyph from the space character's bytes.
        """
        if data is None or blob is None or ncols <= 0:
            return
        if x < 0 or x + ncols > wpitch or ytop < 0 or ytop + 15 >= height:
            return

        off = ytop & 7
        r0 = ytop >> 3
        lastrow = height >> 3
        p0 = r0 * wpitch + x

        for c in range(ncols):
            word = data[blob + 2 * c] | (data[blob + 2 * c + 1] << 8)
            b0 = (word << off) & 0xFF
            b1 = (word >> (8 - off)) & 0xFF

            if b0:
                buf[p0 + c] |= b0
            if b1 and r0 + 1 < lastrow:
                buf[p0 + c + wpitch] |= b1
            if off and r0 + 2 < lastrow:
                b2 = (word >> (16 - off)) & 0xFF
                if b2:
                    buf[p0 + c + 2 * wpitch] |= b2

    def glyph(self, buf, wpitch, height, x, ytop, cp):
        blob, ncols, adv = self.uf_find(cp)
        self.uf_blit(buf, wpitch, height, x, ytop, self.bits, blob, ncols)
        return x + adv

    def text(self, buf, wpitch, height, x, ytop, s):
        for ch in s:
            x = self.glyph(buf, wpitch, height, x, ytop, ord(ch))
        return x

    def utext(self, buf, wpitch, height, x, ytop, cps):
        for cp in cps:
            x = self.glyph(buf, wpitch, height, x, ytop, cp)
        return x

    def text_width(self, s):
        return sum(self.uf_find(ord(c))[2] for c in s)

    def utext_width(self, cps):
        return sum(self.uf_find(c)[2] for c in cps)

    def rune(self, buf, wpitch, height, x, ytop):
        # epd_rune() hands uf_blit the rune blob at offset 0 - BLE_RUNE_BITS is a
        # stand-alone array, not a slice of UF_BITS.
        self.uf_blit(buf, wpitch, height, x, ytop, self.rune_bits, 0, self.rune_w)

    def rune_cols(self, bits=None):
        """The rune bitmap as a list of row-index sets, one per column.

        `bits` defaults to the compiled array; pass another one to ask the same
        question of a candidate bitmap (section 8 of the verifier does).
        """
        src = self.rune_bits if bits is None else bits
        return [set(r for r in range(self.rune_h)
                    if (src[2 * c] | (src[2 * c + 1] << 8)) >> r & 1)
                for c in range(self.rune_w)]

    def rune_asymmetric(self, bits=None):
        """Columns whose ink is not its own mirror image top-to-bottom.

        The reference panel's rune has an arm in each half on the left, so
        flipping it about the centre row must reproduce it.  The first
        revision drew the upper-left arm collinear with the lower chevron's
        chord instead, which left the lower-left quarter blank: the symbol
        leaned, and nothing in the toolchain could see it.  This is the check
        that can.
        """
        return [c for c, rows in enumerate(self.rune_cols(bits))
                if rows != set(self.rune_h - 1 - r for r in rows)]

    # -- clock --------------------------------------------------------------
    # DSEG14 Classic Mini Regular scaled 3/2 - the same face v13.0 drew with.
    # Fixed slots, mirroring epd_clock(): slot i is at CLOCK_SLOT_X(i) for every
    # rendering, slot 2 is the colon.  The glyph metrics come from font_dseg.h,
    # and the blitter walks the same 3/2 pattern the C does: source row/column n
    # expands to 2 output rows/columns when n is even, 1 when n is odd.
    def slot_x(self, i):
        return self.L.call('CLOCK_SLOT_X', i)

    def slot_w(self, i):
        return self.L['CLOCK_COLON_W'] if i == 2 else self.L['CLOCK_CELL_W']

    def clock_width(self, s):
        """Constant now - the face is the same width for every "HH:MM"."""
        return self.L['CLOCK_WIDEST']

    def _dseg(self, ch):
        i = self.dseg_index.get(ch)
        return None if i is None else self.dseg_glyphs[i]

    def draw_digit(self, buf, wp, ht, x, y, w, h, t, ch):
        self.draw_dseg(buf, wp, ht, x, y, ch)

    def draw_colon(self, buf, wp, ht, x, y, h, t):
        self.draw_dseg(buf, wp, ht, x, y, ':')

    def draw_dseg(self, buf, wp, ht, x, y, ch):
        """Mirror of epd_clock()'s glyph loop.

        (x, y) is the slot origin: the font's baseline sits CLOCK_H below it,
        and yo is the ink top's offset FROM that baseline (GFX convention,
        negative = up) - so the ink starts (DSEG_FONT_HEIGHT + yo) scaled
        pixels below the slot top.  Same formula as epd_font.c, which replaced
        an earlier (FONT_HEIGHT - h) version that sat short glyphs one inset
        too low.
        """
        g = self._dseg(ch)
        if g is None:
            return
        off, gw, gh, adv, xo, yo = g[:6]
        num, den = self.L['CLOCK_SCALE_NUM'], self.L['CLOCK_SCALE_DEN']
        x += (xo * num) // den
        y += ((self.L['DSEG_FONT_HEIGHT'] + yo) * num) // den
        bit = off * 8
        bits = self.dseg_bits
        oy = 0
        for sy in range(gh):
            rh = 1 if (sy & 1) else 2
            ox = 0
            for sx in range(gw):
                rw = 1 if (sx & 1) else 2
                if bits[bit >> 3] & (0x80 >> (bit & 7)):
                    for a in range(rh):
                        for b in range(rw):
                            self.plot(buf, wp, ht, x + ox + b, y + oy + a)
                bit += 1
                ox += rw
            oy += rh

    def clock(self, buf, wp, ht, s):
        for i, ch in enumerate(s):
            self.draw_dseg(buf, wp, ht, self.slot_x(i), self.L['CLOCK_Y'], ch)

    def plot(self, buf, wpitch, height, x, y):
        if x < 0 or x >= wpitch or y < 0 or y >= height:
            return
        buf[(y >> 3) * wpitch + x] |= 1 << (y & 7)

    def days_from_civil(self, y, m, d):
        y -= 1 if m <= 2 else 0
        era = _cdiv(y if y >= 0 else y - 399, 400)
        yoe = y - era * 400
        doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
        doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
        return era * 146097 + doe - 719468

    def civil_from_days(self, z):
        z += 719468
        era = _cdiv(z if z >= 0 else z - 146096, 146097)
        doe = z - era * 146097
        yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
        y = yoe + era * 400
        doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
        mp = (5 * doy + 2) // 153
        d = doy - (153 * mp + 2) // 5 + 1
        m = mp + (3 if mp < 10 else -9)
        return y + (1 if m <= 2 else 0), m, d

    def _mdays(self, y, m):
        last = (0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)[m]
        if m == 2 and ((y % 4 == 0 and y % 100 != 0) or y % 400 == 0):
            last = 29
        return last

    def next_day(self, y, m, d):
        d += 1
        if d > self._mdays(y, m):
            d = 1
            m += 1
            if m > 12:
                m, y = 1, y + 1
        return y, m, d

    def cal_date(self, t_local):
        """(year, month, day, weekday); weekday 0 = Sunday."""
        days = t_local // 86400
        y, m, d = self.civil_from_days(days)
        return y, m, d, _cmod(_cmod(days, 7) + 11, 7)

    def cal_li(self, year):
        return self.lunar_info[year - self.cal['CAL_LUNAR_YEAR_FIRST']]

    def cal_leap_month(self, year):
        return self.cal_li(year) & 0xF

    def cal_leap_days(self, year):
        return 30 if (self.cal_li(year) & 0x10000) else 29

    def cal_month_days(self, year, m):
        return 30 if (self.cal_li(year) & (0x10000 >> m)) else 29

    def cal_year_days(self, year):
        total = 348
        for m in range(1, 13):
            if self.cal_month_days(year, m) == 30:
                total += 1
        if self.cal_leap_month(year):
            total += self.cal_leap_days(year)
        return total

    def lunar_from_solar(self, y, m, d):
        """(lm, ld, is_leap) or None."""
        c = self.cal
        offset = (self.days_from_civil(y, m, d)
                  - self.days_from_civil(c['CAL_LUNAR_EPOCH_Y'],
                                         c['CAL_LUNAR_EPOCH_M'],
                                         c['CAL_LUNAR_EPOCH_D']))
        first, nyears = c['CAL_LUNAR_YEAR_FIRST'], c['CAL_LUNAR_YEARS']
        ly, temp, is_leap, j = first, 0, 0, 0

        while offset > 0 and ly <= first + nyears - 1:
            temp = self.cal_year_days(ly)
            offset -= temp
            ly += 1
        if offset < 0:
            offset += temp
            ly -= 1
        if ly < first or ly > first + nyears - 1:
            return None

        leap = self.cal_leap_month(ly)
        j = 1
        while j < 13 and offset > 0:
            if leap > 0 and j == leap + 1 and not is_leap:
                j -= 1
                is_leap = 1
                temp = self.cal_leap_days(ly)
            else:
                temp = self.cal_month_days(ly, j)
            if is_leap and j == leap + 1:
                is_leap = 0
            offset -= temp
            j += 1
        if offset == 0 and leap > 0 and j == leap + 1:
            if is_leap:
                is_leap = 0
            else:
                is_leap = 1
                j -= 1
        if offset < 0:
            offset += temp
            j -= 1
        return j, offset + 1, is_leap

    def term_on(self, y, m, d):
        """Mirror of term_on(): the bound is the TABLE's extent, which is one
        year longer than the advertised range so a December date can see its
        next term in January."""
        c = self.cal
        if y < c['CAL_TERM_YEAR_FIRST'] or y > c['CAL_TERM_YEAR_LAST']:
            return -1
        for n in range(24):
            if (self.term_month[n] == m
                    and self.term_day[y - c['CAL_TERM_YEAR_FIRST']][n] == d):
                return n
        return -1

    def next_term(self, y, m, d):
        """(term index, days ahead) or None - nearest term on or after today."""
        for i in range(21):
            t = self.term_on(y, m, d)
            if t >= 0:
                return t, i
            y, m, d = self.next_day(y, m, d)
        return None

    # -- row composition ----------------------------------------------------
    def put_num(self, dst, n, v):
        if v < 0:
            dst[n] = ord('-')
            n += 1
            v = -v
        ds = []
        if v == 0:
            ds.append(ord('0'))
        while v:
            ds.append(ord('0') + v % 10)
            v //= 10
        for c in reversed(ds):
            dst[n] = c
            n += 1
        return n

    def put_lunar_day(self, dst, n, ld):
        ch = self.ch
        if ld == 10:
            dst[n], dst[n + 1] = ch['UF_C_CHU'], ch['UF_C_SHI']
            n += 2
        elif ld < 10:
            dst[n], dst[n + 1] = ch['UF_C_CHU'], self.numeral[ld]
            n += 2
        elif ld < 20:
            dst[n], dst[n + 1] = ch['UF_C_SHI'], self.numeral[ld - 10]
            n += 2
        elif ld == 20:
            dst[n], dst[n + 1] = self.numeral[2], ch['UF_C_SHI']
            n += 2
        elif ld < 30:
            dst[n], dst[n + 1] = ch['UF_C_NIAN'], self.numeral[ld - 20]
            n += 2
        else:
            dst[n], dst[n + 1] = self.numeral[3], ch['UF_C_SHI']
            n += 2
        return n

    def row1(self, t, mv, temperature):
        """The LEFT part of row 1 - date, weekday, temperature - exactly as
        epd_face composes it, clamps included, so this is also the function
        the width check must use.

        The voltage is NOT part of this string any more: it is drawn right
        aligned on ROW1_RIGHT_X (row1_mv_x), the edge row 3's name/version
        share, so it does not drift with the date's length.  The widest
        clamped date would run into it, so the space before the temperature
        is dropped when that would happen - the same rule epd_face applies,
        and check_row1 proves it is enough for every combination.

        Composed into an Arr sized by ROW1_MAX_CHARS: if a field widens past
        what epd_layout.h reserved, this raises here rather than corrupting a
        stack frame on the tag."""
        L = self.L
        mv = min(mv, L['ROW1_MV_MAX'])
        temperature = max(L['ROW1_TEMP_MIN'], min(temperature, L['ROW1_TEMP_MAX']))
        y, m, d, wd = self.cal_date(t)
        buf = Arr(L['ROW1_MAX_CHARS'])
        n = 0
        n = self.put_num(buf, n, y)
        buf[n] = self.ch['UF_C_YEAR']; n += 1
        n = self.put_num(buf, n, m)
        buf[n] = self.ch['UF_C_MONTH']; n += 1
        n = self.put_num(buf, n, d)
        buf[n] = self.ch['UF_C_DAY']; n += 1
        buf[n] = ord(' '); n += 1
        buf[n] = self.ch['UF_C_WEEK']; n += 1
        buf[n] = self.weekday[wd]; n += 1
        sp = n
        buf[n] = ord(' '); n += 1
        n = self.put_num(buf, n, temperature)
        buf[n] = self.ch['UF_C_DEGC']; n += 1
        if L['ROW1_X'] + self.utext_width(buf.slice(n)) > self.row1_mv_x(mv):
            for i in range(sp, n - 1):   # the mirror of epd_face's memmove
                buf[i] = buf[i + 1]
            n -= 1
        return buf.slice(n)

    def row1_mv_x(self, mv):
        """x of the right-aligned voltage: ROW1_RIGHT_X minus its advance."""
        mv = min(mv, self.L['ROW1_MV_MAX'])
        return self.L['ROW1_RIGHT_X'] - self.text_width('%dmV' % mv)

    def row3(self, t):
        """The row-3 codepoints, or [] when the date is outside the range.

        Mirrors cal_row3() including its CAL_ROW3_MAX scratch array and the
        n >= maxn bail-out."""
        c, ch = self.cal, self.ch
        maxn = self.ch_maxn
        y, m, d, _ = self.cal_date(t)
        if y < c['CAL_YEAR_FIRST'] or y > c['CAL_YEAR_LAST']:
            return []
        lun = self.lunar_from_solar(y, m, d)
        if lun is None:
            return []
        lm, ld, leap = lun
        if not (1 <= lm <= 12 and 1 <= ld <= 30):
            return []

        tmp = Arr(maxn)
        n = 0
        if leap:
            tmp[n] = ch['UF_C_LEAP']; n += 1
        tmp[n] = self.lunar_month[lm]; n += 1
        tmp[n] = ch['UF_C_MONTH']; n += 1
        n = self.put_lunar_day(tmp, n, ld)

        nt = self.next_term(y, m, d)
        if nt is not None:
            term, ahead = nt
            tmp[n] = ord(' '); n += 1
            if ahead == 0:
                tmp[n] = ch['UF_C_JIN']; n += 1
                tmp[n] = ch['UF_C_DAY']; n += 1
            else:
                if ahead >= 10:
                    tmp[n] = ord('0') + ahead // 10; n += 1
                tmp[n] = ord('0') + ahead % 10; n += 1
                tmp[n] = ch['UF_C_TIAN']; n += 1
                tmp[n] = ch['UF_C_HOU']; n += 1
            tmp[n] = self.term[term][0]; n += 1
            tmp[n] = self.term[term][1]; n += 1

        if n >= maxn:
            return []
        return tmp.slice(n)

    def mac_bracket(self, mac):
        # The tail of the advertised name - "ESL_" plus six hex digits - which
        # is what the reference panel shows: four digits, [881A], not the MAC.
        return '[%02X%02X]' % (mac[1], mac[0])

    def row3_version(self):
        return self.version

    def row3_alt_state(self, t):
        """0 = the advertised name, 1 = the firmware version."""
        return (t // self.L['ROW3_ALT_SECS']) & 1

    def row3_text(self, t, mac=(0xA1, 0xB2, 0xC3)):
        return self.row3_version() if self.row3_alt_state(t) \
            else self.mac_bracket(mac)

    def row3_right_x(self, text):
        # ROW3_RIGHT_X is the last column the string OCCUPIES (inclusive), not
        # the pen position after it - that is what makes "inside the band"
        # readable off the header.
        return self.L['ROW3_RIGHT_X'] - self.text_width(text) + 1

    def row3_rune_x(self):
        # A FIXED slot, from epd_layout.h: the two strings differ in width, so
        # following the text would make the rune jump sideways on every swap.
        return self.L['ROW3_RUNE_X']

    # -- the whole face -----------------------------------------------------
    def face(self, buf, wpitch, height, t, mv, temperature, mac=(0xA1, 0xB2, 0xC3),
             connected=True, debug=None):
        L = self.L

        self.utext(buf, wpitch, height, L['ROW1_X'], L['ROW1_Y'],
                   self.row1(t, mv, temperature))
        self.text(buf, wpitch, height, self.row1_mv_x(mv), L['ROW1_Y'],
                  '%dmV' % min(mv, L['ROW1_MV_MAX']))

        hhmm = '%02d:%02d' % ((t // 60 // 60) % 24, (t // 60) % 60)
        self.clock(buf, wpitch, height, hhmm)

        if debug is not None:
            self.text(buf, wpitch, height, L['ROW3_X'], L['ROW3_Y'],
                      'H%02dT%dB%dL%d' % debug)
        else:
            r3 = self.row3(t)
            if r3:
                self.utext(buf, wpitch, height, L['ROW3_X'], L['ROW3_Y'], r3)

        b = self.row3_text(t, mac)
        self.text(buf, wpitch, height, self.row3_right_x(b), L['ROW3_Y'], b)
        if connected:
            self.rune(buf, wpitch, height, self.row3_rune_x(),
                      L['ROW3_Y'] + 1)
        return hhmm


# ---------------------------------------------------------------------------
# helpers for callers
# ---------------------------------------------------------------------------
def new_buffer(face):
    return bytearray(face.L['FACE_W'] * face.L['FACE_H'] // 8)


def ink_extent(face, buf):
    """(xmin, xmax, ymin, ymax) of the set pixels, or None when blank."""
    w, h = face.L['FACE_W'], face.L['FACE_H']
    xs, ys = [], []
    for r in range(h // 8):
        for x in range(w):
            byte = buf[r * w + x]
            for b in range(8):
                if byte & (1 << b):
                    xs.append(x)
                    ys.append(r * 8 + b)
    if not xs:
        return None
    return min(xs), max(xs), min(ys), max(ys)


def bits(face, buf):
    """Row-major 0/1 list of lists, for image output."""
    w, h = face.L['FACE_W'], face.L['FACE_H']
    out = []
    for y in range(h):
        row = []
        base = (y >> 3) * w
        mask = 1 << (y & 7)
        for x in range(w):
            row.append(1 if (buf[base + x] & mask) else 0)
        out.append(row)
    return out
