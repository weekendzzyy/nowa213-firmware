#pragma once

#define epd_height 200
#define epd_width 200
#define epd_buffer_size ((epd_height/8) * epd_width)

// Real on-screen dimensions used by the BW213 panel.
// The physical glass exposes ~250x122 rows; the storage buffer is padded to
// 250x128 because each column is stored as whole bytes (16 bytes/column).
// The bottom (128 - 122) = 6 storage rows are off-screen and should be white.
#define EPD_DISPLAY_WIDTH   250
#define EPD_DISPLAY_HEIGHT  128          // storage / transfer height (byte-aligned)
#define EPD_VISIBLE_HEIGHT  122          // physical glass height (do not draw content here)
#define EPD_DISPLAY_SIZE    ((EPD_DISPLAY_WIDTH) * (EPD_DISPLAY_HEIGHT) / 8)  // 4000 bytes

// ============================================================================
// FEATURE: Time <-> User-Image alternation (switches every minute)
// ----------------------------------------------------------------------------
// The tag shows the live clock/status screen by default. Once a user uploads an
// image over BLE, the firmware alternates every minute between:
//   phase 0 : the time / status screen (epd_display)
//   phase 1 : the last uploaded user image
// The uploaded image is persisted in FLASH (not RAM) so it survives deep sleep,
// reset and power loss. Storage helpers live in epd.c (user_image_*).
// NOTE: an earlier version kept a 5KB RAM copy of the image; that pushed .bss
// past the 64KB SRAM top (stack @ 0x850000) and bricked boot. FLASH is used instead.
// ============================================================================
#define USER_IMG_FLASH_ADDR 0x79000  // free 4KB sector (firmware<0x16300, OTA 0x20000-0x40000, settings 0x78000)
extern uint8_t epd_buffer[epd_buffer_size];        // live display framebuffer (also the image scratch area)
extern uint8_t has_user_image;                     // 1 = a valid saved image exists in flash
extern uint8_t display_toggle;                     // alternation phase: 0 = time/status, 1 = user image
void user_image_check_flash(void);  // at boot: read magic, set has_user_image
void user_image_save(void);         // on BLE upload: erase sector + write image + magic
void user_image_restore(void);      // read saved image from flash into epd_buffer
void user_image_flip_horizontal(void); // mirror columns to cancel EPD's default scan direction

void set_EPD_model(uint8_t model_nr);
void init_epd(void);
uint8_t EPD_read_temp(void);
void EPD_Display(unsigned char *image, int size, uint8_t full_or_partial);
void epd_display_tiff(uint8_t *pData, int iSize);
void epd_display(uint32_t time_is, uint16_t battery_mv, int16_t temperature, uint8_t full_or_partial);
void epd_set_sleep(void);
uint8_t epd_state_handler(void);
void epd_display_char(uint8_t data);
void epd_clear(void);

// v12.0 forensics: the four "what forced a full refresh" counters are owned by
// app.c and drawn by epd.c while EPD_USE_REFRESH_DEBUG is 1.  Each saturates
// at 9.  See the v12.0 block in epd.c for what each letter means.
extern uint8_t dbg_hour, dbg_temp, dbg_batt, dbg_ble;