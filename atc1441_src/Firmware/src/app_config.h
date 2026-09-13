#pragma once

#if defined(__cplusplus)
extern "C" {
#endif

#define CLOCK_SYS_CLOCK_HZ  	24000000

// v5.0 power saving: BLE advertising interval.
// Unit is 0.625 ms -> 1600 = 1 s (original), 16000 = 10 s.
// Advertising is a constant background drain, so a longer interval saves energy.
// Trade-off: a central (phone/browser) may need up to one interval to discover
// the tag. BLE spec caps adv interval at 10.24 s (16384), so 16000 is legal.
#define ADVERTISING_INTERVAL 16000

// Firmware version.  Bump this together with the git tag and the
// firmware_releases/ file name.
//
// v14.0 removed the on-glass version badge (the reference layout has no room
// for one - row 3's right-hand corner belongs to the device name), so this
// string was no longer drawn anywhere.  v14.1 brought it back: the corner now
// alternates between the name and this string every ROW3_ALT_SECS, so what it
// says is what appears on the glass for half the time.
// It is still what the release tooling and the firmware_releases/ file name key
// off, and tools/verify_v14_layout.py fails if the width no longer fits the
// slot epd_layout.h reserves for it.
// Format: "v<major>.<minor>" - keep it 5 characters, or re-check ROW3_TEXT_MAX_ADV.
#define FW_VERSION_STRING "v15.2"

// Numeric version, written into the NFC status block (docs/v15-nfc-command-cheatsheet.md).
#define FW_VERSION_MAJOR 15
#define FW_VERSION_MINOR 2

#define RAM _attribute_data_retention_ // short version, this is needed to keep the values in ram after sleep

#include "application/print/u_printf.h"
enum{
	CLOCK_SYS_CLOCK_1S = CLOCK_SYS_CLOCK_HZ,
	CLOCK_SYS_CLOCK_1MS = (CLOCK_SYS_CLOCK_1S / 1000),
	CLOCK_SYS_CLOCK_1US = (CLOCK_SYS_CLOCK_1S / 1000000),
};

///////////////////////////////////// ATT  HANDLER define ///////////////////////////////////////
typedef enum
{
	ATT_H_START = 0,

	//// Gap ////
	/**********************************************************************************************/
	GenericAccess_PS_H, 					//UUID: 2800, 	VALUE: uuid 1800
	GenericAccess_DeviceName_CD_H,			//UUID: 2803, 	VALUE:  			Prop: Read | Notify
	GenericAccess_DeviceName_DP_H,			//UUID: 2A00,   VALUE: device name
	GenericAccess_Appearance_CD_H,			//UUID: 2803, 	VALUE:  			Prop: Read
	GenericAccess_Appearance_DP_H,			//UUID: 2A01,	VALUE: appearance
	CONN_PARAM_CD_H,						//UUID: 2803, 	VALUE:  			Prop: Read
	CONN_PARAM_DP_H,						//UUID: 2A04,   VALUE: connParameter

	//// gatt ////
	/**********************************************************************************************/
	GenericAttribute_PS_H,					//UUID: 2800, 	VALUE: uuid 1801
	GenericAttribute_ServiceChanged_CD_H,	//UUID: 2803, 	VALUE:  			Prop: Indicate
	GenericAttribute_ServiceChanged_DP_H,   //UUID:	2A05,	VALUE: service change
	GenericAttribute_ServiceChanged_CCB_H,	//UUID: 2902,	VALUE: serviceChangeCCC

	//// battery service ////
	/**********************************************************************************************/
	BATT_PS_H, 								//UUID: 2800, 	VALUE: uuid 180f
	BATT_LEVEL_INPUT_CD_H,					//UUID: 2803, 	VALUE:  			Prop: Read | Notify
	BATT_LEVEL_INPUT_DP_H,					//UUID: 2A19 	VALUE: batVal
	BATT_LEVEL_INPUT_CCB_H,					//UUID: 2902, 	VALUE: batValCCC

	//// Temp service ////
	/**********************************************************************************************/
	TEMP_PS_H, 								//UUID: 2800, 	VALUE: uuid 181A
	TEMP_LEVEL_INPUT_CD_H,					//UUID: 2803, 	VALUE:  			Prop: Read | Notify
	TEMP_LEVEL_INPUT_DP_H,					//UUID: 2A19 	VALUE: tempVal
	TEMP_LEVEL_INPUT_CCB_H,					//UUID: 2902, 	VALUE: tempValCCC

	//// Ota ////
	/**********************************************************************************************/
	OTA_PS_H, 								//UUID: 2800, 	VALUE: telink ota service uuid
	OTA_CMD_OUT_CD_H,						//UUID: 2803, 	VALUE:  			Prop: read | write_without_rsp
	OTA_CMD_OUT_DP_H,						//UUID: telink ota uuid,  VALUE: otaData
	OTA_CMD_OUT_DESC_H,						//UUID: 2901, 	VALUE: otaName

	//// RxTx ////
	/**********************************************************************************************/
	RxTx_PS_H, 								//UUID: , 	VALUE: RxTx service uuid
	RxTx_CMD_OUT_CD_H,						//UUID: , 	VALUE:  			Prop: read | write_without_rsp
	RxTx_CMD_OUT_DP_H,						//UUID: RxTx uuid,  VALUE: RxTxData
	RxTx_CMD_OUT_DESC_H,						//UUID: 2901, 	VALUE: RxTxName

	//// EPD_BLE ////
	/**********************************************************************************************/
	EPD_BLE_PS_H, 								//UUID: , 	VALUE: EPD_BLE service uuid
	EPD_BLE_CMD_OUT_CD_H,						//UUID: , 	VALUE:  			Prop: write_without_rsp
	EPD_BLE_CMD_OUT_DP_H,						//UUID: EPD_BLE uuid,  VALUE: EPD_BLEData
	EPD_BLE_CMD_OUT_DESC_H,						//UUID: , 	VALUE: EPD_BLEName

	ATT_END_H,

}ATT_HANDLE;

#include "vendor/common/default_config.h"

#if defined(__cplusplus)
}
#endif
