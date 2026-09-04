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

---

## 开发工具更新 — 250×122 有效区域修正（2026-09-04）

**问题**：测试图在屏幕上看不到下边框，底部横条与屏幕底边之间还有一段白条。
**根因**：面板存储缓冲区是 250×128（16 字节/列、整字节对齐），但实际玻璃只露出约
**250×122** 行，底部 6 行画到了玻璃外面。之前 `epd_image_tool.py` 与测试图按 250×128
作画，所以底边被裁掉。

**修正**：
- `epd_image_tool.py`：新增 `VISIBLE_H = 122`，输入图先缩放到 **250×122** 可见区域，
  再顶部对齐填充到 250×128 存储缓冲区（底部 6 行留白）。预览图也裁到 122 行，
  与屏幕上实际看到的一致。
- `gen_test_image.py`：改为按 250×122 有效区域绘制边框、方向箭头和底部标记。
- `epd.h`：新增 `EPD_VISIBLE_HEIGHT 122` 宏并补充注释，明确物理可见高度。

**验证**：重新生成测试图 → `epd_image_tool.py --bake --flash` 直写 `0x79000` → 断电重启
后应能看到四边完整黑框。

> 提示：以后制作图片只需关注 250×122 区域；底部 6 行不会显示在玻璃上，工具会自动
> 帮你补白对齐。

---

## 网页传图不同步时间 — 根因与修复工具（2026-09-04）

**现象**：用网页工具传图后，价签时间没有同步。

**根因（已读 atc1441 传图工具源码确认）**：时间同步与传图是**两条不同的 BLE 特征**：
- 传图：`EPD_BLE` 服务 `13187b10-…` / 特征 `4b646063-…`，协议 `0000`→`020000`→`03`分块→`01`。
- 时间同步：`RxTx` 服务 `0x1f10` / 特征 `0x1f1f`，命令 `0xDD` + 4 字节大端 Unix 时间戳
  （固件 `cmd_parser.c` 处理，已在 RxTx 特征上正确接线）。
- atc1441 的传图工具 `connect()` **只连 EPD_BLE 特征，全程不发 `0xDD`、甚至不连 RxTx 特征**。
  所以“传图时同步时间”不会发生——命令根本没发。这**不是固件 bug**（固件 `0xDD` 处理正确）。

**修复**：新增 `web_uploader.html`（WebBLE 单页工具，无需改固件、无需重刷）：
- 载入图片 → 按固件期望的 `col*16 + row//8`（MSB=顶，黑=0）打包为 4000 字节；
- 复用 atc1441 已验证的传图协议发到 EPD_BLE 特征；
- 随后向 RxTx 特征写 `0xDD` + 本地 Unix 时间（默认 `UTC+8`，唐山/北京时区）完成校时；
- 含实时预览（直接渲染 `buf`，即屏幕最终样子，已抵消固件翻转+面板扫描）；
- “上传图片” / “同步时间” / “上传+同步时间” 三个按钮，可只用校时按钮配合原工具。
- 用法：`cd nowa213 && python -m http.server 8000`，浏览器开
  `http://localhost:8000/web_uploader.html`（WebBLE 需 localhost/https，勿用 file://）。

**说明**：`0xDD` 设时间后屏幕不会立即刷新（固件只在每分钟交替或下次传图时重绘时间页），
最迟 1 分钟内显示新时间；想立刻看到可再点一次“上传图片”。
