#pragma once

uint8_t EPD_BWR_213_detect(void);
uint8_t EPD_BWR_213_read_temp(void);
uint8_t EPD_BWR_213_Display(unsigned char *image, int size, uint8_t full_or_partial);
void EPD_BWR_213_set_sleep(void);

/* v15.0: the same refresh, opened up so the black and red frames can be built
 * one after the other in a single buffer, and so the caller can say which gates
 * a partial refresh drives (the time page and the calendar page use different
 * bands).  EPD_BWR_213_Display() is Begin + Load(0x24) + LoadZeros(0x26) +
 * Activate, with the time page's band. */
uint8_t EPD_BWR_213_Begin(uint8_t full_or_partial, uint16_t gate_first, uint16_t gates);
void EPD_BWR_213_Load(unsigned char *image, int size, uint8_t ram_cmd);
void EPD_BWR_213_LoadZeros(int size, uint8_t ram_cmd);
void EPD_BWR_213_Activate(uint8_t full_or_partial);