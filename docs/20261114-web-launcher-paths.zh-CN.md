# Web 启动入口、特殊路径与错误返回验证

日期：2026-11-14。W18/W22 的本机候选增量；源码/候选仍为未发行 dev44，C 盘已安装 dev43 保留。

此前仓库外验收覆盖 wheel console 和 ZIP PowerShell，但 Python、配置及解压目录均为普通路径，ZIP 验收环境也安装了同版本 wheel。本批在新的 F 盘目录把工作目录、Python venv、配置目录和 ZIP 解压目录均设置为含中文、空格和 `&` 的名称。保留所选 Python 的运行库路径，只从 PATH 排除实际包含 Node/npm 的目录。

| 实际入口 | 验证行为 | 结果 |
| --- | --- | --- |
| wheel 的 `videocreate-config-web.exe` | 中文 Python/config/cwd 路径；只读启动、会话/API 摘要中的精确配置路径、HTML/JS/CSS、同实例复用与关闭 | 通过 |
| ZIP `scripts/videocreate.py config-web` | 先卸载 wheel；特殊路径下直接从技能源码启动、资源、配置与复用 | 通过 |
| ZIP `scripts/config-web.ps1` | wheel 不在环境内；实际 Windows PowerShell 调用与路径参数传递 | 通过 |
| ZIP `scripts/Start-ConfigWeb.cmd` | wheel 不在环境内；实际 cmd.exe、PowerShell 与 Python 进程链；特殊字符保持路径数据 | 通过 |
| 错误返回 | PowerShell/CMD 拒绝保留的 8765 端口；返回 1，无 traceback；不绑定或停止原素材服务 | 通过 |
| 依赖诊断 | 缺少 FastAPI/Uvicorn 与缺失传递依赖、运行库/DLL 加载失败分别说明；独立 console 与主 CLI 同样返回结构化错误 | 通过 |

每个成功入口均检查 API 摘要读取的是指定合成配置、只读模式和原配置字节，复用前后 `/health` 的完整实例身份一致。首页及两项资源返回成功，测试关闭后对应监听消失。无 Node/npm 的 PATH 不等于移除它们在机器上的安装，也不等于全新 Windows 验收。没有打开浏览器、写真实配置或调用上游生成。

新增启动诊断修复：独立 console 处理可预期 ConfigError/OSError/ValueError；ModuleNotFoundError 按可选入口包/传递依赖区分，ImportError 报告核查 Python、锁定包和运行库路径，不回显底层导入异常。PowerShell 使用同一 CLI，去掉先行导入检查。CMD 先保存 PowerShell 返回值，再在错误后停留提示，最后返回原退出码；局部环境不向调用者泄漏变量。

首次 paths-r1 把运行 PATH 整体替换，意外去掉 Conda SSL DLL 目录，实际 `_ssl` 导入失败；同一 venv 在原运行 PATH 导入通过。修正测试为只去掉 Node/npm 目录，同时本次候选对刻意缺少 DLL 路径的真实故障也给出结构化说明。paths-r2 的四入口启动已完成，但错误码检查发现 CMD 的 `pause` 把拒绝启动变成 0；受控前/后验证分别得到 0 和 1。修复后 r8 候选在 paths-r3 完整通过，旧失败目录保留。

Web 全专项 76 项通过（13.344 秒），新增两项测试覆盖依赖分类、不绑定 socket、错误不包含原导入详情，以及独立 console/主 CLI 的错误返回一致。核心 1107 项沿用上轮完整结果：本次构建输入只改变 Web launcher、PowerShell、CMD 和启动参考四个文件；136 个核心 Python 文件、22 个前端/静态输入及 11 个 HTTP 模块哈希不变。九组浏览器及两个恢复组沿用，未宣称重新执行。唯一 Python 测试总数 1183，实际入口检查不另外计数。

候选 r8 独立前端重建一致，285 个构建输入及 259 个技能源文件与当前工作树相符；离线锁定依赖、仓库外名称查询、`pip check` 和 43→44→43→44 通过。验证入口为 [候选安装工具](../tools/verify_web_candidate.py)。主要回执：`_local/web-candidate-install-20261114-paths-r3/result.json`、`_local/web-validation-20261114/launcher-web-r1/result.json`、`launcher-change-scope.json`、`cmd-exit-before.json`、`cmd-exit-after.json`。

最终保护回执 `_local/web-validation-20261114/preservation-launchers-final.json` 确认原配置/DPAPI、325 个外部文件、5466 个原项目文件不变；清理回执 `launcher-cleanup.json` 确认测试进程已退出，8765 仍为 PID 2176。未收费生成、未重生样片、未解密真实凭据。全新 Windows、真人读屏与完整任务使用验收、正式版本与采用仍待处理，目标继续 active。
