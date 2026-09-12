#include <stdint.h>
#include "tl_common.h"
#include "app.h"
#include "main.h"
#include "drivers.h"
#include "stack/ble/ble.h"
#include "vendor/common/blt_common.h"

#include "battery.h"
#include "ble.h"
#include "flash.h"
#include "ota.h"
#include "epd.h"
#include "time.h"
#include "bart_tif.h"

RAM uint8_t battery_level;
RAM uint16_t battery_mv;

RAM uint8_t hour_refresh = 100;
RAM uint8_t minute_refresh = 100;

// ---- v5.0 power saving: night silence window ---------------------------------
// Between NIGHT_START_HOUR (inclusive) and NIGHT_END_HOUR (exclusive) the panel
// is not refreshed at all. The internal clock keeps running, so the first tick
// after the window repaints the correct time - and because hour_refresh still
// tracks the hour, that first repaint is a FULL refresh (clears ghosting).
// Set both to 0 to disable night silence entirely.
#define NIGHT_START_HOUR 0
#define NIGHT_END_HOUR   6

RAM uint8_t first_refresh_done = 0; // always paint once after power-up/reset

// ---- v6.0 partial-window bookkeeping ----------------------------------------
// v6.0 turns the per-minute repaint into a REAL partial refresh limited to the
// clock-digit rectangle (see the IL0373 notes in epd_bw_213.c).  Everything drawn
// OUTSIDE that rectangle - the "ESL_..." header, the BLE indicator, the
// temperature and the battery line - would therefore go stale, so a change in
// any of them must force a full (whole-panel) refresh instead.
// 0xFF/0x7FFF/0xFFFF mean "nothing shown yet" and trigger the first full paint.
RAM uint8_t  last_ble_shown  = 0xFF;   // last displayed BLE-connected state
RAM int16_t  last_temp_shown = 0x7FFF; // last displayed panel temperature (degC)
RAM uint16_t last_batt_shown = 0xFFFF; // last displayed battery voltage (mV)

// ---- v14.0: the glass gets a snapshot, not the live reading ------------------
// The partial window is a BAND of glass columns, not a rectangle: SSD1680 drives
// gate lines, so every row inside the band is rewritten.  v14.0's band is
// x 140..231, and row 1's temperature and voltage land inside it.  Handing
// epd_display() the live values would therefore have two costs, both fatal to
// the point of the window:
//   * the ADC's last digit wobbles by a millivolt or two, so row 1 would differ
//     from the glass on nearly every tick and be repainted every minute - the
//     saving the smaller window buys, spent again on a digit nobody is reading;
//   * a value that changes the string's WIDTH (9 -> 10 degC, 999 -> 1000 mV)
//     would slide the rest of the row sideways, and only the part inside the
//     band would be repainted - the glass would show the tail of the new string
//     over the tail of the old one until the next hourly refresh.
// So the displayed values are frozen between full refreshes: they are what is
// on the glass, which is what last_*_shown already means.  The temperature and
// battery still update on every full refresh (hourly, or on the dead bands).
RAM uint16_t shown_mv  = 0xFFFF;       // value currently ON the glass
RAM int16_t  shown_temp = 0;

// ---- v12.0: full-refresh forensics (temporary) ------------------------------
// The tag was reported to flash the WHOLE panel through black/white/black every
// 1-4 minutes at a random interval.  `full` below can only be raised by four
// things, so each one gets a counter and the four counters are drawn on the
// glass (see EPD_USE_REFRESH_DEBUG in epd.c).  One glance after half an hour
// says which of them is doing it instead of guessing at the physics.
//
//   H = the hour changed        - once an hour is the DESIGNED full refresh
//   T = the panel temperature left its dead band
//   B = the battery voltage left its dead band
//   L = the BLE connect state flipped
//
// Counted only when the refresh is actually painted, so the on-glass numbers
// match the flashes the eye sees.  dbg_armed skips the very first tick, whose
// sentinel comparisons (0xFF / 0x7FFF / 0xFFFF) are not real causes.
//
// v13.0: the saturation cap is per-counter, and the on-glass format has to
// agree with it (tools/verify_refresh_debug.py fails if the two drift apart).
// A flat cap of 9 was a mistake: H counts the hourly refresh, of which there
// are 18 between 06:00 and 23:00, so it pegged at "H9" before lunch and the
// reading said nothing.  The cap was chosen from what fits on the glass rather
// than from how often the event happens - it should have been the other way
// round.  The other three are expected to sit at or near zero, where a peg at
// 9 is itself the alarm, so one digit is right for them.
RAM uint8_t  dbg_hour = 0;
RAM uint8_t  dbg_temp = 0;
RAM uint8_t  dbg_batt = 0;
RAM uint8_t  dbg_ble  = 0;
RAM uint8_t  dbg_armed = 0;
#define DBG_BUMP_H(c) do { if ((c) < 99) (c)++; } while (0) // hourly: needs 2 digits
#define DBG_BUMP(c)   do { if ((c) < 9)  (c)++; } while (0) // rare: 9 already means "look"

// ---- v11.0: dead bands for the two analog sources ---------------------------
// Up to v10.0 the panel temperature was compared with `!=`.  That is a trap.
// The SSD1680 internal sensor is quantised to 1 degC, and the reading is taken
// *during* the refresh - epd.c calls EPD_BWR_213_Display(), which issues 0x1B
// and reads the register after 0x20 Master Activation, i.e. while the boosters
// are heating the die.  Storing that value in epd_temperature and handing it
// back through EPD_read_temp()'s cache means every comparison pits "die
// temperature at the end of refresh N-1" against "die temperature at the end of
// refresh N".  Whenever the ambient temperature sits near a quantisation
// boundary, those two readings land on opposite sides of it and toggle by 1
// degree.  Each toggle forced a FULL panel refresh, so the tag flickered
// through the whole black/white/black sequence every few minutes - and the
// interval looked random because it depends purely on where the ambient
// temperature happens to fall between two steps, not on any timer.
//
// A dead band removes it: the panel is only re-driven when the reading really
// moves.  The cost is that the displayed temperature can lag by up to
// (threshold - 1) degC until the next hourly full refresh - invisible for a
// value that moves a couple of degrees per day.
#define TEMP_FULL_HYSTERESIS_C   3
// Same reasoning for the battery: get_battery_mv() is sampled every 30 s in
// main_loop and 32 mV of hysteresis did not absorb the ADC noise.
#define BATT_FULL_HYSTERESIS_MV  100

// Settings
extern settings_struct settings;

_attribute_ram_code_ void user_init_normal(void)
{                            // this will get executed one time after power up
    random_generator_init(); // must
    init_time();
    init_ble();
    init_flash();
    init_nfc();
    // v4.0 clock-only: the user-image alternation is disabled, so the flash
    // image check is no longer needed at boot (see main_loop comment).
    // user_image_check_flash();

    // epd_display_tiff((uint8_t *)bart_tif, sizeof(bart_tif));
    // epd_display(3334533);
}

_attribute_ram_code_ void user_init_deepRetn(void)
{ // after sleep this will get executed
    blc_ll_initBasicMCU();
    rf_set_power_level_index(RF_POWER_P3p01dBm);
    blc_ll_recoverDeepRetention();
}

_attribute_ram_code_ void main_loop(void)
{
    blt_sdk_main_loop();
    handler_time();

    if (time_reached_period(Timer_CH_1, 30))
    {
        battery_mv = get_battery_mv();
        battery_level = get_battery_level(battery_mv);
        set_adv_data(EPD_read_temp() * 10, battery_level, battery_mv);
        ble_send_battery(battery_level);
        ble_send_temp(EPD_read_temp() * 10);
    }

    // v5.0: a BLE time sync (0xDD) repaints immediately instead of waiting for
    // the next minute tick. Computed before the minute check so it also fires
    // inside the night window.
    uint8_t force_refresh = 0;
    if (time_just_set)
    {
        time_just_set = 0;
        force_refresh = 1;
    }

    uint8_t current_minute = (get_time() / 60) % 60;
    if (force_refresh || current_minute != minute_refresh)
    {
        minute_refresh = current_minute;
        uint8_t current_hour = ((get_time() / 60) / 60) % 24;

        // ------------------------------------------------------------------
        // v6.0: decide between a real PARTIAL refresh (clock digits only, cheap)
        // and a FULL panel refresh.  A full refresh is required when:
        //   * the hour changed  -> the hourly ghost-clearing full refresh, or
        //   * something drawn outside the partial window changed (see the
        //     last_*_shown variables above); otherwise those lines would stay
        //     stale until the top of the next hour.
        // v11.0: the temperature and battery comparisons use dead bands, see
        // TEMP_FULL_HYSTERESIS_C / BATT_FULL_HYSTERESIS_MV above.  Without them
        // the 1 degC quantisation of the panel sensor and the ADC noise
        // defeated the window again almost every tick, and the tag did a full
        // black/white/black refresh every few minutes instead of hourly.
        // ------------------------------------------------------------------
        uint8_t force_full = 0;
        uint8_t cause_ble = 0, cause_temp = 0, cause_batt = 0; // v12.0 forensics

        uint8_t ble_now = ble_get_connected();
        if (ble_now != last_ble_shown)
        {
            last_ble_shown = ble_now;
            force_full = 1;
            cause_ble = 1;
        }

        // v11.0: dead band instead of `!=` - see TEMP_FULL_HYSTERESIS_C above.
        // The first comparison still fires (last_temp_shown starts at 0x7FFF).
        // v14.2: (int8_t) - the SSD1680 register is two's complement, so a room
        // below 0 C must read as negative, not as 200+.
        int16_t temp_now = (int8_t)EPD_read_temp();
        if ((temp_now > last_temp_shown ? temp_now - last_temp_shown
                                        : last_temp_shown - temp_now) >= TEMP_FULL_HYSTERESIS_C)
        {
            last_temp_shown = temp_now;
            force_full = 1;
            cause_temp = 1;
        }

        if (last_batt_shown == 0xFFFF)
        {
            last_batt_shown = battery_mv; // first paint: adopt, no forced refresh
        }
        else if ((battery_mv > last_batt_shown ? battery_mv - last_batt_shown
                                               : last_batt_shown - battery_mv) >= BATT_FULL_HYSTERESIS_MV)
        {
            last_batt_shown = battery_mv;
            force_full = 1;
            cause_batt = 1;
        }

        uint8_t hour_changed = (current_hour != hour_refresh) ? 1 : 0;
        uint8_t full = (hour_changed || force_full) ? 1 : 0;
        hour_refresh = current_hour;

        // v5.0 night silence: skip the repaint, but keep the bookkeeping above
        // up to date so the morning tick is a full refresh.
        uint8_t night = (current_hour >= NIGHT_START_HOUR) && (current_hour < NIGHT_END_HOUR);

        // ------------------------------------------------------------------
        // Clock-only mode (v4.0).
        // The previous time<->image alternation was removed on request: the tag
        // now always renders the live clock / status screen on the minute tick.
        // A BLE-uploaded image is still shown ONCE immediately by the 0x01
        // handler in epd_ble_service.c; the next minute tick returns the glass
        // to the clock.
        // To restore alternation later: re-add `user_image_check_flash()` in
        // user_init_normal() and branch here on `has_user_image && display_toggle`.
        // v5.0: the panel is driven only when it is actually visible/useful -
        // never before the first paint of this power cycle, and not at night.
        // ------------------------------------------------------------------
        uint8_t paint = (force_refresh || !first_refresh_done || !night) ? 1 : 0;

        // v12.0 forensics: tally only the full refreshes that are actually
        // painted, so the on-glass counters match the flashes the eye sees.
        // Done BEFORE epd_display() because that is what draws them.
        if (paint && full && dbg_armed)
        {
            if (cause_ble)    DBG_BUMP(dbg_ble);
            if (cause_temp)   DBG_BUMP(dbg_temp);
            if (cause_batt)   DBG_BUMP(dbg_batt);
            if (hour_changed) DBG_BUMP_H(dbg_hour);
        }
        dbg_armed = 1;

        if (paint)
        {
            // v14.0: freeze the displayed values until the next full refresh -
            // see the "snapshot" block above.  `full` is known before the call,
            // so the snapshot is taken on exactly the ticks that repaint the
            // whole panel.
            if (full)
            {
                shown_mv = battery_mv;
                /* v14.2: the panel sensor, which is what v13.0 displayed and
                 * what the BLE side already reports.  v14.0/v14.1 handed this
                 * `temperature` instead, which is get_temperature_c()'s RAW ADC
                 * sample - the °C conversion in that function is commented out
                 * upstream - so the clamp sat at its ceiling and row 1 read 85 C
                 * all day.  (int8_t) because the SSD1680 register is two's
                 * complement: a room below 0 C reads 200+ as unsigned. */
                shown_temp = (int8_t)EPD_read_temp();
            }

            epd_display(get_time(), shown_mv, shown_temp, full);
            first_refresh_done = 1;
        }
    }

    if (time_reached_period(Timer_CH_0, 10))
    {
        if (ble_get_connected())
            set_led_color(3);
        else
            set_led_color(2);
        WaitMs(1);
        set_led_color(0);
    }

    if (epd_state_handler()) // if epd_update is ongoing enable gpio wakeup to put the display to sleep as fast as possible
    {
        cpu_set_gpio_wakeup(EPD_BUSY, 1, 1);
        bls_pm_setWakeupSource(PM_WAKEUP_PAD);
        bls_pm_setSuspendMask(SUSPEND_DISABLE);
    }
    else
    {
        blt_pm_proc();
    }
}
