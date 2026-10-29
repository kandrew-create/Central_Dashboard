# Pasted registration-name validation fix

The visible project name was within the 255-character limit, but its underlying entry contained an embedded Windows CR/LF line break. The user confirmed that the name had been pasted. The previous validator rejected all control characters using the same generic length message, making the valid-length input appear inexplicably invalid.

## Behavior

- Pasted CR/LF/tab separators and their adjacent spaces are folded into a single ordinary space. Surrounding whitespace is trimmed before checking length.
- Empty names, values above 255 characters, and remaining unsupported control characters have distinct messages. Overlength errors include the normalized character count.
- The GUI validates and displays normalized new names before starting database work. Existing customer/site/project/machine selections continue to reuse their IDs without requiring the corresponding new-name fields.
- Backend validation remains authoritative. A failure during registration preserves the previous registry through transaction rollback.

The current project field was cleaned without submitting registration or changing its other fields. No customer/source registration was submitted by this investigation. The updated installer was rebuilt for future pasted inputs; it was not applied over the user's open registration form.

## Executed verification

| Check | Result |
|---|---|
| Focused GUI and name-validation checks | 15 passed |
| Full suite on disposable PostgreSQL 17.11 | 198 passed, zero skipped |
| Full suite on disposable PostgreSQL 18.6 | 198 passed, zero skipped |
| Fresh initialization, migrations, verified HTTPS and repeated starts on both versions | Passed |
| PyInstaller executable and Inno Setup installer build | Passed |
| Executable and installer SHA-256 sidecars | Verified |

Regression coverage includes visible valid project names, Unicode labels, boundary lengths, pasted wrapping with adjacent spaces, empty input, unsupported controls, normalization before GUI submission, actual normalized project storage and rollback after rejected input. Each full suite emitted one Starlette/httpx deprecation warning.

All database regression checks used fresh disposable clusters. The running Central Server and its live registry were not used for test inserts. The rebuilt installer is `dist/installer/Linker-Central-Server-Setup.exe`; its SHA-256 is `94efa398210ebb83431225f5d666b6a0e976d103f92dcfb48168c8f8003d971b`.
