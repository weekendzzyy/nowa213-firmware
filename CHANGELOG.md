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

### 修复 — WebBLE 连接报错 `Invalid Service name: '1f10'`（2026-09-10）

**问题**：`requestDevice` 抛 `TypeError: Invalid Service name: '1f10'`。

**根因**：Web Bluetooth 不接受 16 位短 UUID 别名（`'1f10'` / `'1f1f'`）。
固件 GATT 表中 RxTx 服务/特征确实是 16 位 UUID（`my_RxTx_ServiceUUID = 0x1f10`、
`my_RxTxUUID = 0x1f1f`），但浏览器要求写成完整 128 位形式。

**修复**（`web_uploader.html`）：
- `RXTX_SERVICE` → `00001f10-0000-1000-8000-00805f9b34fb`
- `RXTX_CHAR`    → `00001f1f-0000-1000-8000-00805f9b34fb`
- 顺手修掉“重连”按钮的真 bug：原实现 `device.gatt.connect().then(connect)` 会再次调用
  `requestDevice` 弹出设备选择框；现拆分为 `setupServices()` + `reconnect()`，重连同一设备、不再弹窗。

**顺带核实（无需改动）**：
- ATT 写入不做长度校验：`my_EPD_BLE_Data` / `my_RxTx_Data` 均为单字节 `u8`，而传图每包写
  240 字节一直正常，证明 Telink 栈按 `rf_packet_att_data_t.dat[]` 透传完整负载，
  因此 5 字节的 `0xDD + 时间戳` 不会被截断；`cmd_parser.c` 正是从 `req->dat[1..4]` 组装时间。
- 时区不会被二次叠加：固件 `app.c` 直接用 `get_time()` 做 `%24` / `%60` 取时分，不施加任何
  偏移，故工具发送 `Date.now()/1000 + 8*3600`（东八区本地时间）是正确的。

---

## v4.0 — 2026-09-10（纯时钟模式）

**需求**：不再需要「时间 ↔ 图片」每分钟交替，价签一直显示时间。

**改动**（`atc1441_src/Firmware/src/app.c`）：
- `main_loop()` 的整分 tick 里删除交替分支，直接 `epd_display(get_time(), ...)`，
  即每分钟只重绘时间/状态页。
- `user_init_normal()` 中注释掉 `user_image_check_flash()`（不再需要启动时读 flash 标志）。
- 保留 `epd.c` 中的 `user_image_*` 与 `epd_ble_service.c` 的 0x01 路径不变：
  BLE 上传的图片仍会**立即显示一次**，下一分钟整分刷新时自动回到时钟。
- 代码内留下注释说明如何恢复交替功能（重新调用 `user_image_check_flash()` +
  在整分分支里按 `has_user_image && display_toggle` 分流）。

**构建**：`_end_bss_ = 0x84efc1`（栈顶 0x850000，余量 4159 B，与 v3.0 相同，无 SRAM 风险）。

**发布文件**：`firmware_releases/atc1441_clockonly_v4.0_2026-09-10_90988B.bin`
**SHA256**：`dfafb06bb668c54b4b88d63b7819dcb08d1f24cf2ac7daf33d298a3f3493b2aa`
**大小**：90988 字节

**烧录**：`python TLSR825xComFlasher.py -p COM6 -t 3000 wf 0 <上述文件>`

**另修（`web_uploader.html`）**：校时日志时间显示错误。`t` 已是「UTC+8 的 epoch」，
原代码再用 `toLocaleString()` 按浏览器本地时区渲染 → 二次加 8 小时（显示 22:09 而实际 14:09）。
改为用 `getUTC*` 拼字符串输出，并标注 `(UTC+8)`。**写入设备的时间戳本身一直是对的**，
固件 `time.c` 存原始值、`app.c` 用 `%24`/`%60` 取值，不施加任何时区偏移。

---

## 工具新增 — `web_flasher.html` 网页刷固件（BLE OTA，2026-09-10）

**背景**：CH340 不在时无法用 SWS 串口刷机，改走设备自带的 BLE OTA 通道。

**协议事实（对照 `Firmware/src/ota.c` + 上游 ATC_TLSR_Paper 逐一核实）**：
- OTA 是 atc1441 **自定义实现**，不是 Telink SDK OTA。服务/特征 `0x221f` / `0x331f`
  （`my_OtaServiceUUID` / `my_OtaUUID`），属性 `NOTIFY | WRITE`。
- 镜像放到 OTA bank `0x20000`（`OTA_BANK_START`，大小 `0x20000` = 128 KB），
  命令流：`01` 擦 4 KB 扇区 → `03` 填充 256 字节 RAM 缓冲 → `02` 落一个 bank →
  `07 C001CEED <crc>` 触发 `write_ota_firmware_to_flash()`：擦 `0x00000–0x1FFFF`、
  整块拷贝到地址 0、重启。
- **`0x79000` 用户图扇区与 `0x78000` 设置扇区不在擦除范围内，不受影响。**
- 固件头 bytes[8..11] 必须是 `4B 4E 4C 54`（"TLNK"）；本 `ATC_Paper.bin` 通过。

**发现并规避的坑（已用离线仿真证明）**：
`case 7` 的「CRC 校验」比较的是**设备自己的** `out_buffer[5..6]` 与 `crc_out`，
而不是主机发来的 CRC 字节。正常流程下最后一条 `02` 把两者都清成 0，所以该判断等价于
「只认 magic 词」，上传的 CRC 被完全忽略 —— **OTA 实际上没有完整性校验**。
更进一步：一旦先发过 `04`（回读）或 `06`，`out_buffer` 被污染，magic 门禁反而会失败。
因此本工具在提交前**多发一条 `05 00000000`**，把 `out_buffer` 显式归零，
使门禁确定性通过，从而让「先回读校验、再提交」这一更安全的流程成立。

**`web_flasher.html` 相比官方工具的安全性改进**：
1. 载入 `.bin` 时校验 TLNK 固件头与大小上限，拒绝非法文件；
2. 上传完成后**默认逐字节回读整个镜像比对**（cmd `04`，约 4550 次读），
   全部一致才提交；任何不一致直接中止且**不提交** → 设备继续跑旧固件，不会变砖；
3. 提交前用 cmd `05` 归零门禁；
4. 内置「同步时间」按钮（`0xDD`）——OTA 后设备时间归零，必须重新校时。

**配套离线验证**：`tools/ota_protocol_sim.js`（Node，无依赖）用真实 `ATC_Paper.bin`
重放完整流程，忠实模拟 `ota.c` 状态机与 `write_ota_firmware_to_flash()`，断言：
擦除彻底、回读一致、门禁通过、终态 `0x00000` 处镜像逐字节等于 `.bin`、
镜像之后为 `0xFF`、`0x40000+` 未被触碰；并验证「先回读不归零则拒绝提交」、
「单字节损坏会被回读抓到且不提交」。全部通过。

**用法**：`python -m http.server 8000` → `http://localhost:8000/web_flasher.html`
→ 连接 → 选 `firmware_releases/atc1441_clockonly_v4.0_2026-09-10_90988B.bin` → 开始刷写
→ 刷完设备自动重启断连 → 重新「连接」→ 点「同步时间」。
