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

/* v15.0 page 2: the two halves of cal_row3, split apart so the month calendar's
 * info column can stack them on separate lines instead of running them along
 * one.  Same data, same range checks; cal_row3() is now composed from these two
 * so the time page's row 3 cannot drift from what the calendar page shows.
 *
 *   cal_lunar_text  八月初二          (leap month prefixed, e.g. 闰四月十五)
 *   cal_term_text   11天后秋分 / 今日秋分
 *
 * Both return 0 outside the supported range, as cal_row3 does. */
#define CAL_LUNAR_MAX 8   /* 闰 + 月名 + 月 + 日名(2) + NUL */
#define CAL_TERM_MAX  8   /* 2 digits + 天后 + 节气名(2) + NUL */
int cal_lunar_text(uint32_t t_local, uint16_t *dst, int maxn);
int cal_term_text(uint32_t t_local, uint16_t *dst, int maxn);

/* v15.0 page 2 grid helpers.
 *
 *   cal_weekday(y, m, d)     0 = Monday .. 6 = Sunday.  The month grid is
 *                            Monday-first (decision D3) but cal_date() reports
 *                            tm_wday (0 = Sunday), so the rotation lives here
 *                            rather than in the renderer.
 *   cal_days_in_month(y, m)  28..31, leap years included.
 *
 * Both are exact over the whole proleptic Gregorian range - they share the
 * days_from_civil() arithmetic that cal_date() already uses, so the grid cannot
 * disagree with the header line about what day it is. */
int cal_weekday(int y, int m, int d);
int cal_days_in_month(int y, int m);

/* 1 when the lunar/solar-term tables cover this year.  The renderer must ask
 * this rather than compare against CAL_YEAR_FIRST itself: that macro lives in
 * the generated calendar_data.h, whose tables are static, so including it from
 * a second translation unit would silently duplicate every table in flash. */
int cal_year_supported(int year);
