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
#include "Roboto_Black_80.h"
#include "font_60.h"
#include "font16.h"
#include "font30.h"

// v10.0: firmware-version badge, bottom-right corner.  Same font as the battery
// line (Dialog_plain_16, baseline y = 120) but right-aligned on the virtual
// display:  x = 250 - 2 - width(FW_VERSION_STRING).
// width("v10.0") = 49 px, from the real xAdvance values in font16.h
// (v=10, 1=11, 0=11, .=6) -> x = 199.  tools/verify_version_badge.py re-derives
// this from the font metrics and the string in app_config.h, and fails if the
// three ever disagree, so a longer version cannot silently run off the edge.
#define EPD_VERSION_X 199
#define EPD_VERSION_Y 120

// ---- v11.0: Bluetooth icon instead of the letter "B" -----------------------
// Set EPD_USE_BLE_ICON to 0 to go back to the plain "B" from BLE_conn_string[].
#define EPD_USE_BLE_ICON 1

// 7 x 13 px, the classic Bluetooth rune: a vertical stem at x = 3 with two
// right-pointing chevrons that meet it at the top, the middle and the bottom.
// Bit n of a row selects the pixel at (x + n).
//
//    ...#...      # stem, top
//    ...##..      diagonal  (3,0)->(6,3)
//    ...#.#.
//    ...#..#
//    ...#.#.      diagonal  (6,3)->(3,6)
//    ...##..
//    ...#...      # stem, middle
//    ...##..      diagonal  (3,6)->(6,9)
//    ...#.#.
//    ...#..#
//    ...#.#.      diagonal  (6,9)->(3,12)
//    ...##..
//    ...#...      # stem, bottom
//
// Placement is derived from the glyph it replaces, not guessed:
//   "B" in Dialog_plain_16 at (232, 20) has glyph {w=10, h=12, xo=1, yo=-12},
//   so its ink covers x 233..242 (centre 237.5) and y 8..19 (centre 13.5).
// The rune is 7 x 13: x = 234 puts its centre at 237, i.e. within half a pixel
// of the letter's, and y = 8 seats its bottom row on the baseline the letter
// used.  tools/verify_ble_icon.py re-derives all of this from font16.h.
#define BLE_ICON_W 7
#define BLE_ICON_H 13
#define BLE_ICON_X 234
#define BLE_ICON_Y 8

static const uint8_t BLE_ICON_BITS[BLE_ICON_H] = {
    0x08, 0x18, 0x28, 0x48, 0x28, 0x18, 0x08,
    0x18, 0x28, 0x48, 0x28, 0x18, 0x08
};

// The drawing routine itself lives further down, just above epd_display(), so
// that it sits below the global OBDISP obd that it writes into.

// ---- v12.0: on-glass forensics for the "full refresh every few minutes" bug --
// Four counters owned by app.c (see the v12.0 block there) are drawn next to
// the temperature as "H0 T0 B0 L0".  H = the hour changed, and one per hour is
// the DESIGNED full refresh; T = the panel temperature left its dead band;
// B = the battery voltage left its dead band; L = the BLE connect state
// flipped.  They saturate at 9, so the widest string is 11 glyphs = 107 px.
//
// Geometry (derived, see tools/verify_refresh_debug.py): the temperature "24'C"
// in Special_Elite_Regular_30 at x=10 has ink x 10..71, so x=84 leaves a clean
// gap, and the whole string stays inside the per-minute gate window (glass
// x 54..190) so it is repainted on every tick.  Set EPD_USE_REFRESH_DEBUG to 0
// to take it off the glass again - no other code depends on it.
#define EPD_USE_REFRESH_DEBUG 1
#define EPD_DEBUG_X 84
#define EPD_DEBUG_Y 95

RAM uint8_t epd_model = 0; // 0 = Undetected, 1 = BW213, 2 = BWR213, 3 = BWR154, 4 = BW213ICE, 5 = BWR350
const char *epd_model_string[] = {"NC", "BW213", "BWR213", "BWR154", "213ICE", "BWR350", "BWY350"};
RAM uint8_t epd_update_state = 0;

const char *BLE_conn_string[] = {"", "B"};
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

// Draw the BLE rune at (x, y).  It goes through obdSetPixel() exactly like the
// fonts do, so it lands in the same epd_temp buffer that FixBuffer() later
// converts - no separate pixel format to keep in sync.
static void epd_draw_ble_icon(int x, int y)
{
    int row, col;
    for (row = 0; row < BLE_ICON_H; row++)
    {
        for (col = 0; col < BLE_ICON_W; col++)
        {
            if (BLE_ICON_BITS[row] & (1 << col))
                obdSetPixel(&obd, x + col, y + row, 1, 1);
        }
    }
}

extern uint8_t mac_public[6];
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

    char buff[100];
    sprintf(buff, "ESL_%02X%02X%02X %s", mac_public[2], mac_public[1], mac_public[0], epd_model_string[epd_model]);
    obdWriteStringCustom(&obd, (GFXfont *)&Dialog_plain_16, 1, 17, (char *)buff, 1);
#if EPD_USE_BLE_ICON
    // v11.0: a Bluetooth rune instead of the letter "B".  Drawn only while a
    // central is connected, exactly like the letter it replaces.
    if (ble_get_connected())
        epd_draw_ble_icon(BLE_ICON_X, BLE_ICON_Y);
#else
    sprintf(buff, "%s", BLE_conn_string[ble_get_connected()]);
    obdWriteStringCustom(&obd, (GFXfont *)&Dialog_plain_16, 232, 20, (char *)buff, 1);
#endif
    sprintf(buff, "%02d:%02d", ((time_is / 60) / 60) % 24, (time_is / 60) % 60);
    obdWriteStringCustom(&obd, (GFXfont *)&DSEG14_Classic_Mini_Regular_40, 50, 65, (char *)buff, 1);
    sprintf(buff, "%d'C", EPD_read_temp());
    obdWriteStringCustom(&obd, (GFXfont *)&Special_Elite_Regular_30, 10, 95, (char *)buff, 1);
#if EPD_USE_REFRESH_DEBUG
    // v12.0: why the full refreshes are happening - see the define above.
    sprintf(buff, "H%d T%d B%d L%d", dbg_hour, dbg_temp, dbg_batt, dbg_ble);
    obdWriteStringCustom(&obd, (GFXfont *)&Dialog_plain_16, EPD_DEBUG_X, EPD_DEBUG_Y, (char *)buff, 1);
#endif
    sprintf(buff, "Battery %dmV", battery_mv);
    obdWriteStringCustom(&obd, (GFXfont *)&Dialog_plain_16, 10, 120, (char *)buff, 1);
    sprintf(buff, "%s", FW_VERSION_STRING);
    obdWriteStringCustom(&obd, (GFXfont *)&Dialog_plain_16, EPD_VERSION_X, EPD_VERSION_Y, (char *)buff, 1);
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
