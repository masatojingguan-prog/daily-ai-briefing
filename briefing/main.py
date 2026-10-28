"""エントリポイント: 収集 → 要約 → 配信。

使い方:
    python -m briefing.main            # 収集・要約して Webhook に投稿
    python -m briefing.main --dry-run  # 投稿せずにペイロードを表示
    python -m briefing.main --fetch-only  # 収集結果だけ表示（API を呼ばない）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import notify
from .fetch import collect
from .summarize import summarize

JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "sources.toml"))
    parser.add_argument("--dry-run", action="store_true", help="Webhook に投稿せず内容を表示する")
    parser.add_argument("--fetch-only", action="store_true", help="記事の収集だけ行う")
    args = parser.parse_args()

    config = tomllib.loads(Path(args.config).read_text(encoding="utf-8"))
    articles, failures = collect(config)
    print(f"[info] 合計 {len(articles)} 件（取得失敗 {len(failures)} フィード）")

    if args.fetch_only:
        for a in articles:
            print(f"- [{a.source}] {a.title}\n  {a.url}")
        return 0
    if not articles:
        print("[info] 新着記事がないため終了します")
        return 0

    briefing = summarize(articles)

    date_str = datetime.now(JST).strftime("%Y-%m-%d (%a)")
    footer = f"{len(config['feeds'])} フィード / {len(articles)} 記事から自動生成"
    if failures:
        footer += f"　⚠️ 取得失敗: {', '.join(failures)}"

    slack_token = os.environ.get("SLACK_BOT_TOKEN")
    # カンマ区切りで複数指定可（例: "#ai-news,C0123456789"）
    slack_channels = [c.strip() for c in os.environ.get("SLACK_CHANNEL", "").split(",") if c.strip()]
    teams_url = os.environ.get("TEAMS_WEBHOOK_URL")

    targets = []
    if slack_token and slack_channels:
        payload = notify.build_slack_payload(briefing, date_str, footer)
        for ch in slack_channels:
            targets.append((f"Slack {ch}", lambda ch=ch: notify.post_slack(slack_token, ch, payload)))
    if teams_url:
        payload_teams = notify.build_teams_payload(briefing, date_str, footer)
        targets.append(("Teams", lambda: notify.post(teams_url, payload_teams)))

    if args.dry_run or not targets:
        if not args.dry_run:
            print("[warn] 投稿先（SLACK_BOT_TOKEN + SLACK_CHANNEL / TEAMS_WEBHOOK_URL）が未設定のため投稿しません")
        print(json.dumps(briefing, ensure_ascii=False, indent=2))
        return 0

    errors = []
    for name, send in targets:
        try:
            send()
            print(f"[info] {name} に投稿しました")
        except Exception as e:
            print(f"[error] {name}: {e}")
            errors.append(name)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
