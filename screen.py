"""Keyword shortlist and deterministic validation of GPT relevance assessments."""
import argparse
import html
import json
import os
import re
import unicodedata
from pathlib import Path


CONFIG = Path(__file__).with_name("screening.json")


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def settings():
    cfg = read(CONFIG)
    threshold = float(os.getenv("RELEVANCE_THRESHOLD") or cfg["threshold"])
    if not 0 <= threshold <= 1:
        raise ValueError("阈值必须在 0 和 1 之间")
    cfg["threshold"] = threshold
    return cfg


def normalize(s):
    s = unicodedata.normalize("NFKC", html.unescape(s)).casefold()
    s = re.sub(r"<[^>]+>|[{}^$]", "", s)
    return " ".join(re.sub(r"[-‐‑–—]", " ", s).split())


def match(text, terms):
    for term in terms:
        word = normalize(term)
        # Allow isotope prefixes (171Yb+) and plural nouns, retain the charge.
        if re.search(r"(?<![a-z])" + re.escape(word) + r"s?(?![a-z])", text):
            return term
    return ""


def shortlist(records, cfg):
    result = []
    ids = set()
    for record in records:
        key = record["id"]
        if not key or key in ids or not record["title"].strip():
            raise ValueError(f"候选记录缺 id、标题或 id 重复：{key}")
        ids.add(key)
        text = normalize(record["title"] + " " + record.get("abstract", ""))
        hit = match(text, cfg["direct"])
        for a, b in (("platform", "measurement"), ("optics", "metrology")):
            if hit:
                break
            first, second = match(text, cfg[a]), match(text, cfg[b])
            if first and second:
                hit = first + " + " + second
        if hit:
            result.append({**record, "keyword_match": hit})
    return result


def score(rating):
    for field in ("fit", "contribution", "evidence"):
        value = rating[field]
        if type(value) is not int or not 0 <= value <= 4:
            raise ValueError(f"{field} 必须是 0 至 4 的整数")
    if rating["track"] not in {"core", "method", "background", "pending"}:
        raise ValueError("评分分类无效")
    if not rating["reason"].strip():
        raise ValueError("缺少评分依据")
    return (5 * rating["fit"] + 3 * rating["contribution"] + 2 * rating["evidence"]) / 40


def eligible(rating, threshold):
    total = score(rating)
    return (rating["track"] in {"core", "method"} and rating["evidence"] > 0
            and total >= threshold)


def select(candidates, ratings, cfg):
    shortlisted = shortlist(candidates, cfg)
    by_id = {r["id"]: r for r in ratings}
    if len(by_id) != len(ratings) or set(by_id) != {p["id"] for p in shortlisted}:
        raise ValueError("每篇通过关键词的候选必须恰有一份评分")
    selected = {}
    for p in shortlisted:
        r = by_id[p["id"]]
        if eligible(r, cfg["threshold"]):
            quote = normalize(r["quote"])
            source = normalize(" ".join(p.get(k, "") for k in ("title", "abstract", "excerpt")))
            if not quote or quote not in source:
                raise ValueError(f"入选依据需要候选原文逐字引句：{p['id']}")
            selected[p["id"]] = {**r, "score": score(r), "keyword_match": p["keyword_match"]}
    return selected


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=("shortlist", "select", "verify"))
    ap.add_argument("folder", type=Path, help="包含 candidates.json、ratings.json 和 issue.json 的目录")
    args = ap.parse_args()
    folder, cfg = args.folder, settings()
    records = read(folder / "candidates.json")
    if args.stage == "shortlist":
        result = {"research_direction": cfg["research_direction"], "threshold": cfg["threshold"],
                  "track_criteria": cfg["track_criteria"],
                  "papers": shortlist(records, cfg)}
    else:
        result = select(records, read(folder / "ratings.json"), cfg)
    if args.stage == "verify":
        issue = read(folder / "issue.json")
        ids = [p["id"] for p in issue["papers"]]
        if set(ids) != set(result) or len(set(ids)) != len(ids):
            raise ValueError("日报必须与过线名单逐篇一致")
        sources = {record["id"]: record for record in records}
        for p in issue["papers"]:
            rating = result[p["id"]]
            if p["section"] not in {rating["track"], "update"}:
                raise ValueError("日报栏目与评分分类不符")
            p["rating"] = rating
            for field in ("abstract", "fetched_date", "published_date", "arxiv_id", "categories"):
                if sources[p["id"]].get(field):
                    p[field] = sources[p["id"]][field]
        issue["threshold"] = cfg["threshold"]
        result, filename = issue, "issue.json"
    else:
        filename = args.stage + ".json"
    out = folder / filename
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(out)


if __name__ == "__main__":
    main()
