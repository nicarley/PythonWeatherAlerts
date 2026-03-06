import logging
from typing import Any, Dict, Optional, Tuple

import requests


def _post_json(session: requests.Session, url: str, payload: Dict[str, Any], timeout: int = 8) -> Tuple[bool, str]:
    if not url:
        return False, "missing url"
    try:
        response = session.post(url, json=payload, timeout=timeout)
        response.raise_for_status()
        return True, ""
    except requests.RequestException as e:
        logging.error("Notification delivery failed for %s: %s", url, e)
        return False, str(e)


def _discord_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    title = data.get("title", "Weather Alert")
    severity = data.get("severity", "Unknown")
    location = data.get("location", "Unknown Location")
    summary = (data.get("summary") or "").strip()
    content = f"**{title}**\nSeverity: {severity}\nLocation: {location}"
    if summary:
        content += f"\n{summary[:1200]}"
    link = data.get("link")
    if link:
        content += f"\n{link}"
    return {"content": content}


def _slack_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    title = data.get("title", "Weather Alert")
    severity = data.get("severity", "Unknown")
    location = data.get("location", "Unknown Location")
    summary = (data.get("summary") or "").strip()
    text = f"*{title}*\nSeverity: {severity}\nLocation: {location}"
    if summary:
        text += f"\n{summary[:1200]}"
    link = data.get("link")
    if link:
        text += f"\n<{link}|Open alert>"
    return {"text": text}


def dispatch_notification_channels(
    session: requests.Session,
    channels: Dict[str, Dict[str, Any]],
    payload: Dict[str, Any],
    timeout: int = 8,
    include_errors: bool = False,
) -> Dict[str, Any]:
    results: Dict[str, Any] = {}

    generic_cfg = channels.get("generic", {})
    if generic_cfg.get("enabled") and generic_cfg.get("url"):
        ok, err = _post_json(session, generic_cfg["url"], payload, timeout)
        results["generic"] = {"success": ok, "error": err} if include_errors else ok

    discord_cfg = channels.get("discord", {})
    if discord_cfg.get("enabled") and discord_cfg.get("url"):
        ok, err = _post_json(session, discord_cfg["url"], _discord_payload(payload), timeout)
        results["discord"] = {"success": ok, "error": err} if include_errors else ok

    slack_cfg = channels.get("slack", {})
    if slack_cfg.get("enabled") and slack_cfg.get("url"):
        ok, err = _post_json(session, slack_cfg["url"], _slack_payload(payload), timeout)
        results["slack"] = {"success": ok, "error": err} if include_errors else ok

    return results


def post_webhook_notification(session: requests.Session, webhook_url: str, payload: Dict[str, Any], timeout: int = 8) -> bool:
    # Backward-compatible wrapper for existing generic webhook behavior.
    ok, _ = _post_json(session, webhook_url, payload, timeout)
    return ok
