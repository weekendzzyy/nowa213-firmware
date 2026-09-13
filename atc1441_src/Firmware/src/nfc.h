#pragma once
#include <stdint.h>
#include "main.h"

void init_nfc(void);

/* v15.1: NFC field detection - see nfc.c for the full story. */
void nfc_gpio_reconfig(void);
void nfc_wake_prepare(void);
void nfc_poll(void);
