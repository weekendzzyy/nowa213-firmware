#pragma once

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
 * Left aligned, and the ONLY row that can grow: every other row has a fixed
 * shape.  So the fields are clamped to what the hardware can actually produce,
 * which makes the widest string a known, reachable worst case instead of a
 * guess, and lets the buffer below be sized exactly.
 *
 *   year       4 digits for any timestamp this RTC will ever hold
 *   month/day  1 or 2 digits
 *   weekday    1 glyph
 *   temperature  SSD1680's own operating range is -40..+85 C, so <= 3 chars
 *   battery     a 12-bit ADC on a 3.6 V part cannot exceed 4 digits; the clamp
 *               is there so a stuck-high reading cannot wrap the line
 *
 * Worst case is therefore "2026年12月31日 周六 -40℃ 9999mV":
 *   26 codepoints and 242 px of advance, which ends at x=244 of 250.
 * tools/verify_v14_layout.py walks every day of the supported range and fails
 * if either number below stops being the true maximum.
 */
#define ROW1_Y  2
#define ROW1_X  2

#define ROW1_MV_MAX    9999
#define ROW1_TEMP_MIN  (-40)
#define ROW1_TEMP_MAX  85

/* buffer capacity for the composed row, in codepoints: 26 + NUL.  v14.0 began
 * life with 24, which the widest string overran by three uint16_t. */
#define ROW1_MAX_CHARS 27
/* ... and the advance it costs, so the fit can be asserted at compile time as
 * well as in the verify script (which re-derives it from the real glyphs). */
#define ROW1_MAX_ADV   242

#if ROW1_X + ROW1_MAX_ADV > FACE_W
#error "row 1: the widest date no longer fits across the glass - see the block above"
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

/* ---- row 2: the clock -------------------------------------------------
 * Not a font.  The 40 pt DSEG face the previous layout used has a 0.85
 * digit aspect, so scaling it to a 76 px digit would need 289 px of width;
 * the digits are therefore drawn from geometry (see epd_clock()).
 *
 * The aspect is the reference photo's own, measured off the panel: 37 px of
 * digit to 68 px of height.  CLOCK_H is what the vertical budget allows
 * once two 16 px text rows are placed at ROW1_Y and ROW3_Y.
 *
 * A FIXED-SLOT display, like the seven-segment panel it imitates: all four
 * digits own the same cell every time and the colon owns its own narrower
 * slot, so a '1' never shifts its neighbours.  That is not only how a real
 * display behaves - it is what makes the per-minute gate window possible.
 * Centring the face on its own width instead would move the HOUR digits every
 * time a '1' entered or left the minutes (12:09 -> 12:10 narrows by 19 px and
 * re-centres), so the window would have to cover the whole clock, 214 columns
 * instead of the last two slots' 92, and the power saving would be gone.
 */
#define CLOCK_Y           24
#define CLOCK_H           76
#define CLOCK_ASPECT_PCT  55
#define CLOCK_GAP         8
#define CLOCK_STROKE_PCT  9

/* ---- derived from the constants above; never write these by hand -------- */
#define CLOCK_CELL_W   ((CLOCK_H * CLOCK_ASPECT_PCT + 50) / 100)
#define CLOCK_STROKE   ((CLOCK_H * CLOCK_STROKE_PCT + 50) / 100)
#define CLOCK_COLON_W  ((CLOCK_CELL_W / 3) < 6 ? 6 : (CLOCK_CELL_W / 3))
/* four digits, four gaps, the colon slot - the full width of "HH:MM" */
#define CLOCK_WIDEST   (4 * (CLOCK_CELL_W + CLOCK_GAP) + CLOCK_COLON_W)
#define CLOCK_X0       ((FACE_W - CLOCK_WIDEST) / 2)

/* x of slot i, i = 0..4, left to right: digit digit colon digit digit.
 * Slots 0..2 are spaced by a whole cell, and slot 2 is the narrower colon, so
 * everything from slot 3 on is CLOCK_CELL_W - CLOCK_COLON_W further left than
 * a uniform stride would put it. */
#define CLOCK_SLOT_X(i) (CLOCK_X0 + (i) * (CLOCK_CELL_W + CLOCK_GAP) \
                         - ((i) >= 3 ? (CLOCK_CELL_W - CLOCK_COLON_W) : 0))

#if CLOCK_WIDEST > FACE_W
#error "clock: the widest HH:MM no longer fits across the glass"
#endif
#if CLOCK_X0 < 0
#error "clock: the face is wider than the glass"
#endif
#if CLOCK_STROKE * 4 >= CLOCK_CELL_W
#error "clock: stroke is too thick for the cell - the bars degenerate"
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
 * The window is DERIVED from those slots rather than written down, so it
 * cannot drift from the layout.  tools/verify_v14_layout.py then recomputes
 * the union of columns that actually change across all 1440 renderings of
 * "HH:MM" and fails if it is not inside this range - which is really a check
 * that every digit's ink stays inside its own cell.
 *
 * The other condition the window depends on lives in app.c: the glass must be
 * given the SAME values between full refreshes, or content inside this band
 * (row 1's temperature and voltage sit at x 140..231) would be repainted every
 * minute.  See the "snapshot" block there.
 * ===========================================================================
 */
#define EPD_WIN_GATE_OFFSET 47
/* slot 3 is the first minute digit, slot 4 the second; CLOCK_CELL_W wide */
#define EPD_WIN_GATE_FIRST  (CLOCK_SLOT_X(3) + EPD_WIN_GATE_OFFSET)
#define EPD_WIN_GATE_LAST   (CLOCK_SLOT_X(4) + CLOCK_CELL_W - 1 + EPD_WIN_GATE_OFFSET)
#define EPD_WIN_GATES       (EPD_WIN_GATE_LAST - EPD_WIN_GATE_FIRST + 1)

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
