# Alert behavior contract, version 1

The readable fixtures in [alert-behavior-v1.json](../contracts/alert-behavior-v1.json) define normalized alert behavior. Python exercises them in [test_behavior_contract.py](../tests/test_behavior_contract.py). They use fictional alerts and fixed dates; they are not recorded emergencies.

A passing desktop fixture suite does **not** establish native iPad conformance. The checked-in Swift implementation has not been changed or validated by these Python tests. No Xcode build, iPad device run, or external operator pilot is claimed here.

## Contract

- Rule thresholds use Unknown < Minor < Moderate < Severe < Extreme. Alert kind comes from the normalized title and event, in warning/watch/advisory order. Unknown kinds require an explicit “other” selection.
- Quiet hours use a start-inclusive/end-exclusive interval, including an interval crossing midnight. Equal start and end disables the interval. The fixture time is a supplied local wall time; the application must define its timezone policy. Current desktop callers use host-local time.
- Lifecycle compares semantic revisions. Changes to instructions, title, urgency, expiry, or geometry are updates even if the upstream updated string is unchanged. Distance and runtime display/notification flags are not revisions.
- Cancellation notices never count as active or newly issued alerts. A reference to a known prior alert cancels that alert's ID, preserving the notice ID separately as cancellation_id. A cancellation is not also counted as an expiration.
- Priority is severity descending, urgency descending, certainty descending, distance ascending, then alert ID for a stable tie break. Unknown distance sorts behind known distance at the same severity, urgency, and certainty.
- Expiry is the earliest valid expires or ends instant. ISO offsets convert to UTC; legacy offset-free strings are interpreted as UTC. An absent/invalid timestamp returns no inferred expiry.
- Location groups default to Ungrouped and preserve supplied names.

## Revision serialization

weather_alert.identity.SEMANTIC_FIELDS is the version-1 field list. Use all fields, with missing fields represented as JSON null. Serialize UTF-8 JSON with sorted object keys, compact separators, literal Unicode, and integral floats represented as integers. Preserve array order, including polygon rings. Hash the bytes with SHA-256.

The fixture includes a golden digest and semantic/ignored patches. Native code must reproduce the digest and all patches before it claims compatible revision deduplication. A future serialization change requires a new fixture/schema version and a migration decision for existing outbox keys.

The outbox key is (alert_id, revision, location_id, channel). Different channels succeed independently. A new revision supersedes only queued/failed older work; sent and uncertain outcomes retain their durable keys. A failed callback does not create another send.

## Current implementation matrix

| Behavior | Python desktop core | Checked-in native iPad |
|---|---|---|
| Saved locations and NWS dashboard | Existing application | Existing application |
| Minimum severity and alert kind rules | Shared fixtures | Implemented; fixture runner not yet added |
| Quiet hours / escalation | Existing desktop rules; shared quiet-hour cases | Not implemented |
| Priority order above | Shared helper, GUI integration, and regression tests | Severity, then title; differs from contract |
| Semantic revision identity | Implemented and tested | Not implemented; notification tracking uses in-memory IDs |
| Cancellation/reference lifecycle | Implemented and tested | No equivalent lifecycle contract implementation |
| Durable per-channel recovery | SQLite outbox | Not implemented |
| Managed speech / location groups / acknowledgement workflow | Integrated desktop workflow with regression tests | Not implemented |
| Webhook credential storage | Integrated OS credential store with migration tests | Not implemented |
| Continuous background monitoring | Desktop timer while application runs | Not established; foreground refresh is not a background delivery guarantee |

Native references: iOS/PyWeatherAlertIOS/Stores/AppStore.swift, Models.swift, Services/NWSClient.swift, and Services/NotificationService.swift. Native notification requests currently swallow add-request errors and do not persist revision delivery outcomes. This matrix is an implementation inventory, not a device test report.

## Native acceptance work

1. Add an XCTest fixture reader for the same JSON and normalize native models to the same field names.
2. Run rule/lifecycle/priority/identity cases without network or system notification delivery.
3. Implement persistent revision outcomes and explicit notification errors before claiming restart parity.
4. Add deterministic tests for permission denial, first poll, an initially empty alert set followed by a warning, revisions retaining the same ID, cancellation, stale responses, and app relaunch.
5. Build in Xcode, exercise the supported iPadOS/device matrix, and document foreground/background limitations from device evidence.
