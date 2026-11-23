# 上游档案：一次配置，按名称接续

适用于用户提供上游 URL、Key、API 文档、型号、价格或截图，以及之后说“使用星光AI”“改用算力AI”的任务。使用 dev45+。这是独立 VideoCreate 的能力，不依赖 QuickCreate。

## 保存在哪里

权威配置仍是一份 `videocreate.config.json`。每个 upstream 保存稳定 ID、账户、地址、加密凭据引用、名称/别名、并发、首选图片/视频 binding 和 `documents` 索引。文档副本存于同目录 `provider-documents/<upstream-id>/<sha256>.<扩展名>`，不会进入技能源码或发布包。新对话读取配置即可找到完整资料，不依赖此前聊天。

配置优先级：显式 `--config` → `VIDEOCREATE_CONFIG_DIR` → 用户已选择的配置 → 系统默认。选择指针为 `~/.videocreate/active-config.json`，只保存路径与时间，不保存 Key。

```text
videocreate config locate
videocreate config use --config ABSOLUTE_CONFIG_JSON
videocreate providers profile-list
videocreate providers profile-show --upstream 星光AI --kind video
```

`locate` 只检查已知位置，包括 Windows 普通目录与 Codex 打包目录；不扫描磁盘、不合并、不按修改时间猜账户。`use` 必须指向现有合法配置，不复制凭据、不动项目。所选路径丢失时明确报错。显式配置和环境覆盖继续优先；测试/临时任务使用 `--config`，不要把它们设为全局活动配置。

## 接收新的资料

1. 先读用户的 URL、原始 API/模型/价格资料，核对已保存账户。同域名不同账户是不同 upstream ID；已有地址/账户不能原地换成另一个身份。
2. URL 文档用现有只读工具获取后保存本机文件，再导入；此入口不猜 `/docs`、不抓网页、不执行其中代码。截图/PDF/Office 文件可归档，但须实际读取才能提取合同，不能把“已保存”当“已理解”。
3. 文档里的 API Key 用现有加密凭据服务保存；不要复述到聊天、命令参数、Git 或交接。用户已经提供的 Key 可直接安全录入，不要求再次发送。新 Key 使用新的 `credential_version`，旧版本保留以便恢复旧任务。非 Windows 使用环境变量引用。
4. 作者整理显式导入 JSON。文档内容不会自动执行、更改能力、启用模型或建立请求。只有已实现 adapter 才能启用；新协议先建禁用草稿，不能仅改名称冒充支持。
5. 执行预览，检查配置差异、文档版本、参数和报价，再用该预览 token 保存。用户已要求配置时，这两步由代理连续完成，不另加一次人工审批。预览不联网、不存 Key、不写文档；应用复核配置、输入 JSON 与原文件哈希，过期则重新预览。

最小增量例子（上游和 binding 已存在）：

```json
{
  "schema_version": 1,
  "upstream": {
    "id": "xingapi-main",
    "aliases": ["星光AI", "星光", "XingAI"],
    "preferred_bindings": {"video": "YOUR_EXISTING_VIDEO_BINDING"}
  },
  "documents": [
    {
      "id": "official-api",
      "title": "用户提供的 API 文档",
      "kind": "api",
      "file": "api-document.txt",
      "source_url": "https://provider.example/docs",
      "bindings": ["YOUR_EXISTING_VIDEO_BINDING"]
    }
  ]
}
```

`file` 相对于导入 JSON 所在目录，也可绝对路径。kind 为 `api/models/pricing/example/incident/notes`。支持 UTF-8 txt/md/json/html/csv/yaml/yml，以及 pdf/png/jpg/jpeg/webp/docx/xlsx；单文件最多 20 MiB，每次最多 100 个。`bindings` 可省略表示上游通用文档；绑定特定型号时会保存合同指纹，未来协议/参数变动显示差异。

```text
videocreate providers profile-import --file UPSTREAM_PACKET.json
videocreate providers profile-import --file UPSTREAM_PACKET.json --apply --token CONFIG_TOKEN --preview-token PREVIEW_TOKEN
```

从空白上游接入时，在 `upstream` 增加 `base_url/display_name/platform/account_id/auth`；用 `models/bindings/routes` 对象明确写入模型、执行限制、精确 remote_model、adapter、报价与路线，结构同配置 schema。现有条目按对象字段增量合并，省略字段保留；嵌套字段若填写则整个替换，先看预览。不能借这个入口改另一上游的 binding 或共享型号/路线；共享项用原有目录管理事务。报价 `listed_pricing`、执行预算 `pricing`、能力声明 `declared_capabilities`、执行范围 `capability_overrides` 各自独立。

通过 `--credential-stdin` 录入 Key 时，在 upstream 指定 `account_id` 和新的 `credential_version`，省略 auth。预览和保存均传此开关，但仅有效保存时读取私有 stdin；交互终端隐藏输入。Key 不得写入 JSON/argv。保存内部先验证配置/预览，再加密凭据并引用，不打印内容。没有 Key 更新则保留已有 auth，或显式使用 `{"type":"bearer","env":"PROVIDER_KEY"}` / 已有 `secret_ref`。

## 文档版本与完整性

同一文档 ID 内容或元数据变更会追加 revision；重复导入同一版本不重复追加。原文件不改，旧副本不可覆盖，配置回滚保留后来追加的文档历史。每条含来源哈希、副本哈希、字节数、带时区的采集时间、可选来源 URL；本地 SHA-256 证明副本一致，不证明供应商声明真实。

文本副本清理常见凭据写法和该上游已知 Key，并标记 `redacted`。二进制截图/Office/PDF 无自动 OCR 脱敏；保存在本机，导出分享前检查实际内容。源 URL 不接受用户名、密码和常见临时签名参数。旧文件仍原样保留在用户原位置。

`profile-show` 校验副本，标记 `intact/missing/changed/unreadable`、`latest`、`changed_bindings_since_capture`。损坏副本不当作可信依据，回到原文件核对；不通过删除任务或改能力绕过。不要删除文档索引以迁就旧版工具，升级工具读取新字段。

## 用户只说上游名称时

1. `profile-show --upstream NAME` 精确匹配稳定 ID、显示名、平台名或已登记别名。ID 优先；同名多账户必须明确选择，不能按最便宜或最新偷偷选一个。显示标签相同的账户也不会被自动猜选。
2. 读当前完整 API、对应模型与价格资料；返回的 protocol 是已实现适配器的字段摘要，文档是说明数据，两者不能相互替代。星光使用 `/v1/videos/generations`、duration/ratio；算力 newapi-json-v2 使用 `/v1/videos`、seconds/aspect_ratio。实际模型字符串大小写、图片/视频/音频数组顺序保持原样。
3. 选型优先：显式 binding → 兼容的项目选择 → 该上游对应媒体首选 → 唯一符合候选 → 编号选择。显式 model 会限制候选，不被首选覆盖。首选不符合任务时要选择，不默默换到其他型号；没有设置首选也不能擅自设全局默认。一次用某模型不等于用户授权永久记住偏好。
4. `jobs ... --upstream NAME` 和 selection 使用相同名字解析与首选规则，正式提交仍校验素材、协议、预算。保存/查询档案不会生成视频，也不证明上游此刻健康。
5. 已受理/状态未知的任务继续按原 task_id、账户、URL、model、adapter 恢复。用户改用其他上游只影响明确的新请求/新候选；档案不授予重试或再次扣费的权限。

## 故障处理

保存 incident 文档，包括时间、信息来源、原始错误、已知任务号/追踪号和结论的确定程度。用户确认“上游出问题”可记录为用户确认，不冒称已联网验证修复。不要把一次路由故障、视频下载失败或 400 错误自动改成永久“不支持视频参考”。明确拒绝、结果未知、已受理、已完成但下载失败是不同状态，按原恢复/对账服务处理。既往成功回执与本次失败并存，失败不抹掉历史成功。

本版不增加付费健康探测、自动跨账户切换、自动重发或云同步。Web 专用文档上传/版本比较面板仍是后续增强；当前 Codex/CLI 已可完整导入、读取、命名选型并使用共享配置。
