#include <stdint.h>
#include "tl_common.h"
#include "drivers.h"
#include "stack/ble/ble.h"
#include "drivers/8258/flash.h"
#include "nfc.h"
#include "main.h"
#include "time.h"

uint8_t nfc_reset[] = {0x03, 0xb5, 0xa0};

_attribute_ram_code_ void init_nfc(void)
{
    gpio_write(NFC_CS, 1);
    gpio_set_func(NFC_CS, AS_GPIO);
    gpio_set_output_en(NFC_CS, 1);
    gpio_set_input_en(NFC_CS, 0);
    gpio_setup_up_down_resistor(NFC_CS, PM_PIN_PULLUP_10K);

    nfc_gpio_reconfig();

    gpio_write(NFC_CS, 0);
    sleep_us(500);
    send_i2c(0xae, nfc_reset, sizeof(nfc_reset));
    gpio_write(NFC_CS, 1);
}

// ---- v15.1: NFC field detection - an untapped tap flips to the next page -----
//
// The FM11NC081 IRQ_N line (PC4, open-drain, active low) is asserted while a
// phone RF field is present or the tag is being accessed
// (docs/nowa213_flash_research.md 15.2).  v15.1 deliberately does NOT parse
// anything the phone writes - that is the v15.2 command channel.  The whole
// feature is: "field appeared" = flip to the next page.
//
// Two hardware facts shape the code:
//
//   * main_loop() returns once per BLE event, i.e. roughly every ADVERTISING_
//     INTERVAL (10 s).  Polling PC4 alone would therefore notice a tap up to
//     10 s late.  nfc_wake_prepare() arms PC4 as a PAD wakeup source before
//     every suspend, so a tap wakes the chip at once and the flip happens on
//     the very next main_loop pass.
//
//   * GPIO setup does not necessarily survive a deep-retention wake, and
//     user_init_deepRetn() re-inits exactly the peripherals it needs - so the
//     PC4 input + pull-up are re-applied there via nfc_gpio_reconfig().
//
// A flip is a deliberate user action, so it goes through app_set_page() and
// paints as a FULL refresh even inside the night window (the page_switch_
// pending path in main_loop is deliberately not night-gated).
//
// Anti-chatter: NFC apps poll repeatedly while open, so after a flip the line
// must be released AND a 2 s window must elapse before the next flip is
// accepted.  The full panel refresh itself takes a few seconds, which also
// keeps the debounce wait out of the user's way.

RAM uint8_t nfc_wait_release = 0;  // field seen, wait for it to go away
RAM uint32_t nfc_ignore_until = 0; // unix time before which taps are ignored

_attribute_ram_code_ void nfc_gpio_reconfig(void)
{
    gpio_set_func(NFC_IRQ, AS_GPIO);
    gpio_set_output_en(NFC_IRQ, 0);
    gpio_set_input_en(NFC_IRQ, 1);
    gpio_setup_up_down_resistor(NFC_IRQ, PM_PIN_PULLUP_10K);
}

void nfc_wake_prepare(void)
{
    // IRQ_N is active low: wake when PC4 is driven low.
    cpu_set_gpio_wakeup(NFC_IRQ, 0, 1);
    bls_pm_setWakeupSource(PM_WAKEUP_PAD);
}

void nfc_poll(void)
{
    uint8_t field = (gpio_read(NFC_IRQ) == 0);

    if (nfc_wait_release)
    {
        if (!field)
            nfc_wait_release = 0; // phone taken away, re-arm
        return;
    }

    if (!field || get_time() < nfc_ignore_until)
        return;

    // Debounce: IRQ_N must still be low after a short settle, otherwise a
    // glitch on the open-drain line would page-flip on its own.
    WaitMs(20);
    if (gpio_read(NFC_IRQ) != 0)
        return;

    nfc_wait_release = 1;
    nfc_ignore_until = get_time() + 2;

    uint8_t next = app_get_page() + 1;
    if (next > PAGE_TIME + PAGE_COUNT - 1)
        next = PAGE_TIME;
    app_set_page(next);
}
