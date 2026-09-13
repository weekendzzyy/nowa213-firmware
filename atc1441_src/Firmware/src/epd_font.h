#pragma once

#include <stdint.h>

/* ===========================================================================
 * The v14.0 drawing layer.
 *
 * Everything here writes into the OneBitDisplay virtual screen - the buffer
 * obdCreateVirtualDisplay() was handed - and nothing else.  That buffer is
 * stored one byte per column per eight rows, with bit (y & 7) inside the byte:
 *
 *     byte at   (y >> 3) * wpitch + x
 *     bit       (y & 7)                    set = ink (black)
 *
 * so a glyph blit is two byte-ORs per column.  The functions below are plain
 * flash-resident code on purpose: epd_display() runs from RAM (it is
 * _attribute_ram_code_), and the SRAM it costs is the scarcest resource in
 * this build.  Keeping the drawing out of it costs nothing at runtime.
 *
 * ytop may be any row, not just a multiple of 8 - the blitter shifts.
 * ===========================================================================
 */

/* Draw one Unicode codepoint.  Returns the pen x after it, so calls chain. */
int epd_glyph(uint8_t *scr, int wpitch, int height, int x, int ytop, uint32_t cp);

/* Draw a NUL-terminated ASCII string.  Returns the pen x. */
int epd_text(uint8_t *scr, int wpitch, int height, int x, int ytop, const char *s);

/* Draw a NUL-terminated array of codepoints (Chinese).  Returns the pen x. */
int epd_utext(uint8_t *scr, int wpitch, int height, int x, int ytop,
              const uint16_t *s);

/* Advance widths, for right-aligning without drawing. */
int epd_text_width(const char *s);
int epd_utext_width(const uint16_t *s);
/* Ink right bearing of the string's last glyph - add it to a pen-right x to
 * align by what the eye sees.  See epd_font.c. */
int epd_text_rb(const char *s);

/* The Bluetooth rune, drawn at (x, ytop).  The size is part of the interface
 * because callers lay the device name out around it.  Its width comes from
 * epd_layout.h, which reserves the rune's slot from it; epd_font.c then checks
 * that against the generated bitmap, so no two of the three can drift. */
#ifndef ROW3_RUNE_W
#error "epd_font.h needs epd_layout.h for ROW3_RUNE_W - the rune's slot is reserved from it"
#endif
#define EPD_RUNE_W ROW3_RUNE_W
#define EPD_RUNE_H 13
void epd_rune(uint8_t *scr, int wpitch, int height, int x, int ytop);

/* The seven-segment clock in the row-2 band.  `hhmm` is "HH:MM"; the five
 * slots have fixed x positions, so a '1' never moves its neighbours - which is
 * what lets the per-minute refresh drive only the last two slots. */
void epd_clock(uint8_t *scr, int wpitch, int height, const char *hhmm);

/* v15.0: scaled (nearest-neighbour) and reversed text, both for the month
 * calendar.  The size argument is a PERCENTAGE: 100 = normal, 200 = double,
 * 50 = half.  A percentage rather than a multiplier because Unifont's ASCII is
 * 8 px wide and its Han 16 px, so making the digits as large as the characters
 * means scaling the two halves of ONE string differently.
 * epd_text_scale advances by `adv * ratio / 100`, so a run's width is still
 * predictable.  epd_text_inv CLEARS ink, for punching the date out of the
 * filled today box. */
int epd_text_scale(uint8_t *scr, int wpitch, int height, int x, int ytop,
                   const char *s, int ratio);
int epd_utext_scale(uint8_t *scr, int wpitch, int height, int x, int ytop,
                    const uint16_t *s, int ratio);
int epd_text_inv(uint8_t *scr, int wpitch, int height, int x, int ytop,
                 const char *s);
