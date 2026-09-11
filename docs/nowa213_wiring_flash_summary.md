# 汉朔 Nowa-213R-N 刷机：连线与刷固件速查总结

> 聚焦"接线 + 刷机"两步实操。NFC/DIY/电池等扩展内容见 `nowa213_flash_research.md`。
> 全部步骤已在 2026-09-03 实测通过。

---

## 1. 硬件确认（已实测）

| 项目 | 结论 |
|---|---|
| 设备 | 汉朔（Hanshow）Nowa-213R-N（2.13" / 红黑白 BWR / 带 NFC） |
| 主控 MCU | Telink **TLSR8359F512ET32** |
| 屏幕驱动 | SSD1680（250×122，三色无灰阶） |
| NFC | 复旦微 FM11NC081（I2C：PC0=SDA / PC1=SCL / PC4=IRQ） |
| 板上焊盘丝印 | SWS、RXD、TXD、RST、VCC、GND（已留出，不用飞线找测试点） |
| 电池 | 原配两节纽扣电池**并联**，系统电压 3V |

---

## 2. 工具与软件

- **CH340C USB-TTL 模块**（引脚布局：**5V – RTS – DTR – 3V3** 一侧，另一侧 RX/TX/GND）
  - 电平跳线必须拨到 **3.3V**（严禁 5V，TLSR8359 最大 3.6V，5V 会烧）
  - 非 FTDI、RX 无 LED → pvvx 兼容
- **CH340 驱动**：Windows 设备管理器出现 `USB-SERIAL CH340 (COMx)` 即可（本机为 **COM6**）
- **pvvx 刷机工具**：`TlsrComSwireWriter/TLSR825xComFlasher.py`（已复制至工作区）
- 环境：`pip install pyserial`
- **atc1441 固件**：`atc1441_StellarM3N_E31HA.bin`（90840 字节，atc1441 仓库预编译 `ATC_Paper.bin`，250×122，已复制到刷机目录）

---

## 3. 接线（最终实测可用版）

### 核心接法（SWS 单线，推荐）

| 价签板焊盘 | CH340C 模块 | 说明 |
|---|---|---|
| GND | GND | 共地 |
| VCC | **3V3** | 跳线在 3.3V |
| SWS | **TX**（直连） | 发命令 |
| SWS | **RX**（直连） | 读回应答（整片备份必须接；纯写可省略） |
| RST | **RTS** | 复位（pvvx 用 RTS 拉低复位，源码确认） |

> TX 和 RX 都焊到同一个 SWS 焊盘，正常操作不冲突。
> **DTR 不用接**——早期误判"模块无 RTS 才需 DTR"，实际模块有 RTS，RST 接 RTS 即标准解法。

### 网页 UART 方案（仅写、不能备份，不推荐首用）
| 价签板 | CH340C |
|---|---|
| GND | GND |
| VCC | 3V3 |
| RXD | TXD |
| TXD | RXD |
| RST | RTS |
| SWS | 悬空 |

---

## 4. 备份原厂固件（只读，安全第一）

```powershell
cd D:\WorkBuddy\2026-09-03-13-25-10\nowa213\TlsrComSwireWriter
python TLSR825xComFlasher.py -p COM6 -t 200 rf 0 0x80000 nowa213_original_backup.bin
```

- `-t 200`：激活/唤醒时间，价签久放深度休眠需加长（首跑 `-t 70` 报 `Chip sleep?`，加 RX 接 SWS + `-t 200` 一次过）
- 成功标志：`Read Flash... Done!`，生成 `nowa213_original_backup.bin`
- 验证：524288 字节（= 0x80000 = 整片 512KB）；偏移 `0x238D0` 含 `"hanshow"` 字符串 → 确认原厂固件；未锁读保护，后续任意刷写无障碍

---

## 5. 刷 atc1441 固件

```powershell
python TLSR825xComFlasher.py -p COM6 -t 200 wf 0 atc1441_StellarM3N_E31HA.bin
```

- `wf 0`：从地址 0 写入，pvvx **自动解锁 flash + 按扇区擦写**
- 成功标志：`Write Flash data 0x00000000 to 0x000162d8... Done!`（0x162D8 = 90840 字节，与 bin 一致）
- 实机结果：屏幕显示 `ESL_140EC6 BWR213 / 00:00 / 28°C / Battery 2905mV` → **固件启动成功，屏控 GPIO 完全匹配，无需改引脚**

---

## 5.5 自编译固件：时间↔图片每分钟切换（v2.0，2026-09-04 实测成功）

**功能**：每分钟在「走时界面」与「BLE 上传的图」之间自动交替；没传图时只走时。**图存 Flash（0x79000 扇区），断电不丢、重启自动恢复。**

- 归档：`firmware_releases/atc1441_alternate_flashimg_v2.0_2026-09-04_90972B.bin`（90972 字节，SHA256 `f81eba73…6a0e585`，已刷入实机验证）
- 源码改动（4 文件 5 处）：`epd.c`（删 RAM 缓冲 + `user_image_check_flash/save/restore` 三函数，图存 0x79000："IMG1" magic + 4096B 图像）、`epd.h`（extern/define）、`epd_ble_service.c`（opcode 0x01 推屏后自动存图）、`app.c`（启动查图、切换分支从 Flash 还原图）
- 构建：沙箱无 make，用 `Firmware/build_firmware.py` 精确复刻 makefile 清单，tc32_windows 工具链编译 + `tl_firmware_tools.py add_crc`
- 刷机（注意 `-t 3000`，见坑 #5）：
  ```powershell
  python TLSR825xComFlasher.py -p COM6 -t 3000 wf 0 atc1441_alternate_flashimg.bin
  ```
- **改 RAM 大对象后必查溢出**：`tc32-elf-nm out/ATC_Paper.elf | grep _end_bss_`，必须 < **0x850000**（64KB SRAM 顶 = 栈顶）。boot.link 无溢出检查，编译通过≠能启动。

---

## 6. 救砖还原（随时可用）

```powershell
python TLSR825xComFlasher.py -p COM6 -t 200 wf 0 nowa213_original_backup.bin
```

备份在手，刷坏零风险。

---

## 7. 刷后验证（BLE 是否正常）

1. 拔掉 CH340C **所有**线，价签靠双电池自己复位启动，等 3~5 秒。
2. 安卓装 **nRF Connect** → 扫描 → 找到 **`ESL_140EC6`** 广播 = BLE 正常（最可靠）。
3. 电脑/安卓 Chrome 开 `https://atc1441.github.io/ATC_TLSR_Paper_Image_Upload.html` → 点 Connect → 选 `ESL_140EC6` 即可 BLE 无线传图/OTA。
   - 安卓需开 `设置→应用→Chrome→权限→附近的设备`，否则点 Connect 无反应。
   - iPhone 不行（Safari 禁 Web Bluetooth）。

---

## 8. 关键坑回顾

| 坑 | 原因 | 解决 |
|---|---|---|
| 首跑报 `Chip sleep?` | 未接 CH340 **RX** 到 SWS，速率握手读不回应答 | 补接 RX→SWS + `-t 200` |
| 误判模块无 RTS | 看照片走眼 | 用户纠正：5V-RTS-DTR-3V3；RST 接 RTS |
| 网页 Connect 无反应 | 安卓 Chrome 缺"附近的设备"权限 | 开权限，或 nRF Connect 兜底 |
| 5V 供电 | 跳线拨错 | 必须 3.3V |
| 刷完屏冻结、BLE 死（"时间停止"） | ① pvvx `wf` 后芯片停在 bootloader halt 态不会自启；② 只拔 3V3 时 CH340 TX/RX 的 3.3V 高电平经 SWS 脚 ESD 二极管**倒灌**，芯片没真掉电 | **整根拔 CH340 USB、等 2~3 秒再插**（5 线全断才干净） |
| 自编译固件上电即死、无任何反应 | v1 加 5000 字节 `user_image[]` RAM 缓冲把 `.bss` 推过 64KB SRAM 顶（栈顶 0x850000），boot.link **不查溢出**编译照样过 | 删 RAM 缓冲改存 Flash；每次改 RAM 大对象后用 `tc32-elf-nm | grep _end_bss_` 对照 0x850000 验证 |
| `-t 200` 对已刷 atc1441 固件的芯片报 `Chip sleep?` | atc1441 固件进深睡带 retention，200ms 复位拉不回 bootloader | 刷写用 **`-t 3000`** |

---

## 成品文件清单（工作区）

- `nowa213/TlsrComSwireWriter/nowa213_original_backup.bin` — 原厂固件备份（512KB，救砖底牌）
- `nowa213/TlsrComSwireWriter/atc1441_StellarM3N_E31HA.bin` — atc1441 官方预编译固件（90840B）
- `nowa213/TlsrComSwireWriter/atc1441_alternate_flashimg.bin` — 自编译 v2.0 固件（时间↔图切换，图存 Flash）
- `nowa213/firmware_releases/atc1441_alternate_flashimg_v2.0_2026-09-04_90972B.bin` — v2.0 正式归档（含 SHA256）
- `nowa213/TlsrComSwireWriter/TLSR825xComFlasher.py` — pvvx 刷机工具
- `nowa213/atc1441_src/` — atc1441 源码（含 tc32_windows 工具链；`Firmware/build_firmware.py` 为无 make 构建脚本）
- `nowa213/nowa213_flash_research.md` — 完整研究笔记（含 NFC/DIY/电池扩展）
