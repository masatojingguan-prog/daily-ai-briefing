# daily-ai-briefing

毎朝、AI 関連ニュースと開発環境（言語・ツール・プラットフォーム）の最新情報を収集し、
Gemini API（無料枠）で日本語のブリーフィングにまとめて、指定した Slack チャンネルに投稿します。

```
RSS / Atom (sources.toml) ──▶ 直近26時間の記事を抽出 ──▶ Gemini で選別・日本語要約 ──▶ Slack（指定チャンネル）
```

GitHub Actions で毎朝 7:00 JST に実行されます（`.github/workflows/daily-briefing.yml`）。

## 費用

すべて無料枠内で動きます。

| 要素 | 無料の根拠 |
|---|---|
| GitHub Actions | 公開リポジトリは無料（1回あたり約1分） |
| Gemini API | Google AI Studio の無料枠（1日1リクエストのみ使用） |
| Slack | 無料プランでも自作アプリ（Bot）を利用可能 |

> Gemini の無料枠では、送信した内容が Google のサービス改善に使われる場合があります。
> 送るのは公開ニュースの見出しと抜粋だけです。

## セットアップ

### 1. Gemini API キー

1. [Google AI Studio](https://aistudio.google.com/apikey) で API キーを作成します（クレジットカード不要）。

### 2. Slack アプリ（投稿先チャンネルを指定するため）

1. <https://api.slack.com/apps> → **Create New App** → **From scratch** でアプリを作成します。
2. **OAuth & Permissions** → **Bot Token Scopes** に `chat:write` を追加します。
3. **Install to Workspace** を実行し、表示された **Bot User OAuth Token**（`xoxb-...`）を控えます。
4. 投稿したいチャンネルで `/invite @アプリ名` を実行し、Bot をチャンネルに招待します。

### 3. GitHub に登録

リポジトリの **Settings → Secrets and variables → Actions** で登録します。

| 種類 | 名前 | 内容 |
|---|---|---|
| Secret | `GEMINI_API_KEY` | 手順1のキー |
| Secret | `SLACK_BOT_TOKEN` | 手順2の `xoxb-...` |
| Variable | `SLACK_CHANNEL` | 投稿先。`#ai-news` やチャンネル ID（`C0123456789`）。個人宛ての DM にするならメンバー ID（`U0123456789`）。カンマ区切りで複数指定可 |
| Variable（任意） | `GEMINI_MODEL` | 使うモデル（未設定なら `gemini-3.8-flash`） |
| Secret（任意） | `TEAMS_WEBHOOK_URL` | Teams にも投稿する場合 |

投稿先を変えたいときは、`SLACK_CHANNEL` を書き換えるだけで済みます。

### 4. 動作確認

**Actions → Daily AI Briefing → Run workflow** で手動実行します。
`dry_run` にチェックを入れると、投稿せずにログに出力します。

## 収集対象の変更

`sources.toml` に `[[feeds]]` を追加・削除するだけです。`category` は `ai` / `tools` / `dev` / `mixed`
のいずれか（要約時のヒントとして使われます）。GitHub リポジトリのリリースは
`https://github.com/<owner>/<repo>/releases.atom` で追加できます。

## ローカル実行

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt     # macOS/Linux: .venv/bin/pip

python -m briefing.main --fetch-only   # 記事収集だけ（API キー不要）
python -m briefing.main --dry-run      # 要約まで行い、投稿せずに表示（GEMINI_API_KEY が必要）
python -m briefing.main                # 投稿まで（SLACK_BOT_TOKEN と SLACK_CHANNEL も必要）
```

## トラブルシューティング

| エラー | 対処 |
|---|---|
| `not_in_channel` | Bot をチャンネルに招待する（`/invite @アプリ名`） |
| `channel_not_found` | チャンネル名か ID を確認する。非公開チャンネルは Bot の招待が必要 |
| `missing_scope` | `chat:write` スコープを追加してアプリを再インストールする |
| Gemini API `429` | 無料枠のレート制限。自動で再試行し、続く場合は `GEMINI_MODEL` を `gemini-3.5-flash-lite` などに変える |
| Gemini API `404` | モデル名が廃止された可能性がある。`GEMINI_MODEL` を[無料枠の対象モデル](https://ai.google.dev/gemini-api/docs/pricing)に変える |
