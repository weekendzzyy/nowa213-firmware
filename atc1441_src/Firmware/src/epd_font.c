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
 * The seven-segment clock
 *
 * Drawn from geometry because no font on the toolchain has the right aspect:
 * the DSEG face is 0.85, the reference panel's digits are 0.55, and at 76 px
 * of height that difference is the whole budget.
 *
 * Everything is integer arithmetic on purpose.  The rasteriser is mirrored by
 * tools/verify_v14_layout.py using the same formulas, so the preview the tool
 * prints is the bitmap the firmware will produce - not an artist's impression.
 * ===========================================================================
 */

/* Set one pixel, respecting the column-major packing. */
static void plot(uint8_t *scr, int wpitch, int height, int x, int y)
{
    if (x < 0 || x >= wpitch || y < 0 || y >= height)
        return;
    scr[(y >> 3) * wpitch + x] |= (uint8_t)(1 << (y & 7));
}

/* Scan-line fill of a 4-vertex polygon, even-odd rule, one span per row.
 * Vertices are normalised to top-down per edge and the crossing is rounded
 * half away from zero, which is what the mirror in the verify script does. */
static void fill_quad(uint8_t *scr, int wpitch, int height, const int *px,
                      const int *py)
{
    int ymin = py[0], ymax = py[0], i, y;

    for (i = 1; i < 4; i++)
    {
        if (py[i] < ymin)
            ymin = py[i];
        if (py[i] > ymax)
            ymax = py[i];
    }

    for (y = ymin; y <= ymax; y++)
    {
        int xs[4], nx = 0, a, b;

        for (i = 0; i < 4; i++)
        {
            int j = (i + 1) & 3;
            int ax = px[i], ay = py[i], bx = px[j], by = py[j];

            if (ay == by)
                continue;
            if (ay > by)
            {
                int t = ax; ax = bx; bx = t;
                t = ay; ay = by; by = t;
            }
            if (ay <= y && y < by)
            {
                int den = by - ay;
                int num = (y - ay) * (bx - ax);
                int off = (num >= 0) ? (2 * num + den) / (2 * den)
                                     : (2 * num - den) / (2 * den);
                if (nx < 4)
                    xs[nx++] = ax + off;
            }
        }

        for (a = 1; a < nx; a++) /* at most four entries */
        {
            int v = xs[a];
            for (b = a - 1; b >= 0 && xs[b] > v; b--)
                xs[b + 1] = xs[b];
            xs[b + 1] = v;
        }

        for (a = 0; a + 1 < nx; a += 2)
        {
            int x, x0 = xs[a], x1 = xs[a + 1];
            if (x0 < 0)
                x0 = 0;
            if (x1 >= wpitch)
                x1 = wpitch - 1;
            for (x = x0; x <= x1; x++)
                plot(scr, wpitch, height, x, y);
        }
    }
}

static int seg_on(const char *on, char s)
{
    while (*on)
        if (*on++ == s)
            return 1;
    return 0;
}

static const char *segments(char ch)
{
    switch (ch)
    {
    case '0': return "abcdef";
    case '1': return "bc";
    case '2': return "abged";
    case '3': return "abgcd";
    case '4': return "fgbc";
    case '5': return "afgcd";
    case '6': return "afgecd";
    case '7': return "abc";
    case '8': return "abcdefg";
    case '9': return "abcdfg";
    default:  return "";
    }
}

/* The 45-degree mitre is s, deliberately HALF the stroke thickness.  With
 * s = t the bars recede so far that the face reads as six loose lozenges
 * instead of a digit; the reference panel has segments separated by a thin
 * seam, not a wide notch.
 *
 * INVARIANT: every segment of a digit stays inside its cell [x, x+w-1].  The
 * right-hand bars were first placed at x1 - t + 1, one column further from the
 * right edge than the left-hand bars are from the left edge.  That looked 1 px
 * lopsided and, worse, put ink one column OUTSIDE the cell - and the per-minute
 * gate window is derived from these cell spans (see epd_layout.h), so ink
 * outside its cell is ink the window does not promise to repaint.  At x1 - t
 * the bar occupies [x1-t, x1], symmetric with the left bar's [x, x+t].
 * tools/verify_v14_layout.py asserts the invariant for all 11 glyphs. */
static void draw_digit(uint8_t *scr, int wp, int ht, int x, int y, int w, int h,
                       int t, char ch)
{
    const char *on = segments(ch);
    int x1 = x + w - 1, y1 = y + h - 1, ym = y + h / 2;
    int s = t / 2;
    int xr = x1 - t; /* right-hand bars, symmetric with the left bar's [x, x+t] */
    int px[4], py[4];

    if (s < 2)
        s = 2;

    if (seg_on(on, 'a'))
    {
        px[0] = x + s;      py[0] = y;
        px[1] = x1 - s;     py[1] = y;
        px[2] = x1 - 2 * s; py[2] = y + t;
        px[3] = x + 2 * s;  py[3] = y + t;
        fill_quad(scr, wp, ht, px, py);
    }
    if (seg_on(on, 'g'))
    {
        int yt = ym - t / 2;
        px[0] = x + s;      py[0] = yt;
        px[1] = x1 - s;     py[1] = yt;
        px[2] = x1 - 2 * s; py[2] = yt + t;
        px[3] = x + 2 * s;  py[3] = yt + t;
        fill_quad(scr, wp, ht, px, py);
    }
    if (seg_on(on, 'd'))
    {
        int yt = y1 - t + 1;
        px[0] = x + s;      py[0] = yt;
        px[1] = x1 - s;     py[1] = yt;
        px[2] = x1 - 2 * s; py[2] = yt + t;
        px[3] = x + 2 * s;  py[3] = yt + t;
        fill_quad(scr, wp, ht, px, py);
    }
    if (seg_on(on, 'f'))
    {
        px[0] = x;      py[0] = y + s;
        px[1] = x + t;  py[1] = y + 2 * s;
        px[2] = x + t;  py[2] = ym - s;
        px[3] = x;      py[3] = ym;
        fill_quad(scr, wp, ht, px, py);
    }
    if (seg_on(on, 'b'))
    {
        px[0] = xr;     py[0] = y + s;
        px[1] = xr + t; py[1] = y + 2 * s;
        px[2] = xr + t; py[2] = ym - s;
        px[3] = xr;     py[3] = ym;
        fill_quad(scr, wp, ht, px, py);
    }
    if (seg_on(on, 'e'))
    {
        px[0] = x;      py[0] = ym + s;
        px[1] = x + t;  py[1] = ym + 2 * s;
        px[2] = x + t;  py[2] = y1 - s;
        px[3] = x;      py[3] = y1;
        fill_quad(scr, wp, ht, px, py);
    }
    if (seg_on(on, 'c'))
    {
        px[0] = xr;     py[0] = ym + s;
        px[1] = xr + t; py[1] = ym + 2 * s;
        px[2] = xr + t; py[2] = y1 - s;
        px[3] = xr;     py[3] = y1;
        fill_quad(scr, wp, ht, px, py);
    }
}

static void draw_colon(uint8_t *scr, int wp, int ht, int x, int y, int h, int t)
{
    int cx = x + (CLOCK_COLON_W - t) / 2;
    int cy[2];
    int i, px[4], py[4];

    cy[0] = y + h * 30 / 100;
    cy[1] = y + h * 68 / 100;

    for (i = 0; i < 2; i++)
    {
        px[0] = cx;         py[0] = cy[i];
        px[1] = cx + t;     py[1] = cy[i];
        px[2] = cx + t;     py[2] = cy[i] + t;
        px[3] = cx;         py[3] = cy[i] + t;
        fill_quad(scr, wp, ht, px, py);
    }
}

void epd_clock(uint8_t *scr, int wp, int ht, const char *s)
{
    int t = CLOCK_STROKE;
    int i;

    /* Fixed slots: slot i is at the same x for every rendering, so a '1' in the
     * minutes cannot shift the hour digits.  That is what keeps the per-minute
     * gate window down to the last two slots - see epd_layout.h. */
    for (i = 0; s[i]; i++)
    {
        int x = CLOCK_SLOT_X(i);

        if (s[i] == ':')
            draw_colon(scr, wp, ht, x, CLOCK_Y, CLOCK_H, t);
        else if (s[i] >= '0' && s[i] <= '9')
            draw_digit(scr, wp, ht, x, CLOCK_Y, CLOCK_CELL_W, CLOCK_H, t, s[i]);
    }
}
