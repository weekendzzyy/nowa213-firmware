# 开发指南（DEVELOPMENT.md）

面向「在 Nowa-213R-N 上持续开发自定义固件」的完整流程。结论先行：编译用
`build_firmware.py`，烧录用 pvvx 的 `TLSR825xComFlasher.py`（`-t 3000` 是必选项），
版本用 git 管理（`main` + `feature/*` 分支）。下面逐项展开。

---

## 1. 环境准备

### 1.1 硬件接线（CH340C ↔ 价签）

| 价签 | CH340C | 说明 |
|------|--------|------|
| GND  | GND    | 共地 |
| VCC  | 3V3    | **必须拨 3.3V**，5V 会烧 |
| SWS  | TX     | 烧录数据线（同时接 TX 与 RX） |
| SWS  | RX     | 速率握手的回读线，不接会报 `Chip sleep?` |
| RST  | RTS    | 复位进 bootloader（DTR 不接） |

> 全程保持连接即可，改固件重刷时无需断开 TX/RX。

### 1.2 软件

- **Git Bash**（Windows）或等价 shell。
- **Python 3.x** + `pyserial`：刷机工具依赖。本机用受管 venv：
  ```
  C:/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe
  ```
  若缺 pyserial：`.../python.exe -m pip install pyserial`
- **tc32 工具链**：`atc1441_src/Firmware/tc32_windows/`（**已被 .gitignore 排除，约 183MB**）。
  从 atc1441/ATC_TLSR_Paper 仓库取得，放在该路径即可编译。
- **CH340 驱动**：设备管理器确认 COM 口号（本机实测为 COM6）。

### 1.3 仓库结构

```
nowa213/
├── README.md                 # 项目总览
├── DEVELOPMENT.md            # 本文件
├── CHANGELOG.md              # 版本历史
├── .gitignore
├── atc1441_src/Firmware/    # 固件源码（已 vendor，含 tc32 工具链*、build_firmware.py）
│   ├── src/                 # ★主要改动的代码在这里（app.c / epd.c / epd_ble_service.c / epd.h）
│   ├── components/          # atc1441 上游组件（SDK lib、驱动、tinyFlash…）
│   ├── static_src/          # 启动文件 cstartup_825x.S
│   ├── make/                # tl_firmware_tools.py（加 CRC）
│   └── build_firmware.py    # 无 make 也能编译的脚本（复刻 makefile）
├── TlsrComSwireWriter/      # pvvx 刷机工具 + 各版本 .bin
├── firmware_releases/       # ★发布固件（带版本号/日期/SHA256 文件名）
├── gen_epd_image.py         # 生成 EPD 测试图（250×128 纯黑等）
├── bmp2epd_framebuffer.py   # BMP → SSD1675 帧缓冲转换
├── list_ports.py            # 枚举 COM 口
└── test_black_250x128.*     # 纯黑测试图 / 帧缓冲 / 像素代码
```
（*tc32 工具链被 gitignore，不入库）

---

## 2. 编译

沙箱内无 `make`，用 `build_firmware.py` 按原 `.mk` 精确文件清单编译、链接
`liblt_8258.a`、最后用 `make/tl_firmware_tools.py` 加 CRC。

```powershell
cd atc1441_src/Firmware
python build_firmware.py
# 产物：out/ATC_Paper.elf  +  ATC_Paper.bin（含 CRC，约 90972 字节）
```

### ⚠️ 编译后必须做 SRAM 自检

TLSR8359 只有 **64KB SRAM**，栈顶固定在 `0x850000`。`boot.link` **无溢出检查**，
链接器不会报错，但 `.bss` 越过栈顶会让芯片一上电就崩（表现为「完全没反应」）。

```powershell
cd atc1441_src/Firmware
./tc32_windows/bin/tc32-elf-nm.exe out/ATC_Paper.elf | grep _end_bss_
# 必须 < 0x850000（v2.0 实测 0x84efc1，余量 ~4KB）
```

**加任何全局/静态大数组前，先算 SRAM 占用。** 用户图当初用 5KB RAM 缓冲即踩此坑，
现改为存 Flash（见 §4）。

---

## 3. 烧录与验证

```powershell
cd TlsrComSwireWriter
python TLSR825xComFlasher.py -p COM6 -t 3000 wf 0 <固件>.bin
```

- **`-t 3000`（关键）**：片上若已跑着 atc1441 固件，其深睡带 retention 标志会让
  `-t 200` 的复位拽不回 bootloader，报 `Chip sleep?`。延长激活窗口到 3 秒即可。
- **校验（强烈建议）**：写完整片读回逐字节比对，避免「读回瞬断假象」误判：
  ```powershell
  python TLSR825xComFlasher.py -p COM6 -t 3000 rf 0 0x1635c verify.bin
  python -c "a=open('<固件>.bin','rb').read();b=open('verify.bin','rb').read();print('MATCH' if a==b[:len(a)] else 'MISMATCH')"
  ```
  > 首跑偶尔出现零星 `0xFF` 块（读回瞬断），重刷一次再读回即 MATCH，非真写入损坏。

### ⚠️ 烧录后必须「彻底断电」重启

刷完芯片停在 bootloader 调试态，需干净上电才运行新固件：

- **正确**：拔掉 CH340 的 **USB 整根线**，等 2~3 秒，再插回。
- **错误**：只拔 3V3。CH340 的 TX 是 3.3V 高电平，会经 SWS 脚的 ESD 保护二极管
  **倒灌进芯片 VDD**，导致芯片从未真正掉电、复位不发生 → 卡在 halt 态、屏显冻结帧、
  BLE 也死。表现就是「屏幕没反应、时间停止」。

---

## 4. 代码地图：时间↔图片切换功能（v2.0）

功能：默认显示走时界面；经 BLE 传图后，每分钟在「时间」与「用户图」间交替；图存 Flash，断电不丢。

| 文件 | 位置 | 作用 |
|------|------|------|
| `epd.h` | 顶部 FEATURE 块 | 功能说明 + `USER_IMG_FLASH_ADDR 0x79000` + 外部声明 |
| `epd.c` | `user_image_check_flash/save/restore` | Flash 读写（扇区布局见注释）|
| `epd_ble_service.c` | opcode `0x01` | BLE 收到图推送后调用 `user_image_save()` 持久化 |
| `app.c` | `user_init_normal` | 启动调 `user_image_check_flash()` 恢复状态 |
| `app.c` | `main_loop` 每分钟分支 | 按 `display_toggle` 在时间与图之间切换 |

**Flash 存储布局**（扇区 0x79000，4KB）：
```
[0x00..0x03] magic "IMG1" (小端)   <- 有效性标志，最后写，防断电半截
[0x04..0xFFF] 4096 字节            <- epd_buffer 副本（显示帧缓冲）
```
（固件 <0x16300、OTA 0x20000–0x40000、settings 0x78000，互不冲突）

**像素极性**：缓冲 `0x00`=黑、`0xFF`=白（SSD1675 列主序，1 字节=8 竖像素）。

---

## 5. 如何加一个新功能（标准步骤）

以「加一个功能」为例的模板，遵循「先想清→手术式改动→编译自检→烧录验证→提交」：

1. **定成功标准**：这个功能要改哪块（BLE 接收 / 定时 / 睡眠唤醒 / 显示）？状态放 RAM 还是 Flash？
2. **占位/声明**：在对应 `.h` 加 `extern` 与宏；需要持久化就加 Flash 读写 helper（参考 `user_image_*`）。
3. **接钩子**：BLE 指令在 `epd_ble_service.c`，定时在主循环 `app.c:main_loop`，唤醒在 `app.c:user_init_deepRetn` / NFC。
4. **编译**：`python build_firmware.py`，**必查 `_end_bss_ < 0x850000`**。
5. **烧录 + 校验**：`-t 3000` 写，读回比对；**整根拔 USB 重启**。
6. **上机验证**：按功能实测（如每分钟切换、断电后图是否还在）。
7. **提交**：在 `feature/<名>` 分支提交，验证通过后合并 `main` 并打 `vX.Y` 标签。

---

## 6. Git 工作流

仓库根：`nowa213/`。上游（atc1441、pvvx）已 vendor 化，其 `.git` 已移除，由本仓库统一版本管理。

### 分支策略（GitHub Flow 简化版）
- **`main`**：已验证、可发布的固件。每次合并都应是「实机跑通」的状态。
- **`feature/<名称>`**：新功能开发分支，从 `main` 切出；本地验证通过后再合并回 `main`。
- 短期实验可直接在 `feature/*` 上，不急着合并。

### 提交信息规范（Conventional Commits）
```
feat: 新增 NFC 碰一碰切换深睡/唤醒
fix:  修正 epd_buffer 覆盖导致切回图变乱码
docs: 补充 DEVELOPMENT.md 的 SRAM 自检说明
chore: 升级 build_firmware.py 精确复刻 .mk 文件清单
refactor: 将用户图存储从 RAM 迁移到 Flash
build: 引入 tc32 工具链版本锁定
```

### 发布流程
1. 在 `main` 上 `python build_firmware.py` 出 `.bin`。
2. 复制到 `firmware_releases/`，文件名带版本+日期+大小：
   `atc1441_alternate_flashimg_v2.0_2026-09-04_90972B.bin`
3. 计算并记录 SHA256 到 `CHANGELOG.md`。
4. 打标签：`git tag -a v2.0 -m "时间↔图片切换，图存Flash"`，`git push --tags`（如需）。

### 日常命令
```bash
git status                      # 看改动
git checkout -b feature/nfc-wake # 开功能分支
git add -p                      # 手术式暂存（只加必须改的）
git commit -m "feat: ..."
git checkout main && git merge feature/nfc-wake
git tag -a v2.1 -m "..."
```

---

## 7. 已知踩坑清单

| 现象 | 根因 | 解决 |
|------|------|------|
| `Chip sleep?` | 已跑固件深睡 retention 挡住 `-t 200` 复位 | 改 `-t 3000` |
| 屏幕完全没反应/时间停 | `.bss` 越过 64KB SRAM 栈顶，上电即崩 | 减 RAM 占用（图改存 Flash）|
| 屏幕冻结、BLE 死 | 只拔 3V3，TX 倒灌电，芯片没真复位 | **整根拔 USB**，等 3 秒再插 |
| 传图下方有白边 | 图高 122 但缓冲逻辑高 128，底 6 行未覆盖 | 用 250×128 图（`gen_epd_image.py`）|
| 图片一会儿消失 | `main_loop` 每分钟自动重绘时间界面 | 已是 v2.0「交替」设计；要纯图就禁自动刷新 |
| 读回零星 `0xFF` | 读回瞬断（非真写入） | 重刷一次再读回即 MATCH |

---

## 8. 救砖 / 还原

- **恢复 atc1441 官方固件**（最常用，可救回变砖）：
  ```powershell
  python TLSR825xComFlasher.py -p COM6 -t 3000 wf 0 atc1441_StellarM3N_E31HA.bin
  ```
- **恢复汉朔原厂固件**：`nowa213_original_backup.bin` **当前为 0 字节（已丢失）**，
  需从另一台同型号价签重新备份。本仓库已 gitignore 该损坏文件。
- 任何情况下都先用 `-t 3000` 读回整片确认当前内容，再决定如何处置。
