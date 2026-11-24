"""Local reading room for archived issues. Run python viewer.py."""
import argparse
import hashlib
import json
import re
import shutil
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "viewer"


def catalogue():
    files = sorted((ROOT / "日报").glob("*/issue.json"), reverse=True)
    files.extend([ROOT / "out" / "issue.json", ROOT / "试筛" / "issue.json"])
    issues, pdfs, seen = [], {}, set()
    for path in files:
        if not path.is_file():
            continue
        issue = json.loads(path.read_text(encoding="utf-8-sig"))
        if issue["title"] in seen:
            continue
        seen.add(issue["title"])
        issue["date"] = path.parent.name
        if path.parent.name == "out":
            date = re.search(r"\d{4}-\d{2}-\d{2}", issue["title"])
            issue["date"] = date.group() if date else issue["title"]
        for p in issue["papers"]:
            p.pop("local_pdf", None)
            if p.get("pdf_file"):
                f = (path.parent / p["pdf_file"]).resolve()
                if f.is_relative_to(path.parent.resolve()) and f.suffix.lower() == ".pdf" and f.is_file():
                    token = hashlib.sha256(str(f).encode()).hexdigest()
                    pdfs["/pdf/" + token] = f
                    p["local_pdf"] = "/pdf/" + token
        issues.append(issue)
    return issues, pdfs


class Reader(BaseHTTPRequestHandler):
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
