# critic simulation: requirements register

These requirements came from playing critic by hand for the October 2026 run of the critic simulation: one month of fleet sessions, metered from harness transcripts. Each one states a condition a working critic must handle. Requirements only; the run's results stay out of this repository.

## Run record (component 1)

**C-01. A record for an observation window.** When a run covers a window of many sessions across many seats rather than one execution, the record needs a kind, or a record type, for it, keyed by cluster, seat and harness. The current kinds (legion, spike, fork, trial) each describe one execution.

**C-02. Session to seat, recorded at spawn.** Each harness session id is recorded with its seat label, team, role, generation and harness when the seat starts, so no later reader has to reconstruct it from transcript fields.

**C-03. A way in from a host with no critic store.** When the host that holds a run's ledger and cost outputs cannot reach a critic store, the record still needs a way in: a file intake that registers a prepared record later, or a store every cluster can reach, either way keeping the record's path and sha256 fields intact.

## Transcript ledger (component 2)

**C-04. Dedupe on a stated key, with a fixture.** When usage repeats across the content blocks of one reply, the ledger counts each request once, on one stated key. Where `message.id` and `requestId` can disagree, the ledger says which it uses. Where repeated copies of one message can carry different usage, it takes the last or largest copy, not the first. A fixture fails on a double count and on taking the first copy.

**C-05. Meter at write time.** When the harness removes older transcripts under its own retention, a meter that reads transcripts after the fact reads a floor. Per-request usage is recorded when it happens, outside that retention.

**C-06. A named fallback when telemetry is off.** When seats do not export telemetry, the 1% reconcile against OTEL cannot run. The ledger names a fallback reconcile for that case, or the metered seats turn telemetry on.

**C-07. Activity classes as declared predicates.** Activity classes are declared in critic as predicates over recorded fields, versioned, with the unclassified share reported in every output.

**C-08. A live reading for hub wait.** Turns whose only tool call is a bus wait or an inbox read cost cache reads on long-lived seats. Their per-seat cost is shown as a live reading, not only in an audit after the fact.

## Cost meter (component 3)

**C-09. Billed and list-price columns, kept apart.** A list-price equivalent is not a charge. Where a billed source exists, the meter reconciles against it, keeps billed dollars and list-price equivalents in separate columns, and names each billing source with whether it was read.

**C-10. One dated price table.** When price tables disagree on a rate, the meter uses one table, dated and frozen with its sha256, and every cost output cites it.

**C-11. Read the harness's own meter.** Where the harness writes its own per-session cost record, the meter reads it and reports its difference from list price.

## Outcomes and value

**C-12. Session-to-outcome links written at the time.** When seats post under shared identities, outcomes (PRs merged, reviews, tickets closed) cannot be joined to a session after the fact, and neither can the point where a defect was caught. The GATE or ack that closes a piece of work carries the session id.
