# Source registration without a machine selection

The Windows/Tk and Linux/Qt managers register a SCADA database using its customer,
site, project and source name. Select existing hierarchy entries or enter new
names. Neither form has an Existing machine selector or New machine tag entry.
Registration creates a source, collector, generation, protected upload credential
and draft mapping version. It never chooses a machine automatically or invents a
machine tag.

New credentials authorize only their registered source and initially have no
machine authorizations. Collector connection checks, encrypted setup export,
credential replacement and raw upload acceptance work before equipment is
assigned. Records with unknown mappings remain quarantined. An approved mapping
outside the credential's machine scope is still rejected; an empty scope is never
a wildcard.

Event identification uses a single explicitly authorized machine from the scope
saved when the upload was accepted. With no such assignment, the result is
uncertain, with no candidates and no model call. Event messages and `ev_source`
never supply a substitute identity. Alarm AI suggestions remain separate from
approved machine mappings.

Existing sources, machine UUIDs, credentials, mappings and event identities are
preserved. Administrative registration with an explicit machine ID or tag remains
available for compatibility. Later machine authorization and mapping approval
require explicit administration; they do not expand the immutable scope of
already accepted uploads. Replacing an unassigned credential retains an empty
machine scope.

This change needs no schema migration or upload-protocol change. Linux managers
need both the updated GUI and rebuilt management image; published installers
remain unchanged until rebuilt.

## Verification on 6 November 2026

- Windows manager/form validation: 29 passed; 24 Qt checks skipped because the
  optional Qt dependency is not installed in the Windows development environment.
- Disposable PostgreSQL 17 and 18: 134 passed on each; seven Linux manager checks
  skipped on each Windows run. Checks include source-only registration, encrypted
  export and replacement credentials, cross-customer rejection, unchanged explicit
  machine provisioning, quarantine and uncertain event identity without AI.
- Isolated Linux source copy: all 34 Qt, Linux vault and Docker-agent integration
  checks passed without skips against a fresh disposable PostgreSQL container.
  The disposable container was removed; operational source data was not used.
- A matching management image was built and applied to the existing VMware
  deployment after the previous manager window was closed normally. The selected
  project was stopped before replacing its four management files, then its
  existing services were resumed. No migration or runtime-login provisioning was
  rerun. API/database/worker readiness passed; source/generation/credential/scope
  fingerprints, `.env`, CA, vault files and named volumes remained unchanged.
- Reopened the updated manager in its own desktop service, selected Register
  source and visually verified that the live form has customer/site/project and
  source name, with no machine selector. The server remains ready. No operational
  registration was created for testing; published installers are unchanged.

The source change does not address the separate security-review findings or
claim remote Collector commissioning.
