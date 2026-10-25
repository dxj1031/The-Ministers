"""把可静态托管的部分同步到 personal-page 仓库，发布到 GitHub Pages。

    python tools/export_snapshot.py && python tools/deploy_pages.py
    # 然后在 personal-page 里 commit + push

线上布局（/ministers/ 这个 URL 早就发布过，不能改）：

    personal-page/ministers/
        index.html      朝堂（没有后端时自动退回演示模式）
        support.js      前端运行时
        console.html    监控台（读同目录的 snapshot.json）
        snapshot.json   本地真实跑出来的数据快照

只复制，不碰 git —— 提交信息值得每次自己写一遍。
"""
import os
import re
import shutil
import sys
from urllib.parse import urlparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = Path(os.environ.get("MINISTERS_PAGES", r"E:\StudyData\work\Personal Page")) / "ministers"

FILES = [
    (ROOT / "app" / "front" / "The Court.dc.html", "index.html"),
    (ROOT / "app" / "front" / "support.js", "support.js"),
    (ROOT / "index.html", "console.html"),
    (ROOT / "snapshot.json", "snapshot.json"),
]


def main():
    if not DEST.parent.exists():
        sys.exit(f"找不到 personal-page 仓库：{DEST.parent}\n用 MINISTERS_PAGES 指定路径。")
    DEST.mkdir(exist_ok=True)
    for src, name in FILES:
        if not src.exists():
            sys.exit(f"缺少 {src}" + ("（先跑 tools/export_snapshot.py）" if name.endswith(".json") else ""))
        old = (DEST / name).read_bytes() if (DEST / name).exists() else None
        if name == "index.html":
            content = src.read_text(encoding="utf-8")
            previous = re.search(r'<meta name="ministers-app" content="([^"]*)">', old.decode("utf-8") if old else "")
            hosted = os.environ.get("MINISTERS_APP_URL", previous[1] if previous else "")
            if hosted:
                url = urlparse(hosted)
                if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
                    sys.exit("MINISTERS_APP_URL must be a public HTTPS court URL without credentials, query or fragment.")
                if any(c in hosted for c in '<>"\''):
                    sys.exit("Invalid hosted court URL.")
            content = content.replace('<meta name="ministers-app" content="">', f'<meta name="ministers-app" content="{hosted}">')
            (DEST / name).write_text(content, encoding="utf-8")
        else:
            shutil.copyfile(src, DEST / name)
        mark = "=" if old == src.read_bytes() else "+"
        print(f" {mark} ministers/{name}  {src.stat().st_size // 1024} KB")
    print(f"\n同步到 {DEST}\n下一步：在 personal-page 里 git add ministers && git commit && git push")


if __name__ == "__main__":
    main()
