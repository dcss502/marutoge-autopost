"""まるとげの自動投稿（B2-6）：インスタ・Threads のキーを確かめる／更新する。

使い方（GitHub Actions から呼ぶ。キーは環境変数で渡し、画面には出さない）:
  python scripts/tokens.py check     … 両方のキーで自分のアカウント名が読めるか確かめる
  python scripts/tokens.py refresh   … 両方のキーを更新し、GitHub の秘密の設定（Secrets）を書き換える
"""
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request

IG = {"name": "インスタ", "secret": "IG_TOKEN",
      "me": "https://graph.instagram.com/v21.0/me?fields=user_id,username",
      "refresh": "https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token"}
TH = {"name": "Threads", "secret": "THREADS_TOKEN",
      "me": "https://graph.threads.net/v1.0/me?fields=id,username",
      "refresh": "https://graph.threads.net/refresh_access_token?grant_type=th_refresh_token"}


def get(url, token):
    full = url + "&access_token=" + urllib.parse.quote(token)
    try:
        with urllib.request.urlopen(full, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        # エラーの本文にキーは入らないので、そのまま出してよい
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:500]}")


def check():
    ok = True
    for s in (IG, TH):
        token = os.environ.get(s["secret"], "")
        if not token:
            print(f"{s['name']}: {s['secret']} が入っていない"); ok = False; continue
        try:
            me = get(s["me"], token)
            uid = me.get("user_id") or me.get("id")
            print(f"{s['name']}: OK  @{me.get('username')}  ID={uid}")
        except Exception as e:
            print(f"{s['name']}: NG  {e}"); ok = False
    return ok


def refresh():
    ok = True
    for s in (IG, TH):
        token = os.environ.get(s["secret"], "")
        if not token:
            print(f"{s['name']}: {s['secret']} が入っていない"); ok = False; continue
        try:
            res = get(s["refresh"], token)
            new = res["access_token"]
            days = int(res.get("expires_in", 0)) // 86400
            # 新しいキーを Secrets に書き戻す（GH_TOKEN に Secrets を書ける権限のキーが要る）
            subprocess.run(["gh", "secret", "set", s["secret"], "--body", new], check=True,
                           stdout=subprocess.DEVNULL)
            print(f"{s['name']}: 更新した（あと{days}日）")
        except Exception as e:
            print(f"{s['name']}: 更新できなかった  {e}"); ok = False
    return ok


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    sys.exit(0 if (check() if cmd == "check" else refresh()) else 1)
