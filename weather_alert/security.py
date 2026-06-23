import html
from typing import Any, Dict
from urllib.parse import urlparse


def safe_external_url(url: Any, fallback: str = "#") -> str:
    """Allow only normal web URLs before embedding or opening external content."""
    text = str(url or "").strip()
    parsed = urlparse(text)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        return fallback
    return text


def html_attr(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def first_payload_entry(payload_value: Any) -> Dict[str, Any]:
    if isinstance(payload_value, list):
        return payload_value[0] if payload_value and isinstance(payload_value[0], dict) else {}
    if isinstance(payload_value, dict):
        for key in ["data", "predictions", "current_predictions", "cp"]:
            nested = payload_value.get(key)
            if isinstance(nested, list) and nested:
                return nested[0] if isinstance(nested[0], dict) else {}
            if isinstance(nested, dict):
                return first_payload_entry(nested)
        return payload_value
    return {}
