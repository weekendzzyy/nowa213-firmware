#pragma once

#include <stdint.h>

uint16_t get_battery_mv(void);
uint8_t get_battery_level(uint16_t battery_mv);

/* get_temperature_c() was removed in v14.2 - it returned a raw ADC sample, not
 * degrees C, and the display reads the panel sensor (EPD_read_temp) instead. */
