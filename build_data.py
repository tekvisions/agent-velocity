#!/usr/bin/env python3
"""StackTracker data builder.

Fetches REAL GitHub signals for each curated AI-infra repo and computes a
momentum score (0-100) from commit velocity + release recency + trend.
No fabricated numbers — every value traces to a GitHub API response.

Auth: reads GITHUB_TOKEN from env (GitHub Actions provides it). Falls back to
`gh auth token` for local runs. Writes data.json next to this script.

The `stars_history` is appended to on every run (the prior data.json is read
back in), so the star sparkline builds a real day-over-day series over time.
"""
from __future__ import annotations
import json, os, re, subprocess, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
API = "https://api.github.com"
SITE = "https://agentvelocity.kymatalabs.com"


def token() -> str:
    t = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if t:
        return t.strip()
    try:
        return subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return ""


TOKEN = token()
HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": "stacktracker"}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"


def gh(path: str, *, retries: int = 4):
    """GET a GitHub API path. Returns (status, json|None). Handles 202 (stats
    still computing) with backoff, and 404 (no release) without raising."""
    url = API + path
    for attempt in range(retries):
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                if r.status == 202:  # stats being computed server-side
                    time.sleep(2 + attempt * 2)
                    continue
                return r.status, json.loads(r.read() or "null")
        except urllib.error.HTTPError as e:
            if e.code == 202:
                time.sleep(2 + attempt * 2)
                continue
            if e.code == 404:
                return 404, None
            if e.code in (403, 429):  # rate limit — back off once
                time.sleep(5)
                continue
            return e.code, None
        except Exception:
            time.sleep(1)
    return 0, None


def commit_count(full: str, since_iso: str, until_iso: str | None = None) -> int:
    """Reliable commit count in a window via the commits endpoint's Link header
    (per_page=1 → last-page number == commit count). No 202, fast. Caps at 500."""
    q = f"/repos/{full}/commits?per_page=1&since={since_iso}"
    if until_iso:
        q += f"&until={until_iso}"
    url = API + q
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            link = r.headers.get("Link", "") or ""
            body = json.loads(r.read() or "[]")
    except urllib.error.HTTPError as e:
        return 0
    except Exception:
        return 0
    if 'rel="last"' in link:
        import re
        for part in link.split(","):
            if 'rel="last"' in part:
                m = re.search(r"[?&]page=(\d+)", part)
                if m:
                    return min(int(m.group(1)), 3000)
    return len(body) if isinstance(body, list) else 0


def days_since(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0
    except Exception:
        return None


def momentum(recent4: int, prior4: int, days_release: float | None) -> int:
    """Momentum 0-100 from real commit velocity + release recency + trend.
    recent4 = commits in last 28d, prior4 = commits in the prior 28d."""
    # activity: 400 commits / 28d ≈ very hot
    act = min(recent4 / 400.0, 1.0)
    # release recency: <30d full, decays to 0 by 270d; no release → low floor
    if days_release is None:
        rel = 0.2
    else:
        rel = max(0.0, 1.0 - max(0.0, days_release - 30) / 240.0)
    # trend: ratio of recent vs prior, centered at 0.5 (flat)
    if prior4 > 0:
        tr = min(max((recent4 - prior4) / prior4 * 0.5 + 0.5, 0.0), 1.0)
    else:
        tr = 0.7 if recent4 > 0 else 0.5
    score = round(100 * (0.55 * act + 0.25 * rel + 0.20 * tr))
    return max(0, min(100, score))


# ─────────────────────────  STATIC DETAIL PAGES  ─────────────────────────
def slugify(s: str) -> str:
    """lowercase url-safe slug; MUST match app.js slugify()."""
    return re.sub(r"^-+|-+$", "", re.sub(r"[^a-z0-9]+", "-", str(s or "").lower()))


def repo_slug(r: dict) -> str:
    return slugify(f"{r.get('owner','')}-{r.get('name','')}")


def _esc(s) -> str:
    s = "" if s is None else str(s)
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;").replace("'", "&#39;"))


def _fmt_stars(n: int) -> str:
    n = int(n or 0)
    if n >= 10000:
        return f"{n/1000:.0f}k"
    if n >= 1000:
        return f"{n/1000:.1f}".rstrip("0").rstrip(".") + "k"
    return str(n)


def _rel_date(iso: str | None) -> str:
    d = days_since(iso)
    if d is None:
        return "—"
    if d < 1:
        return "today"
    if d < 2:
        return "1d ago"
    if d < 30:
        return f"{round(d)}d ago"
    if d < 365:
        return f"{round(d/30)}mo ago"
    return f"{round(d/365)}y ago"


def _spark_svg(arr, w=720, h=160) -> str:
    """Larger monthly-commits sparkline for the detail page."""
    arr = [int(x or 0) for x in (arr or [])]
    if len(arr) < 2:
        return '<svg viewBox="0 0 %d %d" preserveAspectRatio="none" aria-hidden="true"></svg>' % (w, h)
    mx, mn = max(arr), min(arr)
    rg = (mx - mn) or 1
    n = len(arr)
    pad = 6
    def pt(i, v):
        x = pad + i * (w - 2 * pad) / (n - 1)
        y = h - pad - (v - mn) / rg * (h - 2 * pad)
        return f"{x:.1f},{y:.1f}"
    line = " ".join(pt(i, v) for i, v in enumerate(arr))
    area = f"{pad:.1f},{h-pad:.1f} " + line + f" {w-pad:.1f},{h-pad:.1f}"
    lx, ly = (w - pad), (h - pad - (arr[-1] - mn) / rg * (h - 2 * pad))
    return (
        f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="none" role="img" aria-label="Monthly commit trend, last 6 months">'
        f'<defs><linearGradient id="avfill" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="#ff4324" stop-opacity="0.28"/>'
        f'<stop offset="1" stop-color="#ff4324" stop-opacity="0"/></linearGradient></defs>'
        f'<polygon points="{area}" fill="url(#avfill)"/>'
        f'<polyline points="{line}" fill="none" stroke="#ff8a2b" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"/>'
        f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="4" fill="#ff4324"/></svg>'
    )


def _badge_svg(r: dict) -> str:
    """shields.io-style embeddable rank badge. Left label "Agent Velocity",
    right "#<rank>" in the app's hot ember; appends "▲N" when the repo climbed
    (rank_delta > 0). Self-contained, theme-neutral, accessible (role/title).
    Character-width estimation keeps the right pill snug without a web font."""
    rank = r.get("rank")
    rank_txt = f"#{rank}" if isinstance(rank, int) else "#—"
    delta = r.get("rank_delta")
    if isinstance(delta, int) and delta > 0:
        rank_txt = f"{rank_txt} ▲{delta}"
    label = "Agent Velocity"
    name = r.get("name", "") or r.get("repo", "")
    # ~6px per char @ 11px DM-Mono-ish; +pad. Stable, no font metrics needed.
    lw = len(label) * 6 + 18
    rw = len(rank_txt) * 6 + 18
    total = lw + rw
    title = f"Agent Velocity — {_esc(name)} ranked {rank_txt}"
    # unique gradient id per badge — guards against id collision if multiple badges
    # are ever inlined together on a third-party page (img-embeds are already isolated)
    gid = f"av{slugify(r.get('repo','') or name) or 'badge'}"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total}" height="20" '
        f'role="img" aria-label="{title}">'
        f'<title>{title}</title>'
        f'<linearGradient id="{gid}" x2="0" y2="100%">'
        f'<stop offset="0" stop-color="#fff" stop-opacity=".12"/>'
        f'<stop offset="1" stop-opacity=".12"/></linearGradient>'
        f'<rect rx="3" width="{total}" height="20" fill="#1b1622"/>'
        f'<rect rx="3" x="{lw}" width="{rw}" height="20" fill="#ff4324"/>'
        f'<rect rx="3" width="{total}" height="20" fill="url(#{gid})"/>'
        f'<g fill="#fff" text-anchor="middle" '
        f'font-family="Verdana,DejaVu Sans,Geneva,sans-serif" font-size="11">'
        f'<text x="{lw/2:.0f}" y="14">{label}</text>'
        f'<text x="{lw + rw/2:.0f}" y="14" font-weight="bold">{_esc(rank_txt)}</text>'
        f'</g></svg>'
    )


def generate_badges(data: dict) -> int:
    """Write a static /badge/<slug>.svg per repo (mirrors detail-page generation).
    Static-deployable: no serverless needed; the daily build refreshes each badge."""
    repos = data.get("repos", [])
    b_dir = os.path.join(HERE, "badge")
    os.makedirs(b_dir, exist_ok=True)
    written = 0
    for r in repos:
        slug = repo_slug(r)
        with open(os.path.join(b_dir, f"{slug}.svg"), "w") as f:
            f.write(_badge_svg(r))
        written += 1
    print(f"  generated {written} rank badges in /badge/", file=sys.stderr)
    return written


def generate_feed(data: dict) -> None:
    """Write feed.json — a small, documented, stable-schema public API subset of
    the board (read-only data already public on the page; no secrets)."""
    repos = sorted(data.get("repos", []), key=lambda x: x.get("rank", 999))
    feed = {
        "$schema_version": "1",
        "generator": "Agent Velocity (Kymata Labs)",
        "generated_at": data.get("generated_at"),
        "site": SITE,
        "docs": f"{SITE}/#how",
        "license": "Data derived from the public GitHub REST API; attribution to Agent Velocity (kymatalabs.com) appreciated.",
        "count": len(repos),
        "repos": [
            {
                "rank": r.get("rank"),
                "name": r.get("name"),
                "owner": r.get("owner"),
                "category": r.get("category"),
                "momentum": r.get("momentum"),
                "stars": r.get("stars"),
                "rank_delta": r.get("rank_delta"),
                "url": f"{SITE}/a/{repo_slug(r)}/",
                "badge": f"{SITE}/badge/{repo_slug(r)}.svg",
            }
            for r in repos
        ],
        "movers": data.get("movers", []),
    }
    with open(os.path.join(HERE, "feed.json"), "w") as f:
        json.dump(feed, f, indent=2)
    print(f"  wrote feed.json: {len(repos)} repos", file=sys.stderr)


def generate_rss(data: dict) -> None:
    """Write rss.xml — the current velocity board (top 30) as a subscribable RSS 2.0
    feed. Stable per-entry guids (detail URLs); pubDate = the board's daily refresh.
    Additive, read-only public data (PRD O7)."""
    from email.utils import format_datetime
    repos = sorted(data.get("repos", []), key=lambda x: x.get("rank", 999))[:30]
    gen_iso = data.get("generated_at")
    try:
        dt = datetime.fromisoformat(gen_iso) if gen_iso else datetime.now(timezone.utc)
    except (TypeError, ValueError):
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    rfc = format_datetime(dt)
    title = "Agent Velocity — the open-source coding-agent race"
    desc = ("The live leaderboard of open-source coding agents — ranked by real GitHub "
            "shipping velocity, recomputed daily by autonomous agents.")
    items = []
    for r in repos:
        url = f"{SITE}/a/{repo_slug(r)}/"
        rank, mom, cat = r.get("rank"), r.get("momentum"), r.get("category")
        rd = r.get("rank_delta")
        move = f" ▲{rd}" if isinstance(rd, int) and rd > 0 else (
               f" ▼{abs(rd)}" if isinstance(rd, int) and rd < 0 else "")
        ttl = f"#{rank} {r.get('name')} — velocity {mom}"
        body = f"#{rank} · velocity {mom}/100 · {cat}{move} · {r.get('stars')} stars"
        items.append(
            "    <item>\n"
            f"      <title>{_esc(ttl)}</title>\n"
            f"      <link>{_esc(url)}</link>\n"
            f'      <guid isPermaLink="true">{_esc(url)}</guid>\n'
            f"      <category>{_esc(cat)}</category>\n"
            f"      <description>{_esc(body)}</description>\n"
            f"      <pubDate>{rfc}</pubDate>\n"
            "    </item>")
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        "  <channel>\n"
        f"    <title>{_esc(title)}</title>\n"
        f"    <link>{SITE}</link>\n"
        f'    <atom:link href="{SITE}/rss.xml" rel="self" type="application/rss+xml"/>\n'
        f"    <description>{_esc(desc)}</description>\n"
        "    <language>en</language>\n"
        f"    <lastBuildDate>{rfc}</lastBuildDate>\n"
        "    <generator>Kymata Labs</generator>\n"
        + "\n".join(items) + "\n"
        "  </channel>\n</rss>\n")
    with open(os.path.join(HERE, "rss.xml"), "w") as f:
        f.write(xml)
    print(f"  wrote rss.xml: {len(items)} items", file=sys.stderr)


def _months_ago_label(i: int, n: int) -> str:
    """Label for bucket i (0=oldest) in an n-bucket series of 30-day windows."""
    back = n - 1 - i
    if back == 0:
        return "now"
    return f"−{back}mo"


def _commit_bars(arr) -> str:
    """Labeled monthly-commit bar chart for the detail page. Each ~30d bucket gets
    a bar (height ∝ commits) + the real count + a months-ago label. The final bar
    (this month) is highlighted as the velocity input."""
    arr = [int(x or 0) for x in (arr or [])]
    n = len(arr)
    if n < 2:
        return ""
    mx = max(arr) or 1
    bars = []
    for i, v in enumerate(arr):
        pct = max(2, round(v / mx * 100))
        last = i == n - 1
        cls = "cb-bar cb-now" if last else "cb-bar"
        cap = f"{v:,}" if v >= 1000 else str(v)
        bars.append(
            f'<div class="cb-col" title="{cap} commits · {_months_ago_label(i,n)}">'
            f'<span class="cb-val">{cap}</span>'
            f'<div class="cb-track"><i class="{cls}" style="height:{pct}%"></i></div>'
            f'<span class="cb-x">{_months_ago_label(i,n)}</span></div>'
        )
    return '<div class="commitbars" role="img" aria-label="Monthly commit counts, last 6 months">' + "".join(bars) + "</div>"


def _velocity_components(r: dict) -> dict:
    """Reconstruct the EXACT momentum() sub-scores so the detail page can show the
    math. Mirrors momentum() in this file — keep in sync if the formula changes."""
    recent4 = int(r.get("recent4w_commits", 0) or 0)
    prior4 = int(r.get("prior4w_commits", 0) or 0)
    d_rel = days_since(r.get("last_release_at"))
    act = min(recent4 / 400.0, 1.0)
    if d_rel is None:
        rel = 0.2
    else:
        rel = max(0.0, 1.0 - max(0.0, d_rel - 30) / 240.0)
    if prior4 > 0:
        tr = min(max((recent4 - prior4) / prior4 * 0.5 + 0.5, 0.0), 1.0)
    else:
        tr = 0.7 if recent4 > 0 else 0.5
    return {
        "act": act, "rel": rel, "tr": tr,
        "act_pts": 0.55 * act * 100, "rel_pts": 0.25 * rel * 100, "tr_pts": 0.20 * tr * 100,
        "recent4": recent4, "prior4": prior4, "d_rel": d_rel,
    }


def _score_rows(r: dict) -> str:
    """Three weighted-component rows (cadence / release / trend) that visibly sum
    to the velocity score. Every number is derived from real GitHub signals."""
    c = _velocity_components(r)
    recent4, prior4 = c["recent4"], c["prior4"]
    # cadence detail
    cad_detail = f"{recent4:,} commits in the last 4 weeks (saturates at 400)"
    # release detail
    if c["d_rel"] is None:
        rel_detail = "no stable GitHub release — scored at the floor"
    else:
        days = int(round(c["d_rel"]))
        rel_detail = f"last release {days}d ago (full credit ≤30d, fades to 0 by 270d)"
    # trend detail
    if prior4 > 0:
        diff = recent4 - prior4
        sign = "+" if diff >= 0 else "−"
        rel_pct = abs(diff) / prior4 * 100
        tr_detail = f"{sign}{abs(diff):,} vs prior 4 weeks ({sign}{rel_pct:.0f}%)"
    else:
        tr_detail = "no commits in the prior window to compare"

    def row(label, weight, sub01, pts, detail):
        meter = round(sub01 * 100)
        return (
            '<div class="sc-row">'
            f'<div class="sc-head"><span class="sc-name">{label}</span>'
            f'<span class="sc-weight">{weight}% weight</span></div>'
            f'<div class="sc-meter"><i style="width:{meter}%"></i></div>'
            f'<div class="sc-foot"><span class="sc-detail">{detail}</span>'
            f'<span class="sc-pts">+{pts:.0f} pts</span></div>'
            '</div>'
        )
    mom = int(r.get("momentum", 0) or 0)
    return (
        row("Commit cadence", 55, c["act"], c["act_pts"], cad_detail)
        + row("Release recency", 25, c["rel"], c["rel_pts"], rel_detail)
        + row("6-month trend", 20, c["tr"], c["tr_pts"], tr_detail)
        + f'<div class="sc-total"><span>Velocity score</span><b>{mom} <span class="sc-of">/ 100</span></b></div>'
    )


def _peers_html(r: dict, all_repos: list) -> str:
    """Other tracked agents in the same category, linked, ranked by velocity — so a
    reader can evaluate this agent against its real competitive set."""
    cat = r.get("category", "")
    me = repo_slug(r)
    peers = [p for p in all_repos if p.get("category") == cat and repo_slug(p) != me]
    peers.sort(key=lambda x: x.get("momentum", 0), reverse=True)
    if not peers:
        return '<p class="sublabel" style="margin-top:18px">The only tracked agent in this category.</p>'
    cards = []
    for p in peers:
        pslug = repo_slug(p)
        pm = int(p.get("momentum", 0) or 0)
        prank = p.get("rank", "—")
        cards.append(
            f'<a class="peer" href="/a/{pslug}/">'
            f'<span class="peer-rank">#{prank}</span>'
            f'<span class="peer-name">{_esc(p.get("name",""))}</span>'
            f'<span class="peer-meter"><i style="width:{pm}%"></i></span>'
            f'<span class="peer-v">{pm}</span></a>'
        )
    return '<div class="peergrid">' + "".join(cards) + "</div>"


def _posture(r: dict) -> dict:
    """Race posture from commit delta — mirrors app.js posture()."""
    d = int(r.get("commit_delta", 0) or 0)
    prior = int(r.get("prior4w_commits", 0) or 0)
    recent = int(r.get("recent4w_commits", 0) or 0)
    pct = (d / prior) if prior > 0 else (1.0 if recent > 0 else 0.0)
    if d > 3 and pct >= 0.12:
        return {"k": "surge", "label": "Accelerating", "icon": "▲"}
    if d > 3:
        return {"k": "up", "label": "Gaining", "icon": "▲"}
    if d < -3 and pct <= -0.12:
        return {"k": "brake", "label": "Braking", "icon": "▼"}
    if d < -3:
        return {"k": "down", "label": "Easing", "icon": "▼"}
    return {"k": "flat", "label": "Holding", "icon": "→"}


def _nav_html() -> str:
    return (
        '<nav id="nav"><div class="wrap nav-in">'
        '<a class="brand" href="/">Agent Velocity <span class="by">// Kymata Labs</span></a>'
        '<div class="nav-links">'
        '<a href="/#board">The board</a>'
        '<a href="/#how" class="hidem">How it\'s made</a>'
        '<a href="https://kymatalabs.com/" class="hidem">Kymata Labs ↗</a>'
        '<button class="themetog" id="themetog" type="button" aria-label="Toggle light/dark theme" title="Toggle theme">'
        '<svg class="i-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>'
        '<svg class="i-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4.2"/><path d="M12 2v2.5M12 19.5V22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M2 12h2.5M19.5 12H22M4.9 19.1l1.8-1.8M17.3 6.7l1.8-1.8"/></svg>'
        '</button></div></div></nav>'
    )


def _footer_html() -> str:
    return (
        '<footer><div class="wrap">'
        '<span class="mono" style="color:var(--hot-2)">How it\'s made</span>'
        '<h2>The race, scored by <em>shipping</em> — not hype.</h2>'
        '<p>An AI agent pulls live GitHub signals for every coding agent daily, scores velocity as commit cadence (55%) + release recency (25%) + 6-month trend (20%), and redeploys this board. Built and run by the same agent stack as '
        '<a class="inl" href="https://kymatalabs.com/" target="_blank" rel="noopener">Kymata Labs</a>.</p>'
        '<div class="foot-row">'
        '<a href="/">← All agents</a>'
        '<span>© 2026 Kymata Labs · Agent Velocity</span>'
        '<a href="https://kymatalabs.com/">kymatalabs ↗</a>'
        '</div></div></footer>'
    )


# inline no-flash theme script + theme-toggle wiring, shared by every detail page
_THEME_HEAD = (
    '<script>(function(){try{var t=localStorage.getItem("theme");if(!t){t=(window.matchMedia&&'
    'window.matchMedia("(prefers-color-scheme:light)").matches)?"light":"dark";}'
    'document.documentElement.dataset.theme=t;}catch(e){document.documentElement.dataset.theme="dark";}})();</script>'
)
_THEME_TOGGLE_JS = (
    '<script>(function(){var b=document.getElementById("themetog");if(!b)return;'
    'b.addEventListener("click",function(){var n=document.documentElement.dataset.theme==="light"?"dark":"light";'
    'document.documentElement.dataset.theme=n;try{localStorage.setItem("theme",n);}catch(e){}'
    'var tc=document.querySelector(\'meta[name="theme-color"]\');if(tc)tc.setAttribute("content",n==="light"?"#f6f3ef":"#0a0910");});})();</script>'
)


def _detail_html(r: dict, generated_at: str | None, all_repos: list | None = None) -> str:
    all_repos = all_repos or []
    slug = repo_slug(r)
    url = f"{SITE}/a/{slug}/"
    name = r.get("name", "")
    owner = r.get("owner", "")
    full = f"{owner}/{name}"
    cat = r.get("category", "")
    blurb = r.get("blurb", "")
    rank = r.get("rank", "—")
    rclass = f"t{rank}" if isinstance(rank, int) and rank <= 3 else ""
    lang = r.get("language") or "—"
    stars = int(r.get("stars", 0) or 0)
    forks = int(r.get("forks", 0) or 0)
    issues = int(r.get("open_issues", 0) or 0)
    mom = int(r.get("momentum", 0) or 0)
    r4 = int(r.get("recent4w_commits", 0) or 0)
    p4 = int(r.get("prior4w_commits", 0) or 0)
    delta = int(r.get("commit_delta", 0) or 0)
    rel_tag = r.get("last_release") or "—"
    rel_when = _rel_date(r.get("last_release_at"))
    gh_url = r.get("html_url") or f"https://github.com/{owner}/{name}"
    home = (r.get("homepage") or "").strip()
    total = len(all_repos) or r.get("repo_count") or 0
    pos = _posture(r)
    title = f"{name} — velocity {mom} · #{rank} | Agent Velocity"
    desc = (f"{full}: shipping velocity {mom}/100, ranked #{rank} among open-source coding agents. "
            f"{r4} commits in the last 4 weeks, {_fmt_stars(stars)} stars. {blurb}").strip()
    desc = re.sub(r"\s+", " ", desc)[:300]

    delta_sub = ""
    if delta > 3:
        delta_sub = f'<div class="sub">▲ {delta} more than prior 4w</div>'
    elif delta < -3:
        delta_sub = f'<div class="sub" style="color:var(--muted)">▼ {abs(delta)} fewer than prior 4w</div>'
    else:
        delta_sub = '<div class="sub" style="color:var(--muted)">→ steady vs prior 4w</div>'

    monthly = r.get("monthly_commits") or []
    axis = '<div class="axis"><span>6 months ago</span><span>now</span></div>' if len(monthly) >= 2 else ""
    bars = _commit_bars(monthly)
    score_rows = _score_rows(r)
    peers = _peers_html(r, all_repos)

    # 6-month commit totals for the panel header
    six_total = sum(int(x or 0) for x in monthly)

    # star history: real series if we have ≥2 datapoints, else a single tracked point
    shist = r.get("stars_history") or []
    if len(shist) >= 2:
        star_series = [int(h.get("stars", 0) or 0) for h in shist]
        star_panel_note = f"day-over-day, last {len(shist)} days tracked"
        star_chart = f'<div class="d-spark mini">{_spark_svg(star_series, 720, 90)}</div>'
    else:
        since = shist[0].get("date") if shist else None
        star_panel_note = (f"tracking since {since} — the day-over-day curve fills in as the board runs"
                           if since else "history fills in as the board runs daily")
        star_chart = ""

    # race-position movement: the climbed/slipped indicator + a rank-over-time curve.
    # The sparkline is INVERTED (rank 1 = top of the chart) so "up = climbing".
    rank_delta = r.get("rank_delta")
    rhist = r.get("rank_history") or []
    if isinstance(rank_delta, int) and rank_delta > 0:
        move_badge = f'<span class="d-move up" title="Climbed {rank_delta} since prior run">▲ {rank_delta}</span>'
        move_word = f"climbed {rank_delta} position{'s' if rank_delta != 1 else ''}"
    elif isinstance(rank_delta, int) and rank_delta < 0:
        move_badge = f'<span class="d-move dn" title="Slipped {abs(rank_delta)} since prior run">▼ {abs(rank_delta)}</span>'
        move_word = f"slipped {abs(rank_delta)} position{'s' if abs(rank_delta) != 1 else ''}"
    elif isinstance(rank_delta, int):
        move_badge = '<span class="d-move flat" title="Held position">→</span>'
        move_word = "held position"
    else:
        move_badge = '<span class="d-move new" title="New to the tracked board">NEW</span>'
        move_word = "new to the board"
    peak = r.get("peak_rank", rank)
    if len(rhist) >= 2:
        # invert so a climb reads as an upward line. Use the series' own worst rank as
        # the baseline (self-contained — no dependency on an outer `total`): worst→0,
        # best→largest, so the polyline rises when the repo climbs.
        _ranks = [int(p.get("rank", rank) or rank) for p in rhist]
        _worst = max(_ranks)
        rank_series = [max(1, (_worst + 1) - rv) for rv in _ranks]
        rank_chart = f'<div class="d-spark mini">{_spark_svg(rank_series, 720, 90)}</div>'
        rank_note = f"position over the last {len(rhist)} days tracked · best: #{peak}"
    else:
        rank_chart = ""
        rank_note = "position movement fills in as the board runs daily"

    # fork ratio (engagement signal) — forks per 1k stars
    fork_ratio = f"{forks/stars*1000:.0f}" if stars else "—"

    out_links = f'<a class="btn primary" href="{_esc(gh_url)}" target="_blank" rel="noopener">View on GitHub ↗</a>'
    if home:
        out_links += f'<a class="btn" href="{_esc(home)}" target="_blank" rel="noopener">Homepage ↗</a>'

    # embeddable rank badge — the viral loop (repos display their rank, link back here)
    badge_url = f"{SITE}/badge/{slug}.svg"
    embed_md = f"[![Agent Velocity rank]({badge_url})]({url})"
    embed_html = f'<a href="{url}"><img src="{badge_url}" alt="Agent Velocity rank"></a>'

    ld = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{SITE}/"},
                    {"@type": "ListItem", "position": 2, "name": "Agent Velocity", "item": f"{SITE}/#board"},
                    {"@type": "ListItem", "position": 3, "name": name, "item": url},
                ],
            },
            {
                "@type": "SoftwareSourceCode",
                "@id": f"{url}#software",
                "name": name,
                "description": blurb,
                "url": url,
                "codeRepository": gh_url,
                "programmingLanguage": (lang if lang != "—" else None),
                "author": {"@type": "Organization", "name": owner},
                "sameAs": [u for u in [gh_url, home or None] if u],
            },
        ],
    }
    # drop null programmingLanguage cleanly
    ssc = ld["@graph"][1]
    if ssc.get("programmingLanguage") is None:
        ssc.pop("programmingLanguage", None)
    ld_json = json.dumps(ld, ensure_ascii=False)

    recomputed = _rel_date(generated_at)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_esc(title)}</title>
<meta name="description" content="{_esc(desc)}">
<meta property="og:title" content="{_esc(name)} — velocity {mom} · #{rank} in the coding-agent race">
<meta property="og:description" content="{_esc(desc)}">
<meta property="og:type" content="article">
<meta property="og:image" content="{SITE}/og.png">
<meta property="og:url" content="{url}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{_esc(name)} — velocity {mom} · #{rank} in the coding-agent race">
<meta name="twitter:description" content="{_esc(desc)}">
<meta name="twitter:image" content="{SITE}/og.png">
<meta name="theme-color" content="#0a0910">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Anton&family=Sora:wght@300;400;600;800&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<link rel="canonical" href="{url}">
<link rel="icon" href="/favicon.svg">
<link rel="stylesheet" href="/style.css">
{_THEME_HEAD}
<script type="application/ld+json">{ld_json}</script>
</head>
<body>
<canvas id="streaks" aria-hidden="true"></canvas>
{_nav_html()}
<main class="detail"><div class="wrap">
  <nav class="crumbs" aria-label="Breadcrumb">
    <a href="/">Home</a><span class="sep">/</span>
    <a href="/#board">Agent Velocity</a><span class="sep">/</span>
    <span aria-current="page">{_esc(name)}</span>
  </nav>

  <div class="d-rankline">
    <div class="d-rank {rclass}"><span class="hash">#</span>{rank}</div>
    <div class="d-titlewrap">
      <h1>{_esc(name)} {move_badge}</h1>
      <div class="d-owner">{_esc(owner)} · <span class="d-cat">{_esc(cat)}</span> · <span class="d-pos {pos['k']}">{pos['icon']} {_esc(pos['label'])}</span></div>
    </div>
  </div>
  <p class="d-blurb">{_esc(blurb)}</p>
  <div class="d-actions">{out_links}</div>

  <div class="d-grid">
    <div class="d-stat hot"><b>{mom}</b><span>Velocity / 100</span><div class="sub">rank #{rank} of {total}</div></div>
    <div class="d-stat"><b>{r4}</b><span>Commits · last 4w</span>{delta_sub}</div>
    <div class="d-stat"><b>{_fmt_stars(stars)}</b><span>Stars</span></div>
    <div class="d-stat"><b>{_fmt_stars(forks)}</b><span>Forks</span></div>
    <div class="d-stat"><b>{_fmt_stars(issues)}</b><span>Open issues</span></div>
    <div class="d-stat"><b>{_esc(lang)}</b><span>Language</span></div>
  </div>

  <section class="d-section">
    <h2>How the velocity score is built</h2>
    <p class="sublabel">A 0–100 measure of <em>shipping pace</em> — weighted from three real GitHub signals. Every number below traces to the live API.</p>
    <div class="scorecard">{score_rows}</div>
  </section>

  <section class="d-section">
    <h2>Shipping momentum</h2>
    <p class="sublabel">Monthly commits · last 6 months · {six_total:,} total (real GitHub commit history)</p>
    <div class="d-spark">{_spark_svg(monthly)}{axis}</div>
    {bars}
    <div class="d-compare">
      <div class="cmp"><span class="cmp-l">Last 4 weeks</span><b>{r4:,}</b></div>
      <div class="cmp-arrow {pos['k']}">{pos['icon']}</div>
      <div class="cmp"><span class="cmp-l">Prior 4 weeks</span><b class="muted">{p4:,}</b></div>
      <div class="cmp-verdict {pos['k']}">{_esc(pos['label'])}{(' · ' + ('+' if delta>=0 else '−') + str(abs(delta)) + ' commits') if p4 or r4 else ''}</div>
    </div>
  </section>

  <section class="d-section">
    <h2>Race position over time</h2>
    <p class="sublabel">Where {_esc(name)} sits on the board, tracked daily — {move_word} since the prior run. {rank_note}.</p>
    {rank_chart}
    <div class="d-grid" style="margin-top:22px">
      <div class="d-stat hot"><b>#{rank}</b><span>Current rank</span></div>
      <div class="d-stat"><b>#{peak}</b><span>Best rank</span></div>
      <div class="d-stat"><b>{move_badge}</b><span>Since prior run</span></div>
    </div>
  </section>

  <section class="d-section">
    <h2>Stars &amp; reach</h2>
    <p class="sublabel">{_esc(star_panel_note)}</p>
    {star_chart}
    <div class="d-grid" style="margin-top:22px">
      <div class="d-stat"><b>{_fmt_stars(stars)}</b><span>Stars</span></div>
      <div class="d-stat"><b>{_fmt_stars(forks)}</b><span>Forks</span></div>
      <div class="d-stat"><b>{fork_ratio}</b><span>Forks · per 1k stars</span></div>
      <div class="d-stat"><b>{_fmt_stars(issues)}</b><span>Open issues</span></div>
    </div>
  </section>

  <section class="d-section">
    <h2>Latest release</h2>
    <p class="sublabel">Newest stable tag on GitHub — release recency is 25% of the velocity score</p>
    <div class="d-grid" style="margin-top:22px">
      <div class="d-stat"><b style="font-size:24px">{_esc(rel_tag)}</b><span>Tag</span></div>
      <div class="d-stat"><b style="font-size:24px">{_esc(rel_when)}</b><span>Released</span></div>
    </div>
  </section>

  <section class="d-section">
    <h2>Category peers · {_esc(cat)}</h2>
    <p class="sublabel">How {_esc(name)} stacks up against the rest of the {_esc(cat)} field, ranked by velocity</p>
    {peers}
  </section>

  <section class="d-section">
    <h2>📛 Embed this badge</h2>
    <p class="sublabel">Show your live Agent Velocity rank in your README — it updates daily and links back here.</p>
    <p style="margin-top:14px"><img src="{badge_url}" alt="Agent Velocity rank badge for {_esc(name)}" style="vertical-align:middle"></p>
    <div class="embed-snippets" style="margin-top:14px">
      <label class="sublabel" style="display:block;margin-bottom:6px">Markdown</label>
      <pre class="embed-code" style="overflow-x:auto;padding:12px;border-radius:8px;background:rgba(127,127,127,.10);font-family:'DM Mono',ui-monospace,monospace;font-size:13px"><code>{_esc(embed_md)}</code></pre>
      <label class="sublabel" style="display:block;margin:14px 0 6px">HTML</label>
      <pre class="embed-code" style="overflow-x:auto;padding:12px;border-radius:8px;background:rgba(127,127,127,.10);font-family:'DM Mono',ui-monospace,monospace;font-size:13px"><code>{_esc(embed_html)}</code></pre>
    </div>
  </section>

  <section class="d-section">
    <h2>Links</h2>
    <div class="d-actions" style="margin-top:18px">{out_links}<a class="btn" href="/">← Back to the board</a></div>
    <p class="sublabel" style="margin-top:18px">Recomputed {_esc(recomputed)} · scored from public-repo GitHub activity. Velocity = commit cadence (55%) + release recency (25%) + 6-month trend (20%). <a class="inl" href="/feed.json">JSON API ↗</a></p>
  </section>
</div></main>
{_footer_html()}
<script>
/* speed-streaks hero — theme-aware (mirrors the hub) */
(function(){{
  if(window.matchMedia && window.matchMedia("(prefers-reduced-motion:reduce)").matches) return;
  var cv=document.getElementById("streaks"); if(!cv) return;
  var ctx=cv.getContext("2d"), W=0,H=0,dpr=Math.min(window.devicePixelRatio||1,2), ps=[], raf;
  var THEME={{dark:{{colors:["255,67,36","255,138,43","255,182,72"],comp:"lighter",aMul:1.0}},
             light:{{colors:["232,53,26","217,101,26","204,120,30"],comp:"source-over",aMul:0.55}}}};
  function curTheme(){{return document.documentElement.dataset.theme==="light"?THEME.light:THEME.dark;}}
  var TH=curTheme();
  function size(){{ W=cv.clientWidth; H=cv.clientHeight; cv.width=W*dpr; cv.height=H*dpr; ctx.setTransform(dpr,0,0,dpr,0,0); build(); }}
  function mk(){{ var sp=2.5+Math.random()*7; return {{ x:-Math.random()*W, y:Math.random()*H, len:60+Math.random()*180, sp:sp, w:Math.random()<0.2?1.8:0.8, c:TH.colors[(Math.random()*TH.colors.length)|0], a:0.10+Math.random()*0.35 }}; }}
  function build(){{ var n=Math.max(18,Math.min(46,Math.round(W/26))); ps=[]; for(var i=0;i<n;i++){{var p=mk();p.x=Math.random()*W;ps.push(p);}} }}
  function frame(){{
    ctx.clearRect(0,0,W,H); ctx.globalCompositeOperation=TH.comp;
    for(var i=0;i<ps.length;i++){{
      var p=ps[i]; p.x+=p.sp; var a=(p.a*TH.aMul);
      var g=ctx.createLinearGradient(p.x-p.len,p.y,p.x,p.y);
      g.addColorStop(0,"rgba("+p.c+",0)"); g.addColorStop(1,"rgba("+p.c+","+a.toFixed(3)+")");
      ctx.strokeStyle=g; ctx.lineWidth=p.w; ctx.beginPath(); ctx.moveTo(p.x-p.len,p.y); ctx.lineTo(p.x,p.y); ctx.stroke();
      ctx.fillStyle="rgba("+p.c+","+Math.min(1,a+0.3).toFixed(3)+")"; ctx.fillRect(p.x-1,p.y-p.w/2,2,p.w);
      if(p.x-p.len>W){{ ps[i]=mk(); }}
    }}
    raf=requestAnimationFrame(frame);
  }}
  window.addEventListener("av:themechange",function(){{ TH=curTheme(); build(); }});
  size(); window.addEventListener("resize", size);
  document.addEventListener("visibilitychange", function(){{ if(document.hidden){{cancelAnimationFrame(raf);}} else {{raf=requestAnimationFrame(frame);}} }});
  raf=requestAnimationFrame(frame);
}})();
</script>
{_THEME_TOGGLE_JS.replace("});})();", "window.dispatchEvent(new Event('av:themechange'));});})();")}
</body>
</html>
"""


def generate_details(data: dict) -> int:
    """Write a/<slug>/index.html for every repo, plus sitemap.xml + llms.txt."""
    repos = data.get("repos", [])
    gen_at = data.get("generated_at")
    a_dir = os.path.join(HERE, "a")
    os.makedirs(a_dir, exist_ok=True)
    written = 0
    slugs = []
    for r in repos:
        slug = repo_slug(r)
        slugs.append(slug)
        d = os.path.join(a_dir, slug)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "index.html"), "w") as f:
            f.write(_detail_html(r, gen_at, repos))
        written += 1
    _write_sitemap(slugs)
    _write_llms(data)
    generate_badges(data)
    generate_feed(data)
    generate_rss(data)
    print(f"  generated {written} detail pages + sitemap + llms.txt + feed.json + rss.xml + badges", file=sys.stderr)
    return written


def _write_sitemap(slugs: list[str]) -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = [f'  <url><loc>{SITE}/</loc><lastmod>{today}</lastmod><changefreq>daily</changefreq><priority>1.0</priority></url>']
    for s in slugs:
        rows.append(f'  <url><loc>{SITE}/a/{s}/</loc><lastmod>{today}</lastmod><changefreq>daily</changefreq><priority>0.7</priority></url>')
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
           + "\n".join(rows) + "\n</urlset>\n")
    with open(os.path.join(HERE, "sitemap.xml"), "w") as f:
        f.write(xml)


def _write_llms(data: dict) -> None:
    repos = sorted(data.get("repos", []), key=lambda x: x.get("rank", 999))
    lines = [
        "# Agent Velocity",
        "",
        "> A live leaderboard ranking open-source coding agents by real GitHub **shipping velocity** — not by stars.",
        "",
        "## What this is",
        "Agent Velocity scores every tracked open-source coding agent on a 0-100 velocity metric computed from commit cadence (55%), release recency (25%), and 6-month commit trend (20%). It answers: who is actually shipping fastest in the coding-agent race?",
        "",
        "## Source & cadence",
        "- Data source: the public GitHub REST API (commits, releases, stars, forks, issues). Every number traces to a real API response — nothing is fabricated.",
        "- Cadence: recomputed and redeployed **daily** by an autonomous agent (Kymata Labs agent stack).",
        "- Caveat: velocity reflects *public-repo* activity only; privately developed agents rank below their true pace.",
        "",
        "## Routes",
        "- `/` — the full leaderboard (podium + sortable table; filter by category; light/dark themes).",
        "- `/a/<owner>-<name>/` — per-agent detail page: velocity, rank, stars, forks, open issues, language, latest release, and a 6-month commit sparkline.",
        "",
        f"## Tracked agents ({len(repos)})",
    ]
    for r in repos:
        slug = repo_slug(r)
        lines.append(f"- [{r.get('owner','')}/{r.get('name','')}]({SITE}/a/{slug}/) — {r.get('category','')} · velocity {r.get('momentum',0)}/100 · rank #{r.get('rank','—')}. {r.get('blurb','')}")
    lines += [
        "",
        "## Publisher",
        "Kymata Labs — https://kymatalabs.com/",
        "",
    ]
    with open(os.path.join(HERE, "llms.txt"), "w") as f:
        f.write("\n".join(lines))


def main() -> int:
    cfg = json.load(open(os.path.join(HERE, "repos.json")))
    # read prior data.json to extend the star history series AND the rank/velocity
    # movement series (so the board can show ▲/▼ position change over time — the
    # "race" narrative — exactly the way stars_history seeds the star sparkline).
    prior_stars = {}
    prior_rankh = {}
    out_path = os.path.join(HERE, "data.json")
    if os.path.exists(out_path):
        try:
            prev = json.load(open(out_path))
            for r in prev.get("repos", []):
                prior_stars[r["repo"]] = r.get("stars_history", [])
                prior_rankh[r["repo"]] = r.get("rank_history", [])
        except Exception:
            pass

    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    # 6 monthly (30d) windows, oldest→newest. Built from the commits endpoint
    # (reliable, no 202). This is BOTH the momentum velocity and the sparkline,
    # so every repo has a real commit-trend curve on day one.
    def iso(dt):
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    windows = [(iso(now - timedelta(days=30 * (i + 1))), iso(now - timedelta(days=30 * i))) for i in range(6)][::-1]

    items = []
    for entry in cfg["repos"]:
        full = entry.get("repo")
        if not full or "/" not in full:
            print(f"  skip malformed entry: {entry!r}", file=sys.stderr)
            continue
        category = entry.get("category", "Uncategorized")
        blurb = entry.get("blurb", "")
        st, core = gh(f"/repos/{full}")
        if st != 200 or not core:
            print(f"  skip {full} (repo status {st})", file=sys.stderr)
            continue
        _, rel = gh(f"/repos/{full}/releases/latest")  # stable only (avoids prereleases)
        # monthly commit buckets (sparkline) + recent/prior 30d velocity (momentum)
        monthly = [commit_count(full, s, until_iso=u) for (s, u) in windows]
        recent4 = monthly[-1]
        prior4 = monthly[-2]
        rel_tag = rel.get("tag_name") if isinstance(rel, dict) else None
        rel_at = rel.get("published_at") if isinstance(rel, dict) else None
        d_rel = days_since(rel_at)
        score = momentum(recent4, prior4, d_rel)

        stars = int(core.get("stargazers_count", 0))
        hist = list(prior_stars.get(full, []))
        if not hist or hist[-1].get("date") != today:
            hist.append({"date": today, "stars": stars})
        hist = hist[-90:]  # cap 90 days

        items.append({
            "repo": full,
            "name": full.split("/")[-1],
            "owner": full.split("/")[0],
            "category": category,
            "blurb": blurb,
            "stars": stars,
            "forks": int(core.get("forks_count", 0)),
            "open_issues": int(core.get("open_issues_count", 0)),
            "language": core.get("language"),
            "archived": bool(core.get("archived")),
            "homepage": (core.get("homepage") or "").strip() or None,
            "html_url": core.get("html_url"),
            "pushed_at": core.get("pushed_at"),
            "last_release": rel_tag,
            "last_release_at": rel_at,
            "monthly_commits": monthly,         # 6 × 30d buckets, real
            "recent4w_commits": recent4,
            "prior4w_commits": prior4,
            "commit_delta": recent4 - prior4,
            "momentum": score,
            "stars_history": hist,
        })
        print(f"  {full}: {stars}★ momentum={score} recent4w={recent4}", file=sys.stderr)
        time.sleep(0.2)  # be polite to the API

    items.sort(key=lambda x: x["momentum"], reverse=True)
    for i, it in enumerate(items):
        it["rank"] = i + 1

    # ── movement tracking ─────────────────────────────────────────────────────
    # Append today's (rank, momentum) to each repo's rank_history (capped 90 days),
    # then derive position movement vs the most recent PRIOR day. rank_delta > 0
    # means the repo CLIMBED (smaller rank number is better). On day one there is no
    # prior, so deltas are None and the UI shows a "new" / no-change state — the
    # series fills in as the board runs daily (same cold-start as stars_history).
    for it in items:
        rh = list(prior_rankh.get(it["repo"], []))
        # only PRIOR points with a real int rank are comparable (a malformed/None rank
        # in the persisted history must never crash the daily cron build).
        prior_pts = [p for p in rh if p.get("date") != today and isinstance(p.get("rank"), int)]
        if not rh or rh[-1].get("date") != today:
            rh.append({"date": today, "rank": it["rank"], "momentum": it["momentum"]})
        rh = rh[-90:]
        it["rank_history"] = rh
        if prior_pts:
            prev_rank = prior_pts[-1].get("rank")
            it["rank_prev"] = prev_rank
            it["rank_delta"] = prev_rank - it["rank"]   # prior_pts are int-rank only
            it["peak_rank"] = min([p["rank"] for p in prior_pts] + [it["rank"]])
            it["tracked_days"] = len(prior_pts) + 1
        else:
            it["rank_prev"] = None
            it["rank_delta"] = None       # None == new/untracked (distinct from 0 == held)
            it["peak_rank"] = it["rank"]
            it["tracked_days"] = 1

    # biggest climbers over the tracked window — the "Movers" strip. Falls back to
    # commit_delta (always present) so the strip is populated on day one too.
    # commit_delta is always int (recent4-prior4), but default-guard the sort keys so a
    # malformed record can never crash the daily cron build (production blast radius).
    climbers = [x for x in items if isinstance(x.get("rank_delta"), int) and x["rank_delta"] > 0]
    movers = sorted(climbers, key=lambda x: (x["rank_delta"], int(x.get("commit_delta") or 0)),
                    reverse=True)[:5]
    if not movers:
        movers = sorted([x for x in items if int(x.get("commit_delta") or 0) > 0],
                        key=lambda x: int(x.get("commit_delta") or 0), reverse=True)[:5]

    trending = sorted([x for x in items if x["commit_delta"] > 0],
                      key=lambda x: x["commit_delta"], reverse=True)[:3]

    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_date": today,
        "repo_count": len(items),
        "categories": cfg["categories"],
        "trending": [t["repo"] for t in trending],
        "movers": [{"repo": mvr["repo"], "name": mvr["name"], "owner": mvr["owner"],
                    "rank": mvr["rank"], "rank_delta": mvr.get("rank_delta"),
                    "momentum": mvr["momentum"], "commit_delta": mvr["commit_delta"]}
                   for mvr in movers],
        "repos": items,
    }
    json.dump(data, open(out_path, "w"), indent=2)
    series_len = len(items[0]["monthly_commits"]) if items else 0
    print(f"wrote {out_path}: {len(items)} repos, {series_len}-month series", file=sys.stderr)
    # resilience guard: a partial/rate-limited run (most repos missing) must FAIL so
    # the cron skips commit+deploy and the last-good page stays live, not a half-empty one.
    expected = len(cfg.get("repos", []))
    floor = max(5, int(expected * 0.6))
    if len(items) < floor:
        print(f"GUARD: only {len(items)}/{expected} repos fetched (< {floor}); refusing to publish.", file=sys.stderr)
        return 1
    # static detail pages + sitemap + llms.txt (only on a healthy, non-guarded run)
    try:
        generate_details(data)
    except Exception as e:
        print(f"  detail generation failed: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
