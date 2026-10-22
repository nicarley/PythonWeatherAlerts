# Operator pilot validation protocol

Status: **planned; not run**. No external participant results or production delivery claims exist for this protocol.

The purpose is to test whether an operator can identify the selected location, the primary hazard, the freshness of the data, and the state of monitoring, then handle an alert without duplicate or misleading notifications.

## Entry gate

- Record the exact commit/build, Python/Qt versions, OS, monitor resolution, display scaling, and enabled channels.
- Complete automated tests and an isolated GUI walkthrough before recruiting operators.
- Use fictional feed fixtures and dedicated test destinations approved for the pilot. No test may post to operational recipients by accident.
- Configure a disposable data directory. Verify logs and exported test evidence exclude webhook secrets.
- Define which features are available in this build. Mark native iPad work separately; the desktop pilot cannot validate native behavior.

## Proposed participants and sessions

Recruit at least five representative operators, including a frequent desktop user, an occasional user, and a keyboard-focused user. Use at least one 1280×800 display and one high-DPI display. Record actual participants and hardware when sessions occur; these are recruitment targets, not completed activity.

Run a 30–45 minute observed session per operator. Explain the fictional scenario, then let the operator work without interface coaching. Capture time, observed mistakes, and the operator's explanation of what the screen means. Ask for verbal feedback after each task.

## Scenarios and proposed acceptance gates

| Scenario | Procedure | Proposed gate |
|---|---|---|
| Orientation | Open a populated dashboard; ask for location, hazard, freshness, and whether monitoring is running. | At least 4 of 5 explain all four within 30 seconds without coaching. |
| Unknown versus clear | Show first-load failure, a successful empty check, and cached data after failure. | Zero operators interpret unavailable/cached data as a newly verified all-clear. |
| Priority and action | Present a nearby minor advisory alongside a severe/immediate warning and an extreme alert. | All operators find the primary hazard and open its protective instructions; record time rather than assume success. |
| Monitoring control | Pause, change interval, resume, and observe next/last check labels. | At least 4 of 5 predict when another check will occur and confirm the final state. |
| Location switching | Rapidly select A → B → A while responses arrive out of order. | No old-location result appears under the new location's identity. |
| Partial outage | Let alerts succeed while forecasts fail; then reverse the failure. | Successful components remain usable, component errors are explicit, and known warnings stay visible. |
| Delivery recovery | One channel succeeds; another has a connect timeout, read timeout, or explicit rejection. Restart between steps. | Successful channel sends once; safe retry respects limits; ambiguous outcome stays uncertain without an automatic resend. |
| Revision and cancellation | Queue an older revision, replace it, expire it, and then issue a referencing cancellation. | Obsolete/expired/cancelled pending jobs do not send. Durable outcomes remain inspectable. |
| Mute | Queue several utterances, mute while one is active, then unmute. | Pending speech clears; the active engine finishes safely; no discarded backlog plays afterward. |
| Incident handling | Acknowledge an alert, add a note, restart, and export the record. | Saved state survives and is correctly attributed. Verify revision-specific acknowledgment and notes independently from provider acceptance. |
| Accessibility | Complete critical actions using keyboard and a high-DPI display. | No inaccessible critical action, missing focus indication, or clipped protective instruction. |

The proposed timings are usability goals, not measured service-level guarantees. Network latency should be recorded separately from local render/delivery processing.

## Fault injection

Use injected fake API and transport implementations for repeatable failures: empty successful response, alert fetch failure, forecast-only failure, response inversion, HTTP 429, connect timeout, read timeout after send, persistence write failure, and process interruption during sending.

Do not label an ambiguous remote outcome as success or as definitely not delivered. Confirm that the recovery view explains the uncertainty and that no automatic action blindly resends it.

## Evidence record

For each scenario record:

- Participant code/role, build, device, scaling, and scenario fixture.
- Start/end timestamps, task outcome, observed errors, and whether coaching occurred.
- Expected and actual component states; delivery IDs/revisions/channels with destinations redacted.
- Severity of each issue, owner, fix reference, and retest result.
- Consent and retention choices for any recording. Store only evidence needed for the pilot.

A simple issue table should include scenario, observed behavior, impact, reproduction, owner, fix, and retest status. Do not replace missing observations with inferred passes.

## Exit gate and follow-up

Block release on any false all-clear, wrong-location attribution, duplicate send after an uncertain outcome, expired-warning replay, secret disclosure, or lost incident action. Resolve or explicitly defer lower-impact usability findings with an owner and rationale.

Publish actual completion counts and failures alongside the final build identifier. If any scenario was skipped, mark it not tested. The pilot may support an operational rollout decision; it is not a substitute for testing native platforms, background behavior, or delivery-service guarantees.
