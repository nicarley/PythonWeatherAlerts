"""Qt bridge for the toolkit-independent monitoring, delivery and speech services.

Only this bridge touches widgets. Network and speech workers publish through
queued signals and can finish independently of the selected location.
"""
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Qt
from .monitoring import MonitoringCoordinator
from .delivery import DeliveryService
from .speech import SpeechQueue
from .operations import OperationsStore
from .identity import alert_revision, expiry_timestamp, alert_priority_key, active_unexpired_alerts, is_cancelled
from .rules import summarize_lifecycle, evaluate_location_rule, default_location_rules
from .escalation import evaluate_escalation
from .proximity import rank_alerts_by_proximity
from .webhook import format_notification_payload


class AppRuntime(QObject):
    monitoring_update = Signal(object)
    delivery_update = Signal(object)
    speech_update = Signal(object)

    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.closing = False
        self.active = set()
        self.generations = {}
        self.revisions = {}
        self.alert_revisions = {}
        self.snapshots = {}
        self.verified_locations = set()
        self._expired_cache_locations = set()
        self.monitoring_update.connect(self.on_snapshot, Qt.ConnectionType.QueuedConnection)
        self.delivery_update.connect(self.on_delivery, Qt.ConnectionType.QueuedConnection)
        self.speech_update.connect(self.on_speech, Qt.ConnectionType.QueuedConnection)
        directory = Path(host._get_user_data_path())
        self.operations = OperationsStore(directory / 'operations.sqlite3')
        self.coordinator = MonitoringCoordinator(host.api_client, host.marine_service, max_pending_locations=100)
        self.delivery = DeliveryService(directory / 'delivery.sqlite3',
            destination_resolver=host.credentials.resolve, on_result=self.delivery_update.emit)
        self.speech = SpeechQueue(on_result=self.speech_update.emit)
        # GUI helpers use stable public handles, never worker internals.
        host.operations = self.operations
        host.delivery_service = self.delivery
        host.monitoring_coordinator = self.coordinator
        host.speech_queue = self.speech
        self.delivery.set_enabled_locations([])
        self.sync_channels()
        self.restore()
        self.delivery.start()

    def sync_channels(self):
        self.delivery.set_enabled_channels(self.enabled_channels())
        configured = {loc['id']: loc for loc in self.host.locations}
        for location_id in tuple(self.active):
            if location_id not in configured:
                self.coordinator.cancel(location_id)
                self.active.discard(location_id)
        self.host._check_in_progress = bool(self.active)
        for record in self.delivery.records(states=('queued', 'failed')):
            location = configured.get(record.location_id)
            if location is None or (not record.alert_id.startswith('test:') and not location.get('rules', {}).get('webhook_enabled', False)):
                self.delivery.cancel_alert(record.location_id, record.alert_id)

    def enabled_channels(self):
        host = self.host
        return [name for name, enabled in (
            ('generic', host.current_enable_webhook_notifications),
            ('discord', host.current_enable_discord_notifications),
            ('slack', host.current_enable_slack_notifications)) if enabled]

    def restore(self):
        host = self.host
        configured = {loc['id'] for loc in host.locations}
        for location_id, payload in self.operations.load_snapshots().items():
            if location_id not in configured:
                continue
            if payload.get('alerts_expired_since_check'):
                self._expired_cache_locations.add(location_id)
            self.coordinator.seed(location_id, payload)
            host.last_known_data_by_location[location_id] = payload
            host.current_alerts_by_location[location_id] = payload.get('alerts') or []
            host.last_active_alerts_by_location[location_id] = {
                a['id']: a for a in payload.get('alerts', []) if a.get('id')}
            alert_state = payload.get('component_status', {}).get('alerts', {})
            host.location_runtime_status[location_id] = {
                'state': 'cached', 'detail': 'Saved data; waiting for a fresh alert check',
                'fetched_at': alert_state.get('fetched_at', payload.get('fetched_at')),
                'alerts_available': location_id not in self._expired_cache_locations and bool(alert_state.get('fetched_at', payload.get('fetched_at')))}
        self.expire_cached_alerts(render=False)

    def expire_cached_alerts(self, now=None, *, render=True):
        """Prune ended cached hazards without turning stale data into an all-clear.

        Safe for the GUI's periodic timer. A fresh successful alert response
        clears the persisted unknown-state marker; forecast callbacks cannot.
        Returns the number of expired/cancelled cached entries removed.
        """
        if self.closing:
            return 0
        host = self.host
        now = time.time() if now is None else float(now)
        removed_count = 0
        selected_changed = False
        configured = {loc['id'] for loc in host.locations}
        for location_id in configured:
            old_alerts = host.current_alerts_by_location.get(location_id, [])
            remaining = active_unexpired_alerts(old_alerts, now)
            removed = [
                item for item in old_alerts
                if is_cancelled(item) or (
                    expiry_timestamp(item) is not None and expiry_timestamp(item) <= now
                )
            ]
            if not removed:
                continue
            removed_count += len(removed)
            host.current_alerts_by_location[location_id] = remaining
            ended_ids = {str(item.get('id') or alert_revision(item)) for item in removed}
            previous = host.last_active_alerts_by_location.get(location_id, {})
            host.last_active_alerts_by_location[location_id] = {
                key: item for key, item in previous.items() if key not in ended_ids
            }
            lifecycle = {
                'new': [], 'updated': [],
                'expired': [item for item in removed if not is_cancelled(item)],
                'cancelled': [item for item in removed if is_cancelled(item)],
                'active': host.last_active_alerts_by_location[location_id],
            }
            host.last_lifecycle_by_location[location_id] = lifecycle
            self.audit(host._record_lifecycle_events, location_id, lifecycle)
            for identifier in ended_ids:
                self.audit(self.delivery.cancel_alert, location_id, identifier)
                host.escalation_repeat_state.pop(f'{location_id}:{identifier}', None)
            self.verified_locations.discard(location_id)
            status = dict(host.location_runtime_status.get(location_id, {}))
            if not remaining:
                self._expired_cache_locations.add(location_id)
                status.update(state='error', alerts_available=False,
                              detail='Last known alerts ended; refresh to verify current alert status')
            else:
                status.update(state='cached', detail='Some saved alerts ended; showing remaining last-known alerts')
            host.location_runtime_status[location_id] = status
            cached = host.last_known_data_by_location.get(location_id)
            if cached is not None:
                cached = dict(cached, alerts=remaining)
                cached['alerts_expired_since_check'] = location_id in self._expired_cache_locations
                host.last_known_data_by_location[location_id] = cached
                self.audit(self.operations.save_snapshot, location_id, cached)
            selected_changed = selected_changed or location_id == host.current_location_id
        if removed_count:
            self.audit(self.delivery.set_enabled_locations, self.verified_locations)
            if render and selected_changed:
                self.audit(host._render_cached_location_data, host.current_location_id)
                status = host.location_runtime_status.get(host.current_location_id, {})
                if not status.get('alerts_available', True):
                    host.alerts_display_area.clear()
                    host._add_alert_placeholder(
                        'Last known alerts ended. Refresh to verify current alert status.', 'error'
                    )
                    host._apply_alert_filters()
                host._update_dashboard_summary()
        return removed_count

    def refresh(self, location_id):
        if self.closing or location_id not in {loc['id'] for loc in self.host.locations}:
            return
        host = self.host
        self.active.add(location_id)
        self.verified_locations.discard(location_id)
        self.delivery.set_enabled_locations(self.verified_locations)
        host._check_in_progress = True
        previous = host.location_runtime_status.get(location_id, {})
        host.location_runtime_status[location_id] = dict(previous, state='loading', detail='Checking NWS alerts')
        if location_id == host.current_location_id:
            host._clear_and_set_loading_states()
        host._update_dashboard_summary()
        try:
            self.generations[location_id] = self.coordinator.refresh(location_id, self.monitoring_update.emit)
        except Exception as exc:
            self.active.discard(location_id)
            host.location_runtime_status[location_id] = dict(previous,
                state='cached' if previous.get('alerts_available') else 'error',
                detail=f'Refresh could not start ({type(exc).__name__})')
            self.finish()

    def finish(self):
        host = self.host
        host._check_in_progress = bool(self.active)
        if not self.active and not self.closing:
            host._schedule_next_timed_check(immediate=False)

    def on_snapshot(self, snapshot):
        host = self.host
        location_id = snapshot.location_id
        if self.closing:
            return
        if location_id not in {loc['id'] for loc in host.locations}:
            self.active.discard(location_id)
            self.finish()
            return
        if snapshot.generation != self.generations.get(location_id):
            return
        key = (location_id, snapshot.generation)
        if snapshot.revision <= self.revisions.get(key, -1):
            return
        self.revisions[key] = snapshot.revision
        self.snapshots[location_id] = snapshot
        try:
            payload = snapshot.to_legacy_dict()
            alerts_source = snapshot.components['alerts']
            source_key = (snapshot.generation, alerts_source.revision)
            fresh_alerts = (alerts_source.has_data and not alerts_source.loading
                            and not alerts_source.cached and alerts_source.error is None
                            and self.alert_revisions.get(location_id) != source_key)
            if fresh_alerts:
                raw_alerts = payload['alerts']
                self._expired_cache_locations.discard(location_id)
                alerts = active_unexpired_alerts(raw_alerts)
                notices = [item for item in raw_alerts if is_cancelled(item)]
                if not alerts and any(
                    expiry_timestamp(item) is not None
                    and alerts_source.fetched_at < expiry_timestamp(item) <= time.time()
                    for item in raw_alerts if not is_cancelled(item)
                ):
                    self._expired_cache_locations.add(location_id)
                if snapshot.coords:
                    alerts = rank_alerts_by_proximity(alerts, *snapshot.coords)
                lifecycle = summarize_lifecycle(host.last_active_alerts_by_location.get(location_id, {}), alerts + notices)
                alerts = sorted(lifecycle['active'].values(), key=alert_priority_key)
                payload['alerts'] = alerts
                host.current_alerts_by_location[location_id] = alerts
                host.last_active_alerts_by_location[location_id] = lifecycle['active']
                host.last_lifecycle_by_location[location_id] = lifecycle
                self.audit(host._record_lifecycle_events, location_id, lifecycle)
                for ended in lifecycle['expired'] + lifecycle['cancelled']:
                    self.audit(self.delivery.cancel_alert, location_id, ended['id'])
                    host.escalation_repeat_state.pop(f"{location_id}:{ended['id']}", None)
                for alert in alerts:
                    alert['_notify_allowed'] = False
                titles = self.audit(self.process_alerts, alerts, location_id, snapshot.coords) or []
                eligible_ids = {
                    str(alert.get('id') or alert_revision(alert)) for alert in alerts
                    if alert.get('_notify_allowed')
                }
                for pending in self.audit(self.delivery.records, states=('queued', 'failed')) or []:
                    if pending.location_id == location_id and not pending.alert_id.startswith('test:') and pending.alert_id not in eligible_ids:
                        self.audit(self.delivery.cancel_alert, location_id, pending.alert_id)
                self.audit(self.enqueue_alerts, location_id, alerts, snapshot.coords)
                if location_id not in self._expired_cache_locations:
                    self.verified_locations.add(location_id)
                else:
                    self.verified_locations.discard(location_id)
                self.delivery.set_enabled_locations(self.verified_locations)
                if titles or location_id == host.current_location_id:
                    self.audit(host._handle_timed_announcements, titles, location_id)
                self.alert_revisions[location_id] = source_key
                self.record('alert_check_seconds', location_id, time.time() - snapshot.started_at)
            elif alerts_source.has_data:
                payload['alerts'] = host.current_alerts_by_location.get(location_id, payload['alerts'])
            payload['alerts_expired_since_check'] = location_id in self._expired_cache_locations
            host.last_known_data_by_location[location_id] = payload
            host.current_conditions_by_location[location_id] = payload.get('current_conditions') or {}
            host.current_marine_data_by_location[location_id] = payload.get('marine_data') or {}
            if alerts_source.error:
                self.verified_locations.discard(location_id)
                self.delivery.set_enabled_locations(self.verified_locations)
            if alerts_source.loading:
                state, detail = 'loading', 'Checking NWS alerts'
            elif alerts_source.error:
                state = 'cached' if alerts_source.has_data else 'error'
                detail = 'Alert check failed; last successful data retained' if alerts_source.has_data else 'Alert status unavailable; retrying on next check'
            elif alerts_source.has_data:
                state, detail = 'online', 'NWS alert check succeeded'
            else:
                state, detail = 'error' if snapshot.complete else 'loading', 'Awaiting an NWS alert response'
            if location_id in self._expired_cache_locations:
                state, detail = 'error', 'Last known alerts ended; refresh to verify current alert status'
            host.location_runtime_status[location_id] = {
                'state': state, 'detail': detail, 'fetched_at': alerts_source.fetched_at,
                'alerts_available': alerts_source.has_data and location_id not in self._expired_cache_locations,
                'component_status': payload.get('component_status', {})}
            self.expire_cached_alerts(render=False)
            payload = host.last_known_data_by_location[location_id]
            if location_id == host.current_location_id:
                host._render_cached_location_data(location_id)
                if not host.location_runtime_status[location_id].get('alerts_available'):
                    host.alerts_display_area.clear()
                    host._add_alert_placeholder('Alert status unavailable' if snapshot.complete else 'Checking NWS alerts…', 'error' if snapshot.complete else 'loading')
                    host._apply_alert_filters()
                self.update_source_labels(snapshot)
                if snapshot.complete and not snapshot.coords:
                    host._set_location_web_placeholder("Weather data unavailable. Use Check now to retry.")
            if fresh_alerts or snapshot.complete:
                self.audit(self.operations.save_snapshot, location_id, payload)
            if fresh_alerts and not self.audit(host.alert_history_manager.save_history):
                host.log_to_gui("Alert history could not be saved. Current weather remains visible.", level="ERROR")
                self.record("history_save_failure", location_id)
            if snapshot.complete:
                for name, component in snapshot.components.items():
                    if component.error:
                        self.record('source_failure', location_id, detail=name)
            host._update_dashboard_summary()
        except Exception as exc:
            # A renderer/rule failure must not strand the scheduler or erase good data.
            host.log_to_gui(f'Weather update could not finish ({type(exc).__name__}). See event log.', level='ERROR')
            import logging
            logging.exception('Weather update handler failed')
            self.record('processing_failure', location_id, detail=type(exc).__name__)
        finally:
            if snapshot.complete:
                self.active.discard(location_id)
                self.finish()

    def update_source_labels(self, snapshot):
        host = self.host
        lines = []
        for name, component in snapshot.components.items():
            status = 'refreshing' if component.loading else 'cached / error' if component.error and component.has_data else 'unavailable' if component.error else 'available' if component.has_data else 'waiting'
            retrieved = datetime.fromtimestamp(component.fetched_at).strftime('%b %d %H:%M:%S') if component.fetched_at else 'never'
            lines.append(f"{name.replace('_', ' ').title()}: {status}; retrieved {retrieved}; source time {component.source_updated_at or 'not provided'}")
        host.forecast_board_status_label.setToolTip('\n'.join(lines))
        forecast_names = ('hourly_forecast', 'daily_forecast')
        if any(snapshot.components[name].error for name in forecast_names):
            host.forecast_board_status_label.setText('Forecast partly unavailable · see source status')
        elif any(snapshot.components[name].loading for name in forecast_names):
            host.forecast_board_status_label.setText('Forecast refreshing')
        else:
            host.forecast_board_status_label.setText('Forecast retrieved · source times in details')
        fetched_at = snapshot.components['alerts'].fetched_at
        if hasattr(host, 'last_check_label'):
            host.last_check_label.setText('Last alert check: ' + (datetime.fromtimestamp(fetched_at).strftime('%H:%M:%S') if fetched_at else 'not yet successful'))
            host.last_check_label.setToolTip('\n'.join(lines))

    def audit(self, operation, *args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except Exception as exc:
            self.host.log_to_gui(f"Local operational record could not be saved ({type(exc).__name__}).", level='ERROR')
            self.host.update_status('Local records unavailable; review the event log. Weather display remains available.')
            return None

    def record(self, *args, **kwargs):
        return self.audit(self.operations.record, *args, **kwargs)

    def process_alerts(self, alerts, location_id, coords=None):
        host = self.host
        config = host._get_location_config(location_id)
        rules = config.get('rules', default_location_rules())
        titles = []
        for alert in alerts:
            identifier = str(alert.get('id') or alert_revision(alert))
            revision = alert_revision(alert)
            expiry = expiry_timestamp(alert)
            escalation = evaluate_escalation(alert, rules, alert.get('distance_miles'), datetime.now())
            allowed, reason = evaluate_location_rule(alert, rules, datetime.now(),
                ignore_quiet_hours=bool(escalation.get('override_quiet_hours')))
            if expiry is not None and expiry <= time.time():
                allowed, reason = False, 'expired'
            alert.update(_rule_allowed=allowed, _rule_reason=reason,
                         _notify_allowed=allowed, _escalation=escalation)
            history_id = f'{location_id}:{identifier}:{revision}'
            self.audit(host.alert_history_manager.add_alert, history_id, {
                'id': history_id, 'alert_id': identifier, 'revision': revision,
                'time': time.strftime('%Y-%m-%d %H:%M'), 'type': alert.get('event', ''),
                'location': config.get('name'), 'location_id': location_id,
                'title': alert.get('title', ''), 'summary': alert.get('summary', ''),
                'instruction': alert.get('instruction', ''), 'link': alert.get('link', ''),
                'severity': alert.get('severity', '')})
            if not allowed:
                host.escalation_repeat_state.pop(f'{location_id}:{identifier}', None)
                self.record('rule_suppression', location_id, detail=reason)
                continue
            escalation_key = f'{location_id}:{identifier}'
            if escalation.get('escalate'):
                repeat = max(1, int(escalation.get('repeat_minutes', 5)))
                repeat_state = host.escalation_repeat_state.setdefault(escalation_key, {'next_ts': time.time() + repeat * 60})
                repeat_state.update(repeat_minutes=repeat, title=alert.get('title') or alert.get('event') or 'Weather alert',
                                    location_name=config.get('name'), location_id=location_id, expires_at=expiry)
            else:
                host.escalation_repeat_state.pop(escalation_key, None)
            if not self.audit(self.operations.claim_effect, location_id, identifier, revision, 'local_notification'):
                self.record('duplicate_suppression', location_id)
                continue
            title = alert.get('title') or alert.get('event') or 'Weather alert'
            titles.append(title)
            source_time = alert.get('sent') or alert.get('updated')
            if source_time:
                try:
                    published = datetime.fromisoformat(source_time.replace('Z', '+00:00')).timestamp()
                    self.record('detection_delay_seconds', location_id, max(0, time.time() - published))
                except (ValueError, TypeError):
                    pass
            for effect, enabled, action in (
                ('sound', host._resolve_bool_override(rules.get('play_sounds'), host.enable_sounds_action.isChecked()),
                 lambda: host._play_alert_sound(title.lower(), rules, escalation.get('escalate', False))),
                ('desktop', host._resolve_bool_override(rules.get('desktop_notifications'), host.desktop_notification_action.isChecked()),
                 lambda: host._show_desktop_notification(f"{config.get('name')}: {title}", alert.get('summary', '')))):
                if enabled:
                    try:
                        action()
                    except Exception as exc:
                        self.record(effect + '_failure', location_id, detail=type(exc).__name__)
                        host.log_to_gui(effect.title() + ' notification unavailable.', level='WARNING')
            if escalation.get('escalate'):
                repeat = max(1, int(escalation.get('repeat_minutes', 5)))
                host.escalation_repeat_state[f'{location_id}:{identifier}'] = {
                    'next_ts': time.time() + repeat * 60, 'repeat_minutes': repeat,
                    'title': title, 'location_name': config.get('name'), 'location_id': location_id, 'expires_at': expiry}
        return titles

    def enqueue_alerts(self, location_id, alerts, coords=None):
        host = self.host
        config = host._get_location_config(location_id)
        if not config.get('rules', {}).get('webhook_enabled', False):
            return
        self.sync_channels()
        for alert in alerts:
            if not alert.get('_notify_allowed'):
                continue
            revision = alert_revision(alert)
            payload = {'source': 'PyWeatherAlert', 'location': config.get('name'),
                'location_id': location_id, **{key: alert.get(key) for key in (
                    'title', 'summary', 'instruction', 'severity', 'event', 'updated', 'link', 'distance_miles')},
                'escalated': bool(alert.get('_escalation', {}).get('escalate'))}
            for channel in self.enabled_channels():
                try:
                    self.delivery.enqueue(alert_id=str(alert.get('id') or revision), revision=revision,
                        location_id=location_id, channel=channel, destination=f'credential:{channel}',
                        payload=format_notification_payload(channel, payload), expires_at=expiry_timestamp(alert))
                except Exception as exc:
                    host.log_to_gui(f'{channel.title()} notification could not be queued ({type(exc).__name__}).', level='ERROR')
                    self.record('delivery_queue_failure', location_id, detail=channel)

    def on_delivery(self, record):
        if self.closing:
            return
        host = self.host
        host.delivery_health.record(record.channel, record.state == 'sent', record.error)
        self.record('delivery_' + record.state, record.location_id, detail=record.channel)
        host.log_to_gui(f"{record.channel.title()}: " + ('provider accepted notification' if record.state == 'sent' else record.state + ' — ' + record.error),
                        level='INFO' if record.state == 'sent' else 'WARNING')
        host._update_dashboard_summary()

    def on_speech(self, result):
        if not self.closing and not result.success and not getattr(result, 'cancelled', False):
            self.host.log_to_gui('Speech unavailable: ' + result.error, level='WARNING')
            self.record('speech_failure')

    def close(self):
        self.closing = True
        self.coordinator.shutdown(wait=False)
        self.delivery.shutdown(wait=False)
        self.speech.shutdown(wait=False)
