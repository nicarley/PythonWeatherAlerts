from weather_alert.webhook import dispatch_notification_channels


class _Response:
    def raise_for_status(self):
        return None


class _Session:
    def __init__(self):
        self.calls = []

    def post(self, url, json=None, timeout=8):
        self.calls.append((url, json, timeout))
        return _Response()


def test_dispatch_notification_channels_posts_to_enabled_targets():
    session = _Session()
    channels = {
        "generic": {"enabled": True, "url": "https://hooks.example.com/generic"},
        "discord": {"enabled": True, "url": "https://discord.com/api/webhooks/123"},
        "slack": {"enabled": True, "url": "https://hooks.slack.com/services/abc"},
    }
    payload = {
        "title": "Tornado Warning",
        "severity": "Severe",
        "location": "Home",
        "summary": "Take shelter now.",
        "link": "https://example.com/alert",
    }

    result = dispatch_notification_channels(session, channels, payload)
    assert result["generic"] is True
    assert result["discord"] is True
    assert result["slack"] is True
    assert len(session.calls) == 3


def test_dispatch_notification_channels_include_errors_shape():
    session = _Session()
    channels = {"generic": {"enabled": True, "url": "https://hooks.example.com/generic"}}
    payload = {"title": "Test"}
    result = dispatch_notification_channels(session, channels, payload, include_errors=True)
    assert result["generic"]["success"] is True
    assert result["generic"]["error"] == ""
