from .api import ApiError, NwsApiClient
from .history import AlertHistoryManager
from .health import DeliveryHealthTracker
from .dedup import AlertDeduplicator
from .proximity import distance_point_to_geometry_miles, rank_alerts_by_proximity
from .escalation import evaluate_escalation
from .settings import SettingsManager
from .rules import (
    SEVERITY_ORDER,
    default_location_rules,
    evaluate_location_rule,
    get_alert_type,
    normalize_location_entry,
    summarize_lifecycle,
)
from .webhook import dispatch_notification_channels, post_webhook_notification
