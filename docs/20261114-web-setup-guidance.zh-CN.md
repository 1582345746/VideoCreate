# 草稿接入整理待办 · r23

日期：2026-11-14。候选仍为未发行 dev44，C 盘安装 dev43 不变。本批落实 M2/W10 的“未知合同明确缺少什么”，没有增加型号合同或收费测试。

原来目录草稿详情只显示“待整理接入”。现在增加只读的“接入整理待办”：未配置协议、未确认操作，以及尚未明确登记的视频时长/分辨率/画幅，或图片尺寸/输出格式逐项说明。typed 参考操作缺少必需素材限制或组合时也说明原因。参数已填写但仍保留草稿时，提示 Codex 核对上游、精确型号、操作和合同来源后再启用。

这些待办只依据已保存的明确字段产生，不采用供应商声明或适配器默认值来消除未知。已有配置的路由、启用、默认资格和请求预检不变；没有待办不代表生成、账单或内容质量通过。用户添加上游仍只需 URL/Key，无需填写内部接入字段。

## 变更与验证

- 产品只改 Web DTO、详情展示和随包说明，重建静态资源。169 个非 Web Python 文件未变，沿用 1121 项核心全回归。
- [变更前专项](../_local/web-validation-20261114/setup-guidance-before-r1/result.json)：原 88 项通过，新增 3 项因缺少待办字段报错；保留此回执。实现后 [Web 91 项](../_local/web-validation-20261114/setup-guidance-web-r1/result.json)全部通过，0 失败/错误/跳过及外连尝试。唯一 Python 合计 1212 项，不重复计数。
- 新测试覆盖真实导入草稿、声明不能补成合同、部分填写与待核对状态、精确大小写合同适用范围、缺少 typed 参考合同仍拒绝启用。没有读取真实凭据。
- [源码浏览器](../_local/web-catalog-failure-20261114-setup-guidance-source-r2/result.json)及[已安装 r23 浏览器](../_local/web-catalog-failure-20261114-setup-guidance-installed-r1/result.json)均通过：视频、图片、大小写相近型号待办只读，不新增必填项、写入或目录请求；应用既有 XingAPI 文档只清除精确 `seedance2.5-V` 的待办，小写 `seedance2.5-v` 和图片草稿保持原字节。既有六类目录失败检查全部保留。
- 新区域共四次桌面/390px axe 扫描均无违规或未决项；[桌面图](../_local/web-catalog-failure-20261114-setup-guidance-source-r2/browser/draft-setup-desktop.png)与[手机宽度图](../_local/web-catalog-failure-20261114-setup-guidance-source-r2/browser/draft-setup-mobile.png)已检查。此结果不代替真人读屏。
- [完整十二组浏览器套件](../_local/web-browser-suite-20261114-setup-guidance-r1/result.json)通过。共 17 个逻辑浏览器组，本批验证 13 个；服务强退、Chrome 崩溃、配置上下文三组保留 r22，原 C 盘数据只读组保留 r16，九阶段维护仍为 r14。
- [候选构建](../_local/web-candidate-20261114-r23/candidate-build.json)及[四入口安装回滚](../_local/web-candidate-install-20261114-setup-guidance-r1/result.json)通过。286 个构建输入、260 个技能文件；前端独立重建一致，特殊路径、无 Node 运行、ZIP 无 wheel、43→44→43→44 均通过。

源码浏览器 r1 在增加新区域 axe 扫描前已通过，最终采用 r2；未覆盖原证据。核心、三类 r22 专项和 r14 维护未改动的验证范围继续明确沿用，不宣称整套在 r23 重跑。

## 当前离线套件与剩余

[r6 离线套件](../_local/web-acceptance-kit-20261114-r6/VideoCreate-dev44-offline-win-cp39.zip)包含 r23、15 个哈希依赖、独立验收器及空白人工模板；5,040,604 字节，SHA-256：`d662f764f9fa2ee245b9f9a53622cbadbf709df234155c6661f3b29c009c58d7`。[构建回执](../_local/web-acceptance-kit-20261114-r6/kit-build.json)与[独立解压验证](../_local/web-acceptance-kit-validation-20261114-r6/result.json)通过。仍仅支持 Windows x64 CPython 3.9，不含 Python 运行时；本机隔离安装不能代替全新 Windows 或人工验收。

额外精确型号/操作合同、token/分钟等计费语义与真实账单、170 条旧格式记录的原身份、真人读屏和完整任务可用性、全新 Windows、正式版本与采用仍需相应证据。素材生产切换继续延后，8765/PID 2176 保持原服务。

[本批保护回执](../_local/web-validation-20261114/preservation-setup-guidance-final.json)确认原配置/DPAPI、325 个外部文件及 5466 个原项目文件不变，37 个原有未提交文件保留。[进程清理](../_local/web-validation-20261114/setup-guidance-cleanup.json)确认本批测试服务已退出。无收费生成、样片重生或正式安装覆盖。
