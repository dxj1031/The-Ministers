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
import shutil
import sys
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
        shutil.copyfile(src, DEST / name)
        mark = "=" if old == src.read_bytes() else "+"
        print(f" {mark} ministers/{name}  {src.stat().st_size // 1024} KB")
    print(f"\n同步到 {DEST}\n下一步：在 personal-page 里 git add ministers && git commit && git push")


if __name__ == "__main__":
    main()
