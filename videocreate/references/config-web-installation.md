# Web 候选的安装、升级、回滚与卸载

本说明适用于 dev44 本机 Web 候选。已安装的 dev43 技能继续保留；候选通过开发测试不代表正式发行或已经采用。当前使用同一 Windows 账户和原 C 盘配置、DPAPI 凭据，程序、虚拟环境和试装目录放在 F 盘。Web 运行需要 Python 和可选 Web 依赖，不需要 Node/npm、FFmpeg 或额外的语音模型。

## 先分清程序与用户数据

| 内容 | 定位与处理 |
| --- | --- |
| 程序 | wheel 所在的专用 Python 环境，或单独解压的 `videocreate` 技能目录。升级、回滚和卸载只处理选中的程序副本 |
| 配置 | 启动终端输出及 Web 设置页显示的完整 `config_path`；`--config` 优先，其次 `VIDEOCREATE_CONFIG_DIR`，Windows 默认在当前进程的 `%LOCALAPPDATA%\VideoCreate`。Codex 沙箱化安装的实际目录可能带 `Packages\…\LocalCache`，以实际路径为准 |
| 凭据及恢复材料 | 配置旁的 `secrets.dpapi`、`backups`、`config-history` 和 `runtime` 等。整组保留；旧凭据版本、备份和未提交草稿也有恢复用途。密文仍依赖原 Windows 账户，复制文件不等于跨账户迁移成功 |
| 项目与素材 | 原项目、任务快照、预算账本、已有成片、组件源和模型目录。可能在配置目录以外，单独保留。历史路径不作批量替换 |
| 素材服务 | 当前 `127.0.0.1:8765` / PID 2176。升级或卸载配置 Web 不停止它，也不删除其程序、目录或链接 |

开始前记录当前程序版本、实际配置路径及目标安装路径。停止写配置的窗口后，可在受保护的本地目录备份整组配置材料并记录 SHA-256；不要把配置、密文或原始备份上传到诊断报告或发行包。本文命令不初始化、导入或重置真实配置，也不执行生成。

关闭浏览器只关闭页面。升级前先等待保存完成，在原配置服务终端按 Ctrl+C，并确认该配置端口已释放。端口占用时读取 `Get-NetTCPConnection -State Listen -LocalPort 8787`，再核对所属进程的命令行和路径；端口号本身不能证明进程身份。不要按 `python`、`VideoCreate` 等名称批量停止进程；8765 保持运行。停止配置服务也不取消其他进程已开始的生成任务。

## 检查候选及依赖

保留整份候选目录中的 `candidate-build.json` 和 `artifacts`。对照回执中**同名文件**的 SHA-256 和字节数，先检查 wheel、ZIP，再使用它们。当前包没有发布者数字签名；同目录哈希只能证明与该回执一致，不能证明来源可信。正式发行须另行决定来源和签名策略。

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath 'F:\VideoCreate\_local\web-candidate-20261114-r14\artifacts\videocreate-3.0.0.dev44-py3-none-any.whl'
Get-FileHash -Algorithm SHA256 -LiteralPath 'F:\VideoCreate\_local\web-candidate-20261114-r14\artifacts\VideoCreate-3.0.0.dev44-web-candidate.zip'
```

以下是本机路径示例，使用前替换为实际核验的候选和**新的专用目录**。Web 依赖闭包 `assets/web-py39.lock.txt` 已在本机 Windows Python 3.9 验证。离线 wheelhouse 必须事先准备与 Python 版本、架构相符的全部 wheel；不能据此宣称所有 Python 3.9+ 或全新 Windows 环境已通过。运行前端无需 npm install。

## wheel：在独立环境试用和升级

```powershell
$vcBasePython = 'C:\Users\FBX\anaconda3\python.exe'
$vcEnvironment = 'F:\VideoCreate\_local\web-runtime-user'
$vcPython = Join-Path $vcEnvironment 'Scripts\python.exe'
$vcWheel = 'F:\VideoCreate\_local\web-candidate-20261114-r14\artifacts\videocreate-3.0.0.dev44-py3-none-any.whl'
$vcWheelhouse = 'F:\VideoCreate\_local\web-wheelhouse'
$vcLock = 'F:\VideoCreate\requirements\web-py39.lock.txt'

# vcEnvironment 应是新目录；已有专用环境升级时跳过创建这一步。
& $vcBasePython -m venv $vcEnvironment
& $vcPython -m pip install --no-index --find-links $vcWheelhouse -r $vcLock
& $vcPython -m pip install --no-index --no-deps $vcWheel
& $vcPython -m pip check
& $vcPython -m videocreate version
& $vcPython -m videocreate config-web --read-only
```

每一步确认退出码为 0 后再继续；PowerShell 调用外部程序失败默认不会中止后续行。环境已装同版本的另一候选时，先关闭该环境的配置服务，再对核验过的 wheel 使用 `--force-reinstall --no-deps`，随后重新执行 `pip check` 和版本检查。依赖锁也变化时先单独更新相应闭包。

首次先只读打开，核对终端和设置页中的版本、模式及原配置路径。路径不符时结束该配置服务，确认当前 `VIDEOCREATE_CONFIG_DIR` 或显式传入 `--config '原配置完整路径'`，不要通过 `config init` 新建一份来掩盖路径错误。只读核对完成后结束服务，再去掉 `--read-only` 启动编辑模式；两种模式不能在同端口复用。

wheel 的 `python -m videocreate` 入口可以独立运行，但 pip 安装不会把技能注册到 Codex 的技能发现目录。当前 C 盘 dev43 技能不会因此升级。版本相同也应核对候选哈希，不应把任意 dev44 当成同一组字节。

## ZIP：保留旧目录，另解压一份

dev44 技能候选 ZIP 包含顶层 `videocreate` 目录，**不包含仓库根目录的 `install.ps1`**。解压到新的 F 盘目录；不覆盖原安装，不把项目或配置放进技能目录。

```powershell
$vcArchive = 'F:\VideoCreate\_local\web-candidate-20261114-r14\artifacts\VideoCreate-3.0.0.dev44-web-candidate.zip'
$vcExtract = 'F:\VideoCreate\_local\web-skill-user'
$vcPython = 'F:\VideoCreate\_local\web-runtime-user\Scripts\python.exe'
Expand-Archive -LiteralPath $vcArchive -DestinationPath $vcExtract
$vcSkill = Join-Path $vcExtract 'videocreate'
& $vcPython (Join-Path $vcSkill 'scripts\videocreate.py') version
& $vcPython (Join-Path $vcSkill 'scripts\videocreate.py') config-web --read-only
```

所选 Python 仍需安装上述 Web 依赖；不要求安装 VideoCreate wheel。也可用 ZIP 中的 `scripts/config-web.ps1 -Python 'Python完整路径' -ReadOnly`，或 `scripts/Start-ConfigWeb.cmd -Python 'Python完整路径' -ReadOnly`。明确指定解释器可避免双击时选错环境。zip 入口优先加载自身源码；升级时换到另一个完整解压目录，并核对新路径和版本。

仓库根目录的历史 `install.ps1 -Force` 会更换技能发现目录中的安装，还会初始化/迁移配置并设置安装、组件档案。它不是本机 Web 候选的旁路试用步骤。本轮不执行该安装器，也不覆盖 C 盘 dev43；以后正式采用时再根据实际安装方式制定步骤。

## 回滚程序前检查配置兼容性

先保留原程序、候选和升级后全部用户数据。程序回滚不回滚配置，也不撤销上游已接收的任务。使用旧程序的只读校验确认当前配置可读；不加 `--ready`，不解析真实密钥：

```powershell
& '旧版环境\Scripts\python.exe' -m videocreate config validate --config '原配置完整路径'
```

dev44 新增的图片 `pricing.per_image` 不被 dev43 接受。发现该字段或其他不兼容约束时，旧版应报错并保留原字节；停止回滚后的编辑，继续使用 dev44。若确实需要移除新功能，先由 dev44 明确预览/保存完整配置变更并保留备份，再以旧版验证。不要为通过旧版校验静默删除价格、账户、接入或任务身份，也不要直接恢复一份早于新任务/换钥的配置。

配置兼容后，wheel 专用环境可安装原来保留且核验过的旧 wheel（`pip install --no-index --no-deps --force-reinstall '旧wheel完整路径'`），然后检查版本与配置；ZIP 切回原解压目录。原稳定安装未动时，结束候选服务即可回到原入口。旧版没有配置 Web 时使用它原有 CLI/界面，不运行不存在的 Web 命令。

## 卸载只处理指定程序副本

先结束该副本的配置服务，保存文档和用户数据，记录专用解释器/解压目录的完整路径。只卸载候选 wheel：

```powershell
& 'F:\VideoCreate\_local\web-runtime-user\Scripts\python.exe' -m pip show videocreate
& 'F:\VideoCreate\_local\web-runtime-user\Scripts\python.exe' -m pip uninstall videocreate
& 'F:\VideoCreate\_local\web-runtime-user\Scripts\python.exe' -c "import importlib.util; print(importlib.util.find_spec('videocreate') is None)"
```

在仓库及 ZIP 解压目录以外运行最后一条，以免源码遮蔽卸载结果。确认 `pip show` 的 Location 指向指定环境后，再回答 pip 的卸载提示。卸载 VideoCreate 不自动删除 FastAPI/Uvicorn 等依赖；它们可能被该环境其他程序使用。

ZIP 没有卸载注册项。确认没有程序运行、目录内不含配置/项目/私人文件后，可先在资源管理器将**这一个解压副本**改名隔离，重新核对数据和原稳定入口，再手动删除。专用虚拟环境同理；共享 Python 环境不整目录删除。历史 `install.ps1 -Uninstall` 会递归删除选定技能目录，并不能保护用户自行塞进其中的项目或配置，因此不用于本候选目录。

保留 C 盘原配置、`secrets.dpapi`、备份、草稿、项目及 8765 素材服务。需要重装时重新安装已核验的程序副本，继续指向同一配置；原 Windows 账户仍是读取 DPAPI 的条件。删除用户数据、撤销远端 Key 或停止远端任务均是单独操作。

## 当前验证范围

开发验证在新的 F 盘隔离目录、合成配置和凭据哨兵上实际运行离线安装、dev43→dev44→dev43→dev44、同版本候选重装、pip 卸载、ZIP 改名隔离及重新安装。逐阶段核对配置、历史、草稿、项目、样片和密文哨兵的路径/字节；不把哨兵可保留当成真实 DPAPI 可解密或任务可恢复的证明。wheel 与 ZIP 都应包含本说明。

四种 Web 启动入口、静态资源及实例复用另由候选安装验证覆盖；最新候选和实际结果以仓库开发回执为准。全新 Windows、真人读屏、完整用户验收及正式采用仍待完成。升级程序不会为模型能力、价格账单或已有样片追加验收结论。
