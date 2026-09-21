# RealWorld API Contract Tests

This directory contains local, unmodified copies of the official RealWorld Hurl tests used to verify the public HTTP API contract.

## Upstream

- Repository: `realworld-apps/realworld`
- Commit: `ebbcdeb8d55b42a3a613c787560498b8ef10003f`
- Source directory: `specs/api/hurl`
- Local directory: `tests/api/hurl`

The upstream commit fixed in `docs/api/CONTRACT.md` remains the source of truth. Do not change local requests or assertions to accommodate this implementation. When the contract version changes through an explicit project decision, replace the files from the newly selected upstream commit and update this document and `docs/api/CONTRACT.md` together.

## Prerequisites

- Install Hurl and make it available on `PATH`.
- Apply the required database migrations.
- Start the API.
- Run the commands from the repository root.

## Command Values

Replace values enclosed in `<...>` before running a command.

| Value | Description | Example |
|---|---|---|
| `<api-origin>` | API origin without `/api` | `http://localhost:8000` |
| `<fresh-unique-value>` | Unique value for one complete test run | `local-20260921-001` |
| `<hurl-file-or-directory>` | Hurl file or directory to execute | `tests/api/hurl/auth.hurl` |
| `<last-entry-number>` | Last entry to execute | `6` |

## Commands

The following examples use PowerShell.

### Run a file or directory

```powershell
hurl --test --jobs 1 `
  --variable "host=<api-origin>" `
  --variable "uid=<fresh-unique-value>" `
  "<hurl-file-or-directory>"
```

Use `tests/api/hurl` as the target to run all local Hurl files.

### Run through a specific entry

```powershell
hurl --test --jobs 1 `
  --variable "host=<api-origin>" `
  --variable "uid=<fresh-unique-value>" `
  --to-entry "<last-entry-number>" `
  "<hurl-file>"
```

This runs the selected file from its first entry through the specified entry. Use one file per command because files can require different last-entry values.

### Diagnose all reachable failures

```powershell
hurl --test --jobs 1 --continue-on-error `
  --variable "host=<api-origin>" `
  --variable "uid=<fresh-unique-value>" `
  "<hurl-file-or-directory>"
```

## Rules

- Do not include `/api` in `host`; each Hurl request already includes it.
- Use a new `uid` for every complete test run.
- Entries in the same file must use the same `uid`.
- Preserve request order and use `--jobs 1` unless the selected files are known to be independent.
- Do not modify upstream requests or assertions to make the implementation pass.
- Use `--continue-on-error` only for diagnosis. A run containing assertion failures is not a passing contract result.
