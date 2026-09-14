# PROJECT_STRUCTURE.md — 仓库结构与命名规范(所有对话/协作者必读)

> 本文档是 nowa213 固件仓库的**结构宪法**。任何新对话(AI 或人)在改动本仓库前,
> 先读完本文档,再动手。目的是杜绝:临时文件乱丢、固件命名随缘、同一产物多个名字。
>
> 详细硬件/驱动知识见 `DEVELOPMENT.md`(构建)与 `docs/` 下各专题文档;
> 本文档只回答:**东西放在哪、叫什么名、什么不该碰**。

---

## 1. 顶层目录地图

```
nowa213/
├── PROJECT_STRUCTURE.md   ← 本文档(结构与命名规范)
├── README.md              ← 项目简介
├── DEVELOPMENT.md         ← 构建方法、刷机流程、BLE 协议说明
├── CHANGELOG.md           ← 每个版本改了什么(发布前必须更新)
├── LICENSE / LICENSES/
│
├── atc1441_src/           ← 上游代码(只读基座,不整理、不重命名)
│   ├── Compatible_models/     机型照片
│   ├── Image2ESL/             上游图片转换工具
│   └── Firmware/              固件源码树
│       ├── src/               ★ 我们真正改的源码(app.c / epd*.c / nfc.c 等)
│       ├── components/        TLSR8258 SDK 库(不改)
│       ├── make/              Makefile
│       ├── out/               编译产物(gitignore,可随时删)
│       ├── tc32_windows/      TC32 工具链 ~183MB(gitignore,手动拷入,别动)
│       └── tc32_linux/        同上,Linux 版
│
├── TlsrComSwireWriter/    ← 上游烧录工具(ComSwire/ComFlasher 脚本)
├── tools/                 ← 我们写的开发/验证脚本(Python/JS)
├── docs/                  ← 专题文档(需求、NFC 速查、设计参考、WIP patch)
│   └── images/                文档引用的截图(入库)
├── firmware_releases/     ← 发布固件 .bin(入库,只增不改名)
├── previews/              ← 离线渲染预览图(gitignore,可再生)
├── epd_preview/           ← epd_image_tool 生成的演示图(gitignore)
├── scratch/               ← 一次性会话输出(gitignore,可随时清空,见 R6)
└── .gitignore
```

**工作区**(仓库外的 `D:\WorkBuddy\...`)应保持只有一个 `nowa213/` 目录;
其他散文件一律放进 `nowa213/scratch/` 或删除。

## 2. 固件发布件命名(R1 — 强制)

```
atc1441_<variant>_v<主>.<次>_<YYYY-MM-DD>_<字节数>B.bin
```

| 字段 | 取值 | 说明 |
|---|---|---|
| variant | `clockonly` / `3page` / `alternate_flashimg` | 固件形态,与旧版保持一致;新形态需先在本表登记 |
| 主.次 | 如 `15.7` | 主版本=大特性,次版本=修复/微调;**每次烧录真机的构建都必须递增版本号**,禁止复用旧版本号 |
| 日期 | 构建当天 | |
| 字节数 | 如 `86664B` | 发布件大小(= `ATC_Paper.bin` 去掉末尾 4 字节 CRC32) |

- 每个发布件**必须**同时打 git tag `v<主>.<次>` 并在 `CHANGELOG.md` 追加条目。
- 实验/未验证构建:版本号加 `-rc1` 后缀(如 `atc1441_3page_v15.8-rc1_...bin`),
  **不得**冒用已发布版本号命名。
- 禁止自由发挥的名字(如 `xxx_busyfix_ble_ota.bin`)。想要描述性信息,写进 CHANGELOG。

## 3. 源码与文档命名(R2)

- 源码文件名小写下划线:`epd_bwr_213.c`、`epd_layout.h`、`nfc.c`。
- 文档命名:`docs/<主题>.md` 或 `docs/v<主><次>-<主题>.md`
  (如 `v15-requirements.md`、`v15-nfc-command-cheatsheet.md`)。
- 工具脚本放 `tools/`,名字小写下划线,头部注释说明用途与输出位置。

## 4. 版本演进流程(R3 — 每次改动都走)

1. 改 `atc1441_src/Firmware/src/` 源码 → 版本字符串递增(`app.c` 里 `FIRMWARE_VERSION`)。
2. 离线验证:`python tools/render_screen_preview.py --page N` / `tools/verify_v14_layout.py`。
3. 编译 → 检查镜像大小与 `_end_bss_` 地址(参考 CHANGELOG 中上一版的数值)。
4. 真机烧录验证 → 通过后:发布件按 R1 命名入 `firmware_releases/`,打 tag,更新 CHANGELOG,commit+push(带 `--tags`)。
5. **未验证的实验改动不留在工作区**:要么完成 R3 全流程,要么 `git diff > docs/<主题>-wip.patch` 留底后回滚。

## 5. 哪些东西不能动(R4)

- `atc1441_src/Firmware/tc32_windows/`、`tc32_linux/`:工具链,~183MB,gitignore。
  丢失后从上游 atc1441/ATC_TLSR_Paper 仓库重新拷入。
- `atc1441_src/Firmware/components/`:SDK 库,除非注明,不修改。
- `firmware_releases/` 已有文件:只增不改名不删除(它们是每个 tag 的可复现产物)。
- `docs/` 已入库文档:改内容可以,改名/删除需在 CHANGELOG 说明。

## 6. 临时文件去向(R5/R6 — 违反即目录退化)

- **R5**:跑命令产生的日志、git 输出捕获、commit message 草稿、退出码记录等一次性文件,
  一律写进 `scratch/`(如 `scratch/build_v153.log`),命名带主题。
- **R6**:`scratch/` 整体 gitignore,**可随时整目录清空**,不许在里面放唯一副本。
- 预览图进 `previews/`(可再生),文档真正引用的截图进 `docs/images/`(入库)。
- 仓库根只允许出现第 1 节列出的文件;发现根目录多出新文件,先移 `scratch/` 再查明用途。

## 7. 新对话快速索引

| 要做什么 | 看哪里 |
|---|---|
| 构建/刷机 | `DEVELOPMENT.md` |
| 需求背景与分期 | `docs/v15-requirements.md` |
| NFC 命令通道怎么用 | `docs/v15-nfc-command-cheatsheet.md` |
| 屏幕版式几何/常量 | `atc1441_src/Firmware/src/epd_layout.h` + `docs/v14-reference-design.md` |
| 各版本改动 | `CHANGELOG.md` |
| 离线看屏幕效果 | `python tools/render_screen_preview.py --page 1/2` |
| 网页刷机/上传工具 | `web_flasher.html`、`web_uploader.html`、`web_tool.html`(浏览器直接打开) |

## 8. 本文档的维护

结构变化(新增顶层目录、新增 variant、改命名规则)必须同步更新本文档,
并在 commit message 中提及。本文档规则与 `.gitignore` 冲突时,以 `.gitignore` 实际行为为准并修复本文档。
