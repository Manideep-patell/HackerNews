"""Fetches Hacker News data (official API) and writes data.json + trends.json."""
import json
import re
import html
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.request import urlopen

BASE = "https://hacker-news.firebaseio.com/v0/"
INTEREST = ["ai", "llm", "agent", "agents", "automation", "n8n", "zapier", "india",
            "startup", "saas", "openai", "claude", "python", "api", "workflow"]
TREND_TERMS = ["ai", "llm", "agent", "automation", "n8n",
               "rust", "python", "saas", "openai", "claude", "startup"]
PAIN = ["is there a tool", "i wish", "how do you", "how do i", "struggling", "alternative to",
        "frustrated", "looking for", "anyone else", "recommend", "painful"]
LEAD_KEYS = ["automation", "ai", "llm", "workflow", "n8n",
             "zapier", "remote", "india", "intern", "junior"]


def get(path):
    for _ in range(3):
        try:
            return json.load(urlopen(BASE + path, timeout=15))
        except Exception:
            pass
    return None


cache = {}


def items(ids):
    need = [i for i in ids if i not in cache]
    with ThreadPoolExecutor(16) as ex:
        for i, it in zip(need, ex.map(lambda x: get(f"item/{x}.json"), need)):
            cache[i] = it
    return [cache[i] for i in ids if cache.get(i) and not cache[i].get("dead") and not cache[i].get("deleted")]


def has(text, word):
    return re.search(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])", text.lower()) is not None


def story(it):
    t = it.get("title", "")
    return {"id": it["id"], "title": t, "url": it.get("url") or f"https://news.ycombinator.com/item?id={it['id']}",
            "hn": f"https://news.ycombinator.com/item?id={it['id']}", "score": it.get("score", 0),
            "comments": it.get("descendants", 0), "by": it.get("by", ""), "time": it.get("time", 0),
            "tags": [k for k in INTEREST if has(t, k)]}


def clean(text):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape((text or "").replace("<p>", " ")))).strip()


top, new, best = (get(f"{n}stories.json") or []
                  for n in ("top", "new", "best"))
ask, show, jobs = (get(f"{n}stories.json") or []
                   for n in ("ask", "show", "job"))

# 1. News dashboard
news = [story(i) for i in items(top[:60])]

# 2. Idea validation: Ask/Show posts scored by engagement + pain phrases
ideas = []
for it in items(ask[:60] + show[:60]):
    s = story(it)
    body = clean(it.get("text", ""))
    hits = [p for p in PAIN if p in (s["title"] + " " + body).lower()]
    s.update(kind="Ask HN" if it["id"] in ask else "Show HN", pain=hits,
             idea_score=s["score"] + 2 * s["comments"] + 15 * len(hits), snippet=body[:240])
    ideas.append(s)
ideas = sorted(ideas, key=lambda x: -x["idea_score"])[:30]

# 3a. Job posts
job_list = []
for it in items(jobs[:40]):
    s = story(it)
    s["snippet"] = clean(it.get("text", ""))[:240]
    job_list.append(s)

# 3b. Leads from latest "Who is hiring?" thread
leads = []
sub = (get("user/whoishiring.json") or {}).get("submitted", [])[:12]
thread = next(
    (t for t in items(sub) if "who is hiring" in t.get("title", "").lower()), None)
if thread:
    for c in items(thread.get("kids", [])[:400]):
        text = clean(c.get("text", ""))
        keys = [k for k in LEAD_KEYS if has(text, k)]
        if len(keys) >= 2:
            leads.append({"id": c["id"], "hn": f"https://news.ycombinator.com/item?id={c['id']}",
                          "text": text[:400], "keys": keys,
                          "emails": sorted(set(re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", text))),
                          "links": sorted(set(re.findall(r"https?://[^\s)\"<]+", text)))[:3]})
    leads.sort(key=lambda x: (-len(x["emails"]), -len(x["keys"])))
    leads = leads[:50]

# 4. Trend tracking: keyword mentions in titles across top/new/best
pool = items(list(dict.fromkeys(top[:100] + new[:100] + best[:100])))
counts = {k: sum(1 for it in pool if has(it.get("title", ""), k))
          for k in TREND_TERMS}
today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
trends = json.load(open("trends.json")) if os.path.exists(
    "trends.json") else {}
trends[today] = {"sample": len(pool), **counts}
trends = dict(sorted(trends.items())[-365:])

json.dump(trends, open("trends.json", "w"), indent=1)
json.dump({"updated": datetime.now(timezone.utc).isoformat(timespec="minutes"), "thread": thread and thread.get("title"),
           "news": news, "ideas": ideas, "jobs": job_list, "leads": leads}, open("data.json", "w"))
print(f"news={len(news)} ideas={len(ideas)} jobs={len(job_list)} leads={len(leads)} trend_sample={len(pool)}")
