# 新对话启动提示

在新对话选择迁移后的工作目录 `F:/VideoCreate`，复制下面内容。此段交给新对话后才是新的开发指令；本轮只完成目录迁移、验证和交接。

```text
请继续开发 VideoCreate 的本机 Web 上游配置工具。

先完整阅读：
1. F:/VideoCreate/docs/20261113-f-drive-migration.zh-CN.md
2. F:/VideoCreate/docs/20261113-new-chat-handoff.zh-CN.md
3. F:/VideoCreate/docs/20261113-web-provider-config-design.zh-CN.md
4. F:/VideoCreate/docs/20261113-complete-development-checklist.zh-CN.md
5. F:/VideoCreate/docs/prototypes/provider-config-web.html

仓库、Git 历史、未提交文件和全部项目已完整复制并逐文件哈希校验。原 E 盘目录只是保留副本，后续只在 F:/VideoCreate 开发。C 盘已安装技能、权威配置与凭据继续使用原位置，不重复配置、不重新安装。历史项目回执中的 E 盘来源路径有意保留，不能全局替换；迁移记录位于 F:/VideoCreate/_local/migration-20261113。

边界：Web 只管理上游、模型、密钥、参数、备注、报价、默认、只读目录/证据、备份与诊断。
首次用户默认只填 URL/Key，显示名/备注可选。Codex 依据已有合同与文档整理模型、协议和参数；复杂字段放高级设置，不要求用户手写内部 binding/route，不用收费 POST 猜协议。
主题、大纲、剧本、角色、分镜、视频生成、恢复、剪辑和审片继续由 Codex + VideoCreate 技能完成。
不再开发 EXE/Tk 主界面，不做网页视频工作台，不复制现有执行底座。

先核实 dev43 已安装和 dev44 未完源码的差别，保留全部未提交文件和现有用户数据。
仅 JSON 用户入口方案已取消。旧 build/dist/acceptance 等生成目录已移到仓库外私有归档，详见清理记录；源码、核心/界面测试、真实项目和配置已保留。
旧 8765 素材服务与隧道不要随意停止或重新配置。配置 Web 采用独立 loopback 端口。
按照完整清单从 M1/M2 开始实施、测试和优化，复用现有配置/目录/价格/凭据服务。
常规可逆实现选择自主推进，不重复询问已明确的产品边界；缺少真实 API 合同等必要条件时再说明问题。
本轮优先完成本机 Web 配置闭环，不调用收费生成测试，不重生已有 30 秒样片。
先给出核实到的基线和当前实施批次，然后实际开始开发。
```

若需要新对话使用目标模式，可另加一句“请为上述开发创建新目标并持续推进”。此前目标已清除，不应自动恢复。
