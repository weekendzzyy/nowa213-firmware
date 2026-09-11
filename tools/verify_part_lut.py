#!/usr/bin/env python3
"""Verify the SSD1680 partial waveform (register 0x32) used by epd_bwr_213.c.

Layout of the 153-byte waveform setting, from the SSD1680 datasheet Rev 0.14,
Figure 6-6 "Waveform Setting mapping" (p.15):

    WS   0.. 59   VS[nX-LUTm]       5 LUTs x 12 bytes
                                    (12 groups x 4 phases x 2 bit = 96 bit)
    WS  60..119   TP[nX] + RP[n]    12 groups x (TP_A, TP_B, TP_C, TP_D, RP)
    WS 120..143   SR[nAB], SR[nCD]  12 groups x 2
    WS 144..149   FR[n]             12 groups x 3 bit, padded to a nibble
    WS 150..152   XON[nAB/ nCD]     12 groups x 2 bit
    WS 153..158   OPT / VGHL / VSH1 / VSH2 / VCOM -> registers 0x3F / 0x03 /
                  0x04 / 0x2C, i.e. NOT part of the 0x32 payload.

So the array in epd_bwr_213.c must be exactly 153 bytes, and the length of the
partial refresh waveform is set by TP[0A] (WS byte 60) because every other
TP/RP/SR value in this particular table is 0 (TP=0 -> phase skipped,
RP=0/SR=0 -> repeat once).

Usage:
    python tools/verify_part_lut.py                 # source layout check
    python tools/verify_part_lut.py <firmware.bin>  # + scan the image

Note on the firmware image: LUT_bwr_213_part lives in .data, so its bytes appear
in the .bin at (LMA of .data) + (symbol VMA - VMA of .data start).  For the
current build .data is linked at VMA 0x848900 / LMA 0x15FB0 (see
`tc32-elf-objdump -h out/ATC_Paper.elf`), which puts this table at 0x1605C.
A second, byte-identical 153-byte table in the image is LUT_bwr_154_part of the
1.54" model - a different array that happens to carry the same waveform, NOT a
stale copy of this one.  That is why editing BWR_213_Len changes only the first
hit (plus the 4-byte trailing CRC).
"""

import re
import sys

SRC = 'atc1441_src/Firmware/src/epd_bwr_213.c'
LUT_LEN = 153


def parse_source(path=SRC):
    text = open(path, encoding='utf-8').read()

    m = re.search(r'#define\s+BWR_213_Len\s+(\d+)', text)
    if not m:
        raise SystemExit('FAIL: cannot find #define BWR_213_Len')
    tp0a = int(m.group(1))

    body = re.search(r'uint8_t\s+LUT_bwr_213_part\s*\[\s*\]\s*=\s*\{(.*?)\};',
                     text, re.S)
    if not body:
        raise SystemExit('FAIL: cannot find LUT_bwr_213_part[]')
    body = re.sub(r'//[^\n]*', '', body.group(1))
    body = body.replace('BWR_213_Len', str(tp0a))
    data = [int(tok, 0) for tok in body.split(',') if tok.strip()]
    return tp0a, data


def report(tp0a, data):
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(('  PASS  ' if cond else '  FAIL  ') + msg)
        if not cond:
            ok = False

    print('LUT_bwr_213_part[] : %d bytes' % len(data))
    chk(len(data) == LUT_LEN, 'payload is %d bytes (expected %d)' % (len(data), LUT_LEN))
    if len(data) != LUT_LEN:
        return ok

    print('\n-- VS section, WS 0..59 (5 LUTs x 12 bytes) --')
    for i in range(5):
        seg = data[i * 12:(i + 1) * 12]
        vs = (seg[0] >> 6) & 3          # D7,D6 = phase A of group 0
        names = {0: 'VSS', 1: 'VSH1', 2: 'VSL', 3: 'VSH2'}
        print('    LUT%d phase-0A VS = %s   (first byte 0x%02X)'
              % (i, names[vs], seg[0]))
    print('\n-- TP / RP, WS 60..119 (12 groups x 5 bytes) --')
    active = []
    for g in range(12):
        seg = data[60 + g * 5:60 + (g + 1) * 5]
        if any(seg):
            active.append((g, seg))
    for g, seg in active:
        print('    group %-2d TP A/B/C/D = %s   RP = %d' % (g, seg[:4], seg[4]))
    chk(len(active) == 1 and active[0][0] == 0,
        'exactly one group is active, and it is group 0')
    chk(g_data_ok(data, tp0a), 'group 0 = TP A=%d, TP B/C/D=0, RP=0' % tp0a)

    print('\n-- SR, WS 120..143 --')
    chk(all(v == 0 for v in data[120:144]), 'all SR[AB]/SR[CD] = 0 (repeat once)')

    print('\n-- FR, WS 144..149 --')
    fr = [((b >> 4) & 0xF, b & 0xF) for b in data[144:150]]
    flat = [v for pair in fr for v in pair]
    print('    FR nibbles: %s' % ' '.join('%X' % v for v in flat))
    chk(all(v == 2 for v in flat), 'every FR[n] nibble = 2')

    print('\n-- XON, WS 150..152 --')
    chk(all(v == 0 for v in data[150:153]),
        'all XON = 0 -> normal gate scan inside the window')

    print('\nwaveform length = %d frames (only TP[0A] is non zero)' % tp0a)
    return ok


def g_data_ok(data, tp0a):
    seg = data[60:65]
    return seg == [tp0a, 0, 0, 0, 0]


def scan_bin(path, data):
    blob = open(path, 'rb').read()
    pat = bytes(data)
    hits = []
    start = 0
    while True:
        i = blob.find(pat, start)
        if i < 0:
            break
        hits.append(i)
        start = i + 1
    print('\n-- scan %s --' % path)
    print('    image size %d bytes' % len(blob))
    if not hits:
        print('  FAIL  the 153-byte LUT pattern is not present')
        return False
    for i in hits:
        print('  PASS  found at 0x%X ; WS[60] = %d frames' % (i, blob[i + 60]))
    return True


def main():
    tp0a, data = parse_source()
    ok = report(tp0a, data)
    if len(sys.argv) > 1:
        ok = scan_bin(sys.argv[1], data) and ok
    print('\nRESULT: %s' % ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
