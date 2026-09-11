#include <stdint.h>
#include "tl_common.h"
#include "main.h"
#include "epd.h"
#include "epd_spi.h"
#include "epd_bwr_213.h"
#include "drivers.h"
#include "stack/ble/ble.h"

// SSD1675 mixed with SSD1680 EPD Controller

#define BWR_213_Len 50
uint8_t LUT_bwr_213_part[] = {

0x40, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
0x40, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,

BWR_213_Len, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
0x22, 0x22, 0x22, 0x22, 0x22, 0x22, 
0x00, 0x00, 0x00, 

};

#define EPD_BWR_213_test_pattern 0xA5
_attribute_ram_code_ uint8_t EPD_BWR_213_detect(void)
{
    // SW Reset
    EPD_WriteCmd(0x12);
    WaitMs(10);

    EPD_WriteCmd(0x32);
    int i;
    for (i = 0; i < 153; i++)// This model has a 159 bytes LUT storage so we test for that
    {
        EPD_WriteData(EPD_BWR_213_test_pattern);
    }
    EPD_WriteCmd(0x33);
    for (i = 0; i < 153; i++)
    {
        if(EPD_SPI_read() != EPD_BWR_213_test_pattern)
            return 0;
    }
    return 1;
}

_attribute_ram_code_ uint8_t EPD_BWR_213_read_temp(void)
{
    uint8_t epd_temperature = 0 ;
    
    // SW Reset
    EPD_WriteCmd(0x12);

    EPD_CheckStatus_inverted(100);

    // Set Analog Block control
    EPD_WriteCmd(0x74);
    EPD_WriteData(0x54);
    // Set Digital Block control
    EPD_WriteCmd(0x7E);
    EPD_WriteData(0x3B);

    // Booster soft start
    EPD_WriteCmd(0x0C);
    EPD_WriteData(0x8B);
    EPD_WriteData(0x9C);
    EPD_WriteData(0x96);
    EPD_WriteData(0x0F);

    // Driver output control
    EPD_WriteCmd(0x01);
    EPD_WriteData(0x28);
    EPD_WriteData(0x01);
    EPD_WriteData(0x01);

    // Data entry mode setting
    EPD_WriteCmd(0x11);
    EPD_WriteData(0x01);

    // Set RAM X- Address Start/End
    EPD_WriteCmd(0x44);
    EPD_WriteData(0x00);
    EPD_WriteData(0x0F);

    // Set RAM Y- Address Start/End
    EPD_WriteCmd(0x45);
    EPD_WriteData(0x28);
    EPD_WriteData(0x01);
    EPD_WriteData(0x2E);
    EPD_WriteData(0x00);

    // Border waveform control
    EPD_WriteCmd(0x3C);
    EPD_WriteData(0x05);

    // Display update control
    EPD_WriteCmd(0x21);
    EPD_WriteData(0x00);
    EPD_WriteData(0x80);

    // Temperature sensor control
    EPD_WriteCmd(0x18);
    EPD_WriteData(0x80);

    // Display update control
    EPD_WriteCmd(0x22);
    EPD_WriteData(0xB1);
    
    // Master Activation
    EPD_WriteCmd(0x20);

    EPD_CheckStatus_inverted(100);

    // Temperature sensor read from register
    EPD_WriteCmd(0x1B);
    epd_temperature = EPD_SPI_read();    
    EPD_SPI_read();

    WaitMs(5);
    
    // deep sleep
    EPD_WriteCmd(0x10);
    EPD_WriteData(0x01);

    return epd_temperature;
}

// ============================================================================
// v7.0 - true gate-window partial refresh (power saving)
// ----------------------------------------------------------------------------
// This is the driver the tag ACTUALLY runs: epd.c prints epd_model_string[] on
// screen and the tag reports "BWR213", i.e. epd_model == 2 -> EPD_BWR_213_*.
// (v5.0's LUT change and v6.0's IL0373 PTL window were written into
// epd_bw_213.c, which is only the fallback branch for a failed detection and
// therefore never executed.  See CHANGELOG v7.0.)
//
// The SSD1680 datasheet (Rev 0.14) has NO partial-window command like the
// IL0373's 0x90 PTL.  What it does have is a way to select WHICH GATES ARE
// DRIVEN, via two registers:
//
//   0x01 Driver Output Control (p.34)
//        byte1 = MUX[7:0], byte2 = MUX[8], byte3 = GD,SM,TB
//        "MUX[8:0]: Specify number of lines for the driver: MUX[8:0] + 1.
//         Multiplex ratio (MUX ratio) from 16 MUX to 296 MUX."
//
//   0x0F Gate Scan Start Position (p.36)
//        byte1 = SCN[7:0], byte2 = SCN[8]
//        "determining the starting gate of display RAM by selecting a value
//         from 0 to 295".  Figure 8-2 works the example through: with MUX ratio
//         093h and Gate Start Position 04Ah, gates G0..G73 are '-' (NOT driven)
//         while G74.. are driven, G74 = ROW74, G75 = ROW75, ...
//
// So MUX[8:0] = N-1 plus SCN = F drives exactly the contiguous range
// G_F .. G_(F+N-1), and driven gate G_n reads RAM row n (identity mapping - the
// GD=0 / SM=0 setting this driver already uses, p.34).  Gates outside the range
// are simply not driven, so they keep the ink from the previous full refresh.
// That is exactly the behaviour we want, and it is where the saving comes from:
// the refresh time is proportional to the number of scanned gates, so the
// boosters / VCOM / source drivers run for ~46% as long.
//
// Geometry is derived, not guessed (see tools/verify_gate_window.py):
//   FixBuffer()  : epd_buffer[col*16 + byteY] = ~ucMirror[ obd[byteY][249-col] ]
//   RAM write    : index i = col*16 + byteY -> RAM X = byteY, RAM Y = 296 - col
//                  (0x11 = 0x01: X increments, Y decrements; 0x4F = 0x0128)
//   hence        : glass_x = 249 - col = RAM_Y - 47
// The clock ink spans glass x [54,190] over all 1440 times, i.e. RAM rows
// [101,237] - the driven range below is that range exactly.
//
// THE DATA PATH IS DELIBERATELY UNCHANGED: the full 250x16-byte frame is still
// streamed to the same RAM addresses, and 0x44/0x45/0x4E/0x4F are untouched.
// Only the set of driven gates shrinks, so a wrong window cannot tear the image
// - the worst case is that the digits stop updating.  Setting
// EPD_USE_GATE_WINDOW to 0 restores the previous full-panel behaviour.
// ============================================================================
#define EPD_USE_GATE_WINDOW 1

#define EPD_WIN_GATE_FIRST 101   // first DRIVEN gate -> 0x0F SCN[8:0]
#define EPD_WIN_GATE_LAST  237   // last  DRIVEN gate
#define EPD_WIN_GATES      (EPD_WIN_GATE_LAST - EPD_WIN_GATE_FIRST + 1)   // 137
#define EPD_WIN_GD_SM_TB   0x01  // GD=0, SM=0, TB=1 - unchanged from the full path

#if EPD_WIN_GATES < 16 || EPD_WIN_GATES > 296
#error "gate window: MUX ratio must stay within 16..296 (SSD1680 p.34)"
#endif
#if EPD_WIN_GATE_FIRST < 0 || EPD_WIN_GATE_LAST > 295
#error "gate window: driven gates must stay within 0..295 (SSD1680 p.36)"
#endif

_attribute_ram_code_ uint8_t EPD_BWR_213_Display(unsigned char *image, int size, uint8_t full_or_partial)
{    
    uint8_t epd_temperature = 0 ;
    
    // SW Reset
    EPD_WriteCmd(0x12);

    EPD_CheckStatus_inverted(100);

    // Set Analog Block control
    EPD_WriteCmd(0x74);
    EPD_WriteData(0x54);
    // Set Digital Block control
    EPD_WriteCmd(0x7E);
    EPD_WriteData(0x3B);

    // Booster soft start
    EPD_WriteCmd(0x0C);
    EPD_WriteData(0x8B);
    EPD_WriteData(0x9C);
    EPD_WriteData(0x96);
    EPD_WriteData(0x0F);

    // Driver output control (0x01).  MUX[8:0] = driven lines - 1; the third byte
    // is GD,SM,TB.  The full refresh keeps the original 296 lines / GD0 SM0 TB1.
    EPD_WriteCmd(0x01);
#if EPD_USE_GATE_WINDOW
    if (!full_or_partial)
    {
        // v7.0 partial refresh: drive ONLY the gates that carry the clock digits
        // (see the block comment above this function).  Everything else is left
        // undriven and keeps its ink from the last full refresh.
        EPD_WriteData((uint8_t)((EPD_WIN_GATES - 1) & 0xFF));            // MUX[7:0]
        EPD_WriteData((uint8_t)(((EPD_WIN_GATES - 1) >> 8) & 0x01));     // MUX[8]
        EPD_WriteData(EPD_WIN_GD_SM_TB);

        // Gate scan start position (0x0F): the first gate that gets driven.
        EPD_WriteCmd(0x0F);
        EPD_WriteData((uint8_t)(EPD_WIN_GATE_FIRST & 0xFF));             // SCN[7:0]
        EPD_WriteData((uint8_t)((EPD_WIN_GATE_FIRST >> 8) & 0x01));      // SCN[8]
    }
    else
#endif
    {
        EPD_WriteData(0x28);
        EPD_WriteData(0x01);
        EPD_WriteData(0x01);
    }

    // Data entry mode setting
    EPD_WriteCmd(0x11);
    EPD_WriteData(0x01);

    // Set RAM X- Address Start/End
    EPD_WriteCmd(0x44);
    EPD_WriteData(0x00);
    EPD_WriteData(0x0F);

    // Set RAM Y- Address Start/End
    EPD_WriteCmd(0x45);
    EPD_WriteData(0x28);
    EPD_WriteData(0x01);
    EPD_WriteData(0x2E);
    EPD_WriteData(0x00);

    // Border waveform control
    EPD_WriteCmd(0x3C);
    EPD_WriteData(0x05);

    // Display update control
    EPD_WriteCmd(0x21);
    EPD_WriteData(0x00);
    EPD_WriteData(0x80);

    // Temperature sensor control
    EPD_WriteCmd(0x18);
    EPD_WriteData(0x80);

    // Display update control
    EPD_WriteCmd(0x22);
    EPD_WriteData(0xB1);
    
    // Master Activation
    EPD_WriteCmd(0x20);

    EPD_CheckStatus_inverted(100);

    // Temperature sensor read from register
    EPD_WriteCmd(0x1B);
    epd_temperature = EPD_SPI_read();    
    EPD_SPI_read();

    WaitMs(5);

    // Set RAM X address
    EPD_WriteCmd(0x4E);
    EPD_WriteData(0x00);

    // Set RAM Y address
    EPD_WriteCmd(0x4F);
    EPD_WriteData(0x28);
    EPD_WriteData(0x01);

    EPD_LoadImage(image, size, 0x24);

    // Set RAM X address
    EPD_WriteCmd(0x4E);
    EPD_WriteData(0x00);

    // Set RAM Y address
    EPD_WriteCmd(0x4F);
    EPD_WriteData(0x28);
    EPD_WriteData(0x01);

    EPD_WriteCmd(0x26);// RED Color TODO make something out of it :)
    int i;
    for (i = 0; i < size; i++)
    {
        EPD_WriteData(0x00);
    }

    if (!full_or_partial)
    {
        EPD_WriteCmd(0x32);
        for (i = 0; i < sizeof(LUT_bwr_213_part); i++)
        {
            EPD_WriteData(LUT_bwr_213_part[i]);
        }
    }
    
    // Display update control
    EPD_WriteCmd(0x22);
    EPD_WriteData(0xC7);
    
    // Master Activation
    EPD_WriteCmd(0x20);

    return epd_temperature;
}

_attribute_ram_code_ void EPD_BWR_213_set_sleep(void)
{
    // deep sleep
    EPD_WriteCmd(0x10);
    EPD_WriteData(0x01);

}