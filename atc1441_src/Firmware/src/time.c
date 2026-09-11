#include <stdint.h>
#include "tl_common.h"
#include "drivers.h"
#include "stack/ble/ble.h"
#include "drivers/8258/flash.h"
#include "time.h"
#include "main.h"

RAM uint16_t time_trime = 5000;// The higher the number the slower the time runs!, -32,768 to 32,767 
RAM uint32_t one_second_trimmed = CLOCK_16M_SYS_TIMER_CLK_1S;
RAM uint32_t current_unix_time;
RAM uint8_t time_just_set = 0; // set by set_time(), cleared by main_loop after repaint
RAM uint32_t last_clock_increase;
RAM uint32_t last_reached_period[10] = {0};
RAM uint8_t has_ever_reached[10] = {0};

_attribute_ram_code_ void init_time(void)
{
    one_second_trimmed += time_trime;
    current_unix_time = 0;
}

_attribute_ram_code_ void handler_time(void)
{
    // v9.0 fix: the clock used to advance by AT MOST ONE SECOND PER CALL, because
    // this was an `if`.  That silently assumed main_loop() runs far more often
    // than once per second - which is no longer true:
    //
    //   app.c main_loop() calls blt_sdk_main_loop() first, and the BLE stack
    //   sleeps inside it (disassembly: blt_sdk_main_loop -> blt_brx_sleep ->
    //   cpu_sleep_wakeup), so it only returns at the next BLE event.  v5.0 raised
    //   ADVERTISING_INTERVAL from 1600 (1 s) to 16000 (10 s), which reduced the
    //   handler_time() call rate to well under 1 Hz.  The clock was therefore
    //   clamped to (calls per second) instead of being driven by real time, and
    //   ran roughly 2x too slow - exactly the reported symptom ("one tag minute
    //   takes two real minutes or more").
    //
    // clock_time() is a valid real-time source for catching up: it is the 16 MHz
    // system timer (timer.h: "system Timer : 16Mhz, Constant") and the SDK keeps
    // it continuous across sleep - main.c calls blc_pm_select_internal_32k_crystal()
    // which sets pm_tim_recover = pm_tim_recover_32k_rc, and that routine
    // extrapolates the 32k RTC (which does run while the MCU sleeps):
    //
    //     sys_tick = tick_cur + ((now_32k - last_32k) * tick_32k_calib) >> 4
    //
    // So catch up in a loop rather than once.  Each iteration is a few cycles; a
    // worst-case backlog of an hour is ~3600 iterations, i.e. microseconds.
    //
    // Boundary: clock_time() is 32-bit at 16 MHz, so it wraps every 268.4 s.  The
    // unsigned delta stays correct only while a single sleep is shorter than that.
    // With ADVERTISING_INTERVAL = 16000 (10 s) the tag wakes far more often than
    // that, so the limit is not reachable - but it is why this fix depends on
    // advertising staying enabled.
    // See tools/verify_time_catchup.py, which models the old and new bodies
    // against the real wake schedule.
    while (clock_time() - last_clock_increase >= one_second_trimmed)
    {
        last_clock_increase += one_second_trimmed;
        current_unix_time++;
    }
}

_attribute_ram_code_ uint8_t time_reached_period(timer_channel ch, uint32_t seconds)
{
    if (!has_ever_reached[ch])
    {
        has_ever_reached[ch] = 1;
        return 1;
    }
    if (current_unix_time - last_reached_period[ch] >= seconds)
    {
        last_reached_period[ch] = current_unix_time;
        return 1;
    }
    return 0;
}

_attribute_ram_code_ void set_time(uint32_t time_now)
{
    current_unix_time = time_now;
    // v5.0: tell main_loop a fresh time arrived (BLE 0xDD) so the panel can be
    // repainted immediately instead of waiting for the next minute tick - which
    // matters at night, when the periodic repaint is intentionally paused.
    time_just_set = 1;
}

_attribute_ram_code_ uint32_t get_time(void)
{
    return current_unix_time;
}
