#include <stdint.h>
#include "tl_common.h"
#include "main.h"
#include "epd.h"
#include "epd_spi.h"
#include "epd_bw_213.h"
#include "drivers.h"
#include "stack/ble/ble.h"

// UC8151C or similar EPD Controller

// v5.0 power saving: frame count of the lightweight per-minute waveform.
// Fewer frames = less panel drive energy, at the cost of slightly weaker ink
// transitions (ghosting). Was 10; the hourly full refresh clears any residue.
// If digits ever look faint or ghosted, raise this back to 8 or 10.
#define lut_bw_213_refresh_time 7
uint8_t lut_bw_213_20_part[] =
    {
        0x20, 0x00, lut_bw_213_refresh_time, 0x01, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00
    };
uint8_t lut_bw_213_22_part[] =
    {
        0x22, 0x80, lut_bw_213_refresh_time, 0x01, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00
    };
uint8_t lut_bw_213_23_part[] =
    {
        0x23, 0x40, lut_bw_213_refresh_time, 0x01, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00
    };

// ============================================================================
// v6.0 — true partial-window refresh (power saving)
// ----------------------------------------------------------------------------
// The controller behind this driver is an IL0373. That is not a guess: the exact
// command set used below (0x00 PSR / 0x61 TRES / 0x50 CDI / 0x20-0x24 LUTs /
// 0x10 DTM1 / 0x13 DTM2 / 0x12 DRF / 0x07 DSLP) is the IL0373 one, and it is a
// DIFFERENT family from the SSD1675/SSD1680 style used by epd_bwr_213.c. Facts
// taken from the IL0373 datasheet (verified register by register):
//
//   * IL0373 has NO 0x44 / 0x45 / 0x4E / 0x4F RAM window registers at all.
//     The only windowing mechanism is 0x90 PTL (Partial Window), used together
//     with 0x91 PTIN (Partial In) and 0x92 PTOUT (Partial Out).
//   * PTL takes exactly 7 data bytes:
//         HRST[7:3], HRED[7:3], VRST[8], VRST[7:0], VRED[8], VRED[7:0], PT_SCAN
//     HRST/HRED address the SOURCE axis in 8-pixel banks, so the byte to write
//     is (pixel & 0xF8).  VRST/VRED are GATE numbers 0..295, sent high byte
//     first (only bit 0 of the first byte is used).
//   * PT_SCAN = 0 -> "Gates scan only inside of the window" (1 = only outside,
//     which is the power-on default).  This is what actually saves energy: with
//     PT_SCAN = 0 the refresh drives only the window instead of all ~296 gates.
//   * Geometry comes from PSR (0x00) + TRES (0x61) here:
//         HRES = 128 source channels -> the 122-pixel VISIBLE axis (glass rows)
//         VRES = 296 gate lines      -> the 250-pixel axis        (glass cols)
//     Data group k (16 source bytes) lands on gate line k, and the glass shows
//     gate line k at column (249 - k); glass row y = source line y.  This is the
//     same mapping the image path and FixBuffer() already rely on.
//
// The DATA PATH IS DELIBERATELY UNCHANGED: the full 250x16-byte frame is still
// streamed exactly as before, only the scanned window shrinks.  So the worst
// case for a wrong window is NOT garbage on screen but simply that the clock
// digits stop updating -- and setting EPD_USE_PARTIAL_WINDOW to 0 below restores
// the previous full-panel behaviour with a single define.
//
// The window is derived from the DSEG14_Classic_Mini_Regular_40 glyph metrics
// used by epd_display(): the "%02d:%02d" string drawn at (50,65) has ink inside
// glass x in [54,190] and y in [25,64].  Both ranges are padded below.
// ============================================================================
#define EPD_USE_PARTIAL_WINDOW 1

#define EPD_WIN_SRC_START   24   // glass row  (source axis, value is bank-aligned)
#define EPD_WIN_SRC_END     71   // glass row  (bank 8 covers rows 64..71)
#define EPD_WIN_GLASS_X0    50   // glass column, left edge of the window
#define EPD_WIN_GLASS_X1   194   // glass column, right edge of the window
#define EPD_WIN_GATE_FIRST  (249 - EPD_WIN_GLASS_X1)   // 55
#define EPD_WIN_GATE_LAST   (249 - EPD_WIN_GLASS_X0)   // 199

#if (EPD_WIN_SRC_END & 0xF8) <= (EPD_WIN_SRC_START & 0xF8)
#error "partial window: HRED must be a higher bank than HRST"
#endif
#if EPD_WIN_GATE_LAST <= EPD_WIN_GATE_FIRST || EPD_WIN_GATE_LAST > 295
#error "partial window: gate range must satisfy VRST < VRED <= 295"
#endif

// Program the PTL window and enter partial mode.  Called on every per-minute
// refresh; the panel is hardware-reset at the start of each EPD_Display(), so
// this state never leaks into the next full refresh (which also sends PTOUT).
static void EPD_BW_213_set_partial_window(void)
{
    EPD_WriteCmd(0x91);                                          // PTIN: enter partial mode
    EPD_WriteCmd(0x90);                                          // PTL : set partial window
    EPD_WriteData((uint8_t)(EPD_WIN_SRC_START & 0xF8));          // HRST[7:3] source start bank
    EPD_WriteData((uint8_t)(EPD_WIN_SRC_END & 0xF8));            // HRED[7:3] source end bank
    EPD_WriteData((uint8_t)((EPD_WIN_GATE_FIRST >> 8) & 0x01));  // VRST[8]
    EPD_WriteData((uint8_t)(EPD_WIN_GATE_FIRST & 0xFF));         // VRST[7:0]
    EPD_WriteData((uint8_t)((EPD_WIN_GATE_LAST >> 8) & 0x01));   // VRED[8]
    EPD_WriteData((uint8_t)(EPD_WIN_GATE_LAST & 0xFF));          // VRED[7:0]
    EPD_WriteData(0x00);                                         // PT_SCAN = 0: scan only INSIDE
}


_attribute_ram_code_ uint8_t EPD_BW_213_read_temp(void)
{
    uint8_t epd_temperature = 0 ;
    EPD_WriteCmd(0x04);

    // check BUSY pin
    EPD_CheckStatus(100);

    EPD_WriteCmd(0x40);
    epd_temperature = EPD_SPI_read();
    EPD_SPI_read();

    // power off
    EPD_WriteCmd(0x02);

    // deep sleep
    EPD_WriteCmd(0x07);
    EPD_WriteData(0xa5);

    return epd_temperature;
}

_attribute_ram_code_ uint8_t EPD_BW_213_Display(unsigned char *image, int size, uint8_t full_or_partial)
{
    uint8_t epd_temperature = 0 ;
    
    // Booster soft start
    EPD_WriteCmd(0x06);
    EPD_WriteData(0x17);
    EPD_WriteData(0x17);
    EPD_WriteData(0x17);
    // power on
    EPD_WriteCmd(0x04);

    // check BUSY pin
    EPD_CheckStatus(100);

    EPD_WriteCmd(0x40);
    epd_temperature = EPD_SPI_read();
    EPD_SPI_read();

    // panel setting
    EPD_WriteCmd(0x00);
    if (full_or_partial)
        EPD_WriteData(0b00011111);
    else
        EPD_WriteData(0b00111111);
    EPD_WriteData(0x0f);

    // resolution setting
    EPD_WriteCmd(0x61);
    EPD_WriteData(0x80);
    EPD_WriteData(0x01);
    EPD_WriteData(0x28);

    // Vcom and data interval setting
    EPD_WriteCmd(0X50);
    EPD_WriteData(0x97);

    if (!full_or_partial)
    {
        EPD_send_lut(lut_bw_213_20_part, sizeof(lut_bw_213_20_part));
        EPD_send_empty_lut(0x21, 260);
        EPD_send_lut(lut_bw_213_22_part, sizeof(lut_bw_213_22_part));
        EPD_send_lut(lut_bw_213_23_part, sizeof(lut_bw_213_23_part));
        EPD_send_empty_lut(0x24, 260);

#if EPD_USE_PARTIAL_WINDOW
        // v6.0: make this a REAL partial refresh - the IL0373 will only scan and
        // drive the clock-digit rectangle instead of the whole panel.
        EPD_BW_213_set_partial_window();
#endif

        EPD_WriteCmd(0x10);
        int i;
        for (i = 0; i < size; i++)
        {
            EPD_WriteData(~image[i]);
        }
    }
    else
    {
        // v6.0: explicitly leave partial mode before a full refresh.  Without
        // this, a full refresh could inherit the PTL window set by an earlier
        // partial one and would then stop clearing ghosting over the rest of
        // the panel.  (The hardware reset in EPD_Display() also clears PTL;
        // this is a second, explicit guarantee.)
        EPD_WriteCmd(0x92); // PTOUT
    }
    // load image data to EPD
    EPD_LoadImage(image, size, 0x13);

    // trigger display refresh
    EPD_WriteCmd(0x12);

    return epd_temperature;
}

_attribute_ram_code_ void EPD_BW_213_set_sleep(void)
{
    // Vcom and data interval setting
    EPD_WriteCmd(0x50);
    EPD_WriteData(0xf7);

    // power off
    EPD_WriteCmd(0x02);

    // deep sleep
    EPD_WriteCmd(0x07);
    EPD_WriteData(0xa5);

}