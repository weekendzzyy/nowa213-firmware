# 版本历史（CHANGELOG）

发布固件统一存放在 `firmware_releases/`，文件名格式：
`atc1441_alternate_flashimg_vX.Y_YYYY-MM-DD_<大小>B.bin`
每条发布记录 SHA256，用于烧录后读回校验比对。

---

## v2.0 — 2026-09-04

**功能**：时间↔图片每分钟自动切换；用户图存 Flash（断电/深睡不丢，重启自动恢复）。

**改动文件**（`atc1441_src/Firmware/src/`）：
- `epd.h` — 新增 FEATURE 说明块、`USER_IMG_FLASH_ADDR 0x79000`、外部声明
- `epd.c` — 新增 `user_image_check_flash / user_image_save / user_image_restore`
  （Flash 持久化，替代 v1 的 5KB RAM 缓冲，修复 SRAM 溢出变砖）
- `epd_ble_service.c` — opcode `0x01` 推送后调用 `user_image_save()`
- `app.c` — 启动 `user_image_check_flash()`；`main_loop` 每分钟在时间与图间切换

**发布文件**：`firmware_releases/atc1441_alternate_flashimg_v2.0_2026-09-04_90972B.bin`
**SHA256**：`f81eba73651b941697d7d2d3750f2f11c7eb21fe15733dc67256511516a0e585`
**大小**：90972 字节

**烧录**：`python TLSR825xComFlasher.py -p COM6 -t 3000 wf 0 <上述文件>`

---

## 上游基线 — atc1441/ATC_TLSR_Paper（Stellar-M3N @ E31HA）

刷机用的原始 atc1441 固件：`TlsrComSwireWriter/atc1441_StellarM3N_E31HA.bin`（90840 字节）。
作为「官方 stock」救砖底牌，也用于回退验证 GPIO 兼容性。

> ⚠️ 汉朔原厂固件备份 `nowa213_original_backup.bin` 已损坏为 0 字节（丢失），
> 无法用于恢复原厂界面；如需原厂请从另一台同型号价签重新备份。
