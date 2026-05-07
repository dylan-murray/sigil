import json
import logging
import os
import urllib.request
import urllib.error
from dataclasses import dataclass, field

from sigil.core.config import Config

logger = logging.getLogger(__name__)


@dataclass
class RunSummary:
    pr_count: int
    issue_count: int
    pr_urls: list[str] = field(default_factory=list)
    issue_urls: list[str] = field(default_factory=list)
    success_count: int = 0
    failure_count: int = 0
    cost_usd: float = 0.0
    model: str = ""


def _resolve_webhook_url(config: Config, key: str, env_var: str) -> str:
    notifications = getattr(config, "notifications", None)
    if isinstance(notifications, dict):
        url = notifications.get(key, "")
        if url:
            return url
    return os.environ.get(env_var, "")


def _should_send(summary: RunSummary, config: Config) -> bool:
    notifications = getattr(config, "notifications", None)
    threshold = "on_results"
    if isinstance(notifications, dict):
        threshold = notifications.get("threshold", "on_results")
    if threshold == "always":
        return True
    return summary.pr_count + summary.issue_count > 0


async def send_notifications(
    summary: RunSummary,
    config: Config,
    *,
    no_notify: bool = False,
) -> None:
    if no_notify:
        logger.debug("Notifications suppressed by --no-notify flag")
        return

    slack_url = _resolve_webhook_url(config, "slack", "SIGIL_SLACK_WEBHOOK")
    discord_url = _resolve_webhook_url(config, "discord", "SIGIL_DISCORD_WEBHOOK")

    if not slack_url and not discord_url:
        logger.debug("No notification webhooks configured — skipping")
        return

    if not _should_send(summary, config):
        logger.debug("Threshold is 'on_results' and no PRs/issues — skipping notifications")
        return

    if slack_url:
        try:
            _send_slack(slack_url, summary)
        except Exception:
            logger.warning("Slack notification failed", exc_info=True)

    if discord_url:
        try:
            _send_discord(discord_url, summary)
        except Exception:
            logger.warning("Discord notification failed", exc_info=True)


def _send_slack(webhook_url: str, summary: RunSummary) -> None:
    payload = _build_slack_payload(summary)
    _post_json(webhook_url, payload)


def _send_discord(webhook_url: str, summary: RunSummary) -> None:
    payload = _build_discord_payload(summary)
    _post_json(webhook_url, payload)


def _post_json(url: str, payload: dict) -> None:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            _ = resp.read()
    except urllib.error.URLError as e:
        logger.warning("Webhook POST failed: %s", e)
        raise


def _build_slack_payload(summary: RunSummary) -> dict:
    blocks: list[dict] = []

    blocks.append(
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "Sigil Run Complete",
            },
        }
    )

    fields: list[dict] = []
    fields.append(
        {
            "type": "mrkdwn",
            "text": f"*PRs opened:* {summary.pr_count}",
        }
    )
    fields.append(
        {
            "type": "mrkdwn",
            "text": f"*Issues filed:* {summary.issue_count}",
        }
    )
    fields.append(
        {
            "type": "mrkdwn",
            "text": f"*Succeeded:* {summary.success_count}",
        }
    )
    fields.append(
        {
            "type": "mrkdwn",
            "text": f"*Failed:* {summary.failure_count}",
        }
    )
    if summary.cost_usd > 0:
        cost_str = (
            f"${summary.cost_usd:.2f}" if summary.cost_usd >= 0.01 else f"${summary.cost_usd:.4f}"
        )
        fields.append(
            {
                "type": "mrkdwn",
                "text": f"*Est. cost:* {cost_str}",
            }
        )
    if summary.model:
        fields.append(
            {
                "type": "mrkdwn",
                "text": f"*Model:* `{summary.model}`",
            }
        )

    blocks.append({"type": "section", "fields": fields})

    if summary.pr_urls:
        links = "\n".join(f"• <{url}|PR>" for url in summary.pr_urls[:10])
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*PRs:*\n{links}"}})

    if summary.issue_urls:
        links = "\n".join(f"• <{url}|Issue>" for url in summary.issue_urls[:10])
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*Issues:*\n{links}"}}
        )

    return {"blocks": blocks}


def _build_discord_payload(summary: RunSummary) -> dict:
    if summary.success_count > 0 and summary.failure_count == 0:
        color = 3066993
    elif summary.failure_count > 0 and summary.success_count == 0:
        color = 15158332
    else:
        color = 16776960

    fields: list[dict] = []
    fields.append({"name": "PRs opened", "value": str(summary.pr_count), "inline": True})
    fields.append({"name": "Issues filed", "value": str(summary.issue_count), "inline": True})
    fields.append({"name": "Succeeded", "value": str(summary.success_count), "inline": True})
    fields.append({"name": "Failed", "value": str(summary.failure_count), "inline": True})

    if summary.cost_usd > 0:
        cost_str = (
            f"${summary.cost_usd:.2f}" if summary.cost_usd >= 0.01 else f"${summary.cost_usd:.4f}"
        )
        fields.append({"name": "Est. cost", "value": cost_str, "inline": True})
    if summary.model:
        fields.append({"name": "Model", "value": f"`{summary.model}`", "inline": True})

    description_parts: list[str] = []
    if summary.pr_urls:
        description_parts.append(
            "**PRs:**\n" + "\n".join(f"- {url}" for url in summary.pr_urls[:10])
        )
    if summary.issue_urls:
        description_parts.append(
            "**Issues:**\n" + "\n".join(f"- {url}" for url in summary.issue_urls[:10])
        )

    embed: dict = {
        "title": "Sigil Run Complete",
        "color": color,
        "fields": fields,
    }
    if description_parts:
        embed["description"] = "\n\n".join(description_parts)

    return {"embeds": [embed]}
