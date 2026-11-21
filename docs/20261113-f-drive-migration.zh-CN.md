# VideoCreate F 盘迁移交接

日期：2026-11-13。新的开发根目录是 **`F:/VideoCreate`**。本次采用完整复制，E 盘原目录保留，没有建立跳转链接。新对话请把 F 盘目录选为项目工作目录，不要在两个副本之间交替修改代码。

用户随后要求 F 盘只保留一个文件夹，已将备份和迁移记录统一收纳为：

```text
F:/VideoCreate/
  _local/
    archive/                 旧产物恢复备份
    migration-20261113/       迁移清单与验证报告
  docs/                      设计、开发清单与交接
  projects/                  视频项目
  videocreate/               技能与代码
```

`_local/` 已忽略 Git 并从源码包中排除。原始迁移 JSON 中的旧位置保留作历史记录，当前目录以本说明为准；最初验证报告另保留为 `initial-migration-verification.json`，当前验证由收纳后的 `verify-migration.py` 生成。

## 1. 迁移范围和校验

| 内容 | 新位置 | 本次处理 |
| --- | --- | --- |
| 开发仓库 | `F:/VideoCreate` | 8,388 个文件，4,286,404,661 字节；复制时逐文件 SHA-256 一致 |
| Git 历史和本地修改 | 新仓库内 `.git/` 及工作文件 | 分支、HEAD、暂存状态、未提交及未跟踪文件完整保留 |
| 既有视频项目 | 新仓库内 `projects/` | 5,466 个文件完整复制，保持原任务、素材和回执 |
| 私有恢复归档 | `F:/VideoCreate/_local/archive` | 10 个文件，903,537,543 字节；逐文件 SHA-256 一致 |
| 本次迁移记录 | `F:/VideoCreate/_local/migration-20261113` | 原始文件清单、原未提交差异、复制验证和后续验证 |

上表是修改 F 盘说明文档之前的完整复制基线。随后更新 F 盘的当前路径说明、文档打包脚本及其验证产物；按用户要求把备份与迁移记录收纳到主项目内，并用 `.gitignore` 和 `MANIFEST.in` 排除私有目录；项目文件、核心源码和原 E 盘目录不随之改写。最终差异以迁移记录目录中的 `migration-verification.json` 为准。

原仓库为 `E:/MyFiles/ToolSkills/VideoCreate`；原恢复归档为同级 `VideoCreate-archive/`。复制脚本保存在迁移记录目录，不需要再次运行；目标已存在时它会拒绝覆盖。

## 2. 路径检查和调整

运行核心、技能薄入口、安装及构建脚本、测试使用相对位置或已有配置目录解析，未发现将旧 E 盘仓库根写死的运行代码。`docs/prototypes/verify-handoff.py` 原来把旧仓库路径写入交接 ZIP 的 README，现改为从脚本自身位置计算 `ROOT`，后续再换目录也能生成正确说明。

F 盘副本的当前完整交接、启动话术和 README 已更新；新文档包会包含本迁移说明。清理记录保留原归档位置作为历史事实，另注明 F 盘副本。原始保护基线和历史验收 JSON 不改写为新的历史。

**历史文件中仍可看到 E 盘路径，这是有意保留的来源证据。** 78 个项目 JSON 含旧仓库根，涉及导出结果、分析结果、媒体探测文件名、来源项目和素材库等。它们不等于技能代码硬编码，不能全局替换，否则可能改变哈希绑定的回执和来源关系。F 盘现有 v3 样片的五层计划和 state 可以只读加载、结构校验通过；该结果不代表所有旧项目都已逐一恢复测试。

少数项目中的一次性准备/分析脚本仍记录原始外部素材位置，例如 `E:/TEMP/`、`E:/Microsoft Edge Downloads/`、微信或 QQ 文件目录。这些外部目录不在本次复制范围。继续旧项目时应优先使用项目内已有副本，必要时按具体字段核对来源后再修复；不要直接重跑历史生成/安装/恢复脚本，也不要为迁移重建远端任务。

当前保留 E 盘原件，因此未进行“拔掉 E 盘”的独立性测试。未来删除 E 盘副本之前，须检查拟恢复项目的素材库、来源项目、回执链接及本机配额注册路径；注册表里的旧路径不能把 F 盘副本误算为另一套独立远端任务。

`tools/migrate-workspace.ps1` 是历史 GrokVideoSkill 更名为相邻 VideoCreate 的移动工具，**不用于本次跨盘复制**。私有归档中的旧清理/安装脚本也只作为历史方法，不在新目录照跑。

## 3. 继续开发时使用的状态

- 分支：`codex/provider-manager`。
- HEAD：`aed9f160ed8d07007ab5b2ef3950706ce0d3a207`。
- 已安装：`3.0.0.dev43`；当前源码：`3.0.0.dev44`，旧 Tk 草稿恢复尚未完成，未发行。
- dev43 的 1,063 项回归通过是历史结果；dev44 历史 manager 回归有 2 项失败，不能称为当前全绿。此次只验证迁移、原型和文档，未重跑完整产品回归。
- 原 73 项工作包仍是 11 项离线实现、60 项部分实现、2 项待开发；Web 拆为 W01–W22 子项，正式 Web 及自动协议匹配尚未实现。
- 保留原 11 个未完成产品文件，不 reset、覆盖或借迁移发布新版本。

最终产品方向仍是**本机 Web 仅配置上游**：用户首次主要填写 URL 和 Key，名称/备注可选。Codex 按已有合同整理模型、协议、参数和内部 binding/route；高级字段可选。不用收费 POST 猜协议。主题、大纲、剧本、角色、分镜、视频生成、恢复、剪辑和审片仍在 Codex + 技能中完成，不做网页视频工作台，不再扩展 EXE/Tk 主界面。

## 4. C 盘安装和服务

已安装技能仍在 `C:/Users/FBX/.codex/skills/videocreate`。权威配置仍为：

```text
C:/Users/FBX/AppData/Local/Packages/OpenAI.Codex_2p2nqsd0c76g0/LocalCache/Local/VideoCreate/videocreate.config.json
```

本次不移动或重装已安装技能，不替换配置，不把密钥写进文档。DPAPI 凭据仍属于当前 Windows 账户；迁开发仓库不要求重新录入 URL/Key。F 盘下的交接 ZIP 仅含文档与演示原型，不能当成运行配置备份。

已有素材服务端口 `8765`、域名 `https://videofiles.hn.takin.cc`，隧道目标 `HTTP → host.docker.internal:8765` 保持原配置；本次不停止或重启服务，不宣称重新验证公网在线状态。拟议的配置 Web 端口 `127.0.0.1:8787` 尚未实现。开发目录改变不会自动更新 Codex 中原项目的工作目录；新对话需选 `F:/VideoCreate`。

已有 30 秒样片位于 `projects/20261112-ancient-cs-comedy/`，精确远端型号为 `seedance2.5-V`，成片仍为 `review_pending`。迁移校验不创建视频，不重新生成样片，不改变审片结论。

## 5. 新对话阅读顺序

1. [完整交接：架构、模块、现状与边界](20261113-new-chat-handoff.zh-CN.md)。
2. [最新完整开发清单](20261113-complete-development-checklist.zh-CN.md)及[机器可读台账](20261113-development-checklist.json)。
3. [Web 设计](20261113-web-provider-config-design.zh-CN.md)和[交互原型](prototypes/provider-config-web.html)。
4. [可直接复制的新对话话术](20261113-new-chat-start.zh-CN.md)。

新对话若被用户要求开始实施，先从 F 盘核对版本、Git 状态、配置路径和未完成 dev44，再按 M1/M2 批次推进。此次迁移本身不启动正式 Web 开发、不恢复旧目标、不发起收费请求。
