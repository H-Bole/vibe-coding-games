"""Generate and publish the static collection from the local daily archive."""

import argparse
from datetime import date
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
import os
import posixpath
import re
import subprocess
import sys
from tempfile import NamedTemporaryFile
from time import sleep
from urllib.parse import quote, unquote, urlsplit
from urllib.request import Request, urlopen

sys.dont_write_bytecode = True
from archive import read_archive
from render import render_site

ROOT = Path(__file__).resolve().parents[1]
REMOTE = "https://github.com/H-Bole/vibe-coding-games.git"
PAGES = "https://h-bole.github.io/vibe-coding-games/"
PRIVATE_TEXT = re.compile(
    r"(?i)(?<![\w:/])[a-z]:[\\/]|file://|codex://|\blocalhost\b|"
    r"127\.0\.0\.1|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|"
    r"sk-(?:proj-)?[A-Za-z0-9_-]{32,}"
)


class PageLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag in {"iframe", "object", "embed", "form", "base"}:
            raise ValueError(f"公开页面出现不支持的标签：{tag}")
        for key, value in attrs:
            if key.startswith("on") or key == "srcdoc":
                raise ValueError(f"公开页面出现不支持的属性：{key}")
            if value and key in {"href", "src"}:
                self.links.append((tag, key, value))


def daily_path(day):
    return f"daily/{day}/index.html"


def site_files(games, reports):
    files = {
        name: re.sub(r"(?m)^[ \t]+$", "", html).encode("utf-8")
        for name, html in render_site(games, reports).items()
    }
    for name in ("style.css", "search.js"):
        files["assets/" + name] = (ROOT / "site" / name).read_bytes()
    files[".nojekyll"] = b""
    expected = {"index.html", "daily/index.html", ".nojekyll", "assets/style.css", "assets/search.js"}
    expected.update(daily_path(report["date"]) for report in reports)
    if set(files) != expected:
        raise ValueError("生成的页面与日报日期不一致")
    for name, contents in files.items():
        text = contents.decode("utf-8")
        if PRIVATE_TEXT.search(text):
            raise ValueError(f"公开文件中有本机路径或非公开内容：{name}")
        if not name.endswith(".html"):
            continue
        parser = PageLinks()
        parser.feed(text)
        parser.close()
        for tag, key, value in parser.links:
            url = urlsplit(value)
            if url.scheme or url.netloc:
                if (tag != "a" or key != "href" or url.scheme not in {"http", "https"}
                        or not url.hostname or url.username is not None):
                    raise ValueError(f"不允许的链接：{name} ({tag})")
                continue
            if not url.path:
                continue
            path = unquote(url.path)
            target = posixpath.normpath(posixpath.join(posixpath.dirname(name), path))
            if target not in files and target.rstrip("/") + "/index.html" not in files:
                raise ValueError(f"站内链接找不到目标：{name} → {value}")
    return files


def write_docs(files):
    docs = ROOT / "docs"
    if docs.is_symlink() or docs.is_junction():
        raise ValueError("docs 指向其他目录，停止生成")
    for current in docs.rglob("*"):
        if current.is_symlink() or current.is_junction():
            raise ValueError(f"docs 中有链接路径：{current.name}")
        if current.is_file() and current.relative_to(docs).as_posix() not in files:
            raise ValueError(f"本地档案未覆盖已有公开文件：{current.relative_to(docs)}")
    changed = 0
    for name, contents in files.items():
        path = docs / name
        if path.exists() and path.read_bytes() == contents:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=path.parent, prefix=".publish-", delete=False) as handle:
            temp = Path(handle.name)
            handle.write(contents)
        try:
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)
        changed += 1
    return changed


def git(*args):
    return subprocess.check_output(
        ["git", "-C", str(ROOT), *args], encoding="utf-8",
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    ).rstrip("\r\n")


def check_checkout(files):
    if git("branch", "--show-current") != "main":
        raise ValueError("发布必须在 main 分支执行")
    # 校验配置值，不使用可能被 Git 重写的远端地址。
    if git("config", "--get-all", "remote.origin.url").lower() != REMOTE.lower():
        raise ValueError("origin 不是预期的游戏合集仓库")
    if git_has_pushurl():
        raise ValueError("origin 另有 pushurl，需先确认发布地址")
    for change in git("status", "--porcelain=v1", "-z", "--untracked-files=all").split("\0"):
        if not change:
            continue
        name = change[3:]
        relative = name.removeprefix("docs/")
        path = ROOT / name
        if (not name.startswith("docs/") or relative not in files
                or not path.is_file() or path.read_bytes() != files[relative]):
            raise ValueError("仓库有其他修改，需先处理再发布")
    git("fetch", "--no-tags", "origin", "main")
    try:
        git("merge-base", "--is-ancestor", "FETCH_HEAD", "HEAD")
    except subprocess.CalledProcessError as error:
        raise ValueError("远端 main 有本地尚未合并的修改，请先同步仓库再重试") from error
    # 只重试推送本工具已经提交的文件，避免顺带上传手动提交。
    for path in git("diff", "--name-only", "FETCH_HEAD", "HEAD", "--").splitlines():
        relative = path.removeprefix("docs/")
        if not path.startswith("docs/") or relative not in files:
            raise ValueError("待推送的提交含有站点文件以外的修改")


def git_has_pushurl():
    return subprocess.run(
        ["git", "-C", str(ROOT), "config", "--get-all", "remote.origin.pushurl"],
        stdout=subprocess.DEVNULL, check=False,
    ).returncode == 0


def push(day):
    git("add", "--", "docs")
    if git("diff", "--cached", "--name-only"):
        git("commit", "-m", f"更新游戏合集与日报 {day}")
    git("push", "origin", "HEAD:refs/heads/main")


def verify_live(files, day):
    # HTML 本身保持可重现，用查询参数避开旧的 CDN 缓存。
    for path in ("index.html", daily_path(day)):
        public_path = path.removesuffix("index.html")
        digest = sha256(files[path]).hexdigest()[:16]
        url = PAGES + quote(public_path, safe="/") + "?v=" + digest
        for attempt in range(10):
            try:
                with urlopen(Request(url, headers={"User-Agent": "Vibe-Coding-Games"}), timeout=8) as page:
                    if page.read() == files[path]:
                        print("已核对线上页面 " + PAGES + public_path)
                        break
            except OSError:
                pass
            if attempt < 9:
                sleep(5)
        else:
            raise ValueError(f"已推送，Pages 尚未确认更新：{PAGES}{public_path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True, help="本地日报及 history.json 的目录")
    parser.add_argument("--date", type=date.fromisoformat, help="必须存在的日报日期")
    parser.add_argument("--publish", action="store_true", help="将生成的网页提交并推送到已配置的站点")
    args = parser.parse_args()
    games, reports = read_archive(args.archive)
    if not reports:
        raise ValueError("档案里没有可发布的日报")
    day = args.date.isoformat() if args.date else reports[0]["date"]
    if day not in {report["date"] for report in reports}:
        raise ValueError(f"{day} 的日报缺失")
    files = site_files(games, reports)
    if args.publish:
        check_checkout(files)
    changed = write_docs(files)
    print(f"已生成 {len(games)} 款合集、{len(reports)} 期日报，更新 {changed} 个文件")
    if args.publish:
        push(day)
        verify_live(files, day)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        print(f"Git 操作未完成（{error.cmd[-1]}，退出码 {error.returncode}）。本地档案已保留。", file=sys.stderr)
        sys.exit(1)
    except (ValueError, OSError) as error:
        print(error, file=sys.stderr)
        sys.exit(1)
