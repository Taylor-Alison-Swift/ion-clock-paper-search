"""Local reading room for archived issues. Run python viewer.py."""
import argparse
import base64
import hashlib
import json
import re
import shutil
import tempfile
import unicodedata
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "viewer"


def issue_day(issue, fallback=""):
    for value in (issue["title"], issue.get("date", ""), fallback):
        match = re.search(r"\d{4}-\d{2}-\d{2}", str(value))
        if match:
            return date.fromisoformat(match.group()).isoformat()
    return ""


def store_import(issue, attachments=None):
    if not isinstance(issue, dict) or not isinstance(issue.get("title"), str):
        raise ValueError("请选择日报邮件的 issue.json")
    day = issue_day(issue)
    if not day or not isinstance(issue.get("papers"), list):
        raise ValueError("缺少期次日期或论文列表")
    for paper in issue["papers"]:
        if not isinstance(paper, dict) or not isinstance(paper.get("title"), str) or not paper["title"].strip():
            raise ValueError("缺少论文标题")
        rating = paper.get("rating")
        if rating and (not isinstance(rating, dict) or not isinstance(rating.get("score"), (int, float))):
            raise ValueError("相关性分数无效")
        for field in ("pdf_file", "pdf_url", "doi"):
            if paper.get(field) and not isinstance(paper[field], str):
                raise ValueError("附件路径或原文地址无效")
    data = json.dumps(issue, ensure_ascii=False, sort_keys=True).encode()
    folder = ROOT / "日报" / "邮件导入" / day / hashlib.sha256(data).hexdigest()
    folder.mkdir(parents=True, exist_ok=True)
    for relative, content in (attachments or {}).items():
        file = (folder / relative).resolve()
        if not file.is_relative_to(folder.resolve()) or file.suffix.lower() != ".pdf" or not content.startswith(b"%PDF-"):
            raise ValueError("无效的 PDF 附件")
        file.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=file.parent, delete=False) as tmp:
            tmp.write(content)
        Path(tmp.name).replace(file)
    with tempfile.NamedTemporaryFile(dir=folder, delete=False) as tmp:
        tmp.write(data)
    Path(tmp.name).replace(folder / "issue.json")
    return folder


def paper_keys(p):
    keys = {"title:" + " ".join(unicodedata.normalize("NFKC", p["title"]).casefold().split())}
    for field in ("doi", "id", "arxiv_id", "pdf_url"):
        value = str(p.get(field) or "").lower().strip()
        if value.startswith(("10.", "https://doi.org/10.")):
            keys.add(value.removeprefix("https://doi.org/"))
        match = re.search(r"(?:^|arxiv:|arxiv.org/(?:pdf|abs)/)(\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?$", value)
        if match:
            keys.add("arxiv:" + match[1])
    return keys


def catalogue():
    files = sorted((ROOT / "日报").glob("*/issue.json"), reverse=True)
    files = sorted((ROOT / "日报" / "邮件导入").glob("*/*/issue.json")) + files
    files.extend([ROOT / "out" / "issue.json", ROOT / "试筛" / "issue.json"])
    groups, pdfs, aliases = {}, {}, {}
    for path in files:
        if not path.is_file():
            continue
        issue = json.loads(path.read_text(encoding="utf-8-sig"))
        day = issue_day(issue, path.parent.name) or path.parent.name
        group = groups.setdefault(day, {**issue, "papers": [], "date": day})
        index = aliases.setdefault(day, {})
        for p in issue["papers"]:
            p.pop("local_pdf", None)
            if p.get("pdf_file"):
                f = (path.parent / p["pdf_file"]).resolve()
                if f.is_relative_to(path.parent.resolve()) and f.suffix.lower() == ".pdf" and f.is_file():
                    token = hashlib.sha256(str(f).encode()).hexdigest()
                    pdfs["/pdf/" + token] = f
                    p["local_pdf"] = "/pdf/" + token
            keys = paper_keys(p)
            existing = next((index[key] for key in keys if key in index), None)
            if existing is None:
                group["papers"].append(p)
                existing = p
            else:
                for key, value in p.items():
                    if value and not existing.get(key):
                        existing[key] = value
            for key in keys:
                index[key] = existing
    return sorted(groups.values(), key=lambda i: (bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", i["date"])), i["date"]), reverse=True), pdfs


class Reader(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/import" or self.headers.get_content_type() != "application/json":
            self.send_error(400)
            return
        if self.headers.get("Origin") != f"http://127.0.0.1:{self.server.server_port}":
            self.send_error(403)
            return
        try:
            size = int(self.headers.get("Content-Length", 0))
            if not 0 < size <= 32 * 1024 * 1024:
                raise ValueError("附件大小无效")
            payload = json.loads(self.rfile.read(size).decode("utf-8-sig"))
            if not isinstance(payload, dict):
                raise ValueError("无效的期次")
            if "issue" in payload:
                issue = payload["issue"]
                names = {Path(p["pdf_file"]).name: p["pdf_file"] for p in issue["papers"] if p.get("pdf_file")}
                attachments = {names[name]: base64.b64decode(encoded, validate=True)
                               for name, encoded in payload["pdfs"].items()}
                store_import(issue, attachments)
            else:
                store_import(payload)
        except (ValueError, TypeError, KeyError):
            self.send_error(400, "Invalid issue JSON or date")
            return
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        path = urlsplit(self.path).path
        assets = {"/": ("index.html", "text/html"), "/reader.css": ("reader.css", "text/css"),
                  "/reader.js": ("reader.js", "text/javascript")}
        if path in assets:
            file, kind = assets[path]
            body = (STATIC / file).read_bytes()
        elif path == "/issues":
            body = json.dumps(catalogue()[0], ensure_ascii=False).encode()
            kind = "application/json"
        elif path.startswith("/pdf/"):
            pdf = catalogue()[1].get(path)
            if not pdf:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(pdf.stat().st_size))
            self.end_headers()
            with pdf.open("rb") as stream:
                shutil.copyfileobj(stream, self.wfile)
            return
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", kind + "; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    args = argparse.ArgumentParser()
    args.add_argument("--port", type=int, default=8776)
    port = args.parse_args().port
    with ThreadingHTTPServer(("127.0.0.1", port), Reader) as server:
        print(f"http://127.0.0.1:{port}", flush=True)
        server.serve_forever()
