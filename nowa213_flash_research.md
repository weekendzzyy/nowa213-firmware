# 汉朔 Nowa-213R-N 刷机研究笔记

> 研究启动：2026-09-03。设备：汉朔（Hanshow）Nowa-213 系列 2.13" 红黑白电子价签（带 NFC）。
> 主控已确认：**Telink TLSR8359F512ET32**。CH340C USB-TTL 已备。

## 1. 设备身份（已确认）
- 品牌：浙江汉朔科技（Hanshow）。你写的"汉硕"实际是"汉朔"（同门，之前 Stellar-M 也是它家的）。
- 型号："213rn" = **Nowa-213R-N**
  - 213 = 2.13 英寸
  - R = 红黑白（BWR：黑/白/红）
  - N = 带 NFC 芯片（ISO/IEC 14443 Type A，200 字节 NDEF 存储）
  - 无 M（无磁控开关）
- FCC ID：2AHB5-NOWA-213（2019-12 认证，2.4GHz 低功率发射器）

## 2. 硬件参数（来自官方手册 V1.0.1 及拆机）
| 项 | 值 |
|---|---|
| 屏幕 | 2.13" 电子墨水，250×122，**不支持灰阶** |
| 显示驱动 IC | **SSD1675**（手册正文"Screen IC Supports 1675"即此，被截断） |
| 主控 SoC | **Telink TLSR8359F512ET32**（32-bit RISC-V，512KB Flash，64KB RAM，BLE） |
| 无线 | BLE 2.4GHz，2402–2480 MHz，最大发射功率 1dBm |
| NFC | 复旦微 **FM11NC081**，I2C 接口（ISO14443-A，200 字节 NDEF） |
| 电池 | 550mAh × 2（可更换，兼容汉朔标准电池） |
| 尺寸 | 69.7 × 34.8 × 12.0 mm |
| LED | RGB 三色闪烁（ Nowa-213R-N 可能焊/不焊，取决于配置） |
| 主板板号 | **HS_EL5102_1M_67_03** |

好消息：
- SSD1675 + 250×122 与微雪 2.13" B 屏同方案，驱动代码现成。
- 主控与汉朔 Stellar-M3N@ E31H 同族，社区有大量 TLSR8359 价签固件可参考。

## 3. 刷机接口（已丝印标出，无需飞线找点）
拆机后主板上一排焊盘已明确标出：

| 焊盘 | 功能 | 说明 |
|---|---|---|
| **SWS** | 单线从机调试口（Single Wire Slave / PA7） | Telink 私有烧录协议 |
| **RXD** | UART RX（PA0） | 用于 UART bootloader / 日志 |
| **TXD** | UART TX（PD7） | 用于 UART bootloader / 日志 |
| **RST** | RESETB（Pin 25） | 低电平复位，烧录时由 CH340 RTS 拉低 |
| **VCC** | 外部 3.3V 输入 | 给 IO 和芯片供电 |
| **GND** | 地 | 共地 |

这些焊盘就是你的全部接口。**无需**点动 IC 引脚。

## 4. CH340C 接线图
你手头的 CH340C 模块（用户确认实物丝印）：一侧引脚顺序为 **5V – RTS – DTR – 3V3**，即 RTS 与 DTR 相邻、夹在 5V 与 3V3 之间。**模块带 RTS**（早期误判为"无 RTS"已纠正）。

RST 复位控制线优先接 **RTS**（标准），DTR 也可作备选——两者都是 modem 控制线，拉低即触发复位。电平跳线**必须拨到 3.3V**，严禁 5V。

### 方案 A：网页 UART 烧录（最简单，atc1441 工具）
使用 WebSerial 网页工具，走 UART bootloader：

| 价签板 | CH340C 模块 |
|---|---|
| GND | GND |
| VCC | 3.3V |
| RXD | TXD |
| TXD | RXD |
| RST | RTS |
| SWS | 悬空 |

> 注意：网页工具通过 UART（RX/TX）+ RTS 复位进入下载模式。如果失败，可把 RST 先手动短接 GND 再松开触发复位。

### 方案 B：SWS 单线烧录（功能全，pvvx 工具，推荐先备份）
使用 `TLSR825xComFlasher.py`，走 SWS 协议：

| 价签板 | CH340C 模块 |
|---|---|
| GND | GND |
| VCC | 3V3 |
| SWS | **TX（直连，无需电阻）** |
| SWS | RX（直连，建议接，提升 pvvx 回读可靠性；仅接 TX 也能工作） |
| RST | RTS |

> **无需 1k 电阻**：pvvx 官方 README 与立创开源实测方案均为 TX 直连 SWS（3V3 同压，总线冲突风险极低）。若担心 TX 推挽与芯片应答冲突，可串 100Ω–10k 限流电阻，但**非必需**。RX 接上让 pvvx 工具回读更稳；立创实测仅接 `TX–SWS + RTS–RST + 3V3 + GND` 也能通。RST 由 RTS 控制低电平复位。

### 供电建议
- 优先从 CH340C 模块取 **3.3V** 给 VCC 焊盘（确认 CH340C 模块的 3.3V 能输出 ≥100mA；价签静态电流低，通常够）。
- 如果 CH340C 模块电流不够或电压不稳，可外接 3.3V LDO，但**必须共地**。
- **严禁 5V**——TLSR8359 最大 3.6V，5V 会烧。

### 4.1 方案 A（网页 UART）vs 方案 B（SWS 单线）核心区别
| 维度 | 方案 A：UART bootloader（atc1441 网页） | 方案 B：SWS 调试口（pvvx Python） |
|---|---|---|
| 通信通道 | 芯片 ROM 内置串口引导程序（PA0/PD7） | Telink 私有单线调试协议 PA7 |
| 能否读取原厂 Flash | **不能**（bootloader 禁读，防抄） | **能**（可整片 512KB 备份） |
| 能否写入 Flash | 能（含 Unlock Flash） | 能 |
| 能否救砖 | 有限（需芯片仍能进 bootloader） | 强（有备份即可整片写回） |
| 工具形态 | 浏览器 WebSerial，一键 | Python 命令行，需装 pyserial |
| 接线 | RXD/TXD 交叉 + RST | TX→SWS（直连，电阻可选）+ RTS→RST，RX 可选接 SWS |
| 适用阶段 | 已知可用固件、快速见效 | 研究/逆向、先备份再动 |

**一句话**：方案 A 是厂商"灌固件"通道（快但不能备份），方案 B 是调试器"读写全功能"通道（能备份、能救砖）。研究阶段**先用方案 B 备份原厂固件**，再决定要不要方案 A 试刷。

## 5. 软件与操作

### 5.1 方案 A：网页一键烧录
1. 安装 CH340C 驱动（Windows 通常自动识别为 COM 口）。
2. 按方案 A 接好线。
3. 用 Chrome / Edge 打开：  
   `https://atc1441.github.io/ATC_TLSR_Paper_UART_Flasher.html`
4. 点击 **Open**，选择 CH340 对应的 COM 口。
5. 选择波特率 **460800**（默认），Atime 默认。
6. 点击 **选择文件**，加载编译好的 `.bin` 固件。
7. 先点 **Unlock Flash**（首次必须解锁），再点 **Write to Flash**。
8. 成功后屏幕自动刷新，显示新内容或 `S24_XXXXXX`。

### 5.2 方案 B：pvvx Python 命令行（推荐先备份原厂固件）
1. 安装 Python 3 + pyserial：
   ```bash
   pip install pyserial
   ```
2. 克隆仓库：
   ```bash
   git clone https://github.com/pvvx/TlsrComSwireWriter.git
   cd TlsrComSwireWriter
   ```
3. **备份原厂 512KB Flash**（强烈建议先做）：
   ```bash
   python TLSR825xComFlasher.py -p COMx -t 70 rf 0 0x80000 nowa213_original_backup.bin
   ```
4. 写入新固件：
   ```bash
   python TLSR825xComFlasher.py -p COMx -t 70 -r wf 0 nowa213_new.bin
   ```
   - `-p COMx`：替换为你的 CH340 串口号（设备管理器查看）。
   - `-t 70`：复位后激活 70ms。
   - `-r`：写完后让 CPU 跑起来。
   - 失败时尝试调整 `-t 100` 或 `-b 921600`。

> 警告：pvvx 工具说明中明确 **FTDI 芯片不行**、RX 带 LED 的模块也不行。CH340C 通常 OK。

## 6. 固件来源与适配风险
atc1441 的 `ATC_TLSR_Paper` 官方支持列表里**没有明确列出 Nowa-213R-N**，但已有这些相近型号：
- Stellar-MFN@ E31A（2.13" 212×104）
- Stellar-M3N@ E31HA（2.13" **250×122**）
- Stellar-MN@ E31H（2.13" 250×122）

你的 Nowa-213R-N 是 **250×122 BWR + TLSR8359 + FM11NC08 系列 NFC + RGB LED**，与 Stellar-M3N@ E31HA 非常接近。但板号不同（HS_EL5102_1M_67_03），GPIO 映射（尤其是 LED、EPD CS/DC/RST、NFC 中断）**可能不同**。

### 稳妥路径
1. **先用 pvvx 工具完整备份原厂 512KB Flash**。
2. **不要直接刷 Stellar-M3N@ E31HA 的现成 bin**，先编译一个"最小测试固件"验证引脚。
3. 用 atc1441 源码（`Firmware/` 目录）为基础，参照 Stellar-MN@ E31H 的引脚定义修改 `Hanshow_Stellar_MN@_E31H_Pinout.txt`，再针对 HS_EL5102_1M_67_03 实测调整：
   - EPD：CS、DC、RST、BUSY、MOSI、CLK
   - LED：R/G/B
   - NFC：SDA/SCL/IRQ/CS
4. 编译命令（Windows）：
   ```bash
   cd Firmware
   makeit.exe clean
   makeit.exe -j12
   ```
   生成 `ATC_Paper.bin`。

## 7. 风险与注意事项
- **先备份，再刷机**。原厂固件读出来保存好，方便救砖。
- **不要 5V 供电**，TLSR8359 绝对耐受不了。
- 网页 UART 烧录如果失败，多半是 RST 时序不对；改手动短接 RST→GND 触发。
- SWS 烧录如果失败，检查 CH340 TX 是否连到 SWS、RX 输入端是否带 LED 下拉（带 LED 的模块 pvvx 不支持）、RTS 是否连到 RST、电平是否为 3.3V。电阻非必需。
- 拆盖不可逆，盖板无法完美复原。
- 刷错固件可能导致屏幕不刷新、BLE 不广播、NFC 失效；有原厂备份可通过 SWS 写回。

## 8. 立即执行清单
1. [x] 确认 CH340C 模块丝印：**5V – RTS – DTR – 3V3**（有 RTS，RST 接 RTS 或 DTR 均可）。电平跳线拨到 3.3V。
2. [ ] 按方案 B（SWS）接线，TX 直连 SWS（电阻可选，无需专门购买）。
3. [ ] 安装 Python + pyserial，下载 pvvx/TlsrComSwireWriter。
4. [ ] 执行备份命令，保存 `nowa213_original_backup.bin`。
5. [ ] 用 atc1441 网页工具（方案 A）或 pvvx 写入你想测试的固件。
6. [ ] 如需定制固件，编译 ATC_TLSR_Paper 并针对 HS_EL5102_1M_67_03 调整 GPIO。

## 9. 参考链接
- atc1441/ATC_TLSR_Paper: https://github.com/atc1441/ATC_TLSR_Paper
- 网页 UART 烧录器: https://atc1441.github.io/ATC_TLSR_Paper_UART_Flasher.html
- 网页 BLE 传图: https://atc1441.github.io/ATC_TLSR_Paper_Image_Upload.html
- pvvx/TlsrComSwireWriter: https://github.com/pvvx/TlsrComSwireWriter
- Telink TLSR8359 数据手册: https://www.ebyte.com/pdf-down/1947.html

## 10. 自写固件可实现功能（基于 TLSR8359 + SSD1675 + FM11NC081）

### 硬件能力盘点
- **MCU**：TLSR8359F512ET32，RISC-V，512KB Flash / 64KB RAM，BLE 5.0 2.4G，内置 RTC，多路 GPIO/I2C/SPI/UART
- **屏**：SSD1675，250×122，**三色 BWR（黑/白/红），无灰阶**
- **NFC**：FM11NC081，Type A，200B NDEF，I2C
- **电池**：550mAh × 2，低功耗，待机可达数月~年

### 功能分层
| 层 | 功能 | 说明 |
|---|---|---|
| **A 已开源**（atc1441 直接可用/小改） | 电子墨水显示任意图片（BLE 推送 BMP） | 核心功能，网页 BLE 传图 |
| | BLE 无线更新屏幕内容 | 手机/电脑推送，免拆机 |
| | NFC 标签改写（URL/文本/名片/WiFi） | 写 NDEF，变智能海报/门禁信息 |
| | 低功耗刷新调度 | 墨水不刷不耗电 |
| **B 小幅改造**（基于 A 源码） | 时钟/日历显示 | RTC + BLE 校时 |
| | 文字/排版/多语言 UI | 自绘字体 |
| | 二维码/条形码生成显示 | 一扫即跳转 |
| | 多页循环 / 按钮翻页 | 若有按键 |
| | 红黑强调色告警 | 三色优势 |
| | 功耗深度优化 | 续航最大化 |
| **C 需自写驱动/扩展** | 外接 I2C/SPI 传感器显示（温湿度等） | 需飞线接外设 |
| | 与自有系统联动（如 AM4 状态副屏） | 私有 BLE 协议 |
| | BLE 私有协议 / mesh 组网 | 多节点 |
| | 数据记录与回放 | 利用 512KB Flash |
| | 作 BLE beacon / 信标 | 定位/广播 |

### 限制
- 分辨率小、仅三色无灰阶（照片需抖动算法）
- RAM 64KB，大图需分块/压缩
- 开发需 Telink **TC32** 工具链（atc1441 提供 `makeit` 构建脚本）
- **建议基于 atc1441 源码改**，勿从零写（Telink SDK 复杂、部分闭源）
- 法律：改造自用 OK，勿冒充原厂价签系统组网

## 11. BLE 无线更新软件（手机/电脑）
atc1441 **未发布专门手机 App**，全部走网页（Web Bluetooth / WebSerial）：

| 用途 | 网页工具 | 可用平台 |
|---|---|---|
| BLE 无线传图 | `https://atc1441.github.io/ATC_TLSR_Paper_Image_Upload.html` | 安卓 Chrome / 电脑 Chrome·Edge |
| BLE OTA 无线刷固件 | `https://atc1441.github.io/ATC_TLSR_Paper_OTA_writing.html` | 同上 |
| USB 串口烧录（方案 A） | `https://atc1441.github.io/ATC_TLSR_Paper_UART_Flasher.html` | 电脑 Chrome·Edge（CH340C 接 RXD/TXD） |

手机平台说明：
- **安卓**：Chrome 支持 Web Bluetooth，浏览器直接打开传图/OTA 网页即可，**无需装 App**。
- **iPhone / iOS**：Safari **不支持 Web Bluetooth**（Apple 限制），网页工具无法使用。变通：用电脑 Chrome 传图，或用 nRF Connect（iOS）手动写 BLE 特征值（不直观）。
- **前提**：必须先刷入 atc1441 固件（原厂固件非此 BLE 协议，工具读不到设备）。

## 12. 实操：接好线后的备份步骤（当前进度）
已接线：**TX→SWS + RTS→RST + 3V3 + GND**（不接 RX，立创实测可行）。

### 12.1 电脑端准备
1. CH340C 插电脑 USB。
2. 设备管理器 → 端口(COM 和 LPT)，记下出现的 COM 号（如 `COM3`）。没出现 → 装 WCH CH340 驱动。
3. 装 Python 3（勾选 Add to PATH）。
4. 装依赖：`pip install pyserial`
5. 下载工具：`git clone https://github.com/pvvx/TlsrComSwireWriter.git` 或下 zip 解压。

### 12.2 备份原厂 512KB Flash（只读，安全）
```bash
cd TlsrComSwireWriter
python TLSR825xComFlasher.py -p COM3 -t 70 rf 0 0x80000 nowa213_original_backup.bin
```
- `-p COM3` 换成实际串口号。
- `-t 70`：RTS 复位后激活 70ms；若设备深度休眠连不上，加大到 `-t 200` 甚至 `-t 500`。
- `rf 0 0x80000`：从地址 0 读 512KB（0x80000）。
- 成功输出：`Open COMx... Reset module (RTS low)... Activate... Read Flash... Done!`，生成 `nowa213_original_backup.bin`。

### 12.3 失败排查
- **连不上/无响应**：加大 `-t`（如 `-t 200`）；重插 CH340 再试；确认 3V3 跳线、TX→SWS、RTS→RST、GND 均导通。
- **波特率报错**：加 `-b 921600` 或降 `-b 460800`。
- **COM 号错**：设备管理器核对，避免选到蓝牙/其他串口。
- pvvx 警告：带 RX-LED 的模块、FTDI 芯片不支持（本模块 CH340C，OK）。

### 12.4 下一步
备份成功后，再决定刷机：atc1441 固件（Nowa-213R-N 不在官方兼容列表，先试 Stellar-M3N@ E31HA 或定制），或基于 atc1441 源码改 GPIO。

## 13. 原厂固件备份结果（2026-09-03 已验证）
- 文件：`nowa213/TlsrComSwireWriter/nowa213_original_backup.bin`
- 大小：524288 字节 = 0x80000 = 整片 512KB（完整）。
- 填充：FF 52.9% / 00 32.4%，含真实代码数据，**非空白片**。
- 厂商特征：偏移 0x238D0 找到 `"hanshow"` 字符串，确认汉朔原厂固件。
- **关键利好**：SWS 能整片读出 → 芯片**未锁读保护**，拥有完整读写权限，后续刷自定义固件无障碍。
- 接线修正记录：本次失败初因是 `Chip sleep?` 报错，根因是**未接 CH340 RX 到 SWS**（速率握手需 RX 回读）。补接 RX→SWS 后 `-t 200` 一次成功。读全片备份必须 TX+RX 双接 SWS。

## 14. 路线 A：试刷 atc1441 现成固件（2026-09-03 进行中）
- atc1441 官方兼容列表**不含 Nowa-213R-N**（仅 Stellar 系列）。最近邻 = **Stellar-M3N@ E31HA（250×122 BWR）**，分辨率与 Nowa-213R-N 物理屏(SSD1675 250×122)一致。
- 仓库 `atc1441_src/Firmware/` 内**直接有预编译 `ATC_Paper.bin`（90840B）**，且 `tc32_windows` 工具链完整打包 → 无需另装编译器即可重编。
- 预编译 bin 头部 `KNLT`(Telink SDK 签名)、入口 0x8026，合法固件；makefile 用 `CHIP_TYPE_8258`+`-llt_8258`（8359 同核，兼容）。
- 已复制到 `TlsrComSwireWriter/atc1441_StellarM3N_E31HA.bin`。
- 刷写命令（COM6，SWS 已 TX+RX 双接）：`python TLSR825xComFlasher.py -p COM6 -t 200 wf 0 atc1441_StellarM3N_E31HA.bin`（pvvx `wf` 自动 FlashUnlock + 扇区擦写，源码549/551行）。
- 还原命令：`... wf 0 nowa213_original_backup.bin`。
- 风险：屏控 GPIO 大概率与 Stellar-M3N 不同 → 屏幕可能不亮；BLE 通常能通（射频 GPIO 标准）。验证用 nRF Connect 或 Chrome 打开 `ATC_TLSR_Paper_Image_Upload.html` 扫 BLE。
- 结论判定：BLE 通=固件启动成功，下一步改 GPIO 重编；BLE 不通=可能砖，用备份还原。

### 14.1 刷写结果（2026-09-03 已验证）
- 用户执行：`python TLSR825xComFlasher.py -p COM6 -t 200 wf 0 atc1441_StellarM3N_E31HA.bin`
- 输出：`Write Flash data 0x00000000 to 0x000162D8`（= 90840 字节，与 bin 大小完全一致），`Done!`
- flash 自动解锁、扇区擦写完成，atc1441 固件已驻留。

### 14.2 下一步验证（拔线 + 网页 BLE 扫描）
1. **拔掉 CH340C 全部线**（TX/RX/RTS/3V3/GND），让价签靠双电池复位启动，等几秒。
2. 电脑 Chrome/Edge 开 `https://atc1441.github.io/ATC_TLSR_Paper_Image_Upload.html` → 点 **Connect**。
3. 浏览器弹设备列表 → 选价签（名含 ATC/Paper）→ 连上 = 固件启动 + BLE 通。
4. 屏幕亮不亮另说（屏控 GPIO 可能不符）；BLE 通即芯片/射频 OK，下一步改 GPIO 重编。
5. 扫不到 → 用 nRF Connect 兜底看广播；仍无 → 可能砖，`wf 0 nowa213_original_backup.bin` 还原。

### 14.3 验证结果（2026-09-03 已回报）
- 用户拔线后，价签屏幕点亮，显示 `ESL_140EC6 BWR213`、`00:00`、`28°C`、`Battery 2905mV`。
- 该画面为 atc1441 固件默认内容 → **atc1441 固件已成功启动**。
- 屏幕正常刷新 → **屏控 GPIO 与 Stellar-M3N@ E31HA 完全匹配**，Nowa-213R-N 可直接使用该固件，**无需移植 GPIO**。
- 网页 `Image_Upload` 点 Connect 无设备弹窗 → 待排查电脑蓝牙/浏览器/距离/BLE 广播名（见 14.4）。

### 14.4 网页 BLE 连接无反应排查
1. **确认电脑有蓝牙**：台式机很多没有内置蓝牙；若任务栏无蓝牙图标，需插 USB 蓝牙适配器。
2. **浏览器与权限**：必须用 Chrome/Edge；点 Connect 后看地址栏左侧是否有"蓝牙"权限提示，要点允许。
3. **距离**：价签放电脑旁边 1 米内。
4. **换安卓手机验证**：安卓 Chrome 开同一网页点 Connect，若手机能扫到，则问题在电脑蓝牙；若手机也扫不到，可能固件进入省电停止广播，需唤醒/按键/换固件版本。
5. **nRF Connect 兜底**：安装 nRF Connect（Win/安卓），扫描所有 BLE 设备，看是否有名为 `ATC_*`、`Paper_*`、`ESL_*` 或 MAC 地址相近的设备，确认广播名。

### 14.5 源码级分析结论（2026-09-03）
- 已查 `atc1441_src/Firmware/src/ble.c`：设备名广播为 `ESL_xxxxxx`（`140EC6` 为 MAC 后三位，固件自动拼接），即屏幕显示的 `ESL_140EC6`。
- 广播类型 `ADV_TYPE_CONNECTABLE_UNDIRECTED`，上电即 `bls_ll_setAdvEnable(1)` 开广播。
- 休眠策略 `DEEPSLEEP_RETENTION_ADV`（ble.c:101/152）→ 进低功耗后 BLE **仍持续广播**，设备一直在发广播，非未开 BLE。
- 已查网页 `ATC_TLSR_Paper_Image_Upload.html`：`requestDevice({acceptAllDevices:true})`，**无 namePrefix 过滤**，会列出所有附近 BLE 设备。
- **结论**：网页扫不到与设备名/广播无关。安卓端点 Connect 无反应的根因是 **安卓 Chrome 的「附近的设备」蓝牙权限未授权** 或 **手机蓝牙未开**，而非固件。
- 排查：① 手机蓝牙已开；② 安卓12+ 设置→应用→Chrome→权限→开启「附近的设备」；③ 点 Connect 后是否弹出设备列表（弹出但无 ESL_140EC6=距离远；不弹=权限问题）；④ nRF Connect 兜底扫 `ESL_140EC6` 确认广播存在。

### 14.6 广播验证完成（2026-09-03 用户回报）
- 用户用 **nRF Connect**（安卓）扫描到设备 **`ESL_140EC6`** → **BLE 广播确认存在且正常**，与源码分析（上电即广播、低功耗持续广播）一致。
- **结论**：atc1441 固件在 Nowa-213R-N 上完全跑通——芯片、屏控 GPIO、BLE 射频全部匹配，**路线 A 成功收官，无需改 GPIO、无需移植**。
- 网页 `Image_Upload` 点 Connect 无反应 = **安卓 Chrome 缺「附近的设备」蓝牙权限**（Android 12+ 必开），与固件无关。
- 下一步：安卓12+ 开 `设置→应用→Chrome→权限→附近的设备` 后，用 Chrome 重新开 `ATC_TLSR_Paper_Image_Upload.html` 点 Connect → 应弹出系统设备列表 → 选 `ESL_140EC6` 即连上，可传图/OTA。
- 连接后可用：BLE 无线传 BMP 图显、OTA 无线刷固件、NFC 改写（FM11NC081）。

## 15. 主板 NFC 能力与"省电开关"可行性（2026-09-03 19:28 分析）

### 15.1 芯片确认
- 板上 NFC = **复旦微 FM11NC08（I2C 版，即 FM11NC081）**，双界面 NFC **通道芯片**（不是纯标签，是 MCU↔NFC 场的桥）。
- atc1441 源码接线（`main.h`）：`NFC_SDA=PC0`、`NFC_SCL=PC1`、`NFC_CS=PC6`、`NFC_IRQ=PC4`。I2C 从地址 `0xAE`（=0x57<<1）。

### 15.2 FM11NC08 硬件能力（来自数据手册）
- 协议 ISO/IEC 14443-A，13.56MHz；内置 8k bit EEPROM，**用户共享区 ~900 byte**（MCU 与 NFC 场双方可读写）。
- 三种模式：ISO14443-3 / ISO14443-4 / AFE 透明传输；可作 **NFC Forum Type 4 Tag**（手机无 App 可读写 NDEF：URL/文本/WiFi/名片）。
- **IRQ_N 中断输出（开漏低有效）**：NFC 场出现或标签被读写时拉低 → 可接 MCU GPIO 做场检测/唤醒。这是关键引脚（接 PC4）。
- I2C 双向：MCU 可主动读共享区（知道手机写了什么）、也可写（手机读 MCU 想展示的数据）。
- **VOUT 场能量输出**（可配置电压）：手机贴近时由 NFC 场取电，但不给 MCU 主力供电。
- 接触端口零待机功耗。

### 15.3 当前固件 NFC 用法（重要：目前是摆设）
- `init_nfc()`（nfc.c）只做：配 PC6(CS) 输出、配 PC4(IRQ) 输入上拉、拉低 CS 发 reset 序列 `0x03 0xb5 0xa0`、拉高 CS。
- **grep 确认：app.c / main.c 中没有任何 `NFC_IRQ` 中断服务、没有 `gpio_set_gpio_wakeup(NFC_IRQ,...)`、loop 里不读 NFC 共享区。**
- 即：atc1441 固件初始化了 NFC 芯片但**未使用其任何功能**（不读 NDEF、不中断唤醒、不桥接数据）。要实现 NFC 功能必须改固件重新编译。

### 15.4 NFC 能实现的功能（改固件后）
- **A. 无 App 可读写标签**：手机贴一下读 URL/文本/WiFi（NDEF），当智能海报/快捷配置。
- **B. 场检测唤醒（贴一下唤醒）**：PC4 配 GPIO 唤醒 + 中断，deep sleep 时一贴手机即唤醒（ESL 标准"靠近即激活"）。
- **C. MCU↔手机数据桥**：MCU 读 NFC 共享区拿手机写的命令/参数；或 MCU 写状态供手机读取。
- **D. 低功耗调度触发**：用 NFC 场作为"用户在场"信号，触发刷新/上报。

### 15.5 NFC 作"省电开关"——分两种语义
1. **当唤醒开关（贴一下唤醒，退出省电）**：✅ 硬件天然支持。把 PC4 配 `gpio_set_gpio_wakeup(NFC_IRQ,1,0)`（低电平唤醒）+ 中断即可。Telink 原生支持 GPIO 唤醒 deep sleep。
2. **当"进入省电"的开关（贴一下让它睡更死）**：⚠️ 可行但**必须改固件**。手机写特定字节到 NFC 共享区 → MCU 在 NFC 中断里读 I2C 拿到命令 → 调 `cpu_sleep_wakeup(DEEPSLEEP,...)` 且**关闭 BLE 广播保留位**（去掉 `DEEPSLEEP_RETENTION_ADV` 的 adv 部分或先 `bls_ll_setAdvEnable(0)`）→ 进入更深休眠。退出需再贴一次（PC4 唤醒）或定时/按键。
3. **❌ 做不到**：NFC 物理断电/彻底关机。FM11NC08 是被动芯片，无控制主电源的开关管，无法切断 TLSR8359 与屏幕供电。最多软件级 deep sleep（μA 级，电池仍缓慢耗电）。

### 15.6 注意：当前固件平时已很省电
- atc1441 用 `DEEPSLEEP_RETENTION_ADV`：进 deep sleep 但 **BLE 持续广播**（μA 级）。墨水屏只在刷新瞬间耗电。
- 所以"靠 NFC 唤醒"的节能收益有限（BLE 本来就在发）；真正省电的是**用语义2关掉 BLE 广播**进纯 deep sleep，代价是失去 BLE 无线更新能力，需贴 NFC 才唤醒。

### 15.7 实现 NFC 省电开关的代码改动方向（待用户确认再做）
- nfc.c：`init_nfc()` 末尾加 `gpio_set_gpio_wakeup(NFC_IRQ, 1, 0);`（低电平唤醒）+ 注册中断回调。
- app.c loop 或中断里：读 I2C `0xAE` 共享区某约定字节（如 0x00 偏移）= 命令字；`0x01`=进深睡关 BLE，`0x02`=恢复广播。
- 进深睡：`bls_ll_setAdvEnable(0); cpu_sleep_wakeup(DEEPSLEEP_RETENTION_ADV 改 DEEPSLEEP, PM_WAKEUP_PAD, 0);`（或保留 RETENTION 但关 adv）。
- 唤醒后 `main.c` 的 `deepRetWakeUp` 分支恢复 BLE。
- 工具链已备（tc32_windows + makeit.exe），改完 `makeit` 重编，`wf 0` 刷入。

### 15.8 实现难度评估（2026-09-03，回答"改功能有多大难度"）

按"想做哪种"分三档（源码现状：NFC 全部未用，需从零加）：

| 目标 | 难度 | 改动量 | 周期 | 真正难点 |
|---|---|---|---|---|
| **a) NFC 场检测 toggle：贴一下省电/唤醒** | ★★☆ 中 | ~40–60 行（nfc.c+app.c+main.h） | 0.5–1 天 | 状态机去抖、深睡/唤醒切换、PC4 wakeup 配置 |
| **b) NFC 唤醒（仅退出深睡）** | ★☆☆ 低 | ~15 行 | 半天 | PC4 配 gpio_wakeup + 中断清标志 |
| **c) NFC 写命令字控制（解析 NDEF）** | ★★★ 高 | ~100–200 行 + 调试 | 1–3 天 | FM11NC08 的 NDEF/Type4 APDU over I2C 协议栈（atc1441 无现成驱动，需啃数据手册） |

**关键取巧——强烈建议走 (a) 场检测 toggle，避开 NDEF：**
- FM11NC08 的 IRQ(PC4) 在 NFC 场靠近时拉低、远离恢复高。不用解析手机写了什么，只需检测"贴了一下"（边沿）就切换 省电↔唤醒 状态。
- 实现：状态机 `awake ↔ deep_sleep`；检测 PC4 下降沿（场靠近）→ 切到对立状态；用延时/边沿去抖避免场持续贴着反复触发。
- 进深睡：`bls_ll_setAdvEnable(0); cpu_sleep_wakeup(DEEPSLEEP, PM_WAKEUP_PAD, 0)`（PC4 设为 wakeup pad）。
- 唤醒：`deepRetWakeUp` 分支恢复 `bls_ll_setAdvEnable(1)`。
- 这样完全绕开 NDEF/APDU 协议栈，(a) 难度从"高"降到"中"，性价比最高。

**诚实修正**：15.5/15.7 里"中等工作量"偏乐观——若走 (c) 解析 NDEF，实际是"高"（协议栈缺失）。走 (a) 场检测则确实是"中"。

**风险点**：
- 深睡后 RAM 不 retention（除非加 RETENTION 标志），toggle 状态需存 retention 区或 flash。
- `PM_WAKEUP_PAD` 唤醒后 IO 需重初始化（nfc.c 的 init 要在 wakeup 分支重跑）。
- 调试需反复 `wf 0` 刷写 + 拔电池复位；有备份兜底（nowa213_original_backup.bin），刷坏零风险。

### 15.9 可行性最终评估（2026-09-03 19:40，用户明确需求后，仅评估不实现）

**用户需求**：手机碰一下 NFC → 深睡↔唤醒切换；唤醒后手机/电脑 BLE 可连改内容；改完再碰 NFC 进深睡省电。= 15.8 的 (a) 场检测 toggle。

**结论：✅ 完全可行，难度比 15.8 估的更低（约 ★★☆ 偏低，半天~1 天）。** 依据已读源码：

1. **引脚已就位**：`main.h` 定义 `NFC_IRQ = GPIO_PC4`；`nfc.c` 的 `init_nfc()` 已把 PC4 配为输入上拉（IRQ 开漏低有效，平时高、场靠近拉低）。直接 `gpio_read(NFC_IRQ)` 即可读场状态，无需新增硬件。
2. **状态机天然成立，无需持久化**：`main.c` 用 `cpu_sleep_wakeup(DEEPSLEEP, ...)` 进纯深睡后，唤醒 = **冷启动**（`deepRetWakeUp` 为 false → 走 `user_init_normal` → BLE 重新广播）。即"唤醒后永远先 AWAKE 广播"，"AWAKE 时碰 NFC → 进 SLEEP"——两者确定，不需要 flash 记状态变量，toggle 逻辑极简。
3. **功耗链路干净**：纯 `DEEPSLEEP` 下 TLSR8359 自耗 ~1–2μA；FM11NC08 是被动芯片，无场不耗电（接触端口零待机），场靠近时由 NFC 场取电产生 IRQ 拉低 → `PM_WAKEUP_PAD`（低电平唤醒）拉醒 MCU。MCU 深睡期间 NFC 不用 MCU 供电，省电彻底。
4. **切换函数就两行**：AWAKE 主循环检测到"贴一下再离开"（PC4 下降沿→上升沿，去抖）后：
   `bls_ll_setAdvEnable(0);` 关广播
   `cpu_sleep_wakeup(DEEPSLEEP, PM_WAKEUP_PAD, 0);` 进深睡，PC4 低电平唤醒。

**真正要写好的只有两处**：
- `app.c` 主循环加 NFC 场边沿检测 + 去抖状态机（避免贴着不放反复 toggle；唤醒后手机还贴着时要先等场离开再 armed）。
- `nfc.c` 加一个读 PC4 的 helper（或直接用 `gpio_read`）。

**剩余风险/待确认（不影响可行性，影响体验）**：
- **唤醒后重绘延迟**：纯 DEEPSLEEP 唤醒=冷启动，BLE 重新广播需几百 ms~1s，手机要等一下再连；屏幕会重跑 init（可能闪一下默认帧）。
- **内容保留**：改完的内容存 flash，唤醒后 `user_init_normal` 应重绘最后帧（需确认 epd 初始化是否重绘，未读 epd.c，待实现时确认）。若只显示默认帧不重绘用户图，需加"唤醒后重绘 flash 中最后一帧"逻辑。
- **BLE 绑定**：重连是否需重新配对取决于 atc1441 绑定策略（绑定信息在 flash，通常保留）。
- **去抖参数**：贴靠时长差异大（手机贴 200ms~数秒），边沿检测要稳。

**一句话**：方案可行、干净、低风险，有原厂备份兜底刷坏零风险。主要工作量在去抖状态机 + 确认唤醒后重绘。决定动手时按 15.8(a) 路径改 `app.c`+`nfc.c`，`makeit` 重编、`wf 0` 刷入。

### 15.10 用户约束与"状态怎么知道"（2026-09-03 19:44 澄清，仅评估）

**用户明确约束**：
- 冷启动延迟（唤醒后几百 ms~1s 才广播）**可接受**。
- 唤醒/深睡切换**不改变屏幕内容**（NFC toggle 不主动触发刷新）。
- BLE 重新配对策略**按固件默认执行，暂无需求**（绑定信息在 flash，通常保留）。

**状态查询方法（怎么知道当前是唤醒还是深睡）**：

| 方法 | 是否需要改固件 | 可靠性 | 说明 |
|---|---|---|---|
| **① BLE 扫描（首选）** | 否，零改动 | 高 | 手机 nRF Connect 或 Chrome 传图网页扫 `ESL_140EC6`：能扫到=唤醒；扫不到=深睡。用户已有 nRF Connect，最省事。 |
| **② LED 视觉指示** | 是，小改 app.c | 高 | AWAKE 态让某 LED（PA7蓝/PD2红/PD3绿）慢闪或常亮；进 SLEEP 前熄灭。一眼看板子即知。深睡 GPIO 掉电，LED 自然灭。 |
| **③ 屏幕内容** | — | **不可用** | 墨水屏双稳态，深睡掉电保持最后图像；且用户要求切换不改内容 → 唤醒与深睡屏幕显示相同，**无法用屏幕区分状态**。 |
| **④ 测电池电流** | 否 | 中 | 深睡 ~1–2μA，唤醒几十 μA+广播。万用表可区分，但不实用。 |
| **⑤ NFC 试探** | — | **不可用** | NFC 是 toggle 开关，贴一下即切换状态，**不能"只读不改"地探测**——想探就会切。 |

**结论**：最实用是 **① BLE 扫描**（零改动，用户工具现成）；若要板子自身可视化状态，加 **② LED 指示**（约 10 行，AWAKE 亮/SLEEP 灭）。屏幕与 NFC 都不适合做状态探针。纯 DEEPSLEEP 唤醒走 `user_init_normal`（其中 `epd_display` 已注释）→ 切换状态不重绘、不闪，完美符合"切换不改屏幕内容"需求（已源码确认，2026-09-03）。

### 15.11 LED 物理位置与当前行为（2026-09-03 19:48，回答"哪里有 LED"）

**引脚（源码确认，100% 准确）**——`main.h` 第 16–18 行 + `led.c` 验证：
- `LED_BLUE = GPIO_PA7`
- `LED_RED = GPIO_PD2`
- `LED_GREEN = GPIO_PD3`
- 三颗 LED 分别挂在 TLSR8359 的 **PA7 / PD2 / PD3**，均为输出、上拉、写 1=灭 / 写 0=亮（见 led.c set_led_color：color0 全写 1=全灭；color1 青=蓝+绿亮；color2 品红=蓝+红亮；color3 黄=红+绿亮）。

**物理位置**：在主控 **TLSR8359F512ET32** 芯片周围找 3 颗 **0402/0603 封装小贴片灯珠**（蓝/红/绿），丝印可能 `L1/L2/L3` 或 `Dx`。PA7=蓝、PD2=红、PD3=绿。

**重要：当前固件 LED 已经在闪（用户可能没注意）**——`app.c` 每 10 个 Timer_CH_0 tick 执行：
- `ble_get_connected()` 真 → `set_led_color(3)`（**黄=已连 BLE**）
- 否则 → `set_led_color(2)`（**品红=未连**）
- `WaitMs(1)` 后 `set_led_color(0)`（全灭）
即**每 10 tick 脉冲 1ms**：连上闪黄、未连闪品红。肉眼看是"偶尔极快微闪"，易忽略。板子屏正常→GPIO 匹配→LED 大概率在。

**⚠️ 物理存在性待用户肉眼确认**：刷入的固件是 `Stellar-M3N@ E31HA`（`@`=带 LED 版），但用户板子型号是 **Nowa-213R-N（N=NFC）**。屏幕亮证明 GPIO 匹配度极高，LED 引脚大概率接了真实灯珠，但需在板子上亲眼确认是否焊了 LED。确认方法：① 肉眼找主控旁 3 颗彩灯；② 万用表蜂鸣档量 PA7/PD2/PD3 对 GND 是否有 LED 正向压降；③ 手机连 BLE 后盯板子 1~2 秒看有无极快闪黄。
**若板子根本没焊 LED**（NFC 版可能省灯珠）：② LED 指示方案不成立，状态查询退回 **① BLE 扫描**（零改动），不影响 NFC toggle 需求本身。

**注意 PA7 复用**：`LED_BLUE=PA7` 与 SWS 调试口（PA7）是同一引脚。固件运行期 PA7 作 LED 输出；SWS 烧录时固件未跑不冲突。烧录用 TX 拉 PA7 时该 LED 会闪，属正常。

### 15.13 电池替换可行性：原配并联 3V ↔ 南孚串联 3V（用户 2026-09-03 确认）

**用户确认事实**：原机两节纽扣电池是**并联**（即 3V 系统，容量 500mAh×2=1000mAh）；两节南孚电池**串联**也是 3V。→ **电压匹配，之前的"欠压致命坑"排除。**

**容量/能量对比（正确算法）**：
- 原配并联：3V × 1000mAh = **3000mWh**（并联加倍容量）
- 南孚5号两串：3V × 2500mAh（单节容量，串联不加倍）= **7500mWh**
- 倍率 = 7500/3000 ≈ **2.5 倍**（用户直觉正确，且 mAh 维度也成立：1000→2500=2.5倍）
- 若用南孚7号（~1100mAh）：仅 ≈1.1 倍，意义不大；**要 2.5 倍必须用 5 号（AA）**

**仍存在的两个真实约束（非电压，但决定是否可行）**：
1. **物理尺寸必外挂**：纽扣仓为 CR 系列（Ø20–24.5mm 扁圆）开模，南孚 5 号（Ø14×50mm）/7 号（Ø10×44mm）**进不了原仓**，必须飞线外挂或改壳。直接"替换"不成立。
2. **截止电压吃掉部分倍率**：碱性南孚从 1.5V/节线性跌到 1.25V/节（系统 2.5V）即基本废；若板子 DC-DC/LDO 最低输入 > 2.5V，会在南孚还有 30–50% 余量时提前截止。**实际可用倍率可能 < 2.5 倍**，取决于板子最低输入电压（待实测或查原理图）。
3. **漏液风险（长期）**：碱性电池有漏液腐蚀板子风险，纽扣锂（CR）不会。若外挂南孚长期供电，需定期检查，或换锂铁/镍氢（但容量更低）。

**结论**：电压匹配成立、能量约 2.5 倍——用户判断正确。实施上只需解决"外挂固定 + 飞线到电池座两极"，并意识到实际倍率可能因截止电压略低于 2.5。低成本高收益改造，建议做。

### 16. 小尺寸电子价签（Nowa-213R-N）DIY 玩法清单（2026-09-03 调研）

按"与用户板子的契合度 + 趣味度 + 难度"分三类。板子现状：TLSR8359 + SSD1675 三色(250×122) + FM11NC081 NFC + BLE，已刷 atc1441，可 BLE 无线传图/OTA。

**A 类：已具备 BLE 无线能力，零/低开发即可玩**
| 玩法 | 说明 | 适配 | 难度 | 关键资源 |
|---|---|---|---|---|
| 桌面时钟/待办/名言屏 | atc1441 自带时钟模式 + 手机 BLE 传图 | ★★★★★ | 零 | atc1441 网页传图器 |
| 电脑硬件监视器副屏（CPU/内存/网速） | PC 端脚本生成图 → BLE 推送，不用拆板 | ★★★★★ | 低 | Image2ESL（MacOS 拖拽传图）、atc1441 网页 |
| AM4 机队/CO2 价格副屏 | 你之前的需求；Python 拉 AM4 数据生成图推屏 | ★★★★★ | 低 | 自写 PC 脚本 + BLE 推送 |
| 电子相框（三色抖动照片） | 黑/白/红抖动显示简单照片 | ★★★★ | 低 | atc1441 + Image2ESL 抖动算法 |
| 智能家居状态面板（Home Assistant） | BLE 推图显示 HA 实体状态 | ★★★★ | 低 | HA + 自写推送脚本 |
| BLE beacon / 室内定位信标 | TLSR8359 原生 iBeacon | ★★★ | 低 | 改固件加广播 |

**B 类：需改固件或外接（你板子独有优势）**
| 玩法 | 说明 | 适配 | 难度 |
|---|---|---|---|
| NFC 智能海报/名片/WiFi 分享 | 手机一贴打开 URL/文本/WiFi（FM11NC081 独有，硬改方案没有） | ★★★★★ | 中（改固件，见 15 节） |
| NFC 省电开关 toggle | 你已规划（15.8a）：贴一下深睡↔唤醒 | ★★★★★ | 中 |
| 多页轮播/场景切换 | 同一屏循环不同内容 | ★★★ | 中 | Vagelis1608/stellar-etags 已加场景切换 |
| 外接 I2C 传感器（温湿度）上屏 | 焊/飞线传感器，改固件读数据 | ★★★ | 中高 |

**C 类：社区出圈参考（多屏，你单块暂玩不了，思路可借鉴）**
| 玩法 | 说明 | 资源 |
|---|---|---|
| 多屏 UART 级联大字幕墙 | 多块价签 UART 菊花链，每屏一字符拼成大显示 | rbaron/pricetag-printer、rbaron/esl-panel（20 节点木箱项目） |
| 价签价格改写安全演示 | Flipper Zero + TagTinker 红外重写价格（原厂协议） | **不适用**：你已刷 atc1441，原厂 2.4G 协议已不在 |
| MSP430 旧版硬改（飞线/拆 MCU） | 黑白 Stellar-M 用 ESP32/ESP8266 驱动 | mydigit TDA-2030、einkcn ESP8266 监视器（思路参考，你板子不用这么折腾） |

**关键开源资源汇总**：
- `atc1441/ATC_TLSR_Paper`（已 clone 到 atc1441_src）：BLE 图显固件、网页传图/OTA、tc32 工具链
- `Vagelis1608/stellar-etags`：网页上传图片 + 时钟模式2 + 图片模式 + 中文（部分）显示 + 场景切换
- `reiyawea/HanshowClock`：汉朔时钟固件
- `rbaron/pricetag-printer`、`rbaron/esl-panel`：多屏级联大显示
- `Image2ESL`：MacOS 拖拽图片经 BLE 传图工具（atc1441 仓库内）
- 立创 `Xiaole.Tao/Universal-ePaper-Driver`：多平台（Arduino/树莓派/STM32）裸屏驱动（硬改参考）

**给你的优先级建议**：A 类里「AM4 副屏」和「电脑监视器」最实用（你已有 BLE 无线能力，不拆板）；B 类里「NFC 智能海报」是你板子独有、别家硬改方案没有的差异化玩法，值得做。C 类多屏墙需要再收几块同型号才玩得起。

### 15.12 LED 驱动代码的归属与"屏幕亮≠LED匹配"澄清（2026-09-03 19:51）

**用户精准提问**：固件（ATC_Paper.bin，为 Stellar-M3N@ E31HA 编译）里的 LED 驱动代码，是否针对"对应的电子价签"（即 Stellar-M3N@ E31HA）？

**答：是，LED 驱动代码就是 atc1441 为 Stellar-M3N@ E31HA 这个具体型号写的。**
- `main.h` 的 `LED_BLUE=PA7 / LED_RED=PD2 / LED_GREEN=PD3` 是 atc1441 针对 Stellar-M3N@ E31HA 的 PCB 引脚定义。该型号 `@` 后缀=带 LED 版，板子上确有这 3 颗灯，固件驱动生效。
- 固件**不知道**你是 Nowa-213R-N——它只是按编译时选定的型号（Stellar-M3N@ E31HA）引脚表驱动。对 Nowa-213R-N 是"碰巧兼容复用"，不是"专门适配"。

**⚠️ 重要误区纠正：屏幕亮 ≠ LED GPIO 匹配。**
- 屏幕能正常显示，只证明**屏幕相关那几个 GPIO**（CS/DC/RST/BUSY/SPI 等，接 SSD1675）与 Stellar-M3N@ E31HA 一致。
- LED 的 PA7/PD2/PD3 是**另一组独立引脚**，屏幕亮不证明它们接了 LED 灯珠。
- 之所以大概率一致：汉朔同系列同分辨率（250×122）PCB 布局通常相同，Stellar-M3N@ E31HA 与 Nowa-213R-N 高度可能共用引脚表。但这只是"大概率"，非"已证明"——最终须实物/万用表确认 Nowa-213R-N 的 PA7/PD2/PD3 上是否有 LED。
- 若 Nowa-213R-N 的 PA7/PD2/PD3 实际悬空或接了别的元件，LED 驱动代码就是"空转"（写悬空引脚，无任何副作用，不影响屏显/BLE/NFC 功能）。

**结论**：要 100% 确认 LED 指示可用，仍需肉眼/万用表验证 Nowa-213R-N 板子上 PA7/PD2/PD3 是否真接 LED。屏幕亮是必要非充分条件。


