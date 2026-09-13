#pragma once

/* The clock layout is derived from the DSEG14 font's metrics, so the font has
 * to come first: everything CLOCK_* below is computed from it. */
#include "font_dseg.h"

/* ===========================================================================
 * v14.0 clock face - the single source of truth for every coordinate.
 *
 * tools/verify_v14_layout.py parses THIS file plus epd.c, re-derives the text
 * widths, the clock extent and the partial-refresh gate window from it, and
 * fails if the numbers below no longer match what the drawing code needs.
 * That is the point: a coordinate is written once, here, and a constant that
 * would run off the glass or leave the window unable to reach the digits
 * cannot get past the build check.
 *
 * The glass is 250 x 122.  The buffer is padded to 250 x 128 because each
 * column is stored as whole bytes (16 per column), so rows 122..127 do not
 * exist on the panel - never place content there.
 * ===========================================================================
 */
#define FACE_W          250
#define FACE_H          128
#define FACE_VISIBLE_H  122

/* ---- row 1: "2026年9月12日 周六 31℃ 2905mV" ----------------------------
 * Composed as TWO strings: the date/weekday/temperature on the left at
 * ROW1_X, and the voltage right aligned on ROW1_RIGHT_X - the same edge row
 * 3's name/version align to, so the face has one right margin and the voltage
 * does not drift left and right with the date's length.  The left part is the
 * only part that can grow, so its fields are clamped to what the hardware can
 * actually produce, which makes the widest string a known, reachable worst
 * case instead of a guess, and lets the buffer below be sized exactly.
 *
 *   year       4 digits for any timestamp this RTC will ever hold
 *   month/day  1 or 2 digits
 *   weekday    1 glyph
 *   temperature  SSD1680's own operating range is -40..+85 C, so <= 3 chars
 *   battery     a 12-bit ADC on a 3.6 V part cannot exceed 4 digits; the clamp
 *               is there so a stuck-high reading cannot wrap the line
 *
 * Left-part worst case is therefore "2026年10月10日 周日 -40℃": 19 codepoints
 * and 188 px of advance.  Against the widest voltage ("9999mV", 48 px) right
 * aligned on 231 - pen start 183 - that would overlap, so epd_face() drops the
 * space before the temperature when it would (188 -> 182 px of advance: the
 * space is worth 6, not 8 - measured, not assumed), and ROW1_X is 1, not 2, so
 * the dropped form ends at exactly the voltage's pen start.  That combination
 * is a sub-zero cold snap with a four-digit battery reading and a two-digit
 * month AND day - unreachable indoors - but tools/verify_v14_layout.py walks
 * every day of the supported range times every clamped temperature and
 * voltage, and fails if the rule ever stops being enough.
 */
#define ROW1_Y        2
#define ROW1_X        1
#define ROW1_RIGHT_X  231

#define ROW1_MV_MAX    9999
#define ROW1_TEMP_MIN  (-40)
#define ROW1_TEMP_MAX  85

/* Buffer capacity for the composed LEFT part, in codepoints: 19 + NUL.  (A
 * 19-codepoint left part is exactly the one that trips the space-drop rule
 * above when the voltage is four digits - but with a shorter voltage it is
 * drawn complete, so 19 is the capacity the buffer needs.) */
#define ROW1_MAX_CHARS 20
/* The advance the left part can cost: 188 before the space-drop rule, 182
 * after it.  The compile-time assertion below checks the DROPPED advance
 * against the WIDEST voltage - the one combination with no slack; the verify
 * script re-derives both numbers from the real glyphs and walks everything. */
#define ROW1_MV_ADV    48    /* "9999mV" - 6 ASCII glyphs at 8 px */
#define ROW1_MAX_ADV   188
#define ROW1_DROP_ADV  182

#if ROW1_X + ROW1_DROP_ADV + ROW1_MV_ADV - 1 > ROW1_RIGHT_X
#error "row 1: the widest left part would run into the right-aligned voltage"
#endif

/* ---- row 3: lunar date + next solar term, and the BLE state ------------
 * Left side is the calendar text; the right side is the Bluetooth rune plus
 * either the device's own advertised name or the firmware version, right
 * aligned on ROW3_RIGHT_X and alternating every ROW3_ALT_SECS.
 *
 * The two sides share the row, so the left text may never reach the rune.  The
 * rune's slot is FIXED - it does not follow the text's left edge, which would
 * make the symbol jump sideways every time the text swapped - so ROW3_RUNE_X
 * is derived from the WIDEST of the two strings, and the narrower one simply
 * leaves a bigger gap.  tools/verify_v14_layout.py walks every day of the
 * supported range and if a future change ever made the longest of them collide
 * with that slot, the build check fails.
 *
 * ROW3_RIGHT_X is deliberately 231, not the glass edge: 231 is the last column
 * the per-minute gate window drives, and the name/version swap has to be
 * repainted by a partial tick.  Anything outside the band keeps its previous
 * state on the panel, so a swap that straddled the edge would leave the tail of
 * the old string rotting next to the new one until the next full refresh.
 * Right-aligning to the band's edge also lines row 3 up with row 1, whose
 * widest string ends at 228.
 *
 * The version half of the swap is stable by construction; the name half is
 * derived from mac_public[], constant for the life of a boot.
 */
#define ROW3_Y         104
#define ROW3_X         2
#define ROW3_RIGHT_X   231
#define RUNE_GAP       3

/* The two right-corner strings, widest first.  "[B2C3]" is the tail of the
 * advertised name - "ESL_" plus six hex digits - which is exactly what the
 * reference panel shows ([881A], four digits, not the whole MAC). */
#define ROW3_TEXT_MAX_CHARS  6
#define ROW3_TEXT_MAX_ADV    48

/* The rune is 8 px wide; epd_font.h asserts its own EPD_RUNE_W against this. */
#define ROW3_RUNE_W    8
#define ROW3_RUNE_X    (ROW3_RIGHT_X - ROW3_TEXT_MAX_ADV - RUNE_GAP - ROW3_RUNE_W)

/* The name/version swap period.  It costs nothing to run it often: the swap
 * rides a partial tick that happens anyway, so 5 minutes is free. */
#define ROW3_ALT_SECS  300

#if ROW3_TEXT_MAX_ADV != 6 * 8
#error "row 3: the widest right-corner string is no longer 6 ASCII glyphs"
#endif
#if ROW3_RIGHT_X + 1 > FACE_W
#error "row 3: the right corner runs off the glass"
#endif
#if ROW1_RIGHT_X != ROW3_RIGHT_X
#error "row 1 and row 3 must share one right edge, or the face looks ragged"
#endif

/* ---- row 2: the clock -------------------------------------------------
 * DSEG14 Classic Mini Regular - the same face v13.0 drew with - scaled 3/2,
 * i.e. 40 px of font -> 60 px on the glass.  The upstream bitmap font cannot
 * reach 68 px (its digits are 26/40 wide, so 68 px of height would need
 * 289 px of width); 60 px is what fits between rows 1 and 3 with room to
 * spare, and it is what the user asked for after seeing v14.1's hand-drawn
 * segments.
 *
 * The 3/2 scale is nearest-neighbour: source row/column n maps to 2 output
 * rows/columns when n is even and 1 when n is odd, so every stroke keeps its
 * width within a pixel.  epd_font.c's blitter walks the same pattern, and
 * tools/epd_face_model.py mirrors it, so the three cannot disagree.
 *
 * Fixed slots, as before: every digit owns the same advance cell and the
 * colon owns a narrower one, so a '1' never shifts its neighbours.  That is
 * not aesthetic - it is what makes the per-minute gate window possible.
 * Centring the face on its own measured width instead would move the HOUR
 * digits every time a '1' entered or left the minutes, so the window would
 * have to cover the whole clock instead of the two minute slots.
 */
#define CLOCK_SCALE_NUM  3
#define CLOCK_SCALE_DEN  2

/* the font's intrinsic metrics (font_dseg.h), scaled to the glass */
#define CLOCK_H          ((DSEG_FONT_HEIGHT * CLOCK_SCALE_NUM) / CLOCK_SCALE_DEN)
#define CLOCK_DIGIT_ADV  ((DSEG_ADV_DIGIT    * CLOCK_SCALE_NUM) / CLOCK_SCALE_DEN)
/* the colon's 9 px advance would be 13.5 scaled; it is FLOORED to 13, which
 * pulls both minute digits 1 px left and puts the ones digit's last ink
 * column exactly on the window band's edge - see EPD_WIN below */
#define CLOCK_COLON_ADV  ((DSEG_ADV_COLON    * CLOCK_SCALE_NUM) / CLOCK_SCALE_DEN)
/* the ink columns a digit can cover inside its cell, across all ten digits */
#define CLOCK_INK_X0     ((DSEG_INK_X0 * CLOCK_SCALE_NUM) / CLOCK_SCALE_DEN)
#define CLOCK_INK_LAST   (((DSEG_INK_X0 + DSEG_INK_W) * CLOCK_SCALE_NUM) / CLOCK_SCALE_DEN - 1)

#define CLOCK_CELL_W     CLOCK_DIGIT_ADV
#define CLOCK_COLON_W    CLOCK_COLON_ADV
/* four digits, four advances, the colon's narrower cell */
#define CLOCK_WIDEST     (4 * CLOCK_DIGIT_ADV + CLOCK_COLON_ADV)
#define CLOCK_X0         ((FACE_W - CLOCK_WIDEST) / 2)
#define CLOCK_Y          31

/* x of slot i, i = 0..4, left to right: digit digit colon digit digit.
 * Two digits precede the colon, so slots 3 and 4 shift by its (floored)
 * advance as well. */
#define CLOCK_SLOT_X(i)  (CLOCK_X0 + ((i) < 3 ? (i) : 2) * CLOCK_DIGIT_ADV \
                          + ((i) >= 3 ? (CLOCK_COLON_ADV + ((i) - 3) * CLOCK_DIGIT_ADV) : 0))

#if CLOCK_WIDEST > FACE_W
#error "clock: the widest HH:MM no longer fits across the glass"
#endif
#if CLOCK_X0 < 0
#error "clock: the face is wider than the glass"
#endif

/* ===========================================================================
 * The partial (per-minute) refresh window.
 *
 * SSD1680 has no partial-window command; the window is built from MUX (0x01)
 * and Gate Scan Start Position (0x0F), which select one contiguous run of
 * gate lines.  The mapping from a glass column to a gate line is
 *     gate = glass_x + EPD_WIN_GATE_OFFSET
 * (derived in epd_bwr_213.c from FixBuffer and the 0x11 data entry mode).
 *
 * The window is the last two slots - hours 3 and 4 of "HH:MM" - and nothing
 * else, because a partial tick is only ever taken when the hour has NOT
 * changed (app.c: full = hour_changed || force_full), and because the fixed
 * slots above guarantee the hour digits hold still.  It scans 92 of 296 lines,
 * 31%, against v13.0's 137 (46%), with much larger digits.
 *
 * The window covers the columns a partial tick can change:
 *   - the two minute digits' ink (CLOCK_MINUTE_INK_FIRST .. LAST) - the hour
 *     digits and the colon only ever change on a full refresh, and
 *   - row 3's right corner (ROW3_RIGHT_X), which v14.1 swaps between the
 *     advertised name and the version every ROW3_ALT_SECS.
 * The two ranges are contiguous by construction - asserted below - so one
 * gate run covers both.
 *
 * The window is DERIVED from those numbers rather than written down, so it
 * cannot drift from the layout.  tools/verify_v14_layout.py then recomputes
 * the union of columns that actually change across all 1440 renderings of
 * "HH:MM" in both swap states and fails if it is not inside this range.
 *
 * The other condition the window depends on lives in app.c: the glass must be
 * given the SAME values between full refreshes, or content inside this band
 * would be repainted every minute.  Row 1's voltage sits at x 188..231, inside
 * the band - see the "snapshot" block there.
 * ===========================================================================
 */
#define EPD_WIN_GATE_OFFSET 47
/* the ink of the two minute digits: each cell's ink is CLOCK_INK_X0 +
 * CLOCK_INK_LAST inside a CLOCK_DIGIT_ADV-wide slot */
#define CLOCK_MINUTE_TENS_X (CLOCK_SLOT_X(3))
#define CLOCK_MINUTE_INK_FIRST (CLOCK_MINUTE_TENS_X + CLOCK_INK_X0)
#define CLOCK_MINUTE_INK_LAST  (CLOCK_SLOT_X(4) + CLOCK_INK_LAST)

#define EPD_WIN_GLASS_FIRST  (CLOCK_MINUTE_INK_FIRST)
#define EPD_WIN_GLASS_LAST   (ROW3_RIGHT_X)

#define EPD_WIN_GATE_FIRST  (EPD_WIN_GLASS_FIRST + EPD_WIN_GATE_OFFSET)
#define EPD_WIN_GATE_LAST   (EPD_WIN_GLASS_LAST + EPD_WIN_GATE_OFFSET)
#define EPD_WIN_GATES       (EPD_WIN_GATE_LAST - EPD_WIN_GATE_FIRST + 1)

/* The minute digits' ink must not reach past the right corner's right edge, or
 * the union would be non-contiguous and one gate run could not cover both. */
#if CLOCK_MINUTE_INK_LAST > ROW3_RIGHT_X
#error "clock: the minute digits' ink runs past the right corner - the window could not be one contiguous gate run"
#endif
/* The window must not also be asked to carry anything that changes off the
 * minute - those all force a full refresh instead (see app.c).  The name/version
 * swap is the one deliberate exception: it changes on a 5-minute boundary, which
 * IS a minute tick, and it sits inside the band on purpose - asserted here. */
#if ROW3_RIGHT_X > EPD_WIN_GATE_LAST - EPD_WIN_GATE_OFFSET
#error "row 3: the name/version swap must sit inside the per-minute band, or a partial tick would leave the tail of the old string on the glass"
#endif
#if ROW3_RUNE_X <= ROW3_X
#error "row 3: no room left between the calendar text and the rune"
#endif
#if EPD_WIN_GATES < 16 || EPD_WIN_GATES > 296
#error "gate window: MUX ratio must stay within 16..296 (SSD1680 p.34)"
#endif
#if EPD_WIN_GATE_FIRST < 0 || EPD_WIN_GATE_LAST > 295
#error "gate window: driven gates must stay within 0..295 (SSD1680 p.36)"
#endif

/* ===========================================================================
 * v15.0 page 2 - the month calendar.
 *
 * Two panes: the date grid on the left, an info column on the right.  The glass
 * is still 250 x 122, and the grid carries a weekday header plus up to six date
 * rows (a 31-day month starting on Sunday spans six weeks), so the row pitch is
 * what makes six rows fit:
 *
 *     header   y = CAL_HEAD_Y (2)                16 px -> ends 18
 *     row i    y = CAL_ROW0_Y (19) + CAL_ROW_H*i   six rows -> 19 .. 120
 *
 * 120 <= 122, so the last row's ink is on the glass.  The pitch is 1 px more
 * than the 16 px glyph so the rows read as rows.
 *
 * The grid is Monday-first (decision D3), so a month whose 1st is not a Monday
 * leaves leading cells EMPTY.  That offset is derived at render time from
 * cal_date() - never stored - so it cannot drift.
 * ===========================================================================
 */
#define CAL_COLS        7
/* 23 px per column.  It was briefly 19 to fit a widened "2026年12月" title -
 * that layout was rejected, so the grid gets its width back. */
#define CAL_COL_W       23                 /* 7 * 23 = 161 */
#define CAL_GRID_W      (CAL_COLS * CAL_COL_W)

#define CAL_DIVIDER_X   CAL_GRID_W         /* vertical rule, glass x 161 */
#define CAL_HEAD_Y      2
#define CAL_ROW0_Y      19
#define CAL_ROW_H       17
#define CAL_ROWS_MAX    6

/* The info column: year+month, today's date (enlarged), the lunar date and the
 * next solar term.  Left aligned on CAL_INFO_X, and CAL_INFO_RIGHT_X is the
 * last column any of its strings may reach.  It is the glass edge here, not the
 * 231 band edge of the time page: this page takes no per-minute partial
 * refresh, so nothing has to stay inside the band. */
#define CAL_INFO_X       (CAL_DIVIDER_X + 4)
#define CAL_INFO_RIGHT_X 249
/* The info column's inner width, for centring runs inside it. */
#define CAL_INFO_WIDTH   (CAL_INFO_RIGHT_X - CAL_INFO_X + 1)

/* rows of the info column (top of each).  Five lines, with the enlarged today
 * date dominating the upper half and the smaller lunar/term/voltage lines
 * stacked below it.  Every one of them is centred in the column. */
#define CAL_INFO_TITLE_Y 2
#define CAL_INFO_TODAY_Y 18
#define CAL_INFO_LUNAR_Y 62
#define CAL_INFO_TERM_Y  82
#define CAL_INFO_VOLT_Y  100

/* The voltage line.  "9999mV" is the widest string the row-1 clamp allows, so
 * the advance is fixed and the centred x is a CONSTANT - which is what lets the
 * partial-refresh window below be derived instead of guessed. */
#define CAL_VOLT_ADV  48
#define CAL_VOLT_X    (CAL_INFO_X + (CAL_INFO_WIDTH - CAL_VOLT_ADV) / 2)

/* The calendar page's own partial window: the vertical band carrying the
 * voltage line, and nothing else.  The page is otherwise midnight-only, so the
 * band is re-driven every CAL_VOLT_REFRESH_HOURS to keep the reading fresh -
 * 48 gates against the time page's 95.
 *
 * Two things the caller must respect:
 *   * a partial refresh re-drives EVERY row inside the band, so the buffer it
 *     is given has to hold the whole page, not just the voltage - which is what
 *     epd_display() rebuilds;
 *   * the band also crosses the enlarged "13日", so the red frame has to be
 *     rebuilt too.  Whether the (single-colour) partial waveform re-drives RED
 *     correctly is unverified on this panel - EPD_CAL_BWR_PARTIAL switches the
 *     page back to full refreshes if it turns out it does not. */
/* CAL_VOLT_REFRESH_HOURS lives in epd.h - app.c needs it for its event
 * dispatch and must not pull this header in (it would duplicate the DSEG
 * bitmap in flash). */
#define CAL_WIN_GLASS_FIRST   (CAL_VOLT_X)
#define CAL_WIN_GLASS_LAST    (CAL_VOLT_X + CAL_VOLT_ADV - 1)
#define CAL_WIN_GATE_FIRST    (CAL_WIN_GLASS_FIRST + EPD_WIN_GATE_OFFSET)
#define CAL_WIN_GATE_LAST     (CAL_WIN_GLASS_LAST + EPD_WIN_GATE_OFFSET)
#define CAL_WIN_GATES         (CAL_WIN_GATE_LAST - CAL_WIN_GATE_FIRST + 1)

/* Today's date is drawn in two pieces: the digits at CAL_TODAY_RATIO and the
 * 日 suffix at CAL_TODAY_SUFFIX_RATIO.
 *
 * The suffix is 100 (i.e. full size) on purpose.  It was tried at 50, to make
 * the digits dominate harder, and the render settled it: a Han glyph at 8 px
 * loses its strokes and simply disappears - "13日" read as "13".  So the
 * contrast comes from the DIGITS growing, not from the suffix shrinking. */
#define CAL_TODAY_RATIO         250
#define CAL_TODAY_SUFFIX_RATIO  100

/* The 日 gets lifted this many px PAST cell-bottom alignment, because the INK
 * bottoms do not coincide: Unifont draws the digits' ink on rows 4..13 of the
 * 16-row cell (3 empty rows below) while 日 fills rows 1..15.  At the today
 * line's 250% those 3 empty rows are 5 px, so plain cell-bottom alignment left
 * the 日 hanging 5 px below the digits' last ink.  Measured from the bitmaps,
 * not eyeballed - tools/epd_face_model.py reproduces the numbers. */
#define CAL_TODAY_SUFFIX_LIFT    5

/* Everything in the info column except the enlarged today date is drawn at
 * one pair of sizes: ASCII digits at 6 px and Han glyphs at 8 px.  Unifont
 * gives ASCII an 8 px advance and Han 16 px, so the ratios are 75% and 50%.
 *
 * 50% Han is the readable floor for this panel: a 16x16 glyph down to 8x8
 * still holds its strokes at the BWR 213's dot pitch, and it is what the user
 * asked for after seeing the previous 7 px / 12 px mix look unbalanced. */
#define CAL_INFO_DIGIT_RATIO     75
#define CAL_INFO_HAN_RATIO       50

/* Trimming the today box by this many px per side keeps the reversed block off
 * its neighbours' ink. */
#define CAL_TODAY_BOX_INSET 2

/* The info column's longest string: "2026年12月" is 4 digits + 年 + 2 digits +
 * 月 = 8 codepoints, plus NUL.  One buffer serves the title, the lunar date
 * (CAL_LUNAR_MAX) and the term (CAL_TERM_MAX); 10 covers all three. */
#define CAL_INFO_MAX 10

#if CAL_GRID_W + 1 >= FACE_W
#error "calendar: the grid leaves no room for the info column"
#endif
#if CAL_ROW0_Y + CAL_ROWS_MAX * CAL_ROW_H > FACE_VISIBLE_H
#error "calendar: six date rows run off the glass"
#endif
#if CAL_INFO_X >= CAL_INFO_RIGHT_X
#error "calendar: the info column has no width"
#endif
#if CAL_TODAY_RATIO < 100 || CAL_TODAY_RATIO > 400
#error "calendar: today-date ratio out of range"
#endif
#if CAL_TODAY_SUFFIX_RATIO < 25 || CAL_TODAY_SUFFIX_RATIO > 100
#error "calendar: today-suffix ratio out of range"
#endif
#if CAL_INFO_TODAY_Y + 16 * CAL_TODAY_RATIO / 100 > CAL_INFO_LUNAR_Y
#error "calendar: the enlarged today date overlaps the lunar line"
#endif
#if CAL_INFO_VOLT_Y + 16 > FACE_VISIBLE_H
#error "calendar: the voltage line runs off the glass"
#endif
#if CAL_INFO_VOLT_Y < CAL_INFO_TERM_Y + 16
#error "calendar: the voltage line overlaps the solar-term line"
#endif
#if CAL_WIN_GATE_LAST > 295
#error "calendar: the voltage band runs past the last gate (SSD1680 p.36)"
#endif
#if CAL_WIN_GATES < 16
#error "calendar: the voltage band is narrower than the 16-line MUX minimum"
#endif
