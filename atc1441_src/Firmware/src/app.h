#include <stdint.h>
#include "tl_common.h"
#include "main.h"
#include "drivers.h"
#include "stack/ble/ble.h"
#include "vendor/common/blt_common.h"

#include "battery.h"
#include "ble.h"
#include "flash.h"

void user_init_normal(void);
void user_init_deepRetn(void);
void set_time(uint32_t time_now);
void main_loop(void);

/* v15.0 page control.  epd_ble_service.c calls app_set_page() when the phone
 * asks for another page; the switch is persisted and taken on the next tick. */
void app_set_page(uint8_t page);
uint8_t app_get_page(void);
void app_page_restore(void);