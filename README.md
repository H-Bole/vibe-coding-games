# Vibe Coding 游戏合集

[浏览合集和全部日报](https://h-bole.github.io/vibe-coding-games/)

收录已推荐的 Vibe Coding 网页游戏，按日期更新。网站提供玩法简介、原站试玩链接和查到的开发证据。A 组有公开游戏源码和明确许可证，B 组是截至当期检索未找到公开源码的作品。早期收藏按当时可核对的资料展示。游戏、源码和素材的权利由原作者和各项目许可证决定。

## 本地生成

需要 Python 3.12 或更新版本。把本地日报目录作为输入，其中应有 history.json 和每日 HTML。生成的站点位于 docs/，可以直接打开 docs/index.html。

    python scripts/publish.py --archive "<本地日报目录>"

## 日常发布

GitHub Pages 从 main 分支的 /docs 发布。日报和本地历史核对完成后，在已配置写权限的本仓库执行：

    python scripts/publish.py --archive "<本地日报目录>" --date YYYY-MM-DD --publish

脚本核对日报与档案、更新站点、推送并检查线上首页和指定日期页。反复执行同一天时复用现有档案。若推送失败，修复连接或权限后可用原命令重试，之后的发布也会补入本地已有的日报。若远端有其他改动，先同步 main 并处理冲突，再重新运行。GitHub 接收提交后仍可能需要一点时间更新 Pages。
