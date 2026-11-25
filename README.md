# 离子光钟文献推送

## 本地阅读网站

在项目目录运行 `python viewer.py`，打开 [本机阅读室](http://127.0.0.1:8776)。可按期次、栏目、作者、单位和摘要检索，收藏保存在当前浏览器，原文优先打开本地 PDF。页面自动读取“试筛”、“日报/日期”和“out”中的 issue.json，刷新即可看新内容。从 GitHub Actions 下载的每期产物可解压到“日报/YYYY-MM-DD/”，保持 PDF 子目录。端口可通过 `--port 7770` 更换。

## 两层筛选

在 [筛选配置](screening.json) 编辑研究方向、关键词和默认阈值 0.60。关键词层在标题与摘要中筛掉明显无关文章；第二层由当前 GPT 逐篇评估方向契合度（50%）、具体贡献（30%）和原文支撑（20%）。归一化分数达到阈值且有原文依据才入选，刊名和作者不加分。网页可展开查看理由与引句。[逐档标准与运行顺序](日报规则.md)

本地定时任务使用当前 Codex 中的 GPT；云端使用 Codex Action 的 OpenAI API 密钥。GitHub Actions Variables 中可设置 `SCORING_MODEL` 选择该 API 支持的 GPT 模型，此模型也负责当期检索整理；`RELEVANCE_THRESHOLD` 可覆盖阈值。

## 邮件和微信同时推送

**普通微信**使用 PushPlus 的微信公众号。发件人在 PushPlus 登录并获取 token，创建订阅组后分享订阅二维码，读者扫码关注并加入。GitHub Secrets 添加 `PUSHPLUS_TOKEN`，Variables 添加 `PUSHPLUS_TOPIC`（订阅组编码）和 `PUSH_CHANNELS=email,wechat`。留空订阅组时只发给 token 所属用户。每期合并为一条微信消息，按核心论文、可直接用于实验的方法、正式发表更新排列，附公开原文链接。全文超出 2 万字时发送同序论文目录；邮件继续附实际文件。PushPlus 返回受理状态，最终送达以微信通知或平台投递记录为准。[PushPlus 接口与订阅说明](https://www.pushplus.plus/doc/guide/api.html)

**企业微信群**可在目标群添加群机器人，将 Webhook 存入 Secrets 的 `WECOM_WEBHOOK`，并设置 `PUSH_CHANNELS=email,wecom`。本地运行时使用同名环境变量。两条微信渠道也可以同时启用。

每天从 arXiv、PRL、PRA、Nature、Science、Nature Communications 和 Metrologia 筛选离子光钟文献，通过邮件或飞书群直接送达读者。读者使用自己的邮箱或飞书即可阅读。GitHub Actions 可以独立运行整套流程。

**核心论文**展示钟种、跃迁和主要结果。**可直接用于实验的方法**展示实验环节、达到的指标与复用条件。每篇附第一作者、通讯作者、英文署名单位、中文摘要及原文 PDF。[两篇历史论文的样刊](试筛/历史论文试筛.md) · [来源与筛选规则](日报规则.md)

## 选择送达方式

| 渠道 | 读者收到的内容 | 部署时需要 |
|---|---|---|
| 邮件 | 一封有分栏的 HTML 简报与论文 PDF 附件，每位读者独立收件。单封附件原始文件累计超过 16 MiB 时，超额论文使用公开 PDF 链接。 | 支持 SMTP 的发件邮箱、应用密码或授权码、收件地址 |
| 飞书群机器人 | 每篇一张卡片，栏目和实验结果显示在卡片顶部，末行直接打开公开 PDF。 | 目标群内创建的自定义机器人 Webhook，可选签名密钥 |

## 部署到 GitHub Actions

1. 将项目放在 GitHub 仓库的默认分支，保留隐藏目录 `.github/`。若使用 fork，请在 Actions 页启用工作流。
2. 打开仓库 **Settings → Secrets and variables → Actions**，在 **Secrets** 添加 `OPENAI_API_KEY`，用于云端检索与摘要，有 API 用量费用。
3. 首批读者默认通过邮件收取 PDF。按下表填写 SMTP 配置与收件地址即可。部署到飞书时，可在 **Variables** 将 `PUSH_CHANNELS` 设置为 `feishu` 或 `email,feishu`。

| 设置位置 | 名称 | 填写内容 |
|---|---|---|
| Variables | SMTP_HOST、SMTP_PORT | 邮件服务商提供的 SMTP 主机和端口。默认 465 使用 TLS，587 使用 STARTTLS。 |
| Secrets | SMTP_USER、SMTP_PASSWORD | 发件邮箱地址及其 SMTP 授权码或应用密码 |
| Secrets | MAIL_TO | 收件邮箱，多个地址用英文逗号隔开 |
| Secrets | FEISHU_WEBHOOK | 在飞书目标群的设置中添加“自定义机器人”，复制其 Webhook |
| Secrets | FEISHU_SECRET | 机器人启用签名校验时填写。若启用关键词校验，请使用标题中固定出现的“离子光钟”。 |

4. 在 **Actions → Ion clock digest → Run workflow** 保留预览选项，运行后下载 Artifacts 中的当期简报和 PDF。取消预览运行一次即可实际投递。北京时间每天 08:00 触发，08:20 再检查当日投递记录；已成功投递时跳过采集和发送。两次调度均由 GitHub 排队。

每次运行会归档当期简报。读者直接从邮件或群聊接收。投递失败时，在原运行上选 **Re-run failed jobs** 可复用已生成的简报；投递记录按期次、收件人或群卡片去重。来源索引与投递记录使用 Actions cache，缓存过期或服务端接受消息后连接中断时可能产生重复。请勿将收件人名单和机器人地址写入仓库。

## 在本机预览或投递

**首次试发**　在 Windows 项目文件夹打开终端，运行 `python -X utf8 test_mail.py`。按提示填写自己的发件邮箱、SMTP 服务器和授权码。程序把两篇历史论文的样刊寄给这个邮箱，授权码仅用于本次进程。QQ 邮箱、163 邮箱和 Gmail 已提供服务器地址默认值。样刊试发无需 OpenAI API 密钥。

使用 Python 3.10 或更新版本。渲染和发送工具只依赖标准库。在项目目录运行：

```sh
python digest.py render "试筛/issue.json" --output "试筛/历史论文试筛.md"
```

本地投递使用与上表同名的环境变量。配置好目标渠道后，以下命令会**实际发送**选定的期次。

```sh
python digest.py send "日报/YYYY-MM-DD/issue.json"
```

本机与云端各自保存投递记录，同一批读者请选择其中一个作为发送端。公开分享此项目时，第三方论文 PDF 可从样刊中的 arXiv 链接获取；正式日报与收件配置保留在各部署环境。
