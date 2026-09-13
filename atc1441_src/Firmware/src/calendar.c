#include <stdint.h>

#include "calendar.h"
#include "calendar_data.h"
#include "font_chars.h"

/* ===========================================================================
 * Civil date from a day number
 *
 * Howard Hinnant's days_from_civil / civil_from_days, which are exact for the
 * whole proleptic Gregorian calendar and need no leap-year table.  Day 0 is
 * 1970-01-01, a Thursday.
 * ===========================================================================
 */
static long days_from_civil(int y, int m, int d)
{
    long era;
    unsigned yoe, doy, doe;

    y -= (m <= 2);
    era = (y >= 0 ? y : y - 399) / 400;
    yoe = (unsigned)(y - era * 400);
    doy = (unsigned)((153 * (m + (m > 2 ? -3 : 9)) + 2) / 5 + d - 1);
    doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    return era * 146097L + (long)doe - 719468L;
}

static void civil_from_days(long z, int *py, int *pm, int *pd)
{
    long era, y;
    unsigned doe, yoe, doy, mp, d, m;

    z += 719468;
    era = (z >= 0 ? z : z - 146096) / 146097;
    doe = (unsigned)(z - era * 146097);
    yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    y = (long)yoe + era * 400;
    doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    mp = (5 * doy + 2) / 153;
    d = doy - (153 * mp + 2) / 5 + 1;
    m = mp + (mp < 10 ? 3 : -9);

    *py = (int)(y + (m <= 2));
    *pm = (int)m;
    *pd = (int)d;
}

static void next_day(int *y, int *m, int *d)
{
    static const unsigned char mdays[13] = {0, 31, 28, 31, 30, 31, 30,
                                            31, 31, 30, 31, 30, 31};
    int last = mdays[*m];

    if (*m == 2 && ((*y % 4 == 0 && *y % 100 != 0) || *y % 400 == 0))
        last = 29;
    (*d)++;
    if (*d > last)
    {
        *d = 1;
        (*m)++;
        if (*m > 12)
        {
            *m = 1;
            (*y)++;
        }
    }
}

void cal_date(uint32_t t_local, int *year, int *month, int *day, int *weekday)
{
    long days = (long)(t_local / 86400u);

    civil_from_days(days, year, month, day);
    /* 1970-01-01 was a Thursday (4).  C's % keeps the sign of the dividend,
     * which would break for pre-1970 values, so bias before reducing. */
    *weekday = (int)(((days % 7) + 11) % 7);
}

/* ===========================================================================
 * Lunar calendar
 *
 * Same bit layout as the published lunarInfo table; see calendar_data.h.
 * This mirrors tools/verify_v14_layout.py line for line, and that script runs
 * both this algorithm and an independent one over every day of the supported
 * range, so a transcription slip here cannot survive the build check.
 * ===========================================================================
 */
static unsigned int cal_li(int year)
{
    return CAL_LUNAR_INFO[year - CAL_LUNAR_YEAR_FIRST];
}

static int cal_leap_month(int year)
{
    return (int)(cal_li(year) & 0xfu);
}

static int cal_leap_days(int year)
{
    return (cal_li(year) & 0x10000u) ? 30 : 29;
}

static int cal_month_days(int year, int m)
{
    return (cal_li(year) & (0x10000u >> m)) ? 30 : 29;
}

/* 348 is 12 x 29, the base every lunar year starts from; a set month bit means
 * that month is one day longer, so the bits each add 1 - adding the full month
 * length would double count and put the walk out by about a year. */
static int cal_year_days(int year)
{
    int total = 348, m;

    for (m = 1; m <= 12; m++)
        if (cal_month_days(year, m) == 30)
            total++;
    if (cal_leap_month(year))
        total += cal_leap_days(year);
    return total;
}

static int lunar_from_solar(int y, int m, int d, int *pm, int *pd, int *pleap)
{
    long offset = days_from_civil(y, m, d)
                  - days_from_civil(CAL_LUNAR_EPOCH_Y, CAL_LUNAR_EPOCH_M,
                                    CAL_LUNAR_EPOCH_D);
    int ly = CAL_LUNAR_YEAR_FIRST, temp = 0, leap, is_leap = 0, j;

    while (offset > 0 && ly <= CAL_LUNAR_YEAR_FIRST + CAL_LUNAR_YEARS - 1)
    {
        temp = cal_year_days(ly);
        offset -= temp;
        ly++;
    }
    if (offset < 0)
    {
        offset += temp;
        ly--;
    }
    if (ly < CAL_LUNAR_YEAR_FIRST || ly > CAL_LUNAR_YEAR_FIRST + CAL_LUNAR_YEARS - 1)
        return 0;

    leap = cal_leap_month(ly);
    j = 1;
    while (j < 13 && offset > 0)
    {
        if (leap > 0 && j == leap + 1 && !is_leap)
        {
            j--;
            is_leap = 1;
            temp = cal_leap_days(ly);
        }
        else
        {
            temp = cal_month_days(ly, j);
        }
        if (is_leap && j == leap + 1)
            is_leap = 0;
        offset -= temp;
        j++;
    }
    if (offset == 0 && leap > 0 && j == leap + 1)
    {
        if (is_leap)
            is_leap = 0;
        else
        {
            is_leap = 1;
            j--;
        }
    }
    if (offset < 0)
    {
        offset += temp;
        j--;
    }

    *pm = j;
    *pd = (int)offset + 1;
    *pleap = is_leap;
    return 1;
}

/* ===========================================================================
 * Solar terms
 *
 * The table stores day-of-month only; the month of term n is fixed across the
 * supported range and that is asserted by the generator, not assumed here.
 *
 * The table runs one year PAST CAL_YEAR_LAST.  next_term() scans forward, so
 * without that row the last days of December 2050 - inside the advertised
 * range - would find nothing and row 3 would drop its term.  Note the two
 * bounds are different on purpose: term_on() gates on the table's extent,
 * cal_row3() on the advertised one.
 * ===========================================================================
 */
static int term_on(int y, int m, int d)
{
    int n;

    if (y < CAL_TERM_YEAR_FIRST || y > CAL_TERM_YEAR_LAST)
        return -1;
    for (n = 0; n < 24; n++)
        if (CAL_TERM_MONTH[n] == m && CAL_TERM_DAY[y - CAL_TERM_YEAR_FIRST][n] == d)
            return n;
    return -1;
}

/* Nearest solar term on or after this date.  The largest gap between two
 * consecutive terms is under 16 days even at aphelion, so a 20 day scan always
 * finds one - provided the scan is allowed to cross into the lookahead year,
 * which is what CAL_TERM_YEAR_LAST is for. */
static int next_term(int y, int m, int d, int *pterm, int *pdays)
{
    int i;

    for (i = 0; i <= 20; i++)
    {
        int t = term_on(y, m, d);

        if (t >= 0)
        {
            *pterm = t;
            *pdays = i;
            return 1;
        }
        next_day(&y, &m, &d);
    }
    return 0;
}

/* ===========================================================================
 * Formatting
 * ===========================================================================
 */
static int put_lunar_day(uint16_t *dst, int n, int ld)
{
    if (ld == 10)
    {
        dst[n++] = UF_C_CHU;
        dst[n++] = UF_C_SHI;
    }
    else if (ld < 10)
    {
        dst[n++] = UF_C_CHU;
        dst[n++] = UF_NUMERAL[ld];
    }
    else if (ld < 20)
    {
        dst[n++] = UF_C_SHI;
        dst[n++] = UF_NUMERAL[ld - 10];
    }
    else if (ld == 20)
    {
        dst[n++] = UF_NUMERAL[2];
        dst[n++] = UF_C_SHI;
    }
    else if (ld < 30)
    {
        dst[n++] = UF_C_NIAN;
        dst[n++] = UF_NUMERAL[ld - 20];
    }
    else
    {
        dst[n++] = UF_NUMERAL[3];
        dst[n++] = UF_C_SHI;
    }
    return n;
}

/* ---- v15.0: the two halves, exposed separately --------------------------
 * The month calendar's info column stacks the lunar date and the solar term on
 * separate lines, so cal_row3 - which joins them with a space - is now built
 * FROM these two instead of being the only entry point.  One implementation
 * each, so the time page's row 3 and the calendar page cannot disagree.
 * ------------------------------------------------------------------------ */
static int lunar_text(uint32_t t_local, uint16_t *dst, int maxn)
{
    int y, m, d, wd, lm, ld, leap, n = 0;

    if (maxn < 6) /* 闰 + 月名 + 月 + 日名(2) + NUL */
        return 0;

    cal_date(t_local, &y, &m, &d, &wd);
    if (y < CAL_YEAR_FIRST || y > CAL_YEAR_LAST)
        return 0;
    if (!lunar_from_solar(y, m, d, &lm, &ld, &leap))
        return 0;
    if (lm < 1 || lm > 12 || ld < 1 || ld > 30)
        return 0;

    if (leap)
        dst[n++] = UF_C_LEAP;
    dst[n++] = UF_LUNAR_MONTH[lm];
    dst[n++] = UF_C_MONTH;
    n = put_lunar_day(dst, n, ld);
    dst[n] = 0;
    return n;
}

static int term_text(uint32_t t_local, uint16_t *dst, int maxn)
{
    int y, m, d, wd, term, ahead, n = 0;

    if (maxn < 7) /* 2 digits + 天后 + 节气名(2) + NUL */
        return 0;

    cal_date(t_local, &y, &m, &d, &wd);
    if (!next_term(y, m, d, &term, &ahead))
        return 0;

    if (ahead == 0)
    {
        dst[n++] = UF_C_JIN;
        dst[n++] = UF_C_DAY;
    }
    else
    {
        if (ahead >= 10)
            dst[n++] = (uint16_t)('0' + ahead / 10);
        dst[n++] = (uint16_t)('0' + ahead % 10);
        dst[n++] = UF_C_TIAN;
        dst[n++] = UF_C_HOU;
    }
    dst[n++] = UF_TERM[term][0];
    dst[n++] = UF_TERM[term][1];
    dst[n] = 0;
    return n;
}

int cal_lunar_text(uint32_t t_local, uint16_t *dst, int maxn)
{
    return lunar_text(t_local, dst, maxn);
}

int cal_term_text(uint32_t t_local, uint16_t *dst, int maxn)
{
    return term_text(t_local, dst, maxn);
}

int cal_row3(uint32_t t_local, uint16_t *dst, int maxn)
{
    uint16_t tmp[CAL_ROW3_MAX];
    uint16_t t2[CAL_TERM_MAX];
    int n, m, tn, k;

    if (maxn < CAL_ROW3_MAX)
        return 0;

    n = lunar_text(t_local, tmp, CAL_ROW3_MAX);
    if (n <= 0)
        return 0;

    /* Worst case is 5 + 1 + 6 = 12 codepoints, well inside CAL_ROW3_MAX; the
     * guard is here so a future longer term string degrades to "no term"
     * instead of running off tmp[]. */
    tn = term_text(t_local, t2, CAL_TERM_MAX);
    if (tn > 0 && n + 1 + tn < CAL_ROW3_MAX)
    {
        tmp[n++] = ' ';
        for (k = 0; k < tn; k++)
            tmp[n++] = t2[k];
    }

    tmp[n] = 0;
    if (n >= maxn)
        return 0;
    for (m = 0; m <= n; m++)
        dst[m] = tmp[m];
    return n;
}

/* ===========================================================================
 * v15.0 page 2 grid helpers.
 *
 * cal_date() reports tm_wday (0 = Sunday); a Monday-first grid wants 0 = Monday,
 * so the +6 rotation is here, once, next to the arithmetic that produces the
 * day number - the renderer never touches weekday numbering itself.
 * ===========================================================================
 */
int cal_weekday(int y, int m, int d)
{
    long days = days_from_civil(y, m, d);
    int wd = (int)(((days % 7) + 11) % 7); /* 0 = Sunday */

    return (wd + 6) % 7; /* 0 = Monday */
}

int cal_days_in_month(int y, int m)
{
    static const unsigned char mdays[13] = {0, 31, 28, 31, 30, 31, 30,
                                            31, 31, 30, 31, 30, 31};
    int last;

    if (m < 1 || m > 12)
        return 0;
    last = mdays[m];
    if (m == 2 && ((y % 4 == 0 && y % 100 != 0) || y % 400 == 0))
        last = 29;
    return last;
}

int cal_year_supported(int year)
{
    return (year >= CAL_YEAR_FIRST && year <= CAL_YEAR_LAST) ? 1 : 0;
}
