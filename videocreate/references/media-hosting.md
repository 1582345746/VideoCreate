# 本机素材与 HTTPS 直链

适用于用户将本机文件通过既有 HTTPS 内网穿透提供给媒体模型的场景。与上游目录使用同一个 `videocreate.config.json`，可在管理器“本机素材与 HTTPS 直链”中配置。只托管明确选择的文件快照，不暴露素材所在文件夹。

## 服务与内网穿透

```text
videocreate media-server configure --public-base-url https://YOUR_DOMAIN --port 8765
videocreate media-server start
videocreate media-server status
videocreate media-server list
videocreate media-server revoke --publication-id PUBLICATION_ID
videocreate media-server stop
```

服务监听 Windows 的 `127.0.0.1`。穿透客户端在 Windows 时，目标使用 `HTTP → 127.0.0.1:8765`；在 Docker Desktop 容器中时，目标使用 `HTTP → host.docker.internal:8765`。公网使用 HTTPS，转发全部路径。不要改为容器的 `127.0.0.1`。`/health` 返回 204，实例头必须匹配当前本机服务，旧进程或别的站点响应不算接通。

服务独立于管理器窗口，关闭窗口后仍可运行；不会自动安装系统开机服务。生成期间需保持电脑、服务和隧道在线。端口修改后先停止旧服务再启动。持久运行信息和素材快照在权威配置旁的 `local-media/`，用户文件及凭据不会打包到技能。

## 项目引用与链接

```text
videocreate media-ref register PROJECT --source FILE --kind image --role identity
videocreate media-ref host PROJECT --source FILE --kind video --role motion --upstream UPSTREAM_ID
videocreate media-ref host PROJECT --source FILE --kind audio --role sound --upstream UPSTREAM_ID --lifetime 14400
videocreate media-ref list PROJECT
videocreate media-ref check PROJECT --reference REFERENCE_JSON --upstream UPSTREAM_ID
```

`register` 检查真实格式、大小、时长和 SHA-256，并将不可变快照复制到项目。当前支持 PNG/JPEG/WebP、MP4、MP3/WAV，单文件不超过 512 MiB，使用 FFprobe 检查。`host` 为快照生成链接，再通过公网完整 GET 核对类型、字节和哈希，成功后将链接用 Windows DPAPI 保存；项目 JSON 只保留凭据引用、源哈希、过期时间和验证证据。失败时撤销刚生成的链接。

外部已有 HTTPS 文件可用 `media-ref link PROJECT --reference REFERENCE_JSON --upstream UPSTREAM_ID --url-file PRIVATE_FILE --expires-at ISO_TIMESTAMP`，或通过 `--url-env VARIABLE_NAME` 读取；也可在终端隐藏输入。稳定链接需明确 `--permanent`，这只是用户对可用性的声明。URL 文件和环境变量不得进入项目或发行包。无需在聊天或命令参数中粘贴链接。

链接按上游、账户和源哈希绑定，更新链接保留历史且不改变源身份。默认有效期 4 小时，检查默认要求至少剩余 2 小时；可按模型排队时间调整。模型必须能在无登录、Cookie 和额外认证头的情况下读取。检查会验证重定向，拒绝私网和保留地址，不向文件服务器发送模型密钥。

管理器“生成文件直链”只创建文件发布，不自动绑定到项目；链接在结果窗口临时显示，可显式复制。CLI `media-server publish --source FILE --kind image --output PRIVATE_RECEIPT_JSON` 将链接保存到指定私有回执。日志与发布列表不输出完整链接。链接持有人在有效期内可下载；撤销和过期阻止后续访问，不能撤回已经下载的副本。

## 本阶段边界

dev16 完成了素材托管、外网读取和项目传输绑定。`media-ref` 不修改分镜、创建生成任务或产生上游费用。`xingapi-video-v1` 仍只支持文生视频；当前不能把这里的引用声明为已经传给模型。下一阶段需接入类型化计划、整批预检及 `images`/`videos`/`audios` 数组。原任务的查询和下载必须沿用原任务号及账户，不依赖素材链接续期，不重新创建。
