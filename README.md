# Nowa-213R-N 电子价签固件开发仓库

汉朔（Hanshow）Nowa-213R-N 2.13" 三色电子价签的刷机与研究项目。本仓库管理自编译固件、刷机工具与开发文档。

## 硬件目标

| 部件 | 型号 | 说明 |
|------|------|------|
| MCU | Telink TLSR8359F512ET32 | RISC-V + BLE 5.0，64KB SRAM，512KB Flash |
| 屏驱 | SSD1675 | 250×122 BWR 三色（无灰阶），列主序 1B=8 竖像素 |
| NFC | 复旦微 FM11NC081 | I2C 标签芯片（PC0 SDA / PC1 SCL / PC4 IRQ / PC6 CS） |
| LED | PA7 蓝 / PD2 红 / PD3 绿 | atc1441 固件定义 |

## 上游来源（已 vendor 到本仓库）

- 固件源码：`atc1441/ATC_TLSR_Paper`（克隆自 GitHub，已移除其 `.git` 由本仓库统一版本管理）
- 刷机工具：`pvvx/TlsrComSwireWriter`（SWS 单线烧录 + UART bootloader）

## 当前固件版本

- **v2.0** — 时间↔图片每分钟自动切换；用户图存 Flash（断电不丢）。
- 发布固件：`firmware_releases/atc1441_alternate_flashimg_v2.0_2026-09-04_90972B.bin`

## 快速开始

```powershell
# 1) 编译（需先准备好 tc32 工具链，见 DEVELOPMENT.md）
cd atc1441_src/Firmware
python build_firmware.py

# 2) 烧录（CH340 接好，COM 口以本机为准）
cd ../../TlsrComSwireWriter
python TLSR825xComFlasher.py -p COM6 -t 3000 wf 0 atc1441_alternate_flashimg.bin

# 3) 彻底断电重启：拔掉 CH340 的 USB 整根线，等 2~3 秒再插回
```

## 文档

- [DEVELOPMENT.md](DEVELOPMENT.md) — 完整开发指南：环境、编译、烧录、Git 流程、加功能步骤、踩坑
- [CHANGELOG.md](CHANGELOG.md) — 版本历史与发布固件 SHA256
- [nowa213_wiring_flash_summary.md](nowa213_wiring_flash_summary.md) — 接线与刷机速查
- [nowa213_flash_research.md](nowa213_flash_research.md) — 硬件研究笔记（NFC / DIY / 电池扩展）

## Git 流程概要

- `main` 分支 = 已验证/已发布的固件；新功能在 `feature/<名称>` 分支开发，验证后合并。
- 提交信息用 Conventional Commits（`feat:` / `fix:` / `docs:` / `chore:` / `refactor:` / `build:`）。
- 发布的 `.bin` 存入 `firmware_releases/`，并在 `CHANGELOG.md` 记录 SHA256。
- 详见 [DEVELOPMENT.md § Git 工作流](DEVELOPMENT.md#6-git-工作流)。
