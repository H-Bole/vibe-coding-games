"""Read the local game archive and prepare its public catalogue and reports."""

import json
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


REPORT_SUFFIX = "-Vibe-Coding游戏精选.html"
EARLY_REPORT = "自动化前游戏精选汇总.html"
PUBLIC_TAGS = frozenset(
    "a article aside b blockquote br caption code dd details div dl dt em footer h2 h3 "
    "h4 header hr li ol p pre section small span strong summary table tbody td tfoot th thead tr ul".split()
)
PUBLIC_CLASSES = frozenset(
    "aside badge badges box card cards chip chips count counts foot footer footnotes head heading "
    "intro kicker label lead leadbox leadgrid leads links meta metrics minor muted note notes notice "
    "num number ordinal panel pick picks pill prior report scope section section-head small stat "
    "stats sub tablebox table-wrap tablewrap tag test top trial try".split()
)
VOID_TAGS = frozenset("area base br col embed hr img input link meta param source track wbr".split())
HIDDEN_TAGS = frozenset("head script style iframe object embed svg math template form noscript".split())
TEXT_BLOCKS = frozenset("br dd div dt li p small span".split())
HOST = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,62}")
PRIVATE_SUFFIXES = frozenset("localhost local localdomain lan internal intranet test example invalid onion home corp".split())
PRIVATE_TOKEN = re.compile(
    r"\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b|"
    r"(?:file|codex|vscode|chrome|edge|about):/{0,3}[^<>。；，、\r\n]+|"
    r"(?<![A-Za-z0-9./])(?:[a-z]:[\\/]|\\\\|/(?:Users|home|mnt|tmp|private|var/tmp)/)"
    r"[^<>。；，、\"'）)\r\n]+|"
    r"\b(?:https?://)?(?:localhost(?::\d+)?|127\.0\.0\.1(?::\d+)?)(?:/[^\s<>。；，、]*)?|"
    r"\b(?:access[_-]?token|auth[_-]?token|api[_-]?key|session[_-]?id|source[_-]?thread|thread[_-]?id|cookie)"
    r"\s*[:：=]\s*[\w.%-]+",
    re.IGNORECASE,
)
PRIVATE_QUERY = re.compile(
    r"(?:^|[&;])[^=&;]*(?:token|secret|password|session|credential|signature|api[_.-]?key)[^=&;]*=",
    re.IGNORECASE,
)
LICENSE_NAME = re.compile(
    r"(?<![A-Za-z0-9])(?:MIT|Unlicense|(?:A?GPL|LGPL|MPL|Apache|BSD|CC0)-[\d.]+"
    r"(?:\s*(?:or later|或更高版本))?|CC0)(?![A-Za-z0-9])",
    re.IGNORECASE,
)
MODEL_NAME = re.compile(
    r"(?:Opus|Fable|Sonnet|GPT|Gemini|Grok|DeepSeek)[ -‑–]?\s*\d", re.IGNORECASE
)
MOBILE_TERM = r"(?:手机|触屏|触控|触摸屏|移动端|平板|iPad|iPhone|Android|mobile)"
MOBILE_SUPPORT = re.compile(
    r"(?:手机[／/与和及或、]电脑|(?:电脑|桌面)[／/与和及或、]手机|"
    r"(?:支持|适配|兼容|可用|可在|可通过|可使用|可选|提供|建议).{0,20}" + MOBILE_TERM + r"|"
    + MOBILE_TERM + r".{0,8}(?:可玩|支持|横屏|滑动|试玩|完成|建议横屏)|"
    r"倾斜手机|(?:键盘|鼠标|手柄)(?:、|或|及|和|与).{0,12}(?:触屏|触控))",
    re.IGNORECASE,
)
MOBILE_LIMIT = re.compile(
    r"(?:不适配|不支持|无法使用|仅支持).{0,12}" + MOBILE_TERM + r"|"
    + MOBILE_TERM + r".{0,12}(?:体验较弱|没有.{0,8}控制|不支持|不可玩|无法操作)",
    re.IGNORECASE,
)
EMPTY_GROUP = re.compile(r"(?:无入选|无符合|暂无|零入选|0\s*款|未找到(?:合格|符合)|本组无)")


def public_text(text: str) -> str:
    text = PRIVATE_TOKEN.sub("", text)
    for term, replacement in (
        (r"已登录\s*(?:的\s*)?(?:itch\s*)?会话|(?:已有|既有)\s*itch\s*登录会话", "已登录环境"),
        ("无登录会话", "未登录环境"),
        ("新浏览器会话|全新会话", "新浏览器环境"),
        (r"(?:已有|既有|现有)\s*(?:的\s*)?(?:itch|浏览器|Edge)?\s*会话|本机", "本次环境"),
    ):
        text = re.sub(term, replacement, text, flags=re.IGNORECASE)
    return text


def public_url(value: str | None) -> str:
    if not value or not isinstance(value, str) or not value.startswith("https://"):
        return ""
    decoded = unquote(unquote(value))
    if re.search(r"[\x00-\x1f\x7f\\]|\s", value) or re.search(r"[\x00-\x1f\x7f\\]", decoded):
        return ""
    if PRIVATE_TOKEN.search(decoded):
        return ""
    try:
        url = urlsplit(value)
        host = url.hostname or ""
        if (
            url.username is not None or url.password is not None or url.port not in (None, 443)
            or not HOST.fullmatch(host) or host.rsplit(".", 1)[1] in PRIVATE_SUFFIXES
            or PRIVATE_QUERY.search(unquote(url.query)) or PRIVATE_QUERY.search(unquote(url.fragment))
        ):
            return ""
    except ValueError:
        return ""
    return value


@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    def find(self, tag: str):
        for child in self.children:
            if isinstance(child, Node) and child.tag not in HIDDEN_TAGS:
                if child.tag == tag:
                    yield child
                yield from child.find(tag)

    def raw_text(self, omit_link_notes=False) -> str:
        if self.tag in HIDDEN_TAGS:
            return ""
        if omit_link_notes and self.tag == "a" and not MODEL_NAME.search(self.raw_text()):
            return ""
        content = "".join(
            child.raw_text(omit_link_notes) if isinstance(child, Node) else child
            for child in self.children
        )
        return f"\n{content}\n" if self.tag in TEXT_BLOCKS else content

    def plain(self, omit_link_notes=False) -> str:
        return " ".join(public_text(self.raw_text(omit_link_notes)).split()).strip(" ·↗")

    def links(self):
        for link in self.find("a"):
            url = public_url(link.attrs.get("href"))
            if url:
                yield link.plain(), url


class ReportParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.root = Node("")
        self.stack = [self.root]
        self.ended = False

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Node(tag, dict(attrs)))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                self.ended |= tag == "body"
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def read_body(path: Path) -> Node:
    parser = ReportParser()
    parser.feed(path.read_text(encoding="utf-8-sig"))
    parser.close()
    bodies = list(parser.root.find("body"))
    if len(bodies) != 1 or not parser.ended or not bodies[0].plain():
        raise ValueError(f"{path.name} 的正文不完整")
    return bodies[0]


def public_html(node: Node) -> str:
    if node.tag in HIDDEN_TAGS or node.tag == "h1":
        return ""
    if node.tag == "header" and next(node.find("h1"), None) is not None:
        return ""

    # 对原文的连续文本一次处理，避免把换行实体拆开。
    parts = []
    pending = []
    for child in node.children:
        if isinstance(child, str):
            pending.append(child)
        else:
            parts.append(escape(public_text("".join(pending)), quote=False))
            pending.clear()
            parts.append(public_html(child))
    parts.append(escape(public_text("".join(pending)), quote=False))
    body = "".join(parts)
    if node.tag not in PUBLIC_TAGS:
        return body

    attrs = {}
    classes = [item for item in (node.attrs.get("class") or "").split() if item in PUBLIC_CLASSES]
    if classes:
        attrs["class"] = " ".join(classes)
    if node.tag == "a":
        url = public_url(node.attrs.get("href"))
        if not url:
            return body
        attrs.update(href=url, target="_blank", rel="noopener noreferrer")
    if node.tag in ("td", "th"):
        for key in ("colspan", "rowspan"):
            value = node.attrs.get(key) or ""
            if re.fullmatch(r"[1-9]\d?", value):
                attrs[key] = value
    if node.tag == "td":
        attrs["data-label"] = node.attrs["data-label"]
    if node.tag == "th":
        attrs["scope"] = "row" if node.attrs.get("scope") == "row" else "col"
    if node.tag == "table" and node.attrs.get("aria-label"):
        attrs["aria-label"] = public_text(node.attrs["aria-label"])
    attributes = "".join(f' {key}="{escape(value, quote=True)}"' for key, value in attrs.items())
    opening = f"<{node.tag}{attributes}>"
    return opening if node.tag in VOID_TAGS else f"{opening}{body}</{node.tag}>"


def name_key(name: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", name).casefold() if c.isalnum())


def url_key(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.hostname or ''}{parts.path.rstrip('/')}?{parts.query}#{parts.fragment}"


def repository_key(url: str) -> str:
    parts = urlsplit(url)
    host = (parts.hostname or "").removeprefix("www.")
    path = unquote(parts.path).rstrip("/")
    if host in ("github.com", "gitee.com") and re.fullmatch(r"/[^/]+/[^/]+", path):
        return host + path.casefold().removesuffix(".git")
    return url_key(url)


def link_keys(primary: str, aliases: list, key) -> set[str]:
    return {key(url) for url in (primary, *aliases) if public_url(url)}


def game_names(game: dict) -> set[str]:
    return {name_key(name) for name in (game["name"], *game["aliases"])}


def license_info(text: str, links: list) -> tuple[str, str]:
    match = LICENSE_NAME.search(text.replace("‑", "-").replace("–", "-"))
    if not match:
        return "", ""
    name = match[0]
    url = next((
        url for label, url in links
        if LICENSE_NAME.search(label.replace("‑", "-").replace("–", "-")) or label in ("许可证", "开源许可证")
    ), "")
    return name, url


def device_info(cells: list[Node]) -> tuple[str, bool]:
    notes = [
        " ".join(note.split()).strip(" ·↗")
        for cell in cells
        for note in re.split(r"[。；;\n]", public_text(cell.raw_text()))
    ]
    limit = next((note for note in notes if MOBILE_LIMIT.search(note)), "")
    if limit:
        return limit, False
    supported = next((note for note in notes if MOBILE_SUPPORT.search(note)), "")
    return supported, bool(supported)


def sections(node: Node):
    if node.tag in HIDDEN_TAGS:
        return
    if node.tag in ("h2", "table"):
        yield node
        return
    for child in node.children:
        if isinstance(child, Node):
            yield from sections(child)


def table_rows(table: Node):
    labels = []
    for row in table.find("tr"):
        headers = [child.plain() for child in row.children if isinstance(child, Node) and child.tag == "th"]
        cells = [child for child in row.children if isinstance(child, Node) and child.tag == "td"]
        if headers:
            labels = headers
        column = 0
        for cell in cells:
            cell.attrs["data-label"] = labels[column] if column < len(labels) else "补充说明"
            span = cell.attrs.get("colspan") or "1"
            column += int(span) if re.fullmatch(r"[1-9]\d?", span) else 1
        if cells:
            yield cells


def daily_games(body: Node, expected: list[tuple[dict, dict]], day: str) -> list[dict]:
    remaining = {group: [(game, entry) for game, entry in expected if game["group"] == group] for group in "AB"}
    games = []
    group = ""
    for section in sections(body):
        if section.tag == "h2":
            heading = section.plain()
            label = re.match(r"^([AB])\s*(?:组|[：:·/])", heading)
            group = label[1] if label else {
                "开源 + 在线试玩": "A",
                "在线试玩 · 未找到公开源码": "B",
            }.get(heading, "")
            continue

        for cells in table_rows(section):
            if not group:
                continue
            if len(cells) == 1 and EMPTY_GROUP.search(cells[0].plain()):
                continue
            if len(cells) < 4:
                raise ValueError(f"{day} {group} 组报告列缺失")
            name, play = next(cells[0].links(), ("", ""))
            play_key = url_key(play)
            matching = [
                (game, entry) for game, entry in remaining[group]
                if name_key(name) in game_names(game)
                and play_key in link_keys(game["play"], entry.get("play_url_aliases", []), url_key)
            ]
            if len(matching) != 1:
                raise ValueError(f"{day} {group} 组作品不能与推荐档案核对：{name or '缺少有效试玩链接'}")
            game, entry = matching[0]
            remaining[group].remove((game, entry))
            source_links = list(cells[3].links())
            if group == "A":
                repository_keys = link_keys(game["repository"], entry.get("repository_aliases", []), repository_key)
                if not repository_keys.intersection(repository_key(url) for _, url in source_links):
                    raise ValueError(f"{day} A 组作品仓库与推荐档案不一致：{game['name']}")
                game["license"], game["license_url"] = license_info(cells[3].plain(), source_links)
            game["summary"] = cells[1].plain()
            game["model"] = cells[2].plain(omit_link_notes=True)
            game["model_url"] = next((url for _, url in cells[2].links()), "")
            game["mobile"], game["mobile_supported"] = device_info([*cells[:2], *cells[3:]])
            games.append(game)

    missing = [game["name"] for pairs in remaining.values() for game, _ in pairs]
    if missing:
        raise ValueError(f"{day} 日报缺少档案中的推荐作品：{', '.join(missing)}")
    return games


def early_games(path: Path, games: list[dict]) -> list[dict]:
    if not games:
        return []
    body = read_body(path)
    remaining = games.copy()
    selected = []
    for card in body.find("article"):
        heading = next(card.find("h3"), None)
        if heading is None:
            continue
        names = {name_key(heading.plain()), name_key(heading.plain().split(" · ", 1)[0])}
        links = list(card.links())
        urls = {url_key(url) for _, url in links}
        repository_urls = {repository_key(url) for _, url in links}
        candidates = [game for game in remaining if names.intersection(game_names(game))]
        if not candidates:
            continue
        matching = [
            game for game in candidates
            if (not game["play"] and not game["repository"])
            or (game["play"] and url_key(game["play"]) in urls)
            or (game["repository"] and repository_key(game["repository"]) in repository_urls)
        ]
        if len(matching) != 1:
            raise ValueError(f"早期汇总无法确认作品身份：{heading.plain()}")
        game = matching[0]
        remaining.remove(game)
        description = next((p for p in card.find("p") if p.attrs.get("class") == "description"), None)
        game["summary"] = description.plain() if description else ""
        for label, value in zip(card.find("dt"), card.find("dd")):
            if label.plain() == "开发模型" and MODEL_NAME.search(value.plain()):
                game["model"] = value.plain()
                game["model_url"] = next((
                    url for text, url in links if re.search(r"模型|制作|开发记录", text)
                ), "")
            if label.plain() == "源码与许可":
                game["license"], game["license_url"] = license_info(value.plain(), links)
        if any("手机试玩" in text for text, _ in links):
            game["mobile"] = "作者提供手机试玩入口"
            game["mobile_supported"] = True
        selected.append(game)
    if remaining:
        raise ValueError(f"早期汇总缺少档案中的推荐作品：{', '.join(game['name'] for game in remaining)}")
    return selected


def read_archive(archive: Path) -> tuple[list[dict], list[dict]]:
    history = json.loads((archive / "history.json").read_text(encoding="utf-8-sig"))
    latest = datetime.fromisoformat(history["updated_at"]).astimezone(timezone(timedelta(hours=8)))
    if not isinstance(history["recommended"], list) or not isinstance(history["leads"], list):
        raise ValueError("history.json 缺少推荐或线索列表")

    dated = defaultdict(list)
    early = []
    seen_play = {}
    seen_repository = {}
    for entry in history["recommended"]:
        if entry["status"] != "recommended":
            continue
        name = public_text(entry["name"]).strip()
        if not name:
            raise ValueError("history.json 有推荐作品名缺失")
        group = entry["group"] or "early"
        day = entry.get("recommended_on") or entry["first_seen"] or ""
        if day and date.fromisoformat(day).isoformat() != day:
            raise ValueError(f"作品的推荐日期格式不正确：{name}")
        game = {
            "name": name,
            "aliases": [public_text(alias).strip() for alias in entry["aliases"] if public_text(alias).strip()],
            "group": group,
            "date": day,
            "play": public_url(entry["play_url"]),
            "repository": public_url(entry["repository_url"]),
            "summary": "",
            "model": "",
            "model_url": "",
            "license": "",
            "license_url": "",
            "mobile": "",
            "mobile_supported": False,
        }
        if group == "early":
            early.append(game)
        elif group in ("A", "B") and day and game["play"] and (bool(game["repository"]) == (group == "A")):
            dated[day].append((game, entry))
        else:
            raise ValueError(f"history.json 的推荐分组、日期或链接不完整：{name}")

        for key in link_keys(game["play"], entry.get("play_url_aliases", []), url_key):
            if key in seen_play:
                raise ValueError(f"推荐档案的试玩链接重复：{seen_play[key]}、{name}")
            seen_play[key] = name
        for key in link_keys(game["repository"], entry.get("repository_aliases", []), repository_key):
            previous = seen_repository.get(key)
            if previous and not (previous["group"] == group == "early" and previous["play"] and game["play"]):
                raise ValueError(f"推荐档案的仓库重复：{previous['name']}、{name}")
            seen_repository[key] = game

    paths = {p.name.removesuffix(REPORT_SUFFIX): p for p in archive.glob(f"????-??-??{REPORT_SUFFIX}")}
    days = sorted(paths, reverse=True)
    current = latest.date().isoformat()
    missing = sorted(dated.keys() - paths.keys())
    if missing:
        raise ValueError(f"推荐档案缺少对应日报：{', '.join(missing)}")
    if not days or days[0] != current:
        raise ValueError(f"最新日报日期与推荐档案不一致，档案更新时间为 {current}")

    games, reports = [], []
    for day in days:
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError(f"日报文件名的日期格式不正确：{day}")
        body = read_body(paths[day])
        daily = daily_games(body, dated[day], day)
        content = public_html(body).strip()
        if not content:
            raise ValueError(f"{day} 日报缺少可发布正文")
        reports.append({
            "date": day,
            "a": sum(game["group"] == "A" for game in daily),
            "b": sum(game["group"] == "B" for game in daily),
            "content": content,
        })
        games.extend(daily)
    games.extend(early_games(archive / EARLY_REPORT, early))
    return sorted(games, key=lambda game: game["date"], reverse=True), reports
