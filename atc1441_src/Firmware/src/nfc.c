#include <stdint.h>
#include "tl_common.h"
#include "drivers.h"
#include "stack/ble/ble.h"
#include "drivers/8258/flash.h"
#include "nfc.h"
#include "main.h"
#include "time.h"
#include "app.h"
#include "battery.h"
#include "i2c.h"
#include "app_config.h"

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

// ---- v15.1 + v15.2: NFC field detection and command channel ------------------
//
// The FM11NC081 (I2C 0xAE, IRQ_N PC4 active low) is an NFC Forum Type 4 Tag with
// an ~900 B user EEPROM.  The phone writes NDEF records there; the MCU reads the
// same EEPROM over I2C.  v15.1 used only the field-present edge (tap = flip).
// v15.2 adds a command channel: scan the EEPROM for our magic frame, execute it,
// then clear the magic so the frame runs exactly once.
//
// User EEPROM base (FM11NC081 datasheet / HiHope SDK): 0x0010, 16-bit I2C
// address.  Read:  i2c_set_id(0xAE); i2c_read_series(addr, 2, buf, len).
// Write: i2c_set_id(0xAE); i2c_write_series(addr, 2, buf, len); + ~10 ms settle.
//
// The frame (docs/v15-requirements.md 4.3):
//   [ magic 0xA5 ][ cmd ][ len ][ payload... ][ sum ]
//   sum = 0xA5 XOR cmd XOR len XOR payload[0..]   (8-bit XOR)
// Two on-air encodings are accepted (cheatsheet 3):
//   * raw binary  - the bytes above verbatim (a "Data"/custom NDEF record);
//   * text hex    - the same bytes written as an ASCII hex string, e.g. the
//                   Text record "A50100A4" (the recommended phone-side form,
//                   because it never gets mangled by UTF-8 like 0xA5 would).
//
// SAFETY (docs/v15-requirements.md 5.1 - hard rule):
//   "省电模式 = turn BLE broadcast off" is NOT implemented and MUST NOT be
//   exposed until the NFC command channel is verified on real hardware.  BLE
//   therefore stays always-on in v15.2.  Command 0x06 mode=0 (省电) is rejected
//   (status 2); 0x03 (open BLE window) is accepted but is a no-op because the
//   window is already permanently open.  This keeps the device always
//   wireless-reachable - a bad NFC frame can never soft-brick it.

#define NFC_E2_BASE       0x0010
#define NFC_CMD_SCAN_LEN  192     // scan window for the command frame
#define NFC_STATUS_ADDR   0x00E0  // reserved status block (outside the scan window)
#define NFC_MAGIC         0xA5

// last command result written to the status block:
//   0 = executed ok, 1 = bad/unknown frame, 2 = rejected (safety), 0xFF = no command (empty tap)
RAM uint8_t nfc_last_cmd = 0;
RAM uint8_t nfc_last_res = 0xFF;

// v15.1 field-detect state
RAM uint8_t nfc_wait_release = 0;
RAM uint32_t nfc_ignore_until = 0;

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

// ---- low-level EEPROM access ------------------------------------------------
static void nfc_e2_read(uint16_t addr, uint8_t *buf, uint8_t len)
{
    i2c_set_id(0xAE);
    i2c_read_series(addr, 2, buf, len);
}

static void nfc_e2_write(uint16_t addr, const uint8_t *buf, uint8_t len)
{
    i2c_set_id(0xAE);
    i2c_write_series(addr, 2, (uint8_t *)buf, len);
    WaitMs(10); // FM11NC081 EEPROM write settle (HiHope demo uses ~10 ms)
}

// ---- frame parsing ----------------------------------------------------------
static int hexval(uint8_t c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    return -1;
}

// raw frame at buf[i]: [A5][cmd][len][payload...][sum]; validate XOR checksum.
// returns total frame length (>=4) if valid, else 0.
static uint8_t valid_raw(const uint8_t *b, uint8_t i, uint8_t n,
                         uint8_t *cmd, uint8_t *plen, const uint8_t **payload)
{
    if (i + 4 > n) return 0;
    if (b[i] != NFC_MAGIC) return 0;
    uint8_t c = b[i+1], l = b[i+2];
    if (i + 3 + l + 1 > n) return 0;
    uint8_t sum = NFC_MAGIC ^ c ^ l;
    for (uint8_t k = 0; k < l; k++) sum ^= b[i+3+k];
    if (sum != b[i+3+l]) return 0;
    *cmd = c; *plen = l; *payload = &b[i+3];
    return (uint8_t)(3 + l + 1);
}

// text-hex frame: ASCII "A5" then hex pairs cmd/len/payload/sum.
// decoded bytes land in paybuf; returns frame char-length if valid, else 0.
static uint8_t valid_text(const uint8_t *b, uint8_t i, uint8_t n,
                          uint8_t *cmd, uint8_t *plen, uint8_t *paybuf, uint8_t paycap)
{
    if (i + 6 > n) return 0;
    if (b[i] != 'A' || b[i+1] != '5') return 0;
    uint8_t pos = i + 2;
    int hi = hexval(b[pos]); int lo = hexval(b[pos+1]);
    if (hi < 0 || lo < 0) return 0;
    uint8_t c = (uint8_t)(hi * 16 + lo); pos += 2;
    hi = hexval(b[pos]); lo = hexval(b[pos+1]);
    if (hi < 0 || lo < 0) return 0;
    uint8_t l = (uint8_t)(hi * 16 + lo); pos += 2;
    if (l > paycap) return 0;
    if (pos + 2 * l + 2 > n) return 0;
    for (uint8_t k = 0; k < l; k++) {
        hi = hexval(b[pos]); lo = hexval(b[pos+1]);
        if (hi < 0 || lo < 0) return 0;
        paybuf[k] = (uint8_t)(hi * 16 + lo); pos += 2;
    }
    hi = hexval(b[pos]); lo = hexval(b[pos+1]);
    if (hi < 0 || lo < 0) return 0;
    uint8_t sumv = (uint8_t)(hi * 16 + lo);
    uint8_t sum = NFC_MAGIC ^ c ^ l;
    for (uint8_t k = 0; k < l; k++) sum ^= paybuf[k];
    if (sum != sumv) return 0;
    *cmd = c; *plen = l;
    return (uint8_t)(pos + 2 - i);
}

// ---- dispatch ---------------------------------------------------------------
// off = index into the scanned buffer where the frame's first byte lives, so the
// magic can be zeroed at NFC_E2_BASE + off to stop re-execution.
static void nfc_exec(uint8_t cmd, uint8_t plen, const uint8_t *payload, uint8_t off)
{
    nfc_last_cmd = cmd;
    switch (cmd)
    {
        case 0x01: // next page (same as an empty tap)
        {
            uint8_t next = app_get_page() + 1;
            if (next > PAGE_TIME + PAGE_COUNT - 1) next = PAGE_TIME;
            app_set_page(next);
            nfc_last_res = 0;
            break;
        }
        case 0x02: // jump to a specific page (1..3)
        {
            if (plen >= 1 && payload[0] >= PAGE_TIME &&
                payload[0] <= PAGE_TIME + PAGE_COUNT - 1) {
                app_set_page(payload[0]);
                nfc_last_res = 0;
            } else {
                nfc_last_res = 1;
            }
            break;
        }
        case 0x04: // set time from 4-byte big-endian unix timestamp (no BLE needed)
        {
            if (plen >= 4) {
                uint32_t t = ((uint32_t)payload[0] << 24) |
                             ((uint32_t)payload[1] << 16) |
                             ((uint32_t)payload[2] << 8) |
                             (uint32_t)payload[3];
                set_time(t); // also flags time_just_set -> main_loop repaints
                nfc_last_res = 0;
            } else {
                nfc_last_res = 1;
            }
            break;
        }
        case 0x05: // force a full refresh of the current page
        {
            app_set_page(app_get_page());
            nfc_last_res = 0;
            break;
        }
        case 0x03: // open BLE window - no-op: BLE is already always-on (省电 mode not implemented)
        {
            nfc_last_res = 0;
            break;
        }
        case 0x06: // set BLE mode: 1=常开 (current state, accepted); 0=省电 rejected by §5.1 rule
        {
            if (plen >= 1 && payload[0] == 1) nfc_last_res = 0;
            else nfc_last_res = 2;
            break;
        }
        default:
            nfc_last_res = 1;
            break;
    }
    // clear the magic so the same frame is not executed again on the next wake
    uint8_t zero = 0;
    nfc_e2_write(NFC_E2_BASE + off, &zero, 1);
}

// write the status block the phone can read back from the reserved EEPROM area
static void nfc_write_status(void)
{
    uint8_t s[16];
    uint16_t mv = get_battery_mv();
    s[0] = 0x5A;
    s[1] = FW_VERSION_MAJOR;
    s[2] = FW_VERSION_MINOR;
    s[3] = (uint8_t)(mv >> 8);
    s[4] = (uint8_t)(mv & 0xFF);
    s[5] = app_get_page();
    s[6] = nfc_last_cmd;
    s[7] = nfc_last_res;
    for (uint8_t k = 8; k < 16; k++) s[k] = 0;
    nfc_e2_write(NFC_STATUS_ADDR, s, 16);
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
    // glitch on the open-drain line would trigger on its own.
    WaitMs(20);
    if (gpio_read(NFC_IRQ) != 0)
        return;

    nfc_wait_release = 1;
    nfc_ignore_until = get_time() + 2;

    // v15.2: scan the NFC EEPROM for a command frame the phone wrote.
    // (Only runs on an actual tap - main_loop calls this every pass but the
    // field check above returns immediately when no phone is present.)
    uint8_t buf[NFC_CMD_SCAN_LEN];
    nfc_e2_read(NFC_E2_BASE, buf, NFC_CMD_SCAN_LEN);

    uint8_t cmd = 0, plen = 0, frame_len = 0, off = 0;
    const uint8_t *payload = NULL;
    uint8_t paybuf[8];

    for (uint8_t i = 0; i + 4 <= NFC_CMD_SCAN_LEN; i++) {
        frame_len = valid_raw(buf, i, NFC_CMD_SCAN_LEN, &cmd, &plen, &payload);
        if (frame_len) { off = i; break; }
    }
    if (!frame_len) {
        for (uint8_t i = 0; i + 6 <= NFC_CMD_SCAN_LEN; i++) {
            frame_len = valid_text(buf, i, NFC_CMD_SCAN_LEN, &cmd, &plen, paybuf, sizeof(paybuf));
            if (frame_len) { off = i; payload = paybuf; break; }
        }
    }

    if (frame_len) {
        nfc_exec(cmd, plen, payload, off);
    } else {
        // empty tap (no valid command) -> flip to the next page (v15.1 semantics)
        nfc_last_cmd = 0;
        nfc_last_res = 0xFF;
        uint8_t next = app_get_page() + 1;
        if (next > PAGE_TIME + PAGE_COUNT - 1) next = PAGE_TIME;
        app_set_page(next);
    }
    nfc_write_status();
}
