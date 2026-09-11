#!/usr/bin/env python3
# BMP(250x122,24bpp) -> SSD1680 BWR-213 framebuffer (black/white plane)
# Layout: column-major, 1 byte = 8 vertical pixels, MSB = top.
#   width=250 -> 250 columns; padded height=128 -> 128/8 = 16 bytes/column
#   buffer size = 250 * 16 = 4000 bytes (the "image plane" firmware loads to 0x24 RAM)
#   red plane is forced 0x00 by firmware (EPD_BWR_213_Display), so NOT included here.
# Pixel polarity (per epd.c: memset 0xff=white, 0x00=black): black pixel -> bit 0, white -> bit 1.

import struct, sys

BMP = "test_black_250x122.bmp"
W, H = 250, 122
PAD_H = 128                     # firmware uses 128 for full bytes
COLS = W
BYTES_PER_COL = PAD_H // 8      # 16
SIZE = COLS * BYTES_PER_COL     # 4000

def load_bmp(path):
    with open(path, "rb") as f:
        d = f.read()
    sig = d[0:2]
    assert sig == b"BM", "not a BMP"
    w = struct.unpack("<I", d[18:22])[0]
    h = struct.unpack("<I", d[22:26])[0]
    bpp = struct.unpack("<H", d[28:30])[0]
    off = struct.unpack("<I", d[10:14])[0]
    assert (w, h, bpp) == (W, H, 24), f"unexpected BMP dims {w}x{h} bpp{bpp}"
    # BMP rows are stored bottom-up
    stride = (w * 3 + 3) & ~3
    px = [[0] * w for _ in range(h)]
    black = white = 0
    for y in range(h):
        row = d[off + (h - 1 - y) * stride : off + (h - 1 - y) * stride + w * 3]
        for x in range(w):
            b, g, r = row[x*3], row[x*3+1], row[x*3+2]
            lum = (r + g + b) // 3
            if lum < 128:
                px[y][x] = 0   # black
                black += 1
            else:
                px[y][x] = 1   # white
                white += 1
    return px, black, white

def to_framebuffer(px):
    buf = bytearray(SIZE)
    for x in range(COLS):
        for br in range(BYTES_PER_COL):
            byte = 0
            for bit in range(8):
                y = br * 8 + bit
                if y < H:
                    if px[y][x] == 1:        # white -> set bit (MSB=top)
                        byte |= (0x80 >> bit)
                    # black -> leave bit 0
            buf[x * BYTES_PER_COL + br] = byte
    return bytes(buf)

def main():
    px, black, white = load_bmp(BMP)
    print(f"pixels: black={black} white={white} total={black+white}")
    buf = to_framebuffer(px)

    # raw binary
    with open("test_black_250x122_framebuffer.bin", "wb") as f:
        f.write(buf)

    # hex text, 16 bytes/line
    lines = []
    for i in range(0, len(buf), 16):
        chunk = buf[i:i+16]
        lines.append(" ".join(f"{b:02X}" for b in chunk))
    with open("test_black_250x122_pixelcode.txt", "w") as f:
        f.write(f"// SSD1680 BWR-213 framebuffer (black/white plane)\n")
        f.write(f"// {W}x{H} image, padded to {W}x{PAD_H}, column-major, 1B=8 vertical px, MSB=top\n")
        f.write(f"// polarity: 0x00=BLACK, 0xFF=WHITE (per firmware epd.c)\n")
        f.write(f"// size = {SIZE} bytes; red plane forced 0x00 by firmware\n")
        f.write(f"// ALL BLACK image -> every byte is 0x00\n\n")
        f.write("\n".join(lines))
        f.write("\n")

    # C array
    with open("test_black_250x122_pixelcode.h", "w") as f:
        f.write(f"// SSD1680 BWR-213 framebuffer, pure-BLACK 250x122 image\n")
        f.write(f"// {SIZE} bytes, column-major, 0x00=black. Red plane = 0x00 (firmware).\n")
        f.write(f"#define EPD_FB_SIZE {SIZE}\n")
        f.write("const uint8_t epd_black_framebuffer[EPD_FB_SIZE] = {\n")
        for i in range(0, len(buf), 16):
            chunk = buf[i:i+16]
            f.write("  " + ", ".join(f"0x{b:02X}" for b in chunk) + ",\n")
        f.write("};\n")

    # BLE command form (minimal): clear-to-black then push
    with open("test_black_250x122_ble_cmds.txt", "w") as f:
        f.write("// Minimal BLE writes to show SOLID BLACK (no need to send 4000 bytes):\n")
        f.write("//   opcode 0x00 + fill byte 0x00  -> memset(epd_buffer, 0x00) = all black\n")
        f.write("//   opcode 0x01                  -> EPD_Display() push to screen\n")
        f.write("00 00\n")
        f.write("01\n")

    print(f"wrote framebuffer ({SIZE} bytes), pixelcode.txt, pixelcode.h, ble_cmds.txt")
    print(f"unique byte values in buffer: {{ {', '.join(sorted(set(f'0x{b:02X}' for b in buf)))} }}")

if __name__ == "__main__":
    main()
