"""収集した記事を Gemini API（無料枠）で日本語ブリーフィングにまとめる。"""

from __future__ import annotations

import copy
import json
import os
import time

import requests

from .fetch import Article

MODEL = os.environ.get("GEMINI_MODEL") or "gemini-3.8-flash"
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

SYSTEM_PROMPT = """\
あなたはソフトウェアエンジニア向けのテックニュース編集者です。
与えられた記事リスト（過去24時間程度に公開されたもの）から、日本のエンジニアが朝に読む
デイリーブリーフィングを作成してください。

方針:
- 対象読者は AI を活用して開発するソフトウェアエンジニア。実務への影響が大きいものを優先する。
- 新モデル・新機能・料金変更・破壊的変更・セキュリティ関連・主要ツールのリリースは重要度が高い。
- Hacker News など雑多なソースからは、AI・開発環境・プログラミングに関係するものだけを拾う。
- マイナーなパッチリリース（バグ修正のみ）はまとめて1件にするか、重要でなければ省略してよい。
- 同じ話題を扱う複数の記事は1件にまとめ、最も一次情報に近い URL を採用する。
- URL は入力に含まれるものだけを使い、創作しない。
- 要約は日本語で1〜2文、何が変わったか・なぜ重要かが分かるように書く。
- highlights は今日特に読むべき 3〜5 件。highlights に入れた記事は sections にも重複して載せない。
- sections は「AI・LLM」「AIコーディングツール」「開発環境・言語・プラットフォーム」
  「開発Tips・VS Code活用」を基本とし、
  該当記事がないセクションは出力しない。
- category=tips の記事や VS Code 関連の記事からは、VS Code で開発する読者が明日から試せる
  実践的な情報（便利な拡張機能・設定・ショートカット、AI コーディングツールの使いこなし、
  開発ワークフローやテスト・デバッグの効率化手法など）を優先して拾う。
  ポエムや初心者向けの環境構築手順、宣伝目的の記事は除外する。
  要約には「何ができるようになるか・どう使うか」を含める。
- 記事がほとんどない日は、無理に件数を増やさず、少ないまま出力する。
"""

ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "日本語の見出し（簡潔に）"},
        "url": {"type": "string"},
        "summary": {"type": "string", "description": "日本語で1〜2文の要約"},
    },
    "required": ["title", "url", "summary"],
}

BRIEFING_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "今日の動向を一言で表すリード文（日本語1文）"},
        "highlights": {"type": "array", "items": ITEM_SCHEMA},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "items": {"type": "array", "items": ITEM_SCHEMA},
                },
                "required": ["name", "items"],
            },
        },
    },
    "required": ["headline", "highlights", "sections"],
}


def _format_articles(articles: list[Article]) -> str:
    lines = []
    for i, a in enumerate(articles, 1):
        lines.append(
            f"[{i}] source={a.source} category={a.category} "
            f"published={a.published:%Y-%m-%d %H:%M}Z\n"
            f"title: {a.title}\nurl: {a.url}\nexcerpt: {a.excerpt}\n"
        )
    return "\n".join(lines)


def _post_with_retry(url: str, headers: dict, body: dict, attempts: int = 4) -> dict:
    """無料枠のレート制限（429）や一時的な 5xx に備えてリトライする。"""
    for attempt in range(attempts):
        resp = requests.post(url, headers=headers, json=body, timeout=180)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code in (429, 500, 502, 503, 504) and attempt < attempts - 1:
            wait = 30 * (attempt + 1)
            print(f"[warn] Gemini API {resp.status_code}、{wait} 秒後に再試行します")
            time.sleep(wait)
            continue
        raise RuntimeError(f"Gemini API error {resp.status_code}: {resp.text[:1000]}")
    raise AssertionError("unreachable")


def summarize(articles: list[Article]) -> dict:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY が設定されていません")

    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{
            "role": "user",
            "parts": [{"text": f"以下が収集した記事です（{len(articles)} 件）。\n\n{_format_articles(articles)}"}],
        }],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": copy.deepcopy(BRIEFING_SCHEMA),
        },
    }
    data = _post_with_retry(
        ENDPOINT.format(model=MODEL),
        {"x-goog-api-key": api_key, "Content-Type": "application/json"},
        body,
    )
    print(f"[info] model={MODEL} usage={data.get('usageMetadata')}")

    block = data.get("promptFeedback", {}).get("blockReason")
    if block:
        raise RuntimeError(f"Gemini blocked the prompt: {block}")
    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError(f"Gemini returned no candidates: {json.dumps(data)[:1000]}")
    candidate = candidates[0]
    if candidate.get("finishReason") not in (None, "STOP"):
        raise RuntimeError(f"Gemini finished abnormally: {candidate.get('finishReason')}")

    # 思考（thought）パートを除いた本文だけを取り出す
    text = "".join(
        p.get("text", "") for p in candidate["content"]["parts"] if not p.get("thought")
    )
    return json.loads(text)
