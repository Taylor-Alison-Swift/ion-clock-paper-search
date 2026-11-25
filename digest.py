"""Render and deliver an ion-clock literature issue (Python 3.10+)."""

import argparse
import base64
import hashlib
import hmac
import html
import json
import os
import re
import smtplib
import sqlite3
import ssl
import time
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen
from screen import eligible, settings


SECTIONS = {"core": "核心论文", "method": "可直接用于实验的方法", "update": "正式发表更新"}


def load_issue(path):
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not data["title"].strip() or not isinstance(data["papers"], list):
        raise ValueError("请检查 title 和 papers")
    for paper in data["papers"]:
        if paper["section"] not in SECTIONS:
            raise ValueError("栏目无效")
        for key in ("headline", "title", "first", "affiliations", "source", "summary"):
            if not paper[key].strip():
                raise ValueError(f"论文缺少 {key}")
        if paper["section"] == "method" and not paper.get("application"):
            raise ValueError("方法论文缺少适用条件")
        for key in ("doi", "pdf_url"):
            if paper.get(key):
                url = urlsplit(paper[key])
                if url.scheme != "https" or not url.hostname:
                    raise ValueError(f"{key} 需要公开 HTTPS 地址")
        if not (paper.get("pdf_url") or paper.get("doi")):
            raise ValueError("缺少原文入口")
        if paper.get("pdf_file"):
            root = path.resolve().parent
            file = (root / paper["pdf_file"]).resolve()
            if not file.is_relative_to(root) or file.suffix.lower() != ".pdf":
                raise ValueError("附件必须为当期目录内的 PDF")
            with file.open("rb") as stream:
                if stream.read(5) != b"%PDF-":
                    raise ValueError(f"无效 PDF: {file.name}")
    return data


def paper_lines(p, local=False):
    pdf = "暂未获取"
    if p.get("pdf_url"):
        pdf = f"[{p.get('version') or '全文'}]({p['pdf_url']})"
    elif p.get("doi"):
        pdf += f" · [原文页面]({p['doi']})"
    if local and p.get("pdf_file"):
        pdf += f" · [下载附件]({quote(Path(p['pdf_file']).as_posix())})"
    source = f"[{p['source']}]({p['doi']})" if p.get("doi") else p["source"]
    lines = [p["title"], source, f"第一作者　{p['first']}",
             f"通讯作者　{p.get('corresponding') or '待核实'}",
             f"署名单位　{p['affiliations']}", f"**中文摘要**　{p['summary']}"]
    if p.get("application"):
        lines.append(f"**实验适用条件**　{p['application']}")
    if p.get("rating"):
        r = p["rating"]
        lines.append(f"**相关性 {r['score']:.3f}**　{r['reason']}")
    return lines + [f"**原文 PDF**　{pdf}"]


def markdown(issue, local=False):
    blocks = ["# " + issue["title"]]
    if issue.get("note"):
        blocks.append(issue["note"])
    for key, label in SECTIONS.items():
        papers = [p for p in issue["papers"] if p["section"] == key]
        if papers:
            blocks.append(f"## {label} · {len(papers)} 篇")
        for p in papers:
            blocks += ["### " + p["headline"], *paper_lines(p, local)]
    if not issue["papers"]:
        blocks.append("本期暂无入选论文。")
    return "\n\n".join(blocks) + "\n"


def reader_attachment(issue_json):
    viewer = Path(__file__).resolve().parent / "viewer"
    page = (viewer / "index.html").read_text(encoding="utf-8-sig")
    css = (viewer / "reader.css").read_text(encoding="utf-8-sig")
    script = (viewer / "reader.js").read_text(encoding="utf-8-sig")
    page = page.replace('<link rel="stylesheet" href="/reader.css">', f"<style>{css}</style>")
    page = page.replace('<script defer src="/reader.js"></script>', "")
    # Escape HTML delimiters inside JSON before embedding publisher text.
    data = issue_json.replace("<", "\\u003c")
    return page.replace("</body>", f'<script type="application/json" id="issue-data">{data}</script>'
                        f"<script>{script}</script></body>").encode("utf-8")


def email_message(issue, folder, recipient, sender):
    message = EmailMessage()
    message["Subject"] = issue["title"]
    message["From"] = sender
    message["To"] = recipient
    issue_json = json.dumps(issue, ensure_ascii=False, indent=2)
    reader = reader_attachment(issue_json)
    metadata = issue_json.encode("utf-8")
    body = ("下载附件「当期文献阅读器.html」，用浏览器打开即可阅读。"
            "归档到本地阅读器时，点击「导入邮件日报」，选择 issue.json，也可以同时选择本期 PDF。\n\n" + markdown(issue))
    attachments = []
    # Reserve space for MIME/base64 overhead on a typical 25 MB SMTP server.
    budget = 16 * 1024 * 1024 - len(reader) - len(metadata)
    if budget < 0:
        raise ValueError("阅读页与期次数据已超过单封邮件附件容量")
    for p in issue["papers"]:
        if p.get("pdf_file"):
            file = folder / p["pdf_file"]
            if file.stat().st_size <= budget:
                attachments.append(file)
                budget -= file.stat().st_size
            elif p.get("pdf_url"):
                body += f"\n《{p['title']}》超出本封附件容量，请使用原文 PDF 链接。\n"
            else:
                raise ValueError("超出附件容量的论文需要公开 PDF 链接")
    message.set_content(body)
    parts = []
    for block in body.strip().split("\n\n"):
        line = html.escape(block)
        line = re.sub(r"\[([^\]]+)\]\((https://[^\s)]+)\)", r'<a href="\2">\1</a>', line)
        line = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
        if line.startswith("### "):
            parts.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith("## "):
            parts.append(f'<h2 style="color:#134f59;border-bottom:2px solid">{line[3:]}</h2>')
        elif line.startswith("# "):
            parts.append(f"<h1>{line[2:]}</h1>")
        else:
            parts.append(f"<p>{line}</p>")
    message.add_alternative('<html lang="zh-CN"><body>' + "".join(parts) + "</body></html>",
                            subtype="html")
    message.add_attachment(reader, maintype="text", subtype="html", filename="当期文献阅读器.html",
                           params={"charset": "utf-8"})
    message.add_attachment(metadata, maintype="application", subtype="json", filename="issue.json")
    for file in attachments:
        message.add_attachment(file.read_bytes(), maintype="application", subtype="pdf",
                               filename=file.name)
    return message


def send_email(message):
    host = os.environ["SMTP_HOST"]
    port = int(os.getenv("SMTP_PORT", "465"))
    context = ssl.create_default_context()
    if port == 465:
        connection = smtplib.SMTP_SSL(host, port, timeout=30, context=context)
    else:
        connection = smtplib.SMTP(host, port, timeout=30)
    with connection as smtp:
        if port != 465:
            smtp.starttls(context=context)
        smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        smtp.send_message(message)


def cards(issue):
    for section, label in SECTIONS.items():
        for p in issue["papers"]:
            yield p.get("doi") or p["pdf_url"], {
                "header": {"template": "blue" if section == "core" else "green",
                           "title": {"tag": "plain_text", "content": issue["title"] + "｜" + label}},
                "elements": [{"tag": "markdown", "content": "**" + p["headline"] + "**\n\n" +
                              "\n\n".join(paper_lines(p)) +
                              ("\n\n" + issue["note"] if issue.get("note") else "")}]}
    if not issue["papers"]:
        yield "empty", {"elements": [{"tag": "markdown", "content": markdown(issue)}]}


def post_card(hook, card):
    payload = {"msg_type": "interactive", "card": card}
    secret = os.getenv("FEISHU_SECRET")
    if secret:
        stamp = str(int(time.time()))
        signature = hmac.new(f"{stamp}\n{secret}".encode(), b"", hashlib.sha256)
        payload.update(timestamp=stamp, sign=base64.b64encode(signature.digest()).decode())
    req = Request(hook, data=json.dumps(payload, ensure_ascii=False).encode(),
                  headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=30) as reply:
        result = json.load(reply)
    if result.get("code", result.get("StatusCode")) != 0:
        raise RuntimeError(f"飞书未接受消息，返回码 {result.get('code', result.get('StatusCode'))}")


def deliver_once(db, identity, send):
    key = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()
    with db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM sent WHERE id=?", (key,)).fetchone():
            return False
        send()
        db.execute("INSERT INTO sent VALUES (?)", (key,))
    return True


def pushplus_report(issue):
    body = markdown(issue)
    if len(body) <= 20000:
        return body
    # Keep every paper and its public link within the standard account limit.
    blocks = ["本期篇幅较长，以下按栏目列出全部论文和原文链接。"]
    if issue.get("note"):
        blocks.append(issue["note"])
    for section, label in SECTIONS.items():
        papers = [p for p in issue["papers"] if p["section"] == section]
        if papers:
            blocks.append(f"## {label} · {len(papers)} 篇")
        for p in papers:
            url = p.get("pdf_url") or p["doi"]
            blocks.append(f"- [{p['title']}]({url})")
    body = "\n\n".join(blocks)
    if len(body) > 20000:
        raise ValueError("本期论文目录超过 PushPlus 普通账户单条消息的 2 万字上限")
    return body


def wecom_posts(issue):
    for p in issue["papers"]:
        title = f"{issue['title']}｜{SECTIONS[p['section']]}"
        body = [f"**{p['headline']}**", *paper_lines(p)]
        if issue.get("note"):
            body.insert(0, issue["note"])
        yield p.get("doi") or p["pdf_url"], title, "\n\n".join(body)
    if not issue["papers"]:
        yield "empty", issue["title"], issue.get("note", "") + "\n本期暂无入选论文。"


def send_wechat(channel, destination, title, body):
    if channel == "wechat":
        url = "https://www.pushplus.plus/send"
        payload = {"token": destination, "title": title, "content": body, "template": "markdown"}
        if os.getenv("PUSHPLUS_TOPIC"):
            payload["topic"] = os.environ["PUSHPLUS_TOPIC"]
        status_key, success = "code", 200
    else:
        url = destination
        content = title + "\n\n" + body
        if len(content.encode()) > 4096:
            # Keep the PDF line intact when shortening a long abstract.
            text, _, pdf = content.rpartition("\n\n")
            tail = "\n…\n\n" + pdf
            limit = 4096 - len(tail.encode())
            if limit <= 0:
                raise ValueError("原文链接超出企业微信单条消息长度")
            content = text.encode()[:limit].decode(errors="ignore") + tail
        payload = {"msgtype": "markdown", "markdown": {"content": content}}
        status_key, success = "errcode", 0
    req = Request(url, data=json.dumps(payload, ensure_ascii=False).encode(),
                  headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=30) as response:
        result = json.load(response)
    status = result.get(status_key)
    if status != success:
        detail = str(result.get("msg") or result.get("errmsg") or "平台未提供详情")
        if destination:
            detail = detail.replace(destination, "[已隐藏]")
        detail = " ".join(detail.split())[:300]
        raise RuntimeError(f"{channel} 接口未接受推送，状态码 {status}，{detail}")


def deliver(issue, folder, state):
    channels = {c.strip() for c in os.getenv("PUSH_CHANNELS", "email").split(",") if c.strip()}
    if not channels or channels - {"email", "feishu", "wechat", "wecom"}:
        raise ValueError("PUSH_CHANNELS 支持 email、wechat、wecom、feishu，用逗号分隔")
    state.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(state, timeout=90)
    try:
        db.execute("CREATE TABLE IF NOT EXISTS sent(id TEXT PRIMARY KEY)")
        if "email" in channels:
            recipients = [v.strip() for v in os.environ["MAIL_TO"].split(",") if v.strip()]
            if not recipients:
                raise ValueError("MAIL_TO 为空")
            for address in recipients:
                message = email_message(issue, folder, address, os.environ["SMTP_USER"])
                deliver_once(db, [issue["title"], "email", address],
                             lambda: send_email(message))
        if "feishu" in channels:
            hook = os.environ["FEISHU_WEBHOOK"]
            for paper_id, card in cards(issue):
                deliver_once(db, [issue["title"], "feishu", hook, paper_id],
                             lambda: post_card(hook, card))
                time.sleep(0.25)
        if "wechat" in channels:
            token = os.environ["PUSHPLUS_TOKEN"]
            topic = os.getenv("PUSHPLUS_TOPIC", "")
            deliver_once(db, [issue["title"], "wechat", token, topic, "issue"],
                         lambda: send_wechat("wechat", token, issue["title"], pushplus_report(issue)))
        if "wecom" in channels:
            dest = os.environ["WECOM_WEBHOOK"]
            for key, title, body in wecom_posts(issue):
                sent = deliver_once(db, [issue["title"], "wecom", dest, "", key],
                                    lambda: send_wechat("wecom", dest, title, body))
                if sent:
                    time.sleep(3.1)
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["render", "send"])
    parser.add_argument("issue", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--state", type=Path, default=Path(".state/delivery.sqlite"))
    args = parser.parse_args()
    issue = load_issue(args.issue)
    if args.command == "render":
        output = args.output or args.issue.with_suffix(".md")
        output.write_text(markdown(issue, local=True), encoding="utf-8")
    else:
        threshold = settings()["threshold"]
        if any(not p.get("rating") or not eligible(p["rating"], threshold) for p in issue["papers"]):
            raise ValueError("日报有未评分或低于当前阈值的文章，请先运行筛选核验")
        deliver(issue, args.issue.parent, args.state)


if __name__ == "__main__":
    main()
