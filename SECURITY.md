# Security Policy

## Supported Versions

CEREBRO-X is a research prototype under active development. Only the latest
version on the `main` branch receives security fixes — there is no
long-term-support branch.

| Version | Supported          |
| ------- | ------------------ |
| main (latest) | :white_check_mark: |
| older tags/commits | :x: |

## Reporting a Vulnerability

**Please do not open a public GitHub issue for a security vulnerability.**

Report it privately by emailing **mohamed.talaat@pharma.asu.edu.eg** with:

- A description of the vulnerability and its potential impact
- Steps to reproduce it (a minimal example is ideal)
- The affected file(s)/endpoint(s), if known

You can expect an acknowledgment within a few days. This is a single-
maintainer project, so response time may vary, but every report will be
read and taken seriously.

If the report is confirmed, a fix will be developed and released as soon as
practical, and you will be credited in the fix's commit/changelog unless you
prefer to remain anonymous.

## Scope

This policy covers the code in this repository: the FastAPI application
(`src/api/`), the authentication/RBAC layer (`src/api/auth.py`), the
pipeline execution code, and the Docker/deployment configuration
(`docker-compose*.yml`, `Dockerfile*`, `nginx/`).

It does **not** cover the scientific validity of the pipeline's outputs
(e.g. a scoring heuristic being inaccurate) — that's tracked as a regular
issue or in [docs/AUDIT_REPORT.md](docs/AUDIT_REPORT.md), not as a security
report. It also does not cover third-party dependencies directly — please
report those to the upstream project, though a note here is still welcome
if a specific pinned version in `requirements.txt`/`Dockerfile` is affected.

## Known limitations (already tracked, not new reports)

The project's own audit ([docs/AUDIT_REPORT.md](docs/AUDIT_REPORT.md))
documents security-relevant findings and their current remediation status
in detail. Please check there first — several historical findings (auth
entrypoint, CORS, secret handling, rate limiting) are already resolved and
verified, and the remaining gaps are listed explicitly rather than hidden.
