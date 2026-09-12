#!/usr/bin/env python3
# Replicates Firmware/makefile build without GNU make.
# Run from the Firmware/ directory.
import os, sys, subprocess, glob

FW = os.path.dirname(os.path.abspath(__file__))
os.chdir(FW)

TC32 = os.path.join(FW, "tc32_windows", "bin")
GCC = os.path.join(TC32, "tc32-elf-gcc.exe")
LD  = os.path.join(TC32, "tc32-elf-ld.exe")
OBJCOPY = os.path.join(TC32, "tc32-elf-objcopy.exe")

OUT = os.path.join(FW, "out")
BIN = os.path.join(FW, "ATC_Paper.bin")
ELF = os.path.join(OUT, "ATC_Paper.elf")
LINK = os.path.join(FW, "static_src", "boot.link")
LIBDIR = os.path.join(FW, "components", "proj_lib")

GCC_FLAGS = ("-ffunction-sections -fdata-sections -Wall -O2 -fpack-struct "
             "-fshort-enums -finline-small-functions -std=gnu99 -funsigned-char "
             "-fshort-wchar -fms-extensions -Wno-unused -DCHIP_TYPE=CHIP_TYPE_8258")
INC = "-I%s -I%s" % (os.path.join(FW, "components"), os.path.join(FW, "src"))
BOOT_FLAG = "-DMCU_STARTUP_825X"

# (src_relative_path, out_subdir_under_out, extra_flags) -- exact files from the .mk lists
SOURCES = [
    # project sources (src/*.c, flat)
    ("src/app.c", "", ""),
    ("src/app_att.c", "", ""),
    ("src/battery.c", "", ""),
    ("src/ble.c", "", ""),
    ("src/epd_ble_service.c", "", ""),
    ("src/i2c.c", "", ""),
    ("src/cmd_parser.c", "", ""),
    ("src/flash.c", "", ""),
    ("src/time.c", "", ""),
    ("src/epd_spi.c", "", ""),
    ("src/epd.c", "", ""),
    ("src/epd_font.c", "", ""),
    ("src/calendar.c", "", ""),
    ("src/epd_bw_213.c", "", ""),
    ("src/epd_bwr_213.c", "", ""),
    ("src/epd_bwr_350.c", "", ""),
    ("src/epd_bwy_350.c", "", ""),
    ("src/epd_bw_213_ice.c", "", ""),
    ("src/epd_bwr_154.c", "", ""),
    ("src/ota.c", "", ""),
    ("src/led.c", "", ""),
    ("src/uart.c", "", ""),
    ("src/nfc.c", "", ""),
    ("src/tiffg4.c", "", ""),
    ("src/one_bit_display.c", "", ""),
    ("src/main.c", "", ""),
    # application
    ("components/application/app/usbaud.c", "application/app", ""),
    ("components/application/app/usbcdc.c", "application/app", ""),
    ("components/application/app/usbkb.c", "application/app", ""),
    ("components/application/app/usbmouse.c", "application/app", ""),
    ("components/application/keyboard/keyboard.c", "application/keyboard", ""),
    ("components/application/print/putchar.c", "application/print", ""),
    ("components/application/print/u_printf.c", "application/print", ""),
    ("components/application/usbstd/usb.c", "application/usbstd", ""),
    ("components/application/usbstd/usbdesc.c", "application/usbstd", ""),
    ("components/application/usbstd/usbhw.c", "application/usbstd", ""),
    # common
    ("components/common/breakpoint.c", "common", ""),
    ("components/common/log.c", "common", ""),
    ("components/common/selection_sort.c", "common", ""),
    ("components/common/string.c", "common", ""),
    ("components/common/utility.c", "common", ""),
    # vendor/common (NOTE: ev.c is intentionally NOT built)
    ("components/vendor/common/blt_common.c", "vendor/common", ""),
    ("components/vendor/common/blt_fw_sign.c", "vendor/common", ""),
    ("components/vendor/common/blt_led.c", "vendor/common", ""),
    ("components/vendor/common/blt_soft_timer.c", "vendor/common", ""),
    ("components/vendor/common/tl_audio.c", "vendor/common", ""),
    # tinyFlash
    ("components/tinyFlash/tinyFlash.c", "tinyFlash", ""),
    # drivers/8258
    ("components/drivers/8258/adc.c", "drivers/8258", ""),
    ("components/drivers/8258/aes.c", "drivers/8258", ""),
    ("components/drivers/8258/analog.c", "drivers/8258", ""),
    ("components/drivers/8258/audio.c", "drivers/8258", ""),
    ("components/drivers/8258/bsp.c", "drivers/8258", ""),
    ("components/drivers/8258/clock.c", "drivers/8258", ""),
    ("components/drivers/8258/emi.c", "drivers/8258", ""),
    ("components/drivers/8258/flash.c", "drivers/8258", ""),
    ("components/drivers/8258/gpio_8258.c", "drivers/8258", ""),
    ("components/drivers/8258/i2c.c", "drivers/8258", ""),
    ("components/drivers/8258/lpc.c", "drivers/8258", ""),
    ("components/drivers/8258/qdec.c", "drivers/8258", ""),
    ("components/drivers/8258/rf_pa.c", "drivers/8258", ""),
    ("components/drivers/8258/s7816.c", "drivers/8258", ""),
    ("components/drivers/8258/spi.c", "drivers/8258", ""),
    ("components/drivers/8258/timer.c", "drivers/8258", ""),
    ("components/drivers/8258/uart.c", "drivers/8258", ""),
    ("components/drivers/8258/watchdog.c", "drivers/8258", ""),
    # boot
    ("static_src/cstartup_825x.S", "", BOOT_FLAG),
    ("components/boot/div_mod.S", "", BOOT_FLAG),
]

def compile_one(src, outpath, extra):
    cmd = "%s %s %s %s -c -o\"%s\" \"%s\"" % (GCC, GCC_FLAGS, INC, extra, outpath, src)
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return r

def main():
    if not os.path.isfile(GCC):
        print("ERROR: tc32 compiler not found at", GCC); sys.exit(1)
    objs = []
    failures = []
    for pattern, sub, extra in SOURCES:
        for src in sorted(glob.glob(os.path.join(FW, pattern))):
            base = os.path.splitext(os.path.basename(src))[0]
            outdir = os.path.join(OUT, sub) if sub else OUT
            os.makedirs(outdir, exist_ok=True)
            outpath = os.path.join(outdir, base + ".o")
            print("CC", os.path.relpath(src, FW))
            r = compile_one(src, outpath, extra)
            if r.returncode != 0:
                failures.append((src, r.stdout, r.stderr))
                print("  -> FAILED")
                if r.stderr: print(r.stderr)
                if r.stdout: print(r.stdout)
            else:
                objs.append(outpath)
    if failures:
        print("\n=== %d file(s) failed to compile ===" % len(failures))
        sys.exit(1)
    print("\nAll %d objects compiled. Linking..." % len(objs))
    objlist = " ".join('"%s"' % o for o in objs)
    ldcmd = '%s --gc-sections -L "%s" -T "%s" -o "%s" %s -llt_8258' % (LD, LIBDIR, LINK, ELF, objlist)
    r = subprocess.run(ldcmd, shell=True, capture_output=True, text=True)
    if r.returncode != 0:
        print("LINK FAILED"); print(r.stderr); print(r.stdout); sys.exit(1)
    print("Link OK ->", ELF)
    oc = '%s -v -O binary "%s" "%s"' % (OBJCOPY, ELF, BIN)
    r = subprocess.run(oc, shell=True, capture_output=True, text=True)
    if r.returncode != 0:
        print("OBJCOPY FAILED"); print(r.stderr); sys.exit(1)
    print("BIN ->", BIN, os.path.getsize(BIN), "bytes")
    # CRC step (matches makefile)
    py = os.path.join(FW, "make", "tl_firmware_tools.py")
    r = subprocess.run('%s "%s" add_crc "%s"' % (sys.executable, py, BIN), shell=True, capture_output=True, text=True)
    if r.returncode != 0:
        print("CRC step issue (non-fatal):"); print(r.stderr); 
    else:
        print("CRC added. Final bin size:", os.path.getsize(BIN))
    print("DONE")

if __name__ == "__main__":
    main()
