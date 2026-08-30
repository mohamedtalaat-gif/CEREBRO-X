# Contributing to CEREBRO-X

Thanks for your interest in this project. CEREBRO-X is a research-prototype
computational pipeline for CNS drug-delivery-system exploration, currently
maintained by a single author. This document sets expectations for anyone
who wants to report a bug, propose a change, or open a pull request.

## Before you start

Read the [README](README.md) first, in particular the
[Validation snapshot](README.md#validation-snapshot-3-drug-benchmark-phase-5)
section. This project makes no claim to be production-ready or clinically
validated, and the 62-criterion scoring rubric is explicitly labeled as an
internal heuristic system, not an externally validated framework.
Contributions that add unvalidated capability should be labeled with the
same honesty the rest of the codebase uses — see
[docs/AUDIT_REPORT.md](docs/AUDIT_REPORT.md) for the kind of scrutiny this
project holds itself to.

## Ways to contribute

- **Bug reports** — use the [bug report template](.github/ISSUE_TEMPLATE/bug_report.md).
  A report that includes the exact input (Excel file or a minimal
  reproduction), the command you ran, and the full traceback/log output is
  far more actionable than a description alone.
- **Feature requests** — use the [feature request template](.github/ISSUE_TEMPLATE/feature_request.md).
  Explain the pharmaceutical/computational problem you're trying to solve,
  not just the API you'd like — the fix is sometimes a different one than
  the one that seems obvious from outside the codebase.
- **Pull requests** — see below.
- **Scientific-integrity issues** — if you find a claim in the code, docs,
  or generated reports that overstates what's actually computed (a citation
  that doesn't match the method, a metric presented as validated when it's
  circular, a placeholder value presented as measured), please open an issue
  even if you're not proposing a fix. This project treats that class of bug
  as seriously as a functional one.

## Development setup

```bash
git clone https://github.com/mohamedtalaat-gif/CEREBRO-X.git
cd CEREBRO-X
pip install -r requirements.txt
pip install -r requirements-ml.txt   # optional: ML/cheminformatics extras
cp .env.example .env                  # fill in secrets before running the API
```

Run the pipeline directly with `python run.py`, or see
[docs/README_DEVELOPER.md](docs/README_DEVELOPER.md) (marked historical —
[README.md](README.md) is the current source of truth on architecture).

## Running tests

```bash
python -m pytest tests/ -m "not slow" -q
```

The full suite should pass before you open a pull request. If you're adding
a bug fix, add a regression test that fails against the old code and passes
against your fix — that's the pattern used throughout `tests/unit/test_all.py`,
and PRs that only touch behavior without a matching test are unlikely to be
merged as-is.

## Pull request guidelines

1. Keep PRs focused — one bug or one feature per PR. A PR that mixes an
   unrelated refactor with a bug fix is harder to review and harder to
   revert if something goes wrong.
2. Explain the *why*, not just the *what*, in the PR description — what was
   actually broken, and how you verified the fix (a failing test, a real
   pipeline run, a before/after comparison).
3. Don't add new "validated"/"production-ready"/similar claims to docs,
   READMEs, or generated report text without the evidence to back them —
   see the Status section linked above for why this matters here
   specifically.
4. New scientific modules or scoring criteria should cite their real source
   (a specific paper, a specific equation) and should not silently reuse an
   existing citation for an unrelated calculation.

## Reporting security issues

Please do **not** open a public issue for a security vulnerability. See
[SECURITY.md](SECURITY.md) for how to report it privately.

## Questions

Muhammad Talaat — mohamed.talaat@pharma.asu.edu.eg
