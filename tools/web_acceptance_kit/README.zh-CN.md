# dev44 离线 Windows 验收套件

本套件用于未发行 dev44 的独立验收。只包含核验过的候选 wheel、技能 ZIP、15 个锁定依赖和验收脚本；没有 Python 安装器、Node、浏览器、配置、凭据、项目或样片。现有依赖仅适用于 **Windows x64、CPython 3.9**，不代表其他 Python 版本或 ARM64 已通过。请从可信来源另行准备相符的 Python（含 venv/ensurepip）与浏览器；不需要联网安装 Web 依赖。

本目录哈希用于检查传输完整性，不能代替发布者签名。先在可信的独立交付记录中核对整份 ZIP 的 SHA-256，再解压。脚本会核对所有文件的字节数/哈希，拒绝缺失、多余或变更的文件；不要把日志、工作环境或人工回执放进此目录。

## 先核验，再在新目录运行

以下路径是新机器示例。替换为实际 Python 和解压位置，每一步确认 `$LASTEXITCODE` 为 0。PowerShell 外部命令失败不会自动停止后续命令。

```powershell
$vcPython = 'C:\Python39\python.exe'
$vcKit = 'F:\VideoCreate验收\VideoCreate-dev44-offline-win-cp39'
$vcWork = 'F:\VideoCreate验收\run-001'
& $vcPython -B -X utf8 (Join-Path $vcKit 'run-offline.py') --verify-only
& $vcPython -B -X utf8 (Join-Path $vcKit 'run-offline.py') --work-dir $vcWork
```

`vcWork` 必须是不存在的新 F 盘目录，且位于套件之外。脚本不复用、清空或覆盖现有目录。路径支持中文、空格与 `&`；由于实际 CMD 入口的解析规则，拒绝双引号、`%`、`!` 和换行。失败时保留已创建环境及 `failure.json`、日志，下一次选择新的目录；不会自动删除失败现场。

自动检查创建独立 venv，以 `--no-index`、仅 wheel、逐包哈希安装全部 15 个依赖，并在 pip 进程中阻止网络连接/DNS。候选程序只读打开新建合成配置；其地址全部替换为 `.invalid`，不读取真实配置或 Key。四个实际入口验证健康、配置路径、静态资源和实例复用；ZIP 验证前会卸载隔离环境中的候选 wheel，随后再装回，便于人工验收。测试服务使用临时 loopback 端口，只清理本脚本启动的精确进程树，不使用 8765，不按名称或端口批量结束程序。所有工作文件与缓存在 `vcWork`。

成功时顶层 `result.json` 中 `ok` 为 true，四入口均显示 `listener_closed`。这只证明该环境上的自动验收；脚本不能判定 Windows 是否为干净新主机，也不授予真人读屏、完整任务体验或正式发行通过。记录实际系统、Python 来源、浏览器/读屏器和观察，使用同目录的 `ACCEPTANCE.zh-CN.md` 模板另存到 `vcWork`。

## 使用合成配置进行人工验收

```powershell
$vcRuntime = Join-Path $vcWork 'run\Python 环境 空格 & 路径\Scripts\python.exe'
$vcConfig = Join-Path $vcWork 'run\合成配置 空格 & 路径\videocreate.config.json'
& $vcRuntime -B -m videocreate config-web --config $vcConfig --port 8787 --read-only
```

若 8787 已被其他实例占用，保留它并选择另一个配置端口；不使用 8765。确认终端输出路径确实为 `vcConfig` 后，在本机浏览器手动打开终端所示地址。先只读检查五页、缩放、键盘和读屏。返回此服务的终端按 Ctrl+C，确认配置端口释放后，如需验证保存，使用同一命令去掉 `--read-only`。

保存测试只使用 `https://acceptance.invalid/v1` 和任意非真实占位 Key，例如 `offline-acceptance-placeholder`；名称、备注可空。Windows 会在合成配置旁加密这个占位值，用于检查 URL/Key 的本地保存流程，不证明真实凭据或其他 Windows 账户可用。不要点击目录检查或填写真实地址/Key，不执行生成、素材服务、项目恢复或发布操作。目录失败和真实上游合同另有开发证据，本套件不执行任何上游检查。

人工验收完成后以 Ctrl+C 结束这一个配置服务，并保留结果、日志与人工观察。套件没有修改 Codex 技能发现目录；原 dev43 安装、C 盘配置、DPAPI 和 8765 继续保留。这里不执行旧安装器，不做正式采用或生产切换。
