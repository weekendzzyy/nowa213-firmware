#pragma once

#include <stdint.h>

/* ===========================================================================
 * Calendar for the v14.0 face.
 *
 * These are ORDINARY functions, deliberately not _attribute_ram_code_.
 * epd_display() is copied into RAM at boot and SRAM is the tightest resource
 * in this build (the whole picture is ~4 KB of the 64 KB), so the tables and
 * the arithmetic live in flash and are called from the RAM routine.  The same
 * reason the glyph blitter is not a RAM function.
 * ===========================================================================
 */

/* Decompose a local timestamp.
 *
 * The timestamp is Beijing wall-clock time expressed as a unix value: the web
 * uploader adds the +8 h offset before sending 0xDD (web_uploader.html,
 * TZ_OFFSET_SECONDS), so the plain UTC civil-date arithmetic below lands on
 * the correct local calendar date and weekday.  *weekday is 0 = Sunday. */
void cal_date(uint32_t t_local, int *year, int *month, int *day, int *weekday);

/* Row 3, left-hand side: the lunar date and the next solar term, written as
 * Unicode codepoints, e.g. 八月初二 11天后秋分.  Returns the number of
 * codepoints written (0 when the date is outside the supported range, in
 * which case the caller draws nothing rather than something wrong). */
#define CAL_ROW3_MAX 16
int cal_row3(uint32_t t_local, uint16_t *dst, int maxn);
