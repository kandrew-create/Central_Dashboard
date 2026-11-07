# Source registration without a machine selection

The Windows/Tk and Linux/Qt managers register a SCADA database using customer, site, project and source name. Select existing hierarchy entries or enter new names. Neither form has a machine selector or tag entry. Registration creates a source, collector, generation and protected upload credential, with no draft mapping or invented machine identity.

Credentials authorize only their registered customer/source/generation. Encrypted setup export, connection checks, credential replacement, upload acceptance and processing work without machine assignment or mapping approval. Central-only 0015 retires the mapping gate and releases historical holds for completed jobs; failed or unfinished jobs still need processing. See [source-scoped processing](source-scoped-processing.md).

Optional event identification uses a single explicitly authorized machine from the immutable scope saved when the upload was accepted. With no such assignment, identification remains uncertain, without candidates or a model call. Events never derive a substitute identity from messages or `ev_source`. This optional identity does not gate upload processing. Alarm AI suggestions remain separate and unverified.

Existing source/machine UUIDs, credentials, scope, original data, receipts, historical annotations and registered event identity remain preserved. Administrative registration with an explicit machine remains available for existing event identity; an empty scope never authorizes every machine. Credential replacement retains that scope. No Collector protocol change is needed.

Deploy matching GUI/API/worker code and migrate Central storage through 0015 before resuming services. Published installers remain unchanged until rebuilt. The evidence below records the earlier registration-only change, including its former mapping behavior; current behavior is described above.

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
