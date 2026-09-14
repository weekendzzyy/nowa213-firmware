#!/usr/bin/env python3
# sim_cal_font.py - OFFLINE simulation only. Overrides CAL_INFO_* ratios in
# memory (never touches epd_layout.h / firmware). Renders the v15.x calendar
# page at candidate font sizes so the user can SEE the result before flashing.
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))   # .../nowa213/tools
sys.path.insert(0, HERE)
from epd_face_model import Face, bits, new_buffer

# Repo root = parent of tools/; previews go to the repo-level previews/.
ROOT = os.path.abspath(os.path.join(HERE, '..'))
OUT = os.path.join(ROOT, 'previews')
os.makedirs(OUT, exist_ok=True)

def render(tag, d_ratio, h_ratio, date='2026-09-13', zoom=4):
    face = Face()
    L = face.L
    # Macros stores #defines as a string-expr dict; override + clear eval cache.
    L.obj['CAL_INFO_DIGIT_RATIO'] = str(d_ratio)
    L.obj['CAL_INFO_HAN_RATIO'] = str(h_ratio)
    L._cache = {}
    W, H = L['FACE_W'], L['FACE_H']
    VIS = L['FACE_VISIBLE_H']
    t = face.cal_stamp(date, '19:06') if hasattr(face, 'cal_stamp') \
        else _stamp(date, '19:06')
    pb = new_buffer(face); pr = new_buffer(face)
    face.calendar_page(pb, W, H, t, 2905, 0)
    face.calendar_page(pr, W, H, t, 2905, 1)
    c = Canvas(W, VIS)
    c.ink_two(bits(face, pb)[:VIS], bits(face, pr)[:VIS], 0, 0)
    p = os.path.join(OUT, 'sim_cal_%s_zoom%d.png' % (tag, zoom))
    c.save(p, zoom)
    # measure worst-case widths
    widths = {
        'title 2026年12月': _w(face, '2026年12月', d_ratio, h_ratio),
        'term  10天后秋分': _w(face, '10天后秋分', d_ratio, h_ratio),
        'lunar 闰二月初二': _w(face, '闰二月初二', d_ratio, h_ratio),
        'volt  9999mV': _w(face, '9999mV', d_ratio, h_ratio),
    }
    print('%-22s d=%d%% h=%d%%  colW=%d  widths=%s'
          % (tag, d_ratio, h_ratio, L['CAL_INFO_WIDTH'], widths))
    print('  wrote %s' % p)
    return p

def _w(face, s, d_ratio, h_ratio):
    # mirror of info_center_mixed width math
    w = 0
    for ch in s:
        cp = ord(ch)
        r = d_ratio if cp < 0x2E80 else h_ratio
        w += (8 if cp < 0x2E80 else 16) * r // 100
    return w

def _stamp(date, time):
    import datetime
    y, m, d = [int(v) for v in date.split('-')]
    hh, mi = [int(v) for v in time.split(':')]
    return int((datetime.datetime(y, m, d, hh, mi)
                - datetime.datetime(1970, 1, 1)).total_seconds())

# minimal Canvas copy (same as render_screen_preview.py)
import struct, zlib
PAPER=(246,245,240); INK=(24,24,26); RED=(176,38,40)
class Canvas(object):
    def __init__(self, w, h, bg=PAPER):
        self.w, self.h = w, h; self.p = [bg]*(w*h)
    def ink_two(self, rb, rr, x0, y0):
        for y in range(min(self.h-y0, len(rb), len(rr))):
            base=(y0+y)*self.w
            for x in range(min(self.w-x0, len(rb[y]), len(rr[y]))):
                if rr[y][x]: self.p[base+x0+x]=RED
                elif rb[y][x]: self.p[base+x0+x]=INK
    def scaled(self, z):
        out=Canvas(self.w*z, self.h*z)
        for y in range(self.h):
            for x in range(self.w):
                c=self.p[y*self.w+x]
                for dy in range(z):
                    b=(y*z+dy)*out.w+x*z
                    for dx in range(z): out.p[b+dx]=c
        return out
    def save(self, path, z=1):
        img=self.scaled(z) if z!=1 else self
        raw=bytearray()
        for y in range(img.h):
            raw.append(0)
            for p in img.p[y*img.w:(y+1)*img.w]: raw+=bytes(p)
        def chunk(tag,data):
            return (struct.pack('>I',len(data))+tag+data
                    +struct.pack('>I',zlib.crc32(tag+data)&0xFFFFFFFF))
        with open(path,'wb') as f:
            f.write(b'\x89PNG\r\n\x1a\n'
                    +chunk(b'IHDR',struct.pack('>IIBBBBB',img.w,img.h,8,2,0,0,0))
                    +chunk(b'IDAT',zlib.compress(bytes(raw),9))
                    +chunk(b'IEND',b''))

if __name__ == '__main__':
    # current (v15.6) baseline vs max
    render('d75h50', 75, 50)   # current 6px digit / 8px Han
    render('d100h100', 100, 100)  # max: full Unifont 8px/16px
    render('d100h94', 100, 94)    # alt: full digits, Han slightly trimmed
