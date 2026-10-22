# Desktop architecture and operating contracts

The desktop keeps Qt rendering in PyWeatherAlertGui.py and connects independent services through weather_alert/runtime.py. A location selection controls presentation; it does not determine which configured locations are monitored.

## Ownership

- MonitoringCoordinator owns bounded background work, per-location generations, cancellation, and per-source snapshots. It publishes successful alerts before starting optional forecast or marine requests. Built-in HTTP clients use isolated worker sessions.
- Immutable LocationSnapshot and ComponentSnapshot values contain separate retrieval and provider timestamps, source errors, and cache state. A forecast result cannot establish that the alert source is available.
- AppRuntime marshals callbacks through queued Qt signals, rejects obsolete generations and revisions, applies rules, and updates the presentation. Completion cleanup executes even if processing or rendering fails.
- DeliveryService owns a durable SQLite outbox. Its unique key is location, alert ID, semantic revision, and channel. The history of seeing an alert does not establish delivery.
- SpeechQueue creates and uses its engine on one owning worker. Mute clears waiting speech; the active utterance finishes safely.
- OperationsStore persists revision-specific acknowledgments, local notification claims, aggregate metrics, and last-known weather. Connections close after each transaction. Acknowledgment never dismisses an official warning.

## Recovery policy

A successful empty alert response is distinct from an unavailable source. Optional source failures retain their previous data and timestamps. Expired cached warnings cease to be active hazards; an empty cache after expiration is not a fresh all-clear.

Queued notification recovery waits for a fresh successful alert check for that location. The current active revision and routing rules are reconciled before recovery resumes. Disabled channels pause their jobs; obsolete, cancelled, expired, removed-location, or currently suppressed jobs are cancelled or expired. Operator-requested test messages bypass the fresh-weather gate and have a short expiry.

Provider acceptance is recorded separately for every channel. Connect timeouts and explicit rate limits can retry with bounded backoff. Interrupted sends and ambiguous remote outcomes become uncertain and are not automatically retried. Acknowledgment is a separate local operator record and does not imply receipt on an external channel.

## Persistence and privacy

Settings and history use versioned validation and atomic replacement. Corrupt originals are preserved for recovery. Legacy history migration permits primitive pickle data and rejects executable objects. Notification credentials resolve from an OS credential store at send time; outbox rows contain credential references. Legacy plaintext values are retained only if their secure migration cannot complete. Settings backups omit webhook credentials.

Diagnostics are opt-in local archives of aggregate source status, package versions, and delivery outcomes. They omit settings, locations, alert payloads, and credential values. Incident exports intentionally include operator and alert evidence; they are different from diagnostics. No telemetry upload is enabled.

## Verification boundaries

Tests inject HTTP, speech, and notification adapters and use disposable app data. The source and packaged smoke modes disable network-facing services, audio, notifications, and persisted user settings while exercising window creation, resizing, and shutdown. Embedded web content, real speech drivers, OS credential prompts, and live providers require platform or pilot checks.

Windows, macOS, and Linux CI workflows validate the desktop independently. Native iPad behavior is tracked in platform-contract.md; desktop test results do not establish native conformance. Signing and an external operator pilot are owner-controlled release steps.
