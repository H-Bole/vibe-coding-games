"""Render the game directory and daily reports for a static site."""

from collections import Counter, defaultdict
from html import escape
from urllib.parse import urlsplit


SITE_NAME = "Vibe Coding 游戏合集"
GROUPS = {"A": "A 组 · 开源", "B": "B 组 · 未找到源码", "early": "早期收藏"}


def external_link(url: str, label: str, css_class: str = "") -> str:
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return ""
    style = f' class="{escape(css_class)}"' if css_class else ""
    return f'<a{style} href="{escape(url)}" target="_blank" rel="noopener noreferrer">{escape(label)}</a>'


def page(title: str, description: str, root: str, active: str, body: str) -> str:
    home_current = ' aria-current="page"' if active == "home" else ""
    archive_current = ' aria-current="page"' if active == "archive" else ""
    if active == "report":
        archive_current = ' aria-current="location"'
    script = f'<script src="{root}assets/search.js" defer></script>' if active == "home" else ""
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="{escape(description)}">
  <meta name="theme-color" content="#f5f3eb">
  <title>{escape(title)}</title>
  <link rel="stylesheet" href="{root}assets/style.css">
  {script}
</head>
<body>
  <a class="skip-link" href="#main-content">跳到主要内容</a>
  <header class="masthead">
    <div class="shell masthead-inner">
      <a class="wordmark" href="{root}index.html"><span class="brand-mark" aria-hidden="true"></span>Vibe Coding</a>
      <nav class="primary-nav" aria-label="主导航">
        <a href="{root}index.html"{home_current}>游戏合集</a>
        <a href="{root}daily/index.html"{archive_current}>日报归档</a>
      </nav>
    </div>
  </header>
  <main id="main-content" class="shell">
  {body}
  </main>
</body>
</html>
'''


def game_card(game: dict, report_dates: set[str]) -> str:
    name = game["name"]
    aliases = " ".join(game.get("aliases") or [])
    group = game["group"]
    date = game.get("date", "")
    summary = game.get("summary", "")
    model = game.get("model", "")
    license_name = game.get("license", "")
    mobile = game.get("mobile", "")
    play = external_link(game.get("play", ""), "在线试玩", "card-play")
    repository = external_link(game.get("repository", ""), "源码", "card-link")
    date_label = f'<time datetime="{escape(date)}">{escape(date)}</time>' if date else ""
    report = f'<a class="card-link" href="daily/{escape(date)}/index.html">看日报</a>' if date in report_dates else ""
    model_link = external_link(game.get("model_url", ""), model) if model else ""
    license_link = external_link(game.get("license_url", ""), license_name) if license_name else ""
    evidence_items = [
        ("开发模型", model_link or escape(model)),
        ("代码许可", license_link or escape(license_name)),
        ("手机支持", escape(mobile)),
    ]
    evidence = "".join(f"<div><dt>{label}</dt><dd>{value}</dd></div>" for label, value in evidence_items if value)
    evidence_block = f'<dl class="game-evidence">{evidence}</dl>' if evidence else ""
    summary_block = f'<p class="game-summary">{escape(summary)}</p>' if summary else ""
    early_note = ""
    if group == "early":
        missing = [label for label, value in (("收录日期", date), ("试玩入口", play), ("代码许可", license_name)) if not value]
        if missing:
            early_note = f'<p class="game-note">档案未记录{"、".join(missing)}。</p>'
    actions = f'<div class="game-actions">{play}{repository}{report}</div>' if play or repository or report else ""
    return f'''<article class="game-card" data-group="{escape(group)}" data-name="{escape(name)}" data-aliases="{escape(aliases)}">
  <div class="game-meta"><span class="game-group">{GROUPS[group]}</span>{date_label}</div>
  <h3>{escape(name)}</h3>
  {summary_block}
  {evidence_block}
  {early_note}
  {actions}
</article>'''


def home(games: list[dict], reports: list[dict]) -> str:
    report_dates = {report["date"] for report in reports}
    counts = Counter(game["group"] for game in games)
    filter_labels = {"all": "全部", **GROUPS}
    filters = []
    for group, label in filter_labels.items():
        count = len(games) if group == "all" else counts[group]
        pressed = "true" if group == "all" else "false"
        filters.append(f'<button type="button" data-filter="{group}" aria-pressed="{pressed}">{label} <span>{count}</span></button>')
    latest = ""
    if reports:
        date = escape(reports[0]["date"])
        latest = f'''<a class="latest" href="daily/{date}/index.html">
          <span>最新一期</span><strong>{date}</strong><span>查看日报 <span aria-hidden="true">↗</span></span>
        </a>'''
    cards = "\n".join(game_card(game, report_dates) for game in games)
    description = "浏览可在线试玩的 Vibe Coding 游戏，查看玩法、开发模型、开源许可和日报依据。"
    empty_message = "没有符合条件的游戏。试试其他名称，或切换分组。" if games else "暂时没有已收录的游戏。"
    empty_hidden = " hidden" if games else ""
    body = f'''
    <section class="home-hero" aria-labelledby="home-title">
      <div class="hero-copy">
        <h1 id="home-title"><span lang="en">Vibe Coding</span> <span>游戏合集</span></h1>
        <p>看玩法、直接试玩，或到日报查阅开发模型与实玩记录。</p>
      </div>
      {latest}
    </section>
    <section class="directory" aria-labelledby="directory-title">
      <div class="directory-heading">
        <h2 id="directory-title">游戏目录</h2>
        <p id="result-count" aria-live="polite">共 {len(games)} 款</p>
      </div>
      <div id="search-tools" class="search-tools" hidden>
        <div class="search-field" role="search">
          <label class="sr-only" for="game-search">搜索游戏名称或别名</label>
          <input id="game-search" type="search" placeholder="搜索游戏名称或别名" autocomplete="off" spellcheck="false">
        </div>
        <div class="filters" role="group" aria-label="按收录分组筛选">{''.join(filters)}</div>
      </div>
      <div class="games">{cards}</div>
      <p id="empty-results" class="empty-state"{empty_hidden}>{empty_message}</p>
    </section>'''
    return page(SITE_NAME, description, "", "home", body)


def recent_issues(reports: list[dict], prefix: str, current_date: str = "") -> str:
    if not reports:
        return ""
    links = []
    for report in reports[:7]:
        date = escape(report["date"])
        current = ' aria-current="page"' if date == current_date else ""
        links.append(f'<a href="{prefix}{date}/index.html"{current}><time datetime="{date}">{date}</time></a>')
    archive_link = f'<a class="all-issues" href="{prefix}index.html">全部日期</a>' if current_date else ""
    return f'''<nav class="recent-issues" aria-label="最近七期日报">
      <span>最近七期</span>
      <div class="issue-tabs">{''.join(links)}{archive_link}</div>
    </nav>'''


def archive(reports: list[dict]) -> str:
    months = defaultdict(list)
    for report in reports:
        months[report["date"][:7]].append(report)
    sections = []
    for month, month_reports in months.items():
        year, number = month.split("-")
        issues = []
        for report in month_reports:
            date = escape(report["date"])
            issues.append(f'''<li><a href="{date}/index.html">
              <time datetime="{date}">{date}</time>
              <span>A 组 {report['a']} 款 <span aria-hidden="true">·</span> B 组 {report['b']} 款</span>
              <span class="issue-arrow" aria-hidden="true">↗</span>
            </a></li>''')
        sections.append(f'''<section class="archive-month" aria-labelledby="month-{month}">
          <div class="month-heading"><h2 id="month-{month}">{year} 年 {int(number)} 月</h2><span>{len(month_reports)} 期</span></div>
          <ul class="issue-list">{''.join(issues)}</ul>
        </section>''')
    history = "\n".join(sections) or '<p class="empty-state">暂时没有已归档的日报。</p>'
    body = f'''
    <header class="page-heading">
      <h1>日报归档</h1>
      <p>按月浏览 {len(reports)} 期日报，查看当期推荐、试玩记录和证据。</p>
    </header>
    {recent_issues(reports, "")}
    {history}'''
    return page(f"日报归档 · {SITE_NAME}", "按月浏览 Vibe Coding 游戏精选日报。", "../", "archive", body)


def daily_report(report: dict, reports: list[dict]) -> str:
    date = escape(report["date"])
    body = f'''
    <header class="page-heading report-heading">
      <h1><time datetime="{date}">{date}</time> 游戏精选</h1>
      <p>A 组 · 开源 {report['a']} 款 <span aria-hidden="true">/</span> B 组 · 未找到源码 {report['b']} 款</p>
    </header>
    {recent_issues(reports, "../", date)}
    <article class="report-content" aria-label="日报正文">{report['content']}</article>'''
    title = f"{report['date']} 游戏精选日报"
    return page(f"{title} · {SITE_NAME}", title, "../../", "report", body)


def render_site(games: list[dict], reports: list[dict]) -> dict[str, str]:
    games = sorted(games, key=lambda game: game.get("date", ""), reverse=True)
    reports = sorted(reports, key=lambda report: report["date"], reverse=True)
    pages = {"index.html": home(games, reports), "daily/index.html": archive(reports)}
    for report in reports:
        pages[f"daily/{report['date']}/index.html"] = daily_report(report, reports)
    return pages
