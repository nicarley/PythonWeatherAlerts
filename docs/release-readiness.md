# Release candidate 26.10.22.2

The desktop implementation is integrated. This is a local release candidate, not a published or signed release. The authoritative application version remains the versionnumber assignment in PyWeatherAlertGui.py, using yy.mm.dd.buildnumber.

## Implemented

- Independent, bounded monitoring with immutable per-source snapshots, request generations, cancellation, and retention of successful data during partial outages.
- Alerts are processed before optional forecast and marine work. Unknown, cached, expired, and successfully empty states remain distinct across the dashboard, list, and map.
- Durable per-location, per-revision, per-channel delivery with safe retries, uncertain outcomes, expiry, cancellation, supersession, and recovery gated by fresh alert data and current rules.
- Speech engine ownership on one worker, bounded queue, mute clearing, and nonblocking shutdown.
- OS-backed webhook credentials, per-channel legacy migration, redacted backups, typed settings validation, and atomic history/settings writes.
- First-run setup, explicit monitoring controls, action-focused warning text, adjustable forecasts, saved panel sizes, location groups, acknowledgment notes, and operational/incident reports.
- Local diagnostics and reliability metrics; deterministic behavior fixtures; a shared release builder and Windows/macOS/Linux CI.

External notification channels remain explicit opt-in: both the location webhook rule and the individual enabled channel must permit delivery. Escalation does not enable a globally disabled external channel.

## Local verification

- The final complete test suite passed: **211 tests** on Windows / Python 3.13. Tests cover the desktop integration, data recovery, settings migration, and release-resource/source-fingerprint checks.
- The offline source smoke test passed through startup, resizing, and shutdown using temporary data and inert API, speech, credential, and notification adapters.
- Light and dark screenshots were inspected at 1500x920, 1280x800, and 1100x720. The primary warning and instruction remain visible at the minimum size; additional alerts and secondary information scroll.
- The Windows executable built successfully and passed its packaged offline smoke check. The final ZIP contains only approved presentation assets; settings and history are excluded. Its source-file hashes match the current implementation.
- Local Windows package: `Build/windows-release-final/weather-alert-station-26.10.22.2-windows-amd64.zip` (258,774,951 bytes). The matching JSON manifest records smoke results, dependency versions, source hashes, and unsigned status. Verified archive SHA-256: `decdcf575fa727ef540c04ed667d52a356ddda5369712ea9818f12a961c80601`.
- No live notifications were sent, user settings were not used for tests, and no external pilot has been conducted.

## External release gates

- Run the new macOS/Linux CI jobs and verify real embedded browser, OS credential prompts, and native speech behavior on supported systems.
- Obtain owner signing credentials and perform any platform-specific signing/notarization required for distribution. The default local package is unsigned.
- Conduct and record the operator pilot in pilot-validation.md.
- Verify the native iPad companion separately; desktop fixture passes do not establish native conformance. See platform-contract.md for its current limits.

## Operational details

Preserve the delivery and operations databases across upgrades. Provider acceptance does not establish human receipt; a local acknowledgment is recorded separately. An uncertain delivery may already have been received and is never blindly retried. Terminal deduplication records currently have no automatic retention purge.

Speech cannot be forcibly interrupted from another thread; mute drops pending items and lets the active utterance finish safely. Cancellation stops new weather work and rejects late callbacks; an in-flight HTTP operation finishes within its client timeout policy.
