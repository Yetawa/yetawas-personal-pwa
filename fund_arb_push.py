import json
import sys
import subprocess

DATE = "2026-07-28"
BASE = "https://fund-arb.onrender.com"
CHAT = "oc_6e928adc4dea6453246716402bd52ed4"
LARK = "/c/Users/USER/.workbuddy/binaries/node/cli-connector-packages/lark-cli"
TO = 280  # 冷算 compute_ranking 约 68s，若无机会心跳分支再算一次约 136s，故放宽超时


def http(method, url):
    """用 curl 取数（沙箱内 urllib 连不上 Render，curl 可通）。"""
    try:
        r = subprocess.run(
            ["curl", "-sS", "--max-time", str(TO), "-X", method, url],
            capture_output=True, text=True, timeout=TO + 20,
        )
        return r.stdout, r.returncode
    except Exception as e:  # noqa
        return "", 1


# 步骤5：取推送文案（服务端用与云端完全相同的算法生成；网页2部分冷算约 68s）
body, rc = http("GET", f"{BASE}/api/push/text?date={DATE}")
print(f"push/text curl_rc={rc} bytes={len(body)}")
try:
    text = json.loads(body).get("text") or ""
except Exception:
    text = ""
print("TEXT_LEN", len(text))

if not text.strip():
    print("NO_OPPORTUNITY: 今日无 |溢价|>阈值 的套利机会，释放锁留给云端")
    http("POST", f"{BASE}/api/push/unlock?date={DATE}")
    sys.exit(0)

print("========= PUSH TEXT PREVIEW =========")
print(text)
print("=====================================")

# 步骤6：发送
r = subprocess.run(
    [LARK, "im", "+messages-send", "--as", "bot", "--chat-id", CHAT, "--text", text],
    capture_output=True, text=True,
)
print("SEND_RC", r.returncode)
print("STDOUT:", r.stdout.strip()[-2000:])
print("STDERR:", r.stderr.strip()[-2000:])

if r.returncode != 0:
    print("SEND_FAILED: 释放锁让云端补推")
    http("POST", f"{BASE}/api/push/unlock?date={DATE}")
    sys.exit(1)

print("SEND_OK: 锁保持占用，云端调度器将跳过本次")
