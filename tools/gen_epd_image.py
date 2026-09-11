#!/usr/bin/env python3
"""
Generate EPD test images + framebuffers for atc1441 Stellar-M BWR213 firmware.

The firmware treats the panel as 250 columns x 128 rows (122 real + 6 padding),
organized column-major: each byte holds 8 vertical pixels of one column,
MSB = top pixel. 0x00 = black, 0xFF = white.

Output formats:
  - 24-bit BMP (250x128, bottom-up, no padding)
  - raw SSD1680 column-major frame buffer (.bin, 4000 bytes for 250x128)
  - hex text (.txt)
  - C array (.h)
  - minimal BLE command text (.txt)  [opcode 0x00 fill + 0x01 display]
"""
import struct
import sys

WIDTH = 250
HEIGHT = 128  # must be multiple of 8
BYTES_PER_COL = HEIGHT // 8
FB_SIZE = WIDTH * BYTES_PER_COL  # 4000 bytes for 250x128


def write_bmp(path: str, pixels):
    """pixels: 2D list[y][x], 0=black, 255=white.  Bottom-up BMP."""
    h = len(pixels)
    w = len(pixels[0])
    row_size = ((w * 3 + 3) // 4) * 4
    img_size = row_size * h
    file_size = 54 + img_size
    header = struct.pack(
        "<2sIHHI",
        b"BM",
        file_size,
        0,
        0,
        54,
    )
    dib = struct.pack(
        "<IiiHHIIiiII",
        40,     # biSize
        w,      # biWidth
        h,      # biHeight (positive = bottom-up)
        1,      # biPlanes
        24,     # biBitCount
        0,      # biCompression
        img_size,
        2835,   # biXPelsPerMeter
        2835,   # biYPelsPerMeter
        0,      # biClrUsed
        0,      # biClrImportant
    )
    rows = []
    for y in range(h - 1, -1, -1):
        row = bytearray()
        for x in range(w):
            v = pixels[y][x]
            row += bytes([v, v, v])
        row += b"\x00" * (row_size - len(row))
        rows.append(bytes(row))
    with open(path, "wb") as f:
        f.write(header + dib + b"".join(rows))


def to_framebuffer(pixels):
    """Convert 250x128 row-major pixel array to SSD1680 column-major buffer."""
    fb = bytearray(FB_SIZE)
    for x in range(WIDTH):
        for byte_y in range(BYTES_PER_COL):
            b = 0
            for bit in range(8):
                y = byte_y * 8 + bit
                if pixels[y][x] == 0:  # black -> bit 0
                    pass  # bit stays 0
                else:  # white -> bit 1
                    b |= 1 << (7 - bit)  # MSB at top
            fb[x * BYTES_PER_COL + byte_y] = b
    return fb


def main():
    # Build 250x128 pure-black image
    pixels = [[0 for _ in range(WIDTH)] for _ in range(HEIGHT)]
    fb = to_framebuffer(pixels)

    # Verify every byte is 0x00
    assert fb == bytearray(FB_SIZE), "expected pure black frame buffer"

    stem = "test_black_250x128"
    write_bmp(f"{stem}.bmp", pixels)
    with open(f"{stem}_framebuffer.bin", "wb") as f:
        f.write(fb)
    with open(f"{stem}_pixelcode.txt", "w") as f:
        f.write(fb.hex())
    with open(f"{stem}_pixelcode.h", "w") as f:
        f.write(f"const unsigned char {stem}_fb[{FB_SIZE}] = {{\n")
        for i in range(0, FB_SIZE, 16):
            line = ", ".join(f"0x{b:02x}" for b in fb[i : i + 16])
            f.write(f"    {line},\n")
        f.write("};\n")
    with open(f"{stem}_ble_cmds.txt", "w") as f:
        f.write("Minimal BLE writes to turn the whole screen black (uses opcode 0x00 fill):\n")
        f.write("00 00   -> memset(epd_buffer, 0x00)  [entire buffer black]\n")
        f.write("01      -> EPD_Display()            [push to panel]\n")

    print(f"Generated {stem}.bmp ({WIDTH}x{HEIGHT})")
    print(f"Frame buffer: {FB_SIZE} bytes, all 0x00")


if __name__ == "__main__":
    main()
