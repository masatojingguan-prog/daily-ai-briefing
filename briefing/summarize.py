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

SELECT_PROMPT = """\
あなたはソフトウェアエンジニア向けのテックニュース編集者です。
与えられた記事リスト（番号・カテゴリ・収集元・タイトル）から、デイリーブリーフィングに載せる
記事を選んでください。

方針:
- 対象読者は AI を活用して VS Code で開発するソフトウェアエンジニア。実務への影響が大きいものを優先する。
- 新モデル・新機能・料金変更・破壊的変更・セキュリティ関連・主要ツールのリリースは重要度が高い。
- category=tips は、明日から試せる実践的な情報（拡張機能・設定・ショートカット、AI コーディングツールの
  使いこなし、開発ワークフローの効率化など）を優先し、ポエム・初心者向け手順・宣伝は選ばない。
- category=mixed は AI・開発環境・プログラミングに関係するものだけを選ぶ。
- 同じ話題の記事が複数あれば、最も一次情報に近いもの1件だけを選ぶ。
- 各カテゴリから最大 {limit} 件。重要な記事が少なければ少なくてよい。
- 選んだ記事の番号を selected に返す。
"""

SELECT_SCHEMA = {
    "type": "object",
    "properties": {"selected": {"type": "array", "items": {"type": "integer"}}},
    "required": ["selected"],
}

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
    """無料枠のレート制限（429）や一時的な 5xx・タイムアウトに備えてリトライする。"""
    for attempt in range(attempts):
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=300)
        except (requests.Timeout, requests.ConnectionError) as e:
            if attempt == attempts - 1:
                raise
            wait = 30 * (attempt + 1)
            print(f"[warn] Gemini API に接続できませんでした（{type(e).__name__}）、{wait} 秒後に再試行します")
            time.sleep(wait)
            continue
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code in (429, 500, 502, 503, 504) and attempt < attempts - 1:
            wait = 30 * (attempt + 1)
            print(f"[warn] Gemini API {resp.status_code}、{wait} 秒後に再試行します")
            time.sleep(wait)
            continue
        raise RuntimeError(f"Gemini API error {resp.status_code}: {resp.text[:1000]}")
    raise AssertionError("unreachable")


def _generate(system_prompt: str, user_text: str, schema: dict) -> dict:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY が設定されていません")

    body = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": copy.deepcopy(schema),
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


def select(articles: list[Article], limit: int) -> list[Article]:
    """タイトルだけを渡して、カテゴリごとに重要な記事を最大 limit 件選ばせる。"""
    lines = [f"[{i}] category={a.category} source={a.source} title: {a.title}"
             for i, a in enumerate(articles, 1)]
    result = _generate(
        SELECT_PROMPT.format(limit=limit),
        f"以下が収集した記事です（{len(articles)} 件）。\n\n" + "\n".join(lines),
        SELECT_SCHEMA,
    )

    # 範囲外・重複の番号を除き、カテゴリごとの上限もこちらで守る
    selected: list[Article] = []
    counts: dict[str, int] = {}
    seen: set[int] = set()
    for n in result.get("selected", []):
        if not isinstance(n, int) or not 1 <= n <= len(articles) or n in seen:
            continue
        seen.add(n)
        a = articles[n - 1]
        if counts.get(a.category, 0) < limit:
            counts[a.category] = counts.get(a.category, 0) + 1
            selected.append(a)
    if not selected:
        raise RuntimeError("Gemini が記事を1件も選びませんでした")
    return selected


def summarize(articles: list[Article]) -> dict:
    return _generate(
        SYSTEM_PROMPT,
        f"以下が収集した記事です（{len(articles)} 件）。\n\n{_format_articles(articles)}",
        BRIEFING_SCHEMA,
    )
