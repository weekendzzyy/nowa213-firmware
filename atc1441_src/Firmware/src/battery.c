#include <stdint.h>
#include "tl_common.h"
#include "main.h"
#include "drivers.h"
#include "stack/ble/ble.h"

#include "battery.h"

_attribute_ram_code_ void adc_init_firmware(ADC_InputPchTypeDef p_ain, ADC_InputNchTypeDef n_ain)
{
	adc_power_on_sar_adc(0);
	adc_set_sample_clk(5);
	adc_set_left_right_gain_bias(GAIN_STAGE_BIAS_PER100, GAIN_STAGE_BIAS_PER100);
	adc_set_chn_enable_and_max_state_cnt(ADC_MISC_CHN, 2);
	adc_set_state_length(240, 0, 10);
	analog_write(anareg_adc_res_m, RES14 | FLD_ADC_EN_DIFF_CHN_M);
	adc_set_ain_chn_misc(p_ain, n_ain);
	adc_set_input_mode_chn_misc(DIFFERENTIAL_MODE);
	adc_set_ref_voltage(ADC_MISC_CHN, ADC_VREF_1P2V);
	adc_set_tsample_cycle_chn_misc(SAMPLING_CYCLES_6);
	adc_set_ain_pre_scaler(ADC_PRESCALER_1);
	adc_power_on_sar_adc(1);
}

_attribute_ram_code_ uint16_t get_adc_reading(ADC_InputPchTypeDef p_ain, ADC_InputNchTypeDef n_ain)
{
	uint16_t temp;
	uint16_t adc_reading_temp;
	volatile unsigned int adc_dat_buf[8];
	int i, j;
	adc_init_firmware(p_ain, n_ain);
	adc_reset_adc_module();
	u32 t0 = clock_time();

	uint16_t adc_sample[8] = {0};
	u32 adc_result;
	for (i = 0; i < 8; i++)
	{
		adc_dat_buf[i] = 0;
	}
	while (!clock_time_exceed(t0, 25))
		;
	adc_config_misc_channel_buf((uint16_t *)adc_dat_buf, 8 << 2);
	dfifo_enable_dfifo2();

	for (i = 0; i < 8; i++)
	{
		while (!adc_dat_buf[i])
			;
		if (adc_dat_buf[i] & BIT(13))
		{
			adc_sample[i] = 0;
		}
		else
		{
			adc_sample[i] = ((uint16_t)adc_dat_buf[i] & 0x1FFF);
		}
		if (i)
		{
			if (adc_sample[i] < adc_sample[i - 1])
			{
				temp = adc_sample[i];
				adc_sample[i] = adc_sample[i - 1];
				for (j = i - 1; j >= 0 && adc_sample[j] > temp; j--)
				{
					adc_sample[j + 1] = adc_sample[j];
				}
				adc_sample[j + 1] = temp;
			}
		}
	}
	dfifo_disable_dfifo2();
	u32 adc_average = (adc_sample[2] + adc_sample[3] + adc_sample[4] + adc_sample[5]) / 4;
	adc_result = adc_average;
	adc_reading_temp = (adc_result * adc_vref_cfg.adc_vref) >> 10;

	adc_power_on_sar_adc(0);
	return adc_reading_temp;
}

_attribute_ram_code_ uint16_t get_battery_mv(void)
{
	/*gpio_set_output_en(GPIO_PB7, 1);
	gpio_set_input_en(GPIO_PB7, 0);
	gpio_write(GPIO_PB7, 1);
	return get_adc_reading(B7P, GND);*/
    adc_init();
	adc_vbat_init(GPIO_PB7);
    adc_power_on_sar_adc(1);
	return adc_sample_and_get_result();
}

_attribute_ram_code_ uint8_t get_battery_level(uint16_t battery_mv)
{
	uint8_t battery_level = (battery_mv - 2200) / (31 - 22);
	if (battery_level > 100)
		battery_level = 100;
	if (battery_mv < 2200)
		battery_level = 0;
	return battery_level;
}

/* get_temperature_c() and adc_temp_init() were removed in v14.2.
 *
 * They read the TLSR8359's own ADC in differential mode across the die's
 * temperature-sensor pins and returned the RAW SAMPLE - the °C conversion
 * (579 - ((raw * 840) >> 13)) is commented out upstream, and the name says
 * "c" anyway.  Nothing ever used the number for anything but drawing it, so
 * v13.0's panel showed it as a plausible-looking temperature while the ADC
 * was actually reporting hundreds of counts.
 *
 * v14.0 rewrote the face around the wrong one of the two sensors and the
 * row-1 clamp sat at its ceiling: the tag read 85 C all day.  The panel
 * sensor (EPD_read_temp(), the SSD1680's own die sensor - the same reading
 * the LUT selection and the BLE side use) is the display source now, and
 * both of these went away with it.
 */
