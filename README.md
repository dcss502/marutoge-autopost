# marutoge-autopost

まるとげ（インスタ・Threads）の自動投稿。Addness のゴール B2-6 / B2-6-3。

- `scripts/tokens.py` … キーの確認（check）と更新（refresh）
- `.github/workflows/tokens.yml` … 手で動かすと確認。毎週月曜に自動で更新
- Secrets：`IG_TOKEN`・`THREADS_TOKEN`（Metaで発行したキー）、`GH_PAT`（Secrets を書き換えるためのキー）。キーはここに書かない
