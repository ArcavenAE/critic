# Apple Signing Readiness

This repository is provisioned for Apple code signing but has no signing
pipeline yet — there is currently no macOS binary artifact to sign.

Provisioned on 2026-07-04 (ArcavenAE fleet signing review):

- **Org secrets**: this repo is on the selected-repository allowlist for the
  10 org-level signing secrets (`APPLE_CERTIFICATE_P12`,
  `APPLE_CERTIFICATE_PASSWORD`, `APPLE_INSTALLER_CERTIFICATE_P12`,
  `APPLE_INSTALLER_CERTIFICATE_PASSWORD`, `APPLE_SIGNING_IDENTITY`,
  `APPLE_INSTALLER_IDENTITY`, `APPLE_NOTARIZATION_APPLE_ID`,
  `APPLE_NOTARIZATION_PASSWORD`, `APPLE_NOTARIZATION_TEAM_ID`,
  `HOMEBREW_TAP_TOKEN`).
- **`release` GitHub environment**: exists with deployment policies
  restricting it to the `main` branch and `v*` / `alpha-*` tags. Signing
  jobs must declare `environment: release` so secrets are only exposed
  inside it.
- **`SIGNING_ENABLED` repo variable**: set to `false`. The signing job in
  any future release workflow should gate on
  `if: vars.SIGNING_ENABLED == 'true'` — flipping this variable is the
  single activation step.

This repo is Rust (operator ruling 2026-10-15, R3 in docs/design/critic-mvp.md) and currently ships no compiled binary, so there is nothing to codesign today. The Phase 0 scripts under `skills/` are Python and are not a signed artifact. If distribution ever needs a signed macOS artifact (a Rust binary, or a .pkg of scripts), copy the org-standard release pipeline: flyloft's `release.yml` is the reference (build, sign-and-notarize, release, homebrew, gated as described above).
