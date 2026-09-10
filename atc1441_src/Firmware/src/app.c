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
RAM int16_t temperature;

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
        temperature = get_temperature_c();
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
        // The battery comparison uses a 32 mV hysteresis, because the 1 mV
        // jitter of the ADC would otherwise defeat the window nearly every tick.
        // ------------------------------------------------------------------
        uint8_t force_full = 0;

        uint8_t ble_now = ble_get_connected();
        if (ble_now != last_ble_shown)
        {
            last_ble_shown = ble_now;
            force_full = 1;
        }

        int16_t temp_now = EPD_read_temp();
        if (temp_now != last_temp_shown)
        {
            last_temp_shown = temp_now;
            force_full = 1;
        }

        if (last_batt_shown == 0xFFFF)
        {
            last_batt_shown = battery_mv; // first paint: adopt, no forced refresh
        }
        else if ((battery_mv > last_batt_shown ? battery_mv - last_batt_shown
                                               : last_batt_shown - battery_mv) >= 32)
        {
            last_batt_shown = battery_mv;
            force_full = 1;
        }

        uint8_t full = (current_hour != hour_refresh || force_full) ? 1 : 0;
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
        if (force_refresh || !first_refresh_done || !night)
        {
            epd_display(get_time(), battery_mv, temperature, full);
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
