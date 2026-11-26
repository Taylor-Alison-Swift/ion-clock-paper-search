"""Import available GitHub digest artifacts into the local reading archive."""
import hashlib
import json
import re
import tempfile
import zipfile
from urllib.request import Request, urlopen

from viewer import ROOT, store_import


REPO = "Taylor-Alison-Swift/ion-clock-paper-search"


def sync():
    archive = ROOT / "日报" / "邮件导入"
    receipts = {p.name for p in archive.glob("*/*/github-*.receipt")
                if (p.parent / "issue.json").is_file()}
    page = 1
    imported = 0
    while True:
        url = f"https://api.github.com/repos/{REPO}/actions/artifacts?per_page=100&page={page}"
        with urlopen(Request(url, headers={"User-Agent": "ion-clock-paper-reader"}), timeout=30) as response:
            artifacts = json.load(response)["artifacts"]
        for artifact in artifacts:
            receipt = f"github-{artifact['id']}.receipt"
            if artifact["expired"] or receipt in receipts or not re.fullmatch(r"digest-\d+-\d+", artifact["name"]):
                continue
            url = f"https://nightly.link/{REPO}/actions/artifacts/{artifact['id']}.zip"
            with tempfile.TemporaryFile() as tmp, urlopen(url, timeout=60) as response:
                sha = hashlib.sha256()
                while chunk := response.read(1024 * 1024):
                    sha.update(chunk)
                    tmp.write(chunk)
                if artifact.get("digest") and artifact["digest"] != "sha256:" + sha.hexdigest():
                    raise ValueError(f"GitHub artifact {artifact['id']} hash mismatch")
                with zipfile.ZipFile(tmp) as z:
                    issue = json.loads(z.read("issue.json"))
                    pdfs = {p["pdf_file"]: z.read(p["pdf_file"]) for p in issue["papers"] if p.get("pdf_file")}
            folder = store_import(issue, pdfs)
            (folder / receipt).touch()
            imported += 1
        if len(artifacts) < 100:
            return imported
        page += 1


if __name__ == "__main__":
    print(f"新同步云端日报 {sync()} 份")
