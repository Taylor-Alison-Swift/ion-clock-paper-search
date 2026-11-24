"""交互式寄送项目样刊到发件人自己的邮箱。"""

import getpass
import os
from pathlib import Path

from digest import deliver, load_issue


def main():
    folder = Path(__file__).resolve().parent
    sample = folder / "试筛" / "issue.json"
    issue = load_issue(sample)
    sender = input("发件邮箱（样刊将发给这个地址）：").strip()
    if "@" not in sender:
        raise SystemExit("请输入完整邮箱地址。")
    domain = sender.rsplit("@", 1)[1].lower()
    known_hosts = {"qq.com": "smtp.qq.com", "163.com": "smtp.163.com",
                   "gmail.com": "smtp.gmail.com"}
    default = known_hosts.get(domain, "")
    hint = f"，回车使用 {default}" if default else ""
    host = input(f"SMTP 服务器{hint}：").strip() or default
    if not host:
        raise SystemExit("请填写邮件服务商提供的 SMTP 服务器地址。")
    port = input("SMTP 端口（回车使用 465，也支持 587）：").strip() or "465"
    password = getpass.getpass("SMTP 授权码或应用密码（输入时隐藏）：")
    os.environ.update(PUSH_CHANNELS="email", MAIL_TO=sender, SMTP_USER=sender,
                      SMTP_HOST=host, SMTP_PORT=port, SMTP_PASSWORD=password)
    deliver(issue, sample.parent, folder / ".state" / "sample-delivery.sqlite")
    print("样刊已提交给邮件服务器或此前已提交，请在收件箱和垃圾邮件文件夹查看。")


if __name__ == "__main__":
    main()
