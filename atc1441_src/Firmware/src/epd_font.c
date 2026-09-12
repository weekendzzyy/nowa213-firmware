#include <stdint.h>

#include "epd_layout.h"
#include "font_unifont.h"
#include "epd_font.h"

/* The rune's size is declared in epd_font.h so callers can lay text out around
 * it; fail the build rather than let the header and the generated bitmap
 * disagree. */
typedef char epd_rune_w_matches_header[(EPD_RUNE_W == BLE_RUNE_W) ? 1 : -1];
typedef char epd_rune_h_matches_header[(EPD_RUNE_H == BLE_RUNE_H) ? 1 : -1];

/* ===========================================================================
 * Glyphs
 *
 * font_unifont.h is generated (tools/gen_v14_tables.py) and stores each glyph
 * column-major: two bytes per column, low byte = rows 0..7, high byte = rows
 * 8..15, bit r = row r.  The panel buffer is packed the same way, so the only
 * work left is a shift when the glyph does not start on a byte boundary.
 * ===========================================================================
 */

/* Binary search: codepoint -> bitmap, column count, advance.
 * A codepoint the subset does not carry still advances, so a missing glyph
 * leaves a gap instead of collapsing the rest of the line together. */
static const unsigned char *uf_find(uint32_t cp, int *cols, int *adv)
{
    int lo = 0, hi = UF_GLYPH_COUNT - 1;

    while (lo <= hi)
    {
        int mid = (lo + hi) >> 1;
        if (UF_CODE[mid] == cp)
        {
            *cols = UF_COLS[mid];
            *adv = UF_ADV[mid];
            return &UF_BITS[UF_OFF[mid]];
        }
        if (UF_CODE[mid] < cp)
            lo = mid + 1;
        else
            hi = mid - 1;
    }

    *cols = 0;
    *adv = (cp >= 0x2E80u) ? 16 : 8; /* CJK ranges are double width */
    return 0;
}

/* Blit `ncols` columns of a glyph so that its row 0 lands on row `ytop`.
 * Handles any ytop by shifting into the one, two or three byte rows it spans. */
static void uf_blit(uint8_t *scr, int wpitch, int height, int x, int ytop,
                    const unsigned char *blob, int ncols)
{
    int c, off, r0, lastrow;
    uint8_t *p0;

    if (!blob || ncols <= 0)
        return;
    if (x < 0 || x + ncols > wpitch || ytop < 0 || ytop + 15 >= height)
        return;

    off = ytop & 7;
    r0 = ytop >> 3;
    lastrow = height >> 3;
    p0 = scr + r0 * wpitch + x;

    for (c = 0; c < ncols; c++)
    {
        int word = blob[2 * c] | (blob[2 * c + 1] << 8);
        uint8_t b0 = (uint8_t)((word << off) & 0xFF);
        uint8_t b1 = (uint8_t)((word >> (8 - off)) & 0xFF);

        if (b0)
            p0[c] |= b0;
        if (b1 && r0 + 1 < lastrow)
            p0[c + wpitch] |= b1;
        if (off && r0 + 2 < lastrow)
        {
            uint8_t b2 = (uint8_t)((word >> (16 - off)) & 0xFF);
            if (b2)
                p0[c + 2 * wpitch] |= b2;
        }
    }
}

int epd_glyph(uint8_t *scr, int wpitch, int height, int x, int ytop, uint32_t cp)
{
    int cols, adv;
    const unsigned char *blob = uf_find(cp, &cols, &adv);

    uf_blit(scr, wpitch, height, x, ytop, blob, cols);
    return x + adv;
}

int epd_text(uint8_t *scr, int wpitch, int height, int x, int ytop, const char *s)
{
    while (*s)
        x = epd_glyph(scr, wpitch, height, x, ytop, (uint32_t)(unsigned char)*s++);
    return x;
}

int epd_utext(uint8_t *scr, int wpitch, int height, int x, int ytop,
              const uint16_t *s)
{
    while (*s)
        x = epd_glyph(scr, wpitch, height, x, ytop, *s++);
    return x;
}

int epd_text_width(const char *s)
{
    int w = 0, cols, adv;

    while (*s)
    {
        uf_find((uint32_t)(unsigned char)*s++, &cols, &adv);
        w += adv;
    }
    return w;
}

int epd_utext_width(const uint16_t *s)
{
    int w = 0, cols, adv;

    while (*s)
    {
        uf_find(*s++, &cols, &adv);
        w += adv;
    }
    return w;
}

void epd_rune(uint8_t *scr, int wpitch, int height, int x, int ytop)
{
    uf_blit(scr, wpitch, height, x, ytop, BLE_RUNE_BITS, BLE_RUNE_W);
}

/* ===========================================================================
 * The clock - DSEG14 Classic Mini Regular, scaled 3/2 (40 px of font -> 60 px
 * on the glass).  This is the same face v13.0 drew with; the hand-drawn
 * segments of v14.0/v14.1 are gone.  The upstream bitmap font cannot reach
 * 68 px (26/40 digits would need 289 px of width), and 60 px is what fits
 * between rows 1 and 3 - and what the user asked for after seeing the
 * hand-drawn face.
 *
 * The bitmap (font_dseg.h) is a GFX bitstream: MSB first, `w` bits per row,
 * rows packed continuously with no byte alignment between rows, each glyph
 * starting on a byte boundary.  The panel buffer is column-major, so drawing
 * is a per-pixel transpose.
 *
 * The 3/2 scale is nearest-neighbour: source row/column n expands to TWO
 * output rows/columns when n is even and ONE when n is odd, so no per-pixel
 * division is needed and a stroke keeps its width within a pixel.  Note that
 * an odd-height glyph (the '7' is 37) then covers ceil(h*3/2) rows - still
 * inside CLOCK_H.  tools/epd_face_model.py walks the identical pattern, so
 * the preview the tool prints is the bitmap the firmware produces.
 * ===========================================================================
 */

/* Set one pixel, respecting the column-major packing. */
static void plot(uint8_t *scr, int wpitch, int height, int x, int y)
{
    if (x < 0 || x >= wpitch || y < 0 || y >= height)
        return;
    scr[(y >> 3) * wpitch + x] |= (uint8_t)(1 << (y & 7));
}

static const DSEG_Glyph *dseg_find(char ch)
{
    if (ch >= '0' && ch <= '9')
        return &DSEG_GLYPHS[ch - '0'];
    if (ch == ':')
        return &DSEG_GLYPHS[10];
    return 0;
}

void epd_clock(uint8_t *scr, int wp, int ht, const char *s)
{
    int i;

    /* Fixed slots: slot i is at the same x for every rendering, so a '1' in
     * the minutes cannot shift the hour digits.  That is what keeps the
     * per-minute gate window down to the two minute slots - epd_layout.h.
     * DSEG14's own advance is the same for all ten digits, asserted by
     * font_dseg.h, so the slots and the font agree. */
    for (i = 0; s[i]; i++)
    {
        const DSEG_Glyph *g = dseg_find(s[i]);
        int x, y, sx, sy, oy;

        if (!g)
            continue;

        /* the glyph's ink origin: the font's baseline sits CLOCK_H below the
         * slot top, and yo is the ink top's offset FROM that baseline (GFX
         * convention, negative = up), so the ink starts (DSEG_FONT_HEIGHT +
         * yo) font px below the slot top.  Using the glyph height here
         * instead - as this once did - puts every glyph whose ink stops
         * short of the baseline (the colon, the '7') one inset too low. */
        x = CLOCK_SLOT_X(i) + ((int) g->xo * CLOCK_SCALE_NUM) / CLOCK_SCALE_DEN;
        y = CLOCK_Y + ((DSEG_FONT_HEIGHT + (int) g->yo) * CLOCK_SCALE_NUM) / CLOCK_SCALE_DEN;

        oy = 0;
        for (sy = 0; sy < g->h; sy++)
        {
            int rh = (sy & 1) ? 1 : 2;   /* the 3/2 pattern: 2,1,2,1 ... */
            int ox = 0;

            for (sx = 0; sx < g->w; sx++)
            {
                int rw = (sx & 1) ? 1 : 2;
                int bit = g->off * 8 + sy * g->w + sx;

                if (DSEG_BITS[bit >> 3] & (0x80 >> (bit & 7)))
                {
                    int a, b;
                    for (a = 0; a < rh; a++)
                        for (b = 0; b < rw; b++)
                            plot(scr, wp, ht, x + ox + b, y + oy + a);
                }
                ox += rw;
            }
            oy += rh;
        }
    }
}
