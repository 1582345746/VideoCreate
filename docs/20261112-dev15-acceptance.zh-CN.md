# VideoCreate dev15：素材库、制作统计与星光首次生成

日期：2026-11-12。版本：3.0.0.dev15。继续执行原 73 项路线图；本报告是阶段验收，目标保持进行中。dev14 的原报告保留为历史记录。

## 本批结果

| 模块 | 本批落地 | 明确限制 |
| --- | --- | --- |
| 跨项目素材库 | 角色、场景、道具、声音卡片；不可变版本；复制媒体；哈希校验；重复入库/导入幂等；并发保护；影响清单 | 不覆盖不同内容的已有资产；不自动修改镜头/声轨；不继承审核；缩略图/试听/对照板仍待补 |
| 管理器 | 素材搜索、详情、从项目入库、导入指定版本；制作统计页 | 启动和控件 smoke 通过；人工视觉、干净机器测试未完成 |
| 制作统计 | 全候选生成时长、选中素材保留时长、去重源区间、变速播放时长、当前审核、重做率、分币种成本 | 源片合格不代表成片验收；未知账单不计算单位实际成本；无跨模型排名 |
| 星光适配器 | `xingapi-video-v1`；duration/ratio；完整任务号；查询退避；原任务恢复；Content-Type/MP4 校验；跨域不传密钥 | 当前只开放文生视频；本地媒体在发送前拒绝；URL 映射/上传待下一阶段 |
| 星光报价 | `providers pricing` 只读查询、带时间证据、描述变化提示；精确名称与计费单位 | 不自动改参数/启用型号；账户报价不是实付账单 |

## 真实 Seedance2.5-V 测试

一个独立 v3 小样项目，预算最多一次创建。请求为 **seedance2.5-V / 5 秒 / 16:9 / 720p**，蓝色立方体旋转的单镜头测试。任务号：`videoprep_9b8b3b22-4676-41da-bce0-7f4a63126b8e`。

一次查询发生 Python 3.9 socket.timeout，运行状态保存为 read_pending。修复查询捕获并新增测试后，使用同一任务号恢复，无第二次 POST。随后完成下载：**5.05 秒、1280×720、24 fps、121 帧、H.264、有音轨**；完整 FFmpeg 解码通过。响应没有回报模型字段，不把请求中的模型字符串当作服务内部路由证明。

源片 SHA-256：`3cdfce6ae3ae1a76ef21b3898f45d778a6461a5b9ff36779b450f918b76f9c36`。

- 项目：`acceptance/20261112-management/xingapi-v-smoke/`。
- 源片：`jobs/job-001/af140420c09a478ca78ef6df659c9a6e/source.mp4`。
- 按原计划静音的本地预览：`deliverables/preview.mp4`；审片页：`reviews/viewer.html`。
- 技术回执：`acceptance/20261112-dev15/xingapi-technical-acceptance.json`；本机 binding evidence 已保存 contract / smoke pass。
- 动作、声音、人物参考等质量仍 **unverified**；实际账单仍未知。小样最初在未取得报价时按请求数限额提交，原 CNY 账本中的 estimated/actual 都是 null；没有事后改写为 USD 实付。

加上 dev14 两次 Grok 请求，本开发阶段累计创建 **3 次**：Aivalux 原任务仍 read_pending；RapidAPI 单次技术通过；星光 V 单次技术通过。

## 文档与价格证据

完整文档由用户提供，站内更新日期 2026-10-30。原文保存在忽略的 acceptance 目录，SHA-256 为 `598f4666348358887b09ddb5c03aee2b23f72a4f141832b7fb951a4bc4cc868c`，发行包只保留合同摘录和来源说明。

当前 Key 的 `/pricing` 返回 USD，720P 单档：933 每条 2.79；C 每条 2.89；Q 每条 1.35；S 每秒 0.299；V 每条 4.9；Wan 每秒 0.22。`per_request_price` 字段在按秒模型也复用，解析必须结合明确的计费单位。

目录新描述与旧截图有差异：S 写明 **0 视频参考**，Wan 写明 **5 音频参考**。新描述追加到本机备注，旧截图声明保留，配置变更有备份；二者都没有自动变成执行能力。

## 测试与交付

- 全量回归：**531 项通过，0 失败、0 错误、0 跳过**。unittest 运行 345.910 秒，进程计时 349.5 秒。覆盖已有流程和 23 项新测试。
- 收到完整文档后新增报价模块：再运行 **28 项针对性测试**，其中 4 项为新报价测试，全部通过；未把它们称作第二次全量回归。
- 回归含本地 HTTP 实验：跨端口 302 不转发 Authorization，JSON Content-Type 不落为视频，429 Retry-After 被保留。
- 素材库与统计窗口实例化通过；无网络、无保存配置；没有宣称人工视觉验收。
- 已安装 EXE 在故意改变默认配置目录的环境下，仍读取固定权威配置，返回 5 上游、25 binding。
- skill-creator 验证通过（UTF-8）；新增 CLI 和真实 RapidAPI 项目统计运行通过。

技能位置：`C:/Users/FBX/.codex/skills/videocreate`。dev14 备份：`C:/Users/FBX/.codex/skill-backups/videocreate-20261112-201514-339a2b48`。

管理器：`C:/Users/FBX/AppData/Local/Packages/OpenAI.Codex_2p2nqsd0c76g0/LocalCache/Local/VideoCreate/manager/3.0.0.dev15/VideoCreateManager.exe`。权威配置为同一 VideoCreate 目录中的 `videocreate.config.json`，已到修订 2。V 只启用 5 秒/16:9/720p 文生视频，其余五个星光条目仍是草稿。原有默认和加密凭据保留。

管理器包含 Python/Tcl/Tk，未签名；精确包体和 SHA 见 `dist/manager-dev15/manager-build.json`。发行物为 `dist/dev15/` 技能 ZIP/wheel 和 `dist/manager-dev15/` 管理器 ZIP。发行包不含用户配置、密钥、任务产物和原始附件。

## 接下来

优先完成类型化图片/视频/音频引用及 HTTPS 对象存储映射、过期和恢复，保持旧图片流程和旧任务快照兼容。随后扩展逐型号参数验证、远端配额、制作分支、素材对照、声音/口型专项和浏览器能力。逐项状态仍以原 73 项目录为准，不以这次小样通过宣称全功能完成。
