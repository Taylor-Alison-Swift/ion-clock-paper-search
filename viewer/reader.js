"use strict";
const $ = selector => document.querySelector(selector);
const labels = {core:"核心论文", method:"可直接用于实验的方法", update:"正式发表更新"};
const dayPattern = /^\d{4}-\d{2}-\d{2}$/;
let issues = [];
let saved = new Set();
try { saved = new Set(JSON.parse(localStorage.getItem("ion-clock-favorites") || "[]")); } catch {}
const paperKey = p => p.doi || p.pdf_url || p.title;
function dayOf(p, issue, dimension) {
  const value = p[dimension];
  if (dayPattern.test(value)) return value;
  return dimension === "fetched_date" && dayPattern.test(issue.date) ? issue.date : "";
}
function link(parent, label, url) {
  if (!url || !(url.startsWith("https://") || /^\/pdf\/[0-9a-f]{64}$/.test(url))) return;
  const a = document.createElement("a");
  a.textContent = label; a.href = url; a.target = "_blank"; a.rel = "noopener noreferrer"; parent.append(a);
}
function article(p, issue) {
  const el = $("#paper").content.firstElementChild.cloneNode(true);
  function set(selector, text) {
    const node = el.querySelector(selector);
    node.textContent = text || ""; node.hidden = !text;
  }
  const arxiv = p.arxiv_id || (p.pdf_url || "").match(/arxiv\.org\/(?:pdf|abs)\/([\w./-]+)/i)?.[1];
  set(".identifier", arxiv?.replace(/\.pdf$/i, ""));
  set("h2", p.title);
  set(".dates-line", "抓取："+(dayOf(p,issue,"fetched_date") || "待核实")+"　|　发表："+(dayOf(p,issue,"published_date") || "待核实"));
  set(".byline","第一作者："+p.first+"　·　通讯作者："+(p.corresponding || "待核实"));
  const categories = Array.isArray(p.categories) ? p.categories : [];
  const relevance = Number.isFinite(p.rating?.score) ? "相关性 "+p.rating.score.toFixed(2) : "";
  for (const text of [labels[p.section],p.source,relevance,...categories].filter(Boolean)) {
    const tag = document.createElement("span");
    tag.textContent = text;
    if (text === p.source) {
      tag.className = "journal";
      tag.title = text;
    }
    el.querySelector(".tags").append(tag);
  }
  set(".affiliation",p.affiliations); set(".summary",p.summary);
  set(".application",p.application && "实验适用条件　"+p.application);
  el.querySelector(".abstract").hidden = !p.abstract;
  set(".abstract p",p.abstract);
  el.querySelector(".rating").hidden = !p.rating;
  if (p.rating) {
    set(".rating summary","评分依据");
    set(".rating p",p.rating.reason+"　"+(p.rating.quote || ""));
  }
  const links = el.querySelector(".links");
  link(links,p.local_pdf ? "本地 PDF" : "公开 PDF",p.local_pdf || p.pdf_url);
  if (p.local_pdf) link(links,"公开 PDF",p.pdf_url);
  if (!p.local_pdf && !p.pdf_url) links.append("暂未获取");
  link(links,"期刊原文",p.doi);
  const id = paperKey(p), button = el.querySelector(".save");
  button.textContent = saved.has(id) ? "★ 已收藏" : "☆ 收藏";
  button.setAttribute("aria-pressed",saved.has(id));
  button.setAttribute("aria-label",button.textContent+" "+p.title);
  button.onclick = () => {
    if (saved.has(id)) saved.delete(id); else saved.add(id);
    try { localStorage.setItem("ion-clock-favorites",JSON.stringify([...saved])); } catch {}
    render();
  };
  return el;
}
function render() {
  const list = $("#list"), query = $("#query").value.toLowerCase().trim();
  const start = $("#start").value, end = $("#end").value, field = $("#dimension").value;
  $("#end").setCustomValidity(start && end && end < start ? "结束日期不能早于开始日期" : "");
  if (!$("#end").checkValidity()) { $("#end").reportValidity(); return; }
  list.replaceChildren(); $("#notes").replaceChildren();
  let total = 0, favorites = 0;
  for (const issue of issues) {
    const currentIssue = !$("#issue").value || $("#issue").value === issue.title;
    for (const p of issue.papers) {
      total++;
      const isSaved = saved.has(paperKey(p));
      if (isSaved) favorites++;
      const day = dayOf(p,issue,field);
      if (!currentIssue || (start && (!day || day < start)) || (end && (!day || day > end))) continue;
      if ($("#saved").checked && !isSaved) continue;
      if ($("#section").value && p.section !== $("#section").value) continue;
      const fields = [p.title,p.headline,p.summary,p.abstract,p.application,p.first,p.corresponding,p.affiliations,p.source,p.arxiv_id,p.doi];
      if (!fields.join(" ").toLowerCase().includes(query)) continue;
      list.append(article(p,issue));
    }
    if ($("#issue").value === issue.title && issue.note) $("#notes").textContent = issue.note;
  }
  $("#status").textContent = "共 "+total+" 篇，收藏 "+favorites+" 篇，当前展示 "+list.childElementCount+" 篇（按"+$("#dimension").selectedOptions[0].text+"筛选）";
  if (!list.childElementCount) $("#list").textContent = "当前筛选条件下暂无论文。";
}
function markShortcut(days) {
  document.querySelectorAll("#quick button").forEach(b => b.setAttribute("aria-pressed",b.dataset.days === days));
}
$("#quick").onclick = event => {
  const days = event.target.dataset.days;
  if (days === undefined) return;
  const today = new Intl.DateTimeFormat("sv-SE",{timeZone:"Asia/Shanghai",year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date());
  const first = new Date(today+"T00:00:00Z");
  first.setUTCDate(first.getUTCDate() - Number(days) + 1);
  $("#start").value = Number(days) ? first.toISOString().slice(0,10) : "";
  $("#end").value = Number(days) ? today : "";
  markShortcut(days); render();
};
$("#filters").onsubmit = event => { event.preventDefault(); render(); };
$("#filters").onreset = () => { setTimeout(() => { markShortcut("0"); render(); },0); };
$("#filters").oninput = event => {
  if (["start","end"].includes(event.target.id)) markShortcut("");
  render();
};
const embeddedIssue = document.getElementById("issue-data");
const catalogue = embeddedIssue ? Promise.resolve().then(() => [JSON.parse(embeddedIssue.textContent)]) : fetch("/issues").then(response => {
  if (!response.ok) throw Error(); return response.json();
});
catalogue.then(data => {
  issues = data;
  const dates = [];
  let total = 0;
  for (const issue of issues) {
    $("#issue").add(new Option(issue.date || issue.title, issue.title));
    for (const p of issue.papers) {
      const day = dayOf(p,issue,"fetched_date"); if (day) dates.push(day);
      total++;
    }
  }
  dates.sort();
  if (embeddedIssue && issues.length === 1) $("#issue").value = issues[0].title;
  $("#coverage").textContent = "收录 "+total+" 篇"+(dates.length ? " | 抓取区间 "+dates[0]+" ～ "+dates.at(-1) : "");
  markShortcut("0"); render();
}).catch(() => { $("#status").textContent = "读取失败，请刷新重试。"; });
