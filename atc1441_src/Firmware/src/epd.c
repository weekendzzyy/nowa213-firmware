#include <stdint.h>
#include "tl_common.h"
#include "main.h"
#include "epd.h"
#include "epd_spi.h"
#include "epd_bw_213.h"
#include "epd_bwr_213.h"
#include "epd_bwr_350.h"
#include "epd_bwy_350.h"
#include "epd_bw_213_ice.h"
#include "epd_bwr_154.h"
#include "drivers.h"
#include "stack/ble/ble.h"

#include "battery.h"

#include "OneBitDisplay.h"
#include "TIFF_G4.h"
extern const uint8_t ucMirror[];

/* v14.0: the face draws every character from one generated Unifont subset, and
 * the clock from geometry.  Dialog_plain_16, Special_Elite_Regular_30,
 * DSEG14_Classic_Mini_Regular_40 and Roboto_Black_80 are no longer referenced
 * by anything, so --gc-sections drops them - that is where most of this
 * release's flash saving comes from, not from making the face smaller. */
#include "epd_layout.h"
#include "epd_font.h"
#include "calendar.h"
#include "font_chars.h"

/* ===========================================================================
 * v14.0 layout - see epd_layout.h for the coordinates and why they are there.
 *
 * The three rows follow the reference panel's face:
 *
 *   row 1  2026年9月12日 周六 31℃ 2905mV
 *   row 2        19:06           (seven segments, drawn from geometry)
 *   row 3  八月初二 11天后秋分        <rune>[A1B2C3]
 *
 * Replaced by this release, and why:
 *   - the "ESL_xxxxxx BWR213" header: the model is reported over BLE and the
 *     device name is now on the glass in row 3, where it is actually useful;
 *   - the "Battery 2905mV" line and the v10.0 version badge: the voltage moved
 *     into row 1, and the face has no free space left for a badge.  Bump and
 *     read FW_VERSION_STRING from the release tooling instead.
 *
 * Diagnostics that changed shape rather than disappeared:
 *   - EPD_USE_REFRESH_DEBUG now draws its counters in row 3, replacing the
 *     calendar text.  The counters only move when a full refresh happens, and
 *     row 3 sits outside the per-minute gate window, so they can never be
 *     repainted by a partial refresh and lie.  Row 1 and the clock stay
 *     visible while a tag is being diagnosed, which is the whole point of
 *     having them on the glass.
 * ===========================================================================
 */
#define EPD_USE_REFRESH_DEBUG 0

RAM uint8_t epd_model = 0; // 0 = Undetected, 1 = BW213, 2 = BWR213, 3 = BWR154, 4 = BW213ICE, 5 = BWR350
const char *epd_model_string[] = {"NC", "BW213", "BWR213", "BWR154", "213ICE", "BWR350", "BWY350"};
RAM uint8_t epd_update_state = 0;

RAM uint8_t epd_temperature_is_read = 0;
RAM uint8_t epd_temperature = 0;

uint8_t epd_buffer[epd_buffer_size];
// FEATURE state: time<->image alternation (see the header block in epd.h).
// A 5KB RAM copy of the image was tried earlier and pushed .bss past the 64KB
// SRAM top (stack @ 0x850000) -> boot crash. Image is kept in FLASH instead.
RAM uint8_t has_user_image = 0;    // 1 = a valid user image is stored in flash
RAM uint8_t display_toggle = 0;    // alternation phase: 0 = time/status, 1 = user image
uint8_t epd_temp[epd_buffer_size]; // scratch buffer for OneBitDisplay
OBDISP obd;                        // virtual display structure
TIFFIMAGE tiff;

// ---- User image persistence (FLASH, zero extra SRAM) ----
// Sector 0x79000 (free: firmware <0x16300, OTA 0x20000-0x40000, settings 0x78000).
// On-flash layout (4KB sector):
//   [0x00..0x03] magic "IMG1" (LE) -> validity flag, written LAST so a power loss
//                                 mid-write leaves the old (still valid) magic intact
//   [0x04..0x04+EPD_DISPLAY_SIZE-1] -> copy of epd_buffer (the display framebuffer)
RAM uint32_t user_image_magic_word = 0x31474D49; // "IMG1" little-endian

// Read the magic at boot; sets has_user_image so main_loop knows whether to alternate.
void user_image_check_flash(void)
{
	uint32_t magic = 0;
	flash_read_page(USER_IMG_FLASH_ADDR, 4, (uint8_t *)&magic);
	has_user_image = (magic == user_image_magic_word) ? 1 : 0;
}

// The BW213 controller's default data-entry mode scans columns right-to-left,
// which horizontally mirrors any image that is sent in natural left-to-right
// column order. FixBuffer() (used for the time/status screen) already mirrors
// the source once, so the double mirror cancels out and the clock is readable.
// User images uploaded over BLE are in natural left-to-right column order, so we
// must mirror them before display/save to get the same cancellation.
void user_image_flip_horizontal(void)
{
	int col, byte_y;
	uint8_t tmp;
	int bytes_per_col = EPD_DISPLAY_HEIGHT / 8;
	for (col = 0; col < EPD_DISPLAY_WIDTH / 2; col++)
	{
		int left = col * bytes_per_col;
		int right = (EPD_DISPLAY_WIDTH - 1 - col) * bytes_per_col;
		for (byte_y = 0; byte_y < bytes_per_col; byte_y++)
		{
			tmp = epd_buffer[left + byte_y];
			epd_buffer[left + byte_y] = epd_buffer[right + byte_y];
			epd_buffer[right + byte_y] = tmp;
		}
	}
}

// Persist the current epd_buffer to flash. Called after every BLE image upload
// (opcode 0x01). Magic is written last so an interrupted erase/write is recoverable.
void user_image_save(void)
{
	flash_erase_sector(USER_IMG_FLASH_ADDR);                              // 1) wipe the 4KB sector
	flash_write_page(USER_IMG_FLASH_ADDR + 4, EPD_DISPLAY_SIZE, epd_buffer); // 2) write pixels
	flash_write_page(USER_IMG_FLASH_ADDR, 4, (uint8_t *)&user_image_magic_word); // 3) mark valid
	has_user_image = 1;
}

// Load the saved image from flash back into epd_buffer for display.
void user_image_restore(void)
{
	flash_read_page(USER_IMG_FLASH_ADDR + 4, EPD_DISPLAY_SIZE, epd_buffer);
}

// With this we can force a display if it wasnt detected correctly
void set_EPD_model(uint8_t model_nr)
{
    epd_model = model_nr;
}

// Here we detect what E-Paper display is connected
_attribute_ram_code_ void EPD_detect_model(void)
{
    EPD_init();
    // system power
    EPD_POWER_ON();

    WaitMs(10);
    // Reset the EPD driver IC
    gpio_write(EPD_RESET, 0);
    WaitMs(10);
    gpio_write(EPD_RESET, 1);
    WaitMs(10);

    // Here we neeed to detect it
    if (EPD_BWR_213_detect())
    {
        epd_model = 2;
    }
    else if (EPD_BWR_154_detect())// Right now this will never trigger, the 154 is same to 213BWR right now.
    {
        epd_model = 3;
    }
    else if (EPD_BW_213_ice_detect())
    {
        epd_model = 4;
    }
    else
    {
        epd_model = 1;
    }

    EPD_POWER_OFF();
}

_attribute_ram_code_ uint8_t EPD_read_temp(void)
{
    if (epd_temperature_is_read)
        return epd_temperature;

    if (!epd_model)
        EPD_detect_model();

    EPD_init();
    // system power
    EPD_POWER_ON();
    WaitMs(5);
    // Reset the EPD driver IC
    gpio_write(EPD_RESET, 0);
    WaitMs(10);
    gpio_write(EPD_RESET, 1);
    WaitMs(10);

    if (epd_model == 1)
        epd_temperature = EPD_BW_213_read_temp();
    else if (epd_model == 2)
        epd_temperature = EPD_BWR_213_read_temp();
    else if (epd_model == 3)
        epd_temperature = EPD_BWR_154_read_temp();
    else if (epd_model == 4)
        epd_temperature = EPD_BW_213_ice_read_temp();
    else if (epd_model == 5)
        epd_temperature = EPD_BWR_350_read_temp();
    else if (epd_model == 6)
        epd_temperature = EPD_BWY_350_read_temp();

    EPD_POWER_OFF();

    epd_temperature_is_read = 1;

    return epd_temperature;
}

_attribute_ram_code_ void EPD_Display(unsigned char *image, int size, uint8_t full_or_partial)
{
    if (!epd_model)
        EPD_detect_model();

    EPD_init();
    // system power
    EPD_POWER_ON();
    WaitMs(5);
    // Reset the EPD driver IC
    gpio_write(EPD_RESET, 0);
    WaitMs(10);
    gpio_write(EPD_RESET, 1);
    WaitMs(10);

    if (epd_model == 1)
        epd_temperature = EPD_BW_213_Display(image, size, full_or_partial);
    else if (epd_model == 2)
        epd_temperature = EPD_BWR_213_Display(image, size, full_or_partial);
    else if (epd_model == 3)
        epd_temperature = EPD_BWR_154_Display(image, size, full_or_partial);
    else if (epd_model == 4)
        epd_temperature = EPD_BW_213_ice_Display(image, size, full_or_partial);
    else if (epd_model == 5)
        epd_temperature = EPD_BWR_350_Display(image, size, full_or_partial);
    else if (epd_model == 6)
        epd_temperature = EPD_BWY_350_Display(image, size, full_or_partial);

    epd_temperature_is_read = 1;
    epd_update_state = 1;
}

_attribute_ram_code_ void epd_set_sleep(void)
{
    if (!epd_model)
        EPD_detect_model();

    if (epd_model == 1)
        EPD_BW_213_set_sleep();
    else if (epd_model == 2)
        EPD_BWR_213_set_sleep();
    else if (epd_model == 3)
        EPD_BWR_154_set_sleep();
    else if (epd_model == 4)
        EPD_BW_213_ice_set_sleep();
    else if (epd_model == 5)
        EPD_BWR_350_set_sleep();
    else if (epd_model == 6)
        EPD_BWY_350_set_sleep();

    EPD_POWER_OFF();
    epd_update_state = 0;
}

_attribute_ram_code_ uint8_t epd_state_handler(void)
{
    switch (epd_update_state)
    {
    case 0:
        // Nothing todo
        break;
    case 1: // check if refresh is done and sleep epd if so
        if (epd_model == 1)
        {
            if (!EPD_IS_BUSY())
                epd_set_sleep();
        }
        else
        {
            if (EPD_IS_BUSY())
                epd_set_sleep();
        }
        break;
    }
    return epd_update_state;
}

_attribute_ram_code_ void FixBuffer(uint8_t *pSrc, uint8_t *pDst, uint16_t width, uint16_t height)
{
    int x, y;
    uint8_t *s, *d;
    for (y = 0; y < (height / 8); y++)
    { // byte rows
        d = &pDst[y];
        s = &pSrc[y * width];
        for (x = 0; x < width; x++)
        {
            d[x * (height / 8)] = ~ucMirror[s[width - 1 - x]]; // invert and flip
        }                                                      // for x
    }                                                          // for y
}

_attribute_ram_code_ void TIFFDraw(TIFFDRAW *pDraw)
{
    uint8_t uc = 0, ucSrcMask, ucDstMask, *s, *d;
    int x, y;

    s = pDraw->pPixels;
    y = pDraw->y;                          // current line
    d = &epd_buffer[(249 * 16) + (y / 8)]; // rotated 90 deg clockwise
    ucDstMask = 0x80 >> (y & 7);           // destination mask
    ucSrcMask = 0;                         // src mask
    for (x = 0; x < pDraw->iWidth; x++)
    {
        // Slower to draw this way, but it allows us to use a single buffer
        // instead of drawing and then converting the pixels to be the EPD format
        if (ucSrcMask == 0)
        { // load next source byte
            ucSrcMask = 0x80;
            uc = *s++;
        }
        if (!(uc & ucSrcMask))
        { // black pixel
            d[-(x * 16)] &= ~ucDstMask;
        }
        ucSrcMask >>= 1;
    }
}

_attribute_ram_code_ void epd_display_tiff(uint8_t *pData, int iSize)
{
    // test G4 decoder
    memset(epd_buffer, 0xff, epd_buffer_size); // clear to white
    TIFF_openRAW(&tiff, 250, 122, BITDIR_MSB_FIRST, pData, iSize, TIFFDraw);
    TIFF_setDrawParameters(&tiff, 65536, TIFF_PIXEL_1BPP, 0, 0, 250, 122, NULL);
    TIFF_decode(&tiff);
    TIFF_close(&tiff);
    EPD_Display(epd_buffer, epd_buffer_size, 1);
}

/* ===========================================================================
 * The face itself.
 *
 * Plain flash-resident code, called from the RAM-resident epd_display().  The
 * comma-separated append helpers build each row as codepoints first and draw
 * it in one call, so a row is one string to measure - which is what lets
 * tools/verify_v14_layout.py reproduce the exact width from the same data.
 * ===========================================================================
 */
extern uint8_t mac_public[6];

static int put_num(uint16_t *dst, int n, int v)
{
    char b[12];
    int k = 0, i;

    if (v < 0)
    {
        dst[n++] = '-';
        v = -v;
    }
    if (v == 0)
        b[k++] = '0';
    while (v)
    {
        b[k++] = (char)('0' + v % 10);
        v /= 10;
    }
    for (i = k - 1; i >= 0; i--)
        dst[n++] = (uint16_t)(unsigned char)b[i];
    return n;
}

static void epd_face(uint8_t *scr, int wp, int ht, uint32_t t, uint16_t mv,
                     int16_t temperature)
{
    /* Sized from epd_layout.h: the widest string the clamps below can produce
     * is 26 codepoints.  It was 24, and the widest real string overran it by
     * three uint16_t into the caller's stack frame. */
    uint16_t r1[ROW1_MAX_CHARS], r3[CAL_ROW3_MAX];
    char b[20];
    int n, x, sp, y, m, d, wd;

    /* Clamp to what the hardware can produce, so the composed line cannot grow
     * past the width epd_layout.h reserved for it.  See the row-1 block there
     * for why these bounds are the honest ones. */
    if (mv > ROW1_MV_MAX)
        mv = ROW1_MV_MAX;
    if (temperature < ROW1_TEMP_MIN)
        temperature = ROW1_TEMP_MIN;
    else if (temperature > ROW1_TEMP_MAX)
        temperature = ROW1_TEMP_MAX;

    /* ---- row 1: 2026年9月12日 周六 31℃ ..... 2905mV (right aligned) ---- */
    cal_date(t, &y, &m, &d, &wd);
    n = 0;
    n = put_num(r1, n, y);
    r1[n++] = UF_C_YEAR;
    n = put_num(r1, n, m);
    r1[n++] = UF_C_MONTH;
    n = put_num(r1, n, d);
    r1[n++] = UF_C_DAY;
    r1[n++] = ' ';
    r1[n++] = UF_C_WEEK;
    r1[n++] = UF_WEEKDAY[wd];
    sp = n;                     /* the space before the temperature */
    r1[n++] = ' ';
    n = put_num(r1, n, temperature);
    r1[n++] = UF_C_DEGC;
    r1[n] = 0;

    /* The voltage is right aligned on ROW1_RIGHT_X - the edge row 3's name
     * and version align to - so its position does not drift with the date's
     * length.  The widest clamped date would reach it (epd_layout.h), and the
     * only thing that can give is the space before the temperature: drop it
     * when the left part would run into the voltage. */
    sprintf(b, "%umV", mv);
    x = ROW1_RIGHT_X - epd_text_width(b);
    if (ROW1_X + epd_utext_width(r1) > x)
    {
        memmove(&r1[sp], &r1[sp + 1], (n - sp) * sizeof r1[0]);
        n--;
    }
    epd_utext(scr, wp, ht, ROW1_X, ROW1_Y, r1);
    epd_text(scr, wp, ht, x, ROW1_Y, b);

    /* ---- row 2: the clock ---- */
    sprintf(b, "%02d:%02d", (int)((t / 60) / 60) % 24, (int)(t / 60) % 60);
    epd_clock(scr, wp, ht, b);

    /* ---- row 3 left: 八月初二 11天后秋分 ---- */
#if EPD_USE_REFRESH_DEBUG
    /* v12.0 forensics, moved here in v14.0: see the block comment at the top
     * of this file for why row 3 and not next to the temperature. */
    sprintf(b, "H%02dT%dB%dL%d", dbg_hour, dbg_temp, dbg_batt, dbg_ble);
    epd_text(scr, wp, ht, ROW3_X, ROW3_Y, b);
#else
    if (cal_row3(t, r3, CAL_ROW3_MAX) > 0)
        epd_utext(scr, wp, ht, ROW3_X, ROW3_Y, r3);
#endif

    /* ---- row 3 right: the rune (only while connected), then the device's
     * advertised name or the firmware version, alternating every
     * ROW3_ALT_SECS.  The name is the string the tag advertises, so what is on
     * the glass is what a scanner shows; the version is the only place left to
     * put it since this layout took the corner over.
     *
     * The rune is drawn at the FIXED slot ROW3_RUNE_X rather than to the left
     * of whichever string is up - the two strings differ in width, so following
     * the text would make the symbol jump sideways on every swap.
     *
     * Both strings are right aligned on ROW3_RIGHT_X, which is the last column
     * the per-minute window drives: the swap is therefore repainted by the
     * partial tick that carries it, and costs no full refresh at all. ---- */
    if ((t / ROW3_ALT_SECS) & 1)
        sprintf(b, "%s", FW_VERSION_STRING);
    else
        sprintf(b, "[%02X%02X]", mac_public[1], mac_public[0]);
    x = ROW3_RIGHT_X - epd_text_width(b) + 1;
    epd_text(scr, wp, ht, x, ROW3_Y, b);
    if (ble_get_connected())
        epd_rune(scr, wp, ht, ROW3_RUNE_X, ROW3_Y + 1);
}

_attribute_ram_code_ void epd_display(uint32_t time_is, uint16_t battery_mv, int16_t temperature, uint8_t full_or_partial)
{
    if (epd_update_state)
        return;

    if (!epd_model)
    {
        EPD_detect_model();
    }
    uint16_t resolution_w = 250;
    uint16_t resolution_h = 128; // 122 real pixel, but needed to have a full byte
    if (epd_model == 1)
    {
        resolution_w = 250;
        resolution_h = 128; // 122 real pixel, but needed to have a full byte
    }
    else if (epd_model == 2)
    {
        resolution_w = 250;
        resolution_h = 128; // 122 real pixel, but needed to have a full byte
    }
    else if (epd_model == 3)
    {
        resolution_w = 200;
        resolution_h = 200;
    }
    else if (epd_model == 4)
    {
        resolution_w = 212;
        resolution_h = 104;
    }
    else if (epd_model == 5)
    {// Just as placeholder right now, needs a complete different driving because of RAM limits
        resolution_w = 250;
        resolution_h = 128; // 122 real pixel, but needed to have a full byte
    }
    else if (epd_model == 6)
    {// Just as placeholder right now, needs a complete different driving because of RAM limits
        resolution_w = 250;
        resolution_h = 128; // 122 real pixel, but needed to have a full byte
    }

    obdCreateVirtualDisplay(&obd, resolution_w, resolution_h, epd_temp);
    obdFill(&obd, 0, 0); // fill with white

    /* The face is drawn from a plain function so that the RAM copy of this one
     * stays small - SRAM is the scarcest resource in this build. */
    epd_face(obd.ucScreen, resolution_w, resolution_h, time_is, battery_mv, temperature);

    FixBuffer(epd_temp, epd_buffer, resolution_w, resolution_h);
    EPD_Display(epd_buffer, resolution_w * resolution_h / 8, full_or_partial);
}

_attribute_ram_code_ void epd_display_char(uint8_t data)
{
    int i;
    for (i = 0; i < epd_buffer_size; i++)
    {
        epd_buffer[i] = data;
    }
    EPD_Display(epd_buffer, epd_buffer_size, 1);
}

_attribute_ram_code_ void epd_clear(void)
{
    memset(epd_buffer, 0x00, epd_buffer_size);
}
