#!/usr/bin/env python3
# =============================================================================
# render_screen_preview.py - offline renderer for the v14.0 clock face
# -----------------------------------------------------------------------------
# Draws the face the firmware will draw, without a tag on the bench, so a layout
# change can be SEEN before it is flashed.
#
# The drawing is not re-implemented here.  tools/epd_face_model.py is the
# line-for-line mirror of epd_font.c / epd.c / calendar.c, and it is the same
# module tools/verify_v14_layout.py measures - so the preview and the checks
# cannot drift apart, and neither can drift from the firmware without the
# other noticing.
#
# No third-party imports: the PNG writer below is ~20 lines of zlib and struct.
# Pillow was the only reason this needed the system interpreter.
#
# Usage:
#   python tools/render_screen_preview.py                     # the reference photo
#   python tools/render_screen_preview.py --window            # + the partial band
#   python tools/render_screen_preview.py --date 2028-06-23 --temp -12
#   python tools/render_screen_preview.py --time 00:00 --mv 9999 --no-ble
#   python tools/render_screen_preview.py --debug 18,0,1,2    # counters on row 3
#   python tools/render_screen_preview.py --zoom 4
# =============================================================================
import argparse
import datetime
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from epd_face_model import Face, bits, new_buffer  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..'))
OUTDIR = os.path.join(ROOT, 'previews')

PAPER = (246, 245, 240)
INK = (24, 24, 26)
BAND_FILL = (250, 232, 218)
BAND_EDGE = (214, 120, 60)
BOX = (200, 30, 40)


# ---------------------------------------------------------------------------
# a minimal PNG writer: 8-bit RGB, filter 0, one IDAT
# ---------------------------------------------------------------------------
def write_png(path, w, h, pix):
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        row = pix[y * w:(y + 1) * w]
        for p in row:
            raw += bytes(p)

    def chunk(tag, data):
        return (struct.pack('>I', len(data)) + tag + data
                + struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF))

    with open(path, 'wb') as fh:
        fh.write(b'\x89PNG\r\n\x1a\n'
                 + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
                 + chunk(b'IDAT', zlib.compress(bytes(raw), 9))
                 + chunk(b'IEND', b''))


class Canvas(object):
    """A small RGB bitmap with the two operations the previews need: fill a
    rectangle (the band tint and the red boxes) and blit the 1-bit face."""

    def __init__(self, w, h, bg=PAPER):
        self.w, self.h = w, h
        self.p = [bg] * (w * h)

    def rect(self, x0, y0, x1, y1, colour, edge=False):
        for y in range(max(0, y0), min(self.h, y1 + 1)):
            for x in range(max(0, x0), min(self.w, x1 + 1)):
                if edge and x0 < x < x1 and y0 < y < y1:
                    continue
                self.p[y * self.w + x] = colour

    def ink(self, rows, x0, y0):
        for y, row in enumerate(rows):
            base = (y0 + y) * self.w
            for x, v in enumerate(row):
                if v:
                    self.p[base + x0 + x] = INK

    def blit_rgb(self, rows, x0, y0):
        """Paste an RGB row-major image (from read_png or resample)."""
        for y, row in enumerate(rows):
            if not 0 <= y0 + y < self.h:
                continue
            base = (y0 + y) * self.w
            for x, c in enumerate(row):
                if 0 <= x0 + x < self.w:
                    self.p[base + x0 + x] = c

    def scaled(self, z):
        out = Canvas(self.w * z, self.h * z)
        for y in range(self.h):
            for x in range(self.w):
                c = self.p[y * self.w + x]
                for dy in range(z):
                    base = (y * z + dy) * out.w + x * z
                    for dx in range(z):
                        out.p[base + dx] = c
        return out

    def save(self, path, z=1):
        img = self.scaled(z) if z != 1 else self
        write_png(path, img.w, img.h, img.p)


def bits_rgb(rows, w, h):
    """The 1-bit face as RGB rows, so it can be pasted into a composite."""
    return [[INK if v else PAPER for v in row[:w]] for row in rows[:h]]


def scale_rgb(rows, z):
    """Nearest-neighbour upscale, the RGB-rows counterpart of Canvas.scaled()."""
    out = []
    for row in rows:
        wide = [c for px in row for c in (px, ) * z]
        for _ in range(z):
            out.append(wide)
    return out


# ---------------------------------------------------------------------------
# a minimal PNG reader: 8-bit RGB, non-interlaced, the one shape write_png emits
# ---------------------------------------------------------------------------
def read_png(path):
    """(w, h, pixels) for an 8-bit RGB PNG, or raise ValueError.

    Only the form write_png() produces is accepted, so the two functions and the
    reference photograph stored next to them stay in one dialect.  Anything else
    (palette, 16-bit, interlaced) is refused by name rather than mis-decoded.
    """
    data = open(path, 'rb').read()
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('%s is not a PNG' % path)

    pos, hdr, idat = 8, None, bytearray()
    while pos + 8 <= len(data):
        n = struct.unpack('>I', data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + n]
        if tag == b'IHDR':
            hdr = struct.unpack('>IIBBBBB', body)
        elif tag == b'IDAT':
            idat += body
        elif tag == b'IEND':
            break
        pos += 12 + n

    if hdr is None:
        raise ValueError('%s has no IHDR' % path)
    w, h, depth, colour, comp, filt, inter = hdr
    if (depth, colour, comp, filt, inter) != (8, 2, 0, 0, 0):
        raise ValueError('%s is bit depth %d, colour type %d, interlace %d; '
                         'only 8-bit RGB non-interlaced is supported'
                         % (path, depth, colour, inter))

    raw = zlib.decompress(bytes(idat))
    stride = w * 3
    out, prev, p = [], bytearray(stride), 0
    for _ in range(h):
        ft = raw[p]
        p += 1
        line = bytearray(raw[p:p + stride])
        p += stride
        for i in range(stride):
            a = line[i - 3] if i >= 3 else 0        # left
            b = prev[i]                             # up
            c = prev[i - 3] if i >= 3 else 0        # up-left
            if ft == 1:
                line[i] = (line[i] + a) & 0xFF
            elif ft == 2:
                line[i] = (line[i] + b) & 0xFF
            elif ft == 3:
                line[i] = (line[i] + ((a + b) >> 1)) & 0xFF
            elif ft == 4:
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
            elif ft != 0:
                raise ValueError('%s uses filter type %d' % (path, ft))
        out.append([tuple(line[i:i + 3]) for i in range(0, stride, 3)])
        prev = line
    return w, h, out


def resample(rows, w, h, tw):
    """Nearest-neighbour width scale; the composite only needs a rough match."""
    th = max(1, int(round(h * tw / float(w))))
    return [[rows[min(h - 1, y * h // th)][min(w - 1, x * w // tw)]
             for x in range(tw)] for y in range(th)]


def stamp(date, time):
    y, m, d = [int(v) for v in date.split('-')]
    hh, mi = [int(v) for v in time.split(':')]
    return int((datetime.datetime(y, m, d, hh, mi)
                - datetime.datetime(1970, 1, 1)).total_seconds())


def main():
    ap = argparse.ArgumentParser(description='render the v14.0 face offline')
    ap.add_argument('--date', default='2026-09-12', help='YYYY-MM-DD, local')
    ap.add_argument('--time', default='19:06', help='HH:MM, local')
    ap.add_argument('--temp', type=int, default=31, help='degrees C as displayed')
    ap.add_argument('--mv', type=int, default=2905, help='battery mV as displayed')
    ap.add_argument('--mac', default='A1B2C3', help="the tag's own short address")
    ap.add_argument('--no-ble', action='store_true', help='disconnected: no rune')
    ap.add_argument('--debug', help='H,T,B,L counters on row 3 instead of the '
                                    'calendar, e.g. 18,0,1,2')
    ap.add_argument('--window', action='store_true',
                    help='tint the per-minute gate window')
    ap.add_argument('--compare', metavar='PNG',
                    help='stack the render under this photograph, scaled to the '
                         'same width - docs/images/reference-panel.png is the '
                         'panel the v14.0 layout was measured from')
    ap.add_argument('--zoom', type=int, default=3)
    ap.add_argument('--tag', default='v14', help='filename tag')
    args = ap.parse_args()

    face = Face()
    L = face.L
    mac = tuple(int(args.mac[i:i + 2], 16) for i in (0, 2, 4))
    debug = tuple(int(v) for v in args.debug.split(',')) if args.debug else None
    t = stamp(args.date, args.time)

    buf = new_buffer(face)
    hhmm = face.face(buf, L['FACE_W'], L['FACE_H'], t, args.mv, args.temp,
                     mac=mac, connected=not args.no_ble, debug=debug)
    rows = bits(face, buf)
    W, H = L['FACE_W'], L['FACE_H']
    VIS = L['FACE_VISIBLE_H']

    rows1 = face.row1(t, args.mv, args.temp)
    print('face: %s %s  %d C  %d mV   partial window %d..%d (%d gates, %.0f%%)'
          % (args.date, hhmm, args.temp, args.mv, L['EPD_WIN_GATE_FIRST'],
             L['EPD_WIN_GATE_LAST'], L['EPD_WIN_GATES'], L['EPD_WIN_GATES'] * 100.0 / 296))
    print('row 1: %s   (%d px, ends at %d) + "%dmV" right aligned at %d..%d'
          % (''.join(chr(c) for c in rows1), face.utext_width(rows1),
             L['ROW1_X'] + face.utext_width(rows1),
             min(args.mv, L['ROW1_MV_MAX']), face.row1_mv_x(args.mv),
             L['ROW1_RIGHT_X'] - 1))
    rx = face.row3_rune_x()
    shown = face.row3_text(t, mac)
    bx = face.row3_right_x(shown)
    other = face.mac_bracket(mac) if shown == face.row3_version() \
        else face.row3_version()
    if debug is None:
        r3 = face.row3(t)
        print('row 3: %s   (%d px, ends at %d; rune slot %d..%d; "%s" at %d..%d, ink ends %d)'
              % (''.join(chr(c) for c in r3), face.utext_width(r3),
                 L['ROW3_X'] + face.utext_width(r3), rx, rx + face.rune_w - 1,
                 shown, bx, bx + face.text_width(shown) - 1,
                 bx + face.text_width(shown) - 1 - face.text_rb(shown)))
        ox = face.row3_right_x(other)
        print('       the other half of the swap, "%s", is %d px at %d..%d, ink ends %d'
              % (other, face.text_width(other), ox,
                 ox + face.text_width(other) - 1, face.text_rb(other) and
                 ox + face.text_width(other) - 1 - face.text_rb(other)))
    else:
        print('row 3: counters H%02dT%dB%dL%d   (calendar text suppressed)'
              % debug)
    print('clock: slots %s  digit cell %d px  DSEG14 at 3/2 = %d px tall'
          % ([face.slot_x(i) for i in range(5)], L['CLOCK_CELL_W'],
             L['CLOCK_H']))

    os.makedirs(OUTDIR, exist_ok=True)
    band = (L['EPD_WIN_GATE_FIRST'], L['EPD_WIN_GATE_LAST']) if args.window else None

    # --- the whole face ---------------------------------------------------
    c = Canvas(W, VIS)
    if band:
        x0 = band[0] - L['EPD_WIN_GATE_OFFSET']
        x1 = band[1] - L['EPD_WIN_GATE_OFFSET']
        c.rect(x0, 0, x1, VIS - 1, BAND_FILL)
    c.ink(rows[:VIS], 0, 0)
    if band:
        x0 = band[0] - L['EPD_WIN_GATE_OFFSET']
        x1 = band[1] - L['EPD_WIN_GATE_OFFSET']
        c.rect(x0, 0, x1, VIS - 1, BAND_EDGE, edge=True)
    main_png = os.path.join(OUTDIR, 'screen_%s_zoom%d.png' % (args.tag, args.zoom))
    c.save(main_png, args.zoom)
    print('wrote %s  (%dx%d)' % (main_png, W * args.zoom, VIS * args.zoom))

    # --- row 3, right-hand end -------------------------------------------
    # The rune sits in a slot reserved whether or not anything is connected, so
    # the calendar text can never reach it; the red box is that slot.
    x0, y0 = max(0, rx - 24), L['ROW3_Y'] - 2
    x1, y1 = L['ROW3_RIGHT_X'] + 1, L['ROW3_Y'] + 17
    sub = Canvas(x1 - x0, y1 - y0)
    sub.ink([r[x0:x1] for r in rows[y0:y1]], 0, 0)
    sub.rect(rx - x0, L['ROW3_Y'] + 1 - y0, rx + face.rune_w - 1 - x0,
             L['ROW3_Y'] + face.rune_h - y0, BOX, edge=True)
    z = 6
    p = os.path.join(OUTDIR, 'row3_right_zoom%d.png' % z)
    sub.save(p, z)
    print('wrote %s  (red box = the rune slot %d..%d%s)'
          % (p, rx, rx + face.rune_w - 1, '' if not args.no_ble else ', empty'))

    # --- the clock --------------------------------------------------------
    x0, y0 = L['CLOCK_X0'] - 4, L['CLOCK_Y'] - 4
    x1, y1 = L['CLOCK_X0'] + L['CLOCK_WIDEST'] + 4, L['CLOCK_Y'] + L['CLOCK_H'] + 4
    sub = Canvas(x1 - x0, y1 - y0)
    sub.ink([r[x0:x1] for r in rows[y0:y1]], 0, 0)
    p = os.path.join(OUTDIR, 'clock_zoom2.png')
    sub.save(p, 2)
    print('wrote %s  (clock %d..%d)' % (p, L['CLOCK_X0'],
                                        L['CLOCK_X0'] + L['CLOCK_WIDEST'] - 1))

    # --- the reference panel, for the docs --------------------------------
    # Stacked rather than side by side: the two are the same shape, and the eye
    # reads the differences down a column far better than across a gap.
    if args.compare:
        pw, ph, pix = read_png(args.compare)
        ref = resample(pix, pw, ph, W * args.zoom)
        comp = Canvas(W * args.zoom, len(ref) + VIS * args.zoom + 30)
        comp.blit_rgb(ref, 0, 0)
        comp.blit_rgb(scale_rgb(bits_rgb(rows, W, VIS), args.zoom),
                      0, len(ref) + 30)
        p = os.path.join(OUTDIR, 'reference_vs_%s_zoom%d.png'
                         % (args.tag, args.zoom))
        comp.save(p)
        print('wrote %s  (%dx%d; top = the %dx%d reference, bottom = this render)'
              % (p, comp.w, comp.h, pw, ph))
    return 0


if __name__ == '__main__':
    sys.exit(main())
