# dev44 独立 Windows 离线验收套件

日期：2026-11-14。本批只增加交付工具、离线验收脚本和说明，不修改产品、前端、静态资源或 Schema。候选继续使用 **r16 / 未发行 dev44**，C 盘 dev43 安装不变。

## 可交付材料

- 套件：[VideoCreate-dev44-offline-win-cp39.zip](../_local/web-acceptance-kit-20261114-r1/VideoCreate-dev44-offline-win-cp39.zip)，5,032,531 字节。
- ZIP SHA-256：`5d41a35edc3e4df7e2ba327e6fd18eecb63e5bc2c28228178bfd6e490ccc05c4`。解压前对照本记录核对；套件内清单只检查内容完整性，没有发布者签名。
- [构建回执](../_local/web-acceptance-kit-20261114-r1/kit-build.json)记录原 r16 两个产物及候选回执哈希、286 个输入/260 个技能文件一致、15 个依赖 wheel 和全部归档内容扫描。
- 套件内含独立运行的 [run-offline.py](../tools/web_acceptance_kit/run-offline.py)、[使用说明](../tools/web_acceptance_kit/README.zh-CN.md)和 [人工验收回执模板](../tools/web_acceptance_kit/ACCEPTANCE.zh-CN.md)。模板初始均为“未执行”，自动成功不改写人工结论。

套件仅支持 **Windows x64 + CPython 3.9**。现有原生依赖是 `pydantic_core-2.46.5-cp39-cp39-win_amd64.whl`；不包含 Python 安装器、浏览器、Node、真实配置/凭据、项目或样片。未下载或安装其他运行时。另一台机器需先有相符 Python（含 venv/ensurepip）、浏览器和可用 F 盘。

## 本机实际验证

使用 [构建工具](../tools/build_web_acceptance_kit.py)打包冻结产物，再由 [验证工具](../tools/verify_web_acceptance_kit.py)把交付 ZIP 解压到带中文、空格和 `&` 的新目录；验证时不从仓库导入产品源码，不使用构建目录中的未打包文件，也不要求 Git、Node/npm 或原机器的配置目录。

[完整验收回执](../_local/web-acceptance-kit-validation-20261114-r1/result.json)与[套件运行结果](<../_local/web-acceptance-kit-validation-20261114-r1/自动验收 工作 空格 & 路径/result.json>)记录：

| 范围 | 结果 |
| --- | --- |
| 套件完整性 | 22 个清单文件逐项核对，清单本身另以 SHA-256 绑定；缺失、多余和变更的文件均拒绝 |
| 离线安装 | 新建 F 盘 venv；15 个精确版本、逐包哈希、仅 wheel、`--no-index`；pip 进程禁止连接/DNS，`pip check` 通过 |
| 继承环境 | 故意设置外部 pip 源/find-links/配置文件及另一合成配置目录；套件自行覆盖，仍只安装本地 wheel，不改另一目录 |
| 真实入口 | wheel console、ZIP Python、PowerShell、CMD 均启动、读取静态资源、读取合成配置摘要、复用同一实例，并关闭各自监听 |
| ZIP 独立性 | ZIP 三入口前先卸载隔离环境中的 VideoCreate wheel并确认无法导入；结束后装回供人工验收使用 |
| 配置与版本 | 只使用新建 `.invalid` 地址合成配置，路径/只读模式与 dev44 一致；发布 Schema 与运行时一致；配置字节未变 |
| 路径与环境 | 中文/空格/`&` 的解压、解释器、工作和配置路径通过；运行 PATH 无 Node/npm |
| 安装前拒绝 | 候选元数据被修改、缺失依赖、多余文件、已有输出目录、输出位于套件内、CMD 展开字符路径均在安装前拒绝；已有目录无新增文件且字节不变 |
| 不支持的运行时 | 模拟 32 位运行时的检查拒绝，未创建输出；没有声称在真实 32 位 Windows 测试 |
| 异常 ZIP | 越界、Windows 设备名、大小写重复、ADS 和符号链接均在解压前拒绝；目标目录未创建 |
| 运行后完整性 | 再次 `--verify-only` 通过，交付目录不含运行日志或环境，全部字节与原清单相同 |

自动脚本不会打开浏览器；四入口属于 HTTP/安装检查，不新增浏览器逻辑组或核心/Web 测试项。产品、原测试和所有 r16 输入字节未变，因此沿用 **1121 核心 + 85 Web = 1206 项**和 **14 个逻辑浏览器组**，不重计或重复跑无变化的全回归。原安装回滚和 r14 九阶段维护证据保持原范围；套件没有补跑 dev43 回滚，也没有重新生成候选。

## 使用与剩余门槛

按套件 README 核验后，为 `run-offline.py --work-dir` 指定一个不存在的 F 盘目录。失败现场保留，不自动覆盖重试。成功的工作目录保留独立程序和合成配置；人工可先只读核对，再在合成配置上用占位 Key 验证本地保存、键盘、缩放和读屏。没有真实上游检查、生成、样片重生或发布步骤；关闭配置服务不操作 8765。

这台电脑上的新 venv不能证明全新 Windows 主机通过。`result.json` 明确保留 `clean_windows_host: not-established-by-runner`、`human_acceptance: not-performed`。新主机、真人读屏/完整任务可用性、正式版本和采用仍需实际环境、观察及独立决定；本批不覆盖稳定安装、不切换生产素材服务。额外型号合同、其他计费单位和 170 条旧记录的原身份缺口仍按原清单保留。
