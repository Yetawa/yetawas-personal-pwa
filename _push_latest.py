# -*- coding: utf-8 -*-
"""把最新生成的行情快照推送到 GitHub（Contents API，避免 git push 直连）。

用法（在 Bash 里先取到 token，再注入环境变量）：
    GH_TOKEN=xxxx python _push_latest.py
    GH_TOKEN=xxxx python _push_latest.py sector_data.json fish_snapshot.json

不带参数时默认推送 5 个文件：
    sector_data.json / sector_dashboard.html / fish_snapshot.json
    / fish_model.json / pivot_snapshot.json
"""
import base64
import json
import os
import sys
import urllib.request

OWNER, REPO, BRANCH = "Yetawa", "yetawas-personal-pwa", "main"
DEFAULT_FILES = [
    "sector_data.json",
    "sector_dashboard.html",
    "fish_snapshot.json",
    "fish_model.json",
    "pivot_snapshot.json",
]
API = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/"


def _req(url, token, method="GET", payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "fund-arb-push")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def sha_of(path, token):
    try:
        d = _req(f"{API}{path}?ref={BRANCH}", token)
        return d.get("sha")
    except Exception as e:
        if "404" in str(e):
            return None
        raise


def push(path, token, message):
    if not os.path.exists(path):
        print(f"  ! 本地缺失，跳过 {path}")
        return False
    raw = open(path, "rb").read()
    sha = sha_of(path, token)
    payload = {
        "message": message,
        "content": base64.b64encode(raw).decode(),
        "branch": BRANCH,
    }
    if sha:
        payload["sha"] = sha
    try:
        out = _req(API + path, token, method="PUT", payload=payload)
    except Exception as e:
        print(f"  x {path} 失败: {e}")
        return False
    commit = (out.get("commit") or {}).get("sha", "")[:10]
    print(f"  √ {path} -> {commit}")
    return True


def main():
    token = os.environ.get("GH_TOKEN", "").strip()
    if not token:
        print("缺少 GH_TOKEN 环境变量")
        sys.exit(1)
    files = sys.argv[1:] or DEFAULT_FILES
    msg = os.environ.get("PUSH_MSG", "chore(data): daily close snapshots 2026-10-29")
    print(f"推送 {len(files)} 个文件到 {OWNER}/{REPO}@{BRANCH}：")
    ok = sum(push(f, token, msg) for f in files)
    print(f"完成 {ok}/{len(files)}")
    sys.exit(0 if ok == len(files) else 2)


if __name__ == "__main__":
    main()
