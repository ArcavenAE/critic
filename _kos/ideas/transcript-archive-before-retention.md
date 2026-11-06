# Keep harness transcripts past the harness's own retention, for later reading

- **Status:** idea. Nothing here is ruled, and nothing is to be built from it.
- **Subject:** critic. Weighed against the alternatives below.
- **Asked by:** the operator, relayed by director, 2026-11-05. Paraphrased, since the request names a private project: session files are reported to be aging out; which project, critic perhaps, should archive, compress or otherwise preserve them for later processing?
- **Extends:** C-05 in `sim/requirements.md` ("Meter at write time"), which names the same pressure from the meter's side: "a meter that reads transcripts after the fact reads a floor."

## Short answer

Yes, keep them, and critic is the right home for the idea. The cheaper first step is not an archive. It is to find out what actually deletes the files and when, then raise the harness's retention setting on each host so nothing ages out while an archive is designed. An archive is worth building once the reader exists that needs months of history, and C-05 suggests the meter should not be that reader.

## Which project owns it

The test: if the subject project did not exist, would this node be filed at all?

- **critic.** critic is the reader. Its transcript ledger (C-04), its cost meter (C-09 to C-11) and its outcome links (C-12) all read transcripts, and C-05 exists because they age out. Without critic, nobody in the fleet would reprocess old transcripts, and an archive would be storage with no reader. That makes critic the owner.
- **The fleet usage-reporting project** (a private project that reports per-host harness configuration and usage). It also reads usage, but as configuration and current-state reporting, not month-scale reprocessing. It is a candidate second reader, not the owner. If it becomes the main consumer, this idea should move.
- **director.** director keeps custody of outputs and asks that would otherwise be lost when a session dies. A transcript is not an output in that sense: director's custody covers the record a seat hands on, not the raw log. Putting a bulk archive under director would widen custody into storage. It stays an object here.

## What deletes the transcripts

Claude Code has a `cleanupPeriodDays` setting for how long it keeps local transcripts. On the host where this was drafted, the key is **absent** from user settings, project settings and local settings, and no managed settings file exists. So the harness's default applies. I did not confirm the default's value or the exact deletion rule from the harness itself.

One reading does not fit a simple age cut: on that host, 46 of 1,466 transcript files were last modified in September 2026, the oldest on 2026-09-10, more than 50 days before the draft. Either cleanup runs only under conditions that host has not met, or it keys on something other than file mtime, or the report of aging out comes from other hosts. Settling this is the first probe, because the cheaper fix depends on it.

## The cheaper first step

Raise `cleanupPeriodDays` per host, in user settings, to a value that outlives the longest window any reader needs. It costs disk, not code. That host held 1,466 files and 7.6 GB. It does not solve cross-host collection or encryption. But it stops the loss while the rest is decided. Changing a user setting on every host is the operator's call and is not done here.

## If an archive is built

**Per host, no cross-host copy.** Each host archives its own transcripts into a local store the harness does not prune. Copying between hosts is out of scope: it widens where secret-shaped text lives, and fleet practice rules out ad hoc copies between hosts. Until an archive exists, a manual preserve is the stopgap: copy the files a reader will need into a dated, local directory before they age out.

**Compression and dedup.**
- Transcripts are JSON lines and compress well. One 55.6 MB transcript compressed with zstd at level 19 to 2.8 MB, about 20 to 1. That is one sample, not a fleet figure.
- Dedup has two levels. Whole files dedup by content hash. Within a session, repeated message copies are the C-04 case, and they belong to the ledger, not the archive. The archive stores bytes as written, so a later reader can apply a corrected rule.

**Secret-shaped content.** Transcripts hold tool output, environment fragments and pasted text, so they carry strings shaped like credentials. The archive needs:
- a file mode readable by the user only;
- encryption at rest, with the key in an operator-owned store the archiver cannot write, the same line the platform draws for third-party bearer material at rest;
- a retention period of its own, so the archive is not a second unbounded copy of every secret.

Reading an archived transcript is then a deliberate act with a key, not a directory listing.

## What later processing needs from it

- **Re-attribution.** Joining a session to its seat, team and generation after the fact (C-02 asks for this at spawn; old sessions predate it). This needs the session id, the project directory name and the first records of each file intact.
- **critic ledgers.** The transcript ledger and cost meter re-run over a window when a dedupe rule or price table changes (C-04, C-10). This needs the original bytes, not a summary.
- **Usage metrics** of the kind the operator has asked for across the fleet: per-seat and per-role cost, wait-turn cost (C-08), activity classes (C-07). These want months of history, which is the case for keeping more than the harness default.

## Open questions

1. What exactly deletes a transcript, and on which hosts has it happened? This is a one-host probe: read the harness's documented rule, then compare a host's oldest file against it.
2. Is a raised retention enough, so that the archive is never needed? It is, if C-05's write-time meter lands and the only later readers are the ledger re-runs.
3. Should the archive key live with the operator's store per host, or does one key per fleet suffice? The custody rule suggests per host.
