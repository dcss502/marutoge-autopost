"""まるとげの自動投稿（B2-6-4）：投稿リスト（queue/<期間>/queue.json）を読み、時刻になった投稿をインスタ・Threadsへ出す。

- 出すのは approved が true の週の、skip が false の投稿だけ。X は当面手で予約するので出さない
- 予定の時刻を過ぎていて、遅れが MAX_LATE_MIN 分以内のものだけ出す（Actions が止まっていた後に古い投稿をまとめて出さないため）
- 出した結果は state/posted.json に残し、同じ投稿を二度出さない。失敗は3回まで次の回に出し直す
- 画像・動画は GitHub Pages の公開URL（PAGES_BASE）から API に取りに来てもらう

使い方（GitHub Actions から。キーは環境変数）:
  python scripts/post.py               … 時刻になった投稿を出す
  python scripts/post.py --dry-run     … 出すはずの投稿を表示するだけ
  python scripts/post.py --only 20261020-0730-P32 [--platform instagram|threads] [--now]
                                       … 指定の1本だけ（--now で時刻を待たずに出す。テスト投稿用）
"""
import argparse
import datetime as dt
import glob
import json
import os
import sys
import time
import urllib.parse
import urllib.request

JST = dt.timezone(dt.timedelta(hours=9))
MAX_LATE_MIN = 90
MAX_TRIES = 3
PAGES_BASE = os.environ.get("PAGES_BASE", "https://dcss502.github.io/marutoge-autopost").rstrip("/")
STATE = "state/posted.json"
IG_API = "https://graph.instagram.com/v21.0"
TH_API = "https://graph.threads.net/v1.0"


def call(method, url, params):
    data = urllib.parse.urlencode(params).encode()
    if method == "GET":
        req = urllib.request.Request(url + "?" + data.decode())
    else:
        req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:500]}")


def media_url(period, path):
    return f"{PAGES_BASE}/queue/{period}/{urllib.parse.quote(path)}"


# ---------- インスタ ----------
def ig_wait(cid, token, minutes):
    # 動画は処理に時間がかかるので、FINISHED になるまで待つ
    for _ in range(minutes * 6):
        st = call("GET", f"{IG_API}/{cid}", {"fields": "status_code,status", "access_token": token})
        code = st.get("status_code")
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"インスタの処理に失敗: {st}")
        time.sleep(10)
    raise RuntimeError("インスタの処理が時間内に終わらなかった")


def post_instagram(p, period):
    token = os.environ["IG_TOKEN"]
    uid = call("GET", f"{IG_API}/me", {"fields": "user_id", "access_token": token})["user_id"]
    ig = p["instagram"]
    urls = [media_url(period, m) for m in ig["media"]]
    base = {"access_token": token}
    if ig["type"] == "reel":
        cid = call("POST", f"{IG_API}/{uid}/media", {**base, "media_type": "REELS", "video_url": urls[0],
                                                       "caption": ig["caption"], "share_to_feed": "true"})["id"]
        ig_wait(cid, token, 10)
    elif ig["type"] == "carousel":
        kids = []
        for u in urls:
            k = call("POST", f"{IG_API}/{uid}/media", {**base, "image_url": u, "is_carousel_item": "true"})["id"]
            ig_wait(k, token, 3); kids.append(k)
        cid = call("POST", f"{IG_API}/{uid}/media", {**base, "media_type": "CAROUSEL", "children": ",".join(kids),
                                                       "caption": ig["caption"]})["id"]
        ig_wait(cid, token, 3)
    else:
        cid = call("POST", f"{IG_API}/{uid}/media", {**base, "image_url": urls[0], "caption": ig["caption"]})["id"]
        ig_wait(cid, token, 3)
    return call("POST", f"{IG_API}/{uid}/media_publish", {**base, "creation_id": cid})["id"]


# ---------- Threads ----------
def post_threads(p, period):
    token = os.environ["THREADS_TOKEN"]
    th = p["threads"]
    urls = [media_url(period, m) for m in th["media"]]
    base = {"access_token": token}
    body = {"text": th["text"]}
    if th.get("topic"):
        body["topic_tag"] = th["topic"]
    if len(urls) >= 2:
        kids = [call("POST", f"{TH_API}/me/threads", {**base, "media_type": "IMAGE", "image_url": u,
                                                      "is_carousel_item": "true"})["id"] for u in urls]
        time.sleep(30)
        cid = call("POST", f"{TH_API}/me/threads", {**base, **body, "media_type": "CAROUSEL",
                                                    "children": ",".join(kids)})["id"]
    else:
        cid = call("POST", f"{TH_API}/me/threads", {**base, **body, "media_type": "IMAGE", "image_url": urls[0]})["id"]
    time.sleep(30)  # 公式のおすすめ：作ってから公開まで30秒ほど待つ
    return call("POST", f"{TH_API}/me/threads_publish", {**base, "creation_id": cid})["id"]


POSTERS = {"instagram": post_instagram, "threads": post_threads}


def load_state():
    if os.path.exists(STATE):
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1, sort_keys=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only")
    ap.add_argument("--platform", choices=list(POSTERS))
    ap.add_argument("--now", action="store_true")
    a = ap.parse_args()

    now = dt.datetime.now(JST)
    platforms = [a.platform] if a.platform else list(POSTERS)
    missing = [k for k in ("IG_TOKEN", "THREADS_TOKEN") if not os.environ.get(k)]
    dry = a.dry_run or bool(missing)
    if missing and not a.dry_run:
        print(f"キーがまだ入っていない（{', '.join(missing)}）ので、投稿はせず表示だけにする")

    state = load_state()
    failed = False
    for qf in sorted(glob.glob("queue/*/queue.json")):
        with open(qf, encoding="utf-8-sig") as f:
            q = json.load(f)
        if not q.get("approved") and not a.only:
            continue
        for p in q["posts"]:
            if a.only and p["id"] != a.only:
                continue
            if p.get("skip") and not a.only:
                continue
            at = dt.datetime.fromisoformat(p["at"])
            late = (now - at).total_seconds() / 60
            if not (a.only and a.now) and not (0 <= late <= MAX_LATE_MIN):
                continue
            for pf in platforms:
                rec = state.setdefault(p["id"], {}).setdefault(pf, {"tries": 0})
                if rec.get("posted_id") or rec["tries"] >= MAX_TRIES:
                    continue
                label = f"{p['id']} {pf}（{p['folder']}）"
                if dry:
                    print(f"[表示だけ] {label} を出す予定"); continue
                rec["tries"] += 1
                try:
                    rec["posted_id"] = POSTERS[pf](p, q["period"])
                    rec["posted_at"] = dt.datetime.now(JST).isoformat(timespec="seconds")
                    rec.pop("error", None)
                    print(f"出した: {label}")
                except Exception as e:
                    rec["error"] = str(e)[:500]
                    failed = True
                    print(f"失敗（{rec['tries']}回目）: {label}  {e}")
                save_state(state)
    if not dry:
        save_state(state)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
