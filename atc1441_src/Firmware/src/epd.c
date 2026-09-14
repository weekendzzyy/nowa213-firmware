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

/* v15.0: 1 = the calendar page re-drives only the voltage band every
 * CAL_VOLT_REFRESH_HOURS, instead of rebuilding the whole panel.  Set to 0 to
 * go back to full refreshes: whether the single-colour partial waveform
 * re-drives the RED layer correctly is unverified on this panel, and a faint
 * "3日" after a 2-hour tick is the symptom that would condemn it. */
#define EPD_CAL_BWR_PARTIAL 1

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

/* ---- v15.0 page state (flash, its own 4 KB sector at 0x7A000) -------------
 * One magic byte plus one page byte, magic written last so an interrupted
 * save keeps the previous valid page.  A sector erase is the price of the
 * update, which is fine: the page only changes when the user asks for it. */
uint8_t page_state_load(void)
{
	uint8_t magic = 0;
	uint8_t page = PAGE_TIME;

	flash_read_page(PAGE_STATE_FLASH_ADDR, 1, &magic);
	if (magic == PAGE_STATE_MAGIC)
	{
		flash_read_page(PAGE_STATE_FLASH_ADDR + 1, 1, &page);
		if (page < PAGE_TIME || page > PAGE_TIME + PAGE_COUNT - 1)
			page = PAGE_TIME;
	}
	return page;
}

void page_state_save(uint8_t page)
{
	uint8_t magic = PAGE_STATE_MAGIC;

	if (page < PAGE_TIME || page > PAGE_TIME + PAGE_COUNT - 1)
		page = PAGE_TIME;
	flash_erase_sector(PAGE_STATE_FLASH_ADDR);
	flash_write_page(PAGE_STATE_FLASH_ADDR + 1, 1, &page);
	flash_write_page(PAGE_STATE_FLASH_ADDR, 1, &magic);
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
        // NOTE: EPD_IS_BUSY() is true while the panel is updating (active-low
        // BUSY pin - see epd_spi.c busy-wait loops).  Both controllers share the
        // same BUSY polarity, so the panel must be put to sleep when it is IDLE,
        // i.e. when !EPD_IS_BUSY().  The model-2 branch below used to test
        // EPD_IS_BUSY() (sleep-while-busy), which cut every refresh short by
        // powering off VCI mid-update and cleared epd_update_state too early.
        if (!EPD_IS_BUSY())
            epd_set_sleep();
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

/* v15.4: the red RAM (0x26) has the opposite polarity from the black RAM
 * (0x24).  The controller treats 0x00 in 0x26 as "no red" (the old
 * EPD_BWR_213_LoadZeros path proved that), whereas FixBuffer's inversion
 * would turn a source background of 0 into 0xFF -> red.  Keep the X mirror,
 * drop the inversion. */
_attribute_ram_code_ void FixBufferRed(uint8_t *pSrc, uint8_t *pDst, uint16_t width, uint16_t height)
{
    int x, y;
    uint8_t *s, *d;
    for (y = 0; y < (height / 8); y++)
    { // byte rows
        d = &pDst[y];
        s = &pSrc[y * width];
        for (x = 0; x < width; x++)
        {
            d[x * (height / 8)] = ucMirror[s[width - 1 - x]]; // flip only
        }                                                     // for x
    }                                                         // for y
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
    /* aligned by INK: the last glyph's right bearing is part of the edge */
    x = ROW1_RIGHT_X - epd_text_width(b) + epd_text_rb(b);
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
    /* aligned by INK - the old hard-coded "+ 1" happened to fit the version's
     * trailing digit but left the name's ']' floating 3 px further left */
    x = ROW3_RIGHT_X - epd_text_width(b) + epd_text_rb(b);
    epd_text(scr, wp, ht, x, ROW3_Y, b);
    if (ble_get_connected())
        epd_rune(scr, wp, ht, ROW3_RUNE_X, ROW3_Y + 1);
}

/* ===========================================================================
 * v15.0 page 2 - the month calendar.  Coordinates come from the CAL_* block in
 * epd_layout.h; this file only draws.
 *
 * It is drawn TWICE per refresh: once with red_only = 0 (everything black,
 * including the filled box under today) and once with red_only = 1 (the weekend
 * cells and the enlarged today date).  The two passes fill the two RAMs the
 * SSD1680 keeps - a BWR pixel is the pair (black bit, red bit), so a glyph that
 * is meant to be red must NOT also be painted black, or the controller resolves
 * it the other way.  That is also why the today box and its date are skipped in
 * the red pass: the box is black and the date is erased out of it.
 *
 * Everything here is derived from cal_date()/cal_weekday() at draw time - the
 * grid's leading offset, the weekend columns and today's cell are never stored.
 * ===========================================================================
 */
static void fill_rect(uint8_t *scr, int wpitch, int height, int x, int y,
                      int w, int h)
{
    int i, j;

    for (j = 0; j < h; j++)
    {
        int yy = y + j;

        if (yy < 0 || yy >= height)
            continue;
        for (i = 0; i < w; i++)
        {
            int xx = x + i;

            if (xx < 0 || xx >= wpitch)
                continue;
            scr[(yy >> 3) * wpitch + xx] |= (uint8_t)(1 << (yy & 7));
        }
    }
}

/* column index -> tm_wday.  The grid is Monday-first, so column 0 is Monday and
 * column 6 is Sunday; 0 (Sunday) is the last column, not the first. */
#define CAL_COL_WDAY(i) (((i) == CAL_COLS - 1) ? 0 : (i) + 1)
#define CAL_IS_WEEKEND(i) (CAL_COL_WDAY(i) == 0 || CAL_COL_WDAY(i) == 6)

/* The info column's strings vary in length (1日 .. 30日, 小寒 .. 大寒), so a
 * shared left edge would read as a ragged block.  Each line is centred on
 * CAL_INFO_WIDTH instead - see the constant, which is also what makes the
 * voltage's x a compile-time number. */
static void info_center(uint8_t *scr, int wp, int ht, const uint16_t *s, int sc,
                        int y)
{
    int x = CAL_INFO_X + (CAL_INFO_WIDTH - epd_utext_width(s) * sc / 100) / 2;

    epd_utext_scale(scr, wp, ht, x, y, s, sc);
}

/* Draw a mixed run - ASCII digits and Han glyphs - with the two scaled
 * DIFFERENTLY, centred in the info column.
 *
 * Unifont gives ASCII an 8 px advance and Han 16 px, so a single scale can
 * never make the digits look as large as the characters; "13日" and "2026年9月"
 * both need the digits to grow while the Han stays put (or shrinks).  Width is
 * summed with the same advances the blitter uses, so the centring cannot
 * disagree with what is drawn. */
static int info_center_mixed(uint8_t *scr, int wp, int ht, const uint16_t *s,
                             int a_ratio, int h_ratio, int y, int align)
{
    int w = 0, i, x, max_h = 0;

    for (i = 0; s[i]; i++)
    {
        int r = (s[i] < 0x2E80u) ? a_ratio : h_ratio;
        int h = 16 * r / 100;

        w += (s[i] < 0x2E80u ? 8 : 16) * r / 100;
        if (h > max_h)
            max_h = h;
    }
    x = CAL_INFO_X + (CAL_INFO_WIDTH - w) / 2;

    /* align = 0 centres a smaller glyph in the run; align = 1 drops it to the
     * run's BOTTOM edge.  Today's "13日" wants the latter: the number is the
     * focus and the 日 should sit on its foot, not float in the middle. */
    for (i = 0; s[i]; i++)
    {
        uint16_t one[2];
        int r = (s[i] < 0x2E80u) ? a_ratio : h_ratio;
        int off = max_h - 16 * r / 100;

        /* The lift goes to the SMALLER glyphs only.  The run's tallest glyphs
         * define where the bottom IS; lifting them too just moves the whole
         * line and leaves every relative offset exactly as wrong as before -
         * which is exactly what the first attempt did. */
        if (align && off > 0)
            off -= CAL_TODAY_SUFFIX_LIFT;

        one[0] = s[i];
        one[1] = 0;
        x = epd_utext_scale(scr, wp, ht, x, y + (align ? off : off / 2), one, r);
    }
    return x;
}

static void info_text_center(uint8_t *scr, int wp, int ht, const char *s, int y)
{
    /* Pure ASCII, so the digit ratio is the only one that applies to it - the
     * voltage follows the same 80% as every other black numeral. */
    int x = CAL_INFO_X
            + (CAL_INFO_WIDTH - epd_text_width(s) * CAL_INFO_DIGIT_RATIO / 100)
              / 2;

    epd_text_scale(scr, wp, ht, x, y, s, CAL_INFO_DIGIT_RATIO);
}

static void epd_face_calendar(uint8_t *scr, int wp, int ht, uint32_t t,
                              uint16_t mv, int red_only)
{
    uint16_t buf[CAL_INFO_MAX];
    int y, m, d, wd, days, first, i, n, x;

    cal_date(t, &y, &m, &d, &wd);

    if (!red_only)
    {
        /* the divider and the rule under the weekday header */
        fill_rect(scr, wp, ht, CAL_DIVIDER_X, 0, 1, FACE_VISIBLE_H);
        fill_rect(scr, wp, ht, 0, CAL_HEAD_Y + 16, CAL_GRID_W, 1);
    }

    /* ---- weekday header: 一 二 三 四 五 六 日 ---- */
    for (i = 0; i < CAL_COLS; i++)
    {
        if (CAL_IS_WEEKEND(i) != red_only)
            continue;
        x = i * CAL_COL_W + (CAL_COL_W - 16) / 2;
        epd_glyph(scr, wp, ht, x, CAL_HEAD_Y, UF_WEEKDAY[CAL_COL_WDAY(i)]);
    }

    /* Outside the supported range the header still reads, but there is no grid
     * to draw - same rule cal_row3() uses for row 3. */
    if (!cal_year_supported(y))
        return;

    days = cal_days_in_month(y, m);
    first = cal_weekday(y, m, 1); /* 0 = Monday: the leading cells of row 0 */

    for (i = 1; i <= days; i++)
    {
        int cell = first + i - 1;
        int row = cell / 7;
        int col = cell % 7;
        int today, cw, cx, cy;
        char b[8];

        if (row >= CAL_ROWS_MAX)
            break;

        sprintf(b, "%d", i);
        cw = epd_text_width(b);
        cx = col * CAL_COL_W + (CAL_COL_W - cw) / 2;
        cy = CAL_ROW0_Y + row * CAL_ROW_H;
        today = (i == d);

        if (today)
        {
            /* The box takes the colour its weekday gets: black Mon-Fri, red at
             * the weekend.  So it is drawn in the pass that OWNS that colour,
             * and the date is erased out of it - in the black RAM erasing
             * leaves white, and in the red RAM it leaves "no red", which is
             * also white on the panel.  Nothing else may paint this cell. */
            if (CAL_IS_WEEKEND(col) != red_only)
                continue;
            fill_rect(scr, wp, ht,
                      col * CAL_COL_W + CAL_TODAY_BOX_INSET,
                      cy - CAL_TODAY_BOX_INSET,
                      CAL_COL_W - 2 * CAL_TODAY_BOX_INSET,
                      16 + 2 * CAL_TODAY_BOX_INSET);
            epd_text_inv(scr, wp, ht, cx, cy, b);
        }
        else if (CAL_IS_WEEKEND(col) == red_only)
        {
            epd_text(scr, wp, ht, cx, cy, b);
        }
    }

    /* ---- info column ---- */
    if (!red_only)
    {
        char vb[10];

        n = 0;
        n = put_num(buf, n, y);
        buf[n++] = UF_C_YEAR;
        n = put_num(buf, n, m);
        buf[n++] = UF_C_MONTH;
        buf[n] = 0;
        info_center_mixed(scr, wp, ht, buf, CAL_INFO_DIGIT_RATIO,
                          CAL_INFO_HAN_RATIO, CAL_INFO_TITLE_Y, 0);

        n = cal_lunar_text(t, buf, CAL_INFO_MAX);
        if (n > 0)
            info_center_mixed(scr, wp, ht, buf, CAL_INFO_DIGIT_RATIO,
                              CAL_INFO_HAN_RATIO, CAL_INFO_LUNAR_Y, 0);

        n = cal_term_text(t, buf, CAL_INFO_MAX);
        if (n > 0)
            info_center_mixed(scr, wp, ht, buf, CAL_INFO_DIGIT_RATIO,
                              CAL_INFO_HAN_RATIO, CAL_INFO_TERM_Y, 0);

        /* The voltage, clamped the same way row 1 clamps it - CAL_VOLT_ADV is
         * that clamp's widest result, which is what fixes the band the partial
         * refresh drives. */
        if (mv > ROW1_MV_MAX)
            mv = ROW1_MV_MAX;
        sprintf(vb, "%umV", mv);
        info_text_center(scr, wp, ht, vb, CAL_INFO_VOLT_Y);
    }
    else
    {
        n = 0;
        n = put_num(buf, n, d);
        buf[n++] = UF_C_DAY;
        buf[n] = 0;
        info_center_mixed(scr, wp, ht, buf, CAL_TODAY_RATIO,
                          CAL_TODAY_SUFFIX_RATIO, CAL_INFO_TODAY_Y, 1);
    }
}

_attribute_ram_code_ void epd_display(uint32_t time_is, uint16_t battery_mv, int16_t temperature, uint8_t full_or_partial, uint8_t page)
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

    /* ---- v15.0 page dispatch ------------------------------------------
     * Only the time page can take a per-minute PARTIAL refresh; the calendar
     * and image pages are full-refresh only.  That is exactly why neither of
     * them has to keep its content inside the per-minute gate band, and why
     * switching pages is always a full refresh. */
    if (page == PAGE_CALENDAR)
    {
        int size = resolution_w * resolution_h / 8;
        /* EPD_BWR_213_Begin/Activate take 0 = gate-windowed (partial),
         * non-zero = full panel.  full_or_partial == 1 means a page switch or
         * midnight full refresh; otherwise we are in the 2-hour voltage-band
         * tick.  EPD_CAL_BWR_PARTIAL switches that tick to windowed. */
        uint8_t cal_full = full_or_partial ? 1
                           : (EPD_CAL_BWR_PARTIAL ? 0 : 1);

        /* Black frame first: once those bytes are out they live in the
         * controller, so this this single framebuffer can be rebuilt as the red
         * frame and sent too.  See the BWR block comment in epd_bwr_213.c. */
        epd_face_calendar(obd.ucScreen, resolution_w, resolution_h, time_is,
                          battery_mv, 0);
        FixBuffer(epd_temp, epd_buffer, resolution_w, resolution_h);

        if (epd_model == 2)
        {
            uint8_t t2;

            EPD_init();
            EPD_POWER_ON();
            WaitMs(5);
            gpio_write(EPD_RESET, 0);
            WaitMs(10);
            gpio_write(EPD_RESET, 1);
            WaitMs(10);

            /* The band this partial refresh drives is the VOLTAGE one, not the
             * time page's minute digits - that is what gate_first/gates are
             * for.  Both frames are still sent in full: only the driven gate
             * range shrinks, so a wrong window cannot tear the page, it can
             * only fail to update. */
            t2 = EPD_BWR_213_Begin(cal_full, CAL_WIN_GATE_FIRST,
                                   CAL_WIN_GATES);
            EPD_BWR_213_Load(epd_buffer, size, 0x24);

            obdFill(&obd, 0, 0);
            epd_face_calendar(obd.ucScreen, resolution_w, resolution_h, time_is,
                              battery_mv, 1);
            FixBufferRed(epd_temp, epd_buffer, resolution_w, resolution_h);
            EPD_BWR_213_Load(epd_buffer, size, 0x26);

            EPD_BWR_213_Activate(cal_full);

            epd_temperature = t2;
            epd_temperature_is_read = 1;
            epd_update_state = 1;
        }
        else
        {
            /* A panel with no red layer: draw the red pass in black on top. */
            epd_face_calendar(obd.ucScreen, resolution_w, resolution_h, time_is,
                              battery_mv, 1);
            FixBuffer(epd_temp, epd_buffer, resolution_w, resolution_h);
            EPD_Display(epd_buffer, size, 1);
        }
        return;
    }

    if (page == PAGE_IMAGE)
    {
        /* The uploaded image is 1bpp and already in panel column order (the
         * uploader mirrors it), so it goes straight out - no OBD, no red. */
        if (has_user_image)
            user_image_restore();
        else
            memset(epd_buffer, 0xff, epd_buffer_size);
        EPD_Display(epd_buffer, resolution_w * resolution_h / 8, 1);
        return;
    }

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
