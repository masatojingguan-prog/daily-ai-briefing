"""ブリーフィングを Slack / Microsoft Teams の Incoming Webhook に投稿する。"""

from __future__ import annotations

import requests


def _slack_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _slack_item(item: dict) -> str:
    return f"• *<{item['url']}|{_slack_escape(item['title'])}>*\n　{_slack_escape(item['summary'])}"


def _section_blocks(text_lines: list[str]) -> list[dict]:
    """Slack の section ブロックは 3000 文字上限なので分割する。"""
    blocks, buf = [], ""
    for line in text_lines:
        if buf and len(buf) + len(line) + 1 > 2900:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": buf}})
            buf = ""
        buf = f"{buf}\n{line}" if buf else line
    if buf:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": buf}})
    return blocks


def build_slack_payload(briefing: dict, date_str: str, footer: str) -> dict:
    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": f"📰 AI・開発 デイリーブリーフィング {date_str}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": _slack_escape(briefing["headline"])}},
    ]
    if briefing["highlights"]:
        blocks.append({"type": "divider"})
        blocks += _section_blocks(["*🔥 今日のハイライト*"] + [_slack_item(i) for i in briefing["highlights"]])
    for section in briefing["sections"]:
        if not section["items"]:
            continue
        blocks.append({"type": "divider"})
        blocks += _section_blocks([f"*{_slack_escape(section['name'])}*"] + [_slack_item(i) for i in section["items"]])
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": footer}]})
    # Slack は 1 メッセージ 50 ブロックまで
    return {"text": f"AI・開発 デイリーブリーフィング {date_str}", "blocks": blocks[:50]}


def build_teams_payload(briefing: dict, date_str: str, footer: str) -> dict:
    """Teams の Workflows（Power Automate）Webhook 向け Adaptive Card。"""

    def item_block(item: dict) -> dict:
        return {"type": "TextBlock", "wrap": True, "text": f"- **[{item['title']}]({item['url']})**  \n{item['summary']}"}

    body: list[dict] = [
        {"type": "TextBlock", "size": "Large", "weight": "Bolder", "wrap": True,
         "text": f"📰 AI・開発 デイリーブリーフィング {date_str}"},
        {"type": "TextBlock", "wrap": True, "text": briefing["headline"]},
    ]
    groups = [("🔥 今日のハイライト", briefing["highlights"])] + [(s["name"], s["items"]) for s in briefing["sections"]]
    for name, items in groups:
        if not items:
            continue
        body.append({"type": "TextBlock", "size": "Medium", "weight": "Bolder", "separator": True,
                     "spacing": "Large", "wrap": True, "text": name})
        body += [item_block(i) for i in items]
    body.append({"type": "TextBlock", "isSubtle": True, "size": "Small", "wrap": True, "text": footer})
    return {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.4",
                "msteams": {"width": "Full"},
                "body": body,
            },
        }],
    }


def post_slack(token: str, channel: str, payload: dict) -> None:
    """Slack Bot トークンで指定チャンネルに投稿する（chat.postMessage）。"""
    resp = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {token}"},
        json={"channel": channel, "unfurl_links": False, "unfurl_media": False, **payload},
        timeout=30,
    )
    data = resp.json()
    if not data.get("ok"):
        hint = {
            "not_in_channel": "Bot をチャンネルに招待してください（/invite @アプリ名）",
            "channel_not_found": "チャンネル名/ID を確認してください。非公開チャンネルは Bot の招待が必要です",
            "invalid_auth": "SLACK_BOT_TOKEN（xoxb-...）を確認してください",
            "missing_scope": "Slack アプリに chat:write スコープを付けて再インストールしてください",
        }.get(data.get("error"), "")
        raise RuntimeError(f"Slack error: {data.get('error')} {hint}")


def post(url: str, payload: dict) -> None:
    resp = requests.post(url, json=payload, timeout=30)
    if resp.status_code >= 300:
        raise RuntimeError(f"Webhook failed ({resp.status_code}): {resp.text[:500]}")
