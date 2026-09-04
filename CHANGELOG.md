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

---

## v3.0 — 2026-09-04

**功能**：修复 BLE 上传图片的两个显示问题（相对 v2.0）。
- 水平翻转（镜像）：BW213 控制器默认列扫描为右→左，用户图未抵消该镜像，
  显示成左右镜像。新增 `user_image_flip_horizontal()`，在推送/保存前对图像做
  水平镜像，与时间页（FixBuffer 已镜像一次）行为一致。
- 右侧黑边：v2.0 推送/恢复时按 `epd_buffer_size`（5000 字节）发送，而实际屏
  面积为 250×128/8 = 4000 字节，多发的 1000 字节被渲染为右侧黑块。改为按
  新增宏 `EPD_DISPLAY_SIZE`（4000）发送与保存。

**改动文件**（`atc1441_src/Firmware/src/`）：
- `epd.h` — 新增 `EPD_DISPLAY_WIDTH/HEIGHT/SIZE` 宏；声明 `user_image_flip_horizontal()`
- `epd.c` — 新增 `user_image_flip_horizontal()`；`user_image_save/restore` 改用 `EPD_DISPLAY_SIZE`
- `epd_ble_service.c` — opcode `0x01` 推送前调用 `user_image_flip_horizontal()`，
  显示尺寸改为 `EPD_DISPLAY_SIZE`
- `app.c` — 每分钟恢复显示用户图时尺寸改为 `EPD_DISPLAY_SIZE`

**发布文件**：`firmware_releases/atc1441_alternate_flashimg_v3.0_2026-09-04_91052B.bin`
**SHA256**：`e84de57fb619c3edad5b8f7469c600846fc28e577bf70721bcd32622a40993f0`
**大小**：91052 字节

**烧录**：`python TLSR825xComFlasher.py -p COM6 -t 3000 wf 0 <上述文件>`

> ⚠️ 升级提示：v3 改变了 Flash 中用户图的存储尺寸（v2 存 4096 字节，v3 存
> 4000 字节，布局仍从 `0x79000+4` 起、magic 不变）。旧 v2 存的用户图在 v3 下
> 仍可被 `user_image_restore` 读回并显示，但方向仍是镜像的（v2 存的是未镜像
> 原图，v3 恢复时不再翻转），因此**建议重传一次图片**使镜像方向正确。

---

## 开发工具（随 v3.0 之后加入）

**`nowa213/epd_image_tool.py`**：加速图片方向验证，无需反复刷机+蓝牙上传。
- **PC 预览**：输入图片/原始帧缓冲，秒出两张 PNG：
  - `*_v3_fixed.png` — 预测 v3 固件刷入后屏幕显示的正确方向。
  - `*_v2_buggy.png`  — 预测 v2 固件时的镜像方向。
- **直写 Flash（跳过蓝牙）**：`--bake` 生成 `*_flash_sector.bin`（4096 字节，
  含 `IMG1` magic + 已镜像的 4000 像素），然后用 SWS 刷机命令只写
  `0x79000` 扇区即可：
  ```
  python TLSR825xComFlasher.py -p COM6 -t 3000 wf 0x79000 <name>_flash_sector.bin
  ```
  断电重启后价签即显示新图。v3 固件只须刷一次，之后换图不必再走 BLE。
