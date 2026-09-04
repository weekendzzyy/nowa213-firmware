#!/usr/bin/env python3
# =============================================================================
# Nowa-213R-N (TLSR8359 + BW213, 250x128) EPD image helper
# -----------------------------------------------------------------------------
# Two fast ways to verify an image WITHOUT the slow "flash -> BLE upload -> look"
# loop:
#
#   1) PREVIEW  (no device at all, ~2s):
#      Renders what the screen WILL show under v3 (fixed) vs v2 (buggy).
#        - v3 fixed : render the framebuffer as-is  (firmware flips once, the
#                     panel's right->left column scan mirrors it back -> correct)
#        - v2 buggy : render the HORIZONTALLY MIRRORED framebuffer (what v2 did:
#                     raw send + 5000-byte overflow black band on the right)
#
#   2) BAKE + direct flash (skip BLE entirely):
#      Build the 0x79000 user-image sector (magic "IMG1" + flipped pixels) and
#      write ONLY that 4KB sector with the SWS flasher. v3 firmware is already
#      on the device, so after a power-cycle it shows the new image. No full
#      reflash, no BLE upload.
#
# Framebuffer layout (matches firmware epd.c / epd_ble_service.c):
#   4000 bytes = 250 columns x 16 bytes/column (128 rows / 8 bits per byte)
#   column c      -> bytes [c*16 .. c*16+15]
#   row y in col  -> byte index (y//8), bit (7 - (y % 8))
#   0x00 = BLACK pixel, 0xFF = WHITE pixel   (epd.c: memset(epd_buffer,0xff)=white)
#
# The BW213 controller scans columns right->left, so a raw framebuffer appears
# horizontally mirrored on the glass. v3 calls user_image_flip_horizontal() once
# before display/save so the mirror cancels. v2 sent the raw buffer (no flip)
# and used epd_buffer_size=5000 (extra 1000 bytes -> right-side black band).
# =============================================================================
import os, sys, argparse, subprocess
from PIL import Image, ImageDraw, ImageFont

W, H = 250, 128
FB = W * (H // 8)          # 4000
MAGIC = b'IMG1'            # little-endian 0x31474D49, written LAST by firmware

def image_to_framebuffer(path, invert=False):
    """Load an image, resize to 250x128, threshold to 1bpp EPD framebuffer.
    dark pixel -> 0 (black), light pixel -> 1 (white)."""
    img = Image.open(path).convert('L').resize((W, H))
    buf = bytearray(FB)
    for col in range(W):
        for row in range(H):
            px = img.getpixel((col, row))
            bit = 0 if px < 128 else 1
            if invert:
                bit ^= 1
            if bit:
                buf[col * 16 + row // 8] |= (0x80 >> (row % 8))
    return bytes(buf)

def raw_to_framebuffer(path):
    with open(path, 'rb') as f:
        data = f.read(FB)
    if len(data) < FB:
        data = data + b'\xff' * (FB - len(data))
    return data

def flip_horizontal(buf):
    """Mirror columns: swap col c with col (W-1-c). 16 bytes per column.
    This is exactly what firmware user_image_flip_horizontal() does."""
    out = bytearray(buf)
    for c in range(W // 2):
        a, b = c * 16, (W - 1 - c) * 16
        for k in range(16):
            out[a + k], out[b + k] = buf[b + k], buf[a + k]
    return bytes(out)

def framebuffer_to_image(buf):
    img = Image.new('L', (W, H), 255)
    px = img.load()
    for col in range(W):
        for row in range(H):
            byte = buf[col * 16 + row // 8]
            bit = (byte >> (7 - (row % 8))) & 1
            px[col, row] = 0 if bit == 0 else 255
    return img

def _label(img, text, fill=0):
    """Draw a small caption above the panel (adds 16px headroom)."""
    h = img.height + 16
    canvas = Image.new('L', (img.width, h), 255)
    canvas.paste(img, (0, 16))
    d = ImageDraw.Draw(canvas)
    try:
        f = ImageFont.load_default()
    except Exception:
        f = None
    d.text((2, 2), text, fill=fill, font=f)
    return canvas

def render_previews(buf, outdir, name):
    os.makedirs(outdir, exist_ok=True)
    v3 = _label(framebuffer_to_image(buf), "v3 FIXED (correct orientation)")
    v2 = _label(framebuffer_to_image(flip_horizontal(buf)),
                "v2 BUGGY (mirrored + right black band)")
    v3p = os.path.join(outdir, f'{name}_v3_fixed.png'); v3.save(v3p)
    v2p = os.path.join(outdir, f'{name}_v2_buggy.png');  v2.save(v2p)
    pad = 16
    combo = Image.new('L', (W * 2 + pad, H + 16), 255)
    combo.paste(v3.crop((0, 16, W, H + 16)), (0, 16))
    combo.paste(v2.crop((0, 16, W, H + 16)), (W + pad, 16))
    combop = os.path.join(outdir, f'{name}_compare.png'); combo.save(combop)
    return v3p, v2p, combop

def bake_sector(buf, outdir, name):
    """Store the FLIPPED buffer: v3's restore path displays it raw, the panel's
    right->left scan mirrors it back -> correct orientation. Magic first."""
    flipped = flip_horizontal(buf)
    sector = MAGIC + flipped                     # 4 + 4000 = 4004
    sector = sector + b'\xff' * (4096 - len(sector))  # pad to one 4KB sector
    path = os.path.join(outdir, f'{name}_flash_sector.bin')
    with open(path, 'wb') as f:
        f.write(sector)
    return path

def main():
    ap = argparse.ArgumentParser(description='Nowa-213R-N EPD image helper')
    ap.add_argument('input', help='image (png/jpg/bmp) OR raw .bin framebuffer')
    ap.add_argument('--outdir', default='epd_preview')
    ap.add_argument('--name', default='img')
    ap.add_argument('--invert', action='store_true', help='invert polarity')
    ap.add_argument('--bake', action='store_true', help='write 0x79000 flash sector .bin')
    ap.add_argument('--flash', action='store_true',
                    help='also flash the sector to 0x79000 via SWS (device on COM6)')
    args = ap.parse_args()

    ext = os.path.splitext(args.input)[1].lower()
    buf = raw_to_framebuffer(args.input) if ext == '.bin' else image_to_framebuffer(args.input, args.invert)

    v3p, v2p, combop = render_previews(buf, args.outdir, args.name)
    print('Previews written:')
    print('  v3 fixed :', v3p)
    print('  v2 buggy :', v2p)
    print('  compare  :', combop)
    print('=> v3_fixed.png is what the screen shows after the v3 fix (correct).')
    print('=> v2_buggy.png is what v2 showed (mirrored, with right black band).')

    if args.bake or args.flash:
        sector = bake_sector(buf, args.outdir, args.name)
        print('\nBaked sector:', sector, '(magic IMG1 + flipped pixels, 4096 bytes)')
        flasher = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               'TlsrComSwireWriter', 'TLSR825xComFlasher.py')
        cmd = [sys.executable, flasher, '-p', 'COM6', '-t', '3000', 'wf', '0x79000', sector]
        print('Flash command:', ' '.join(cmd))
        if args.flash:
            print('Flashing...')
            subprocess.run(cmd, check=True)
            print('Done. Power-cycle the tag to see the new image.')

if __name__ == '__main__':
    main()
