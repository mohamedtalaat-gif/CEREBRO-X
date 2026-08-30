## What does this PR do?

<!-- One or two sentences. What was broken/missing, and what this changes. -->

## Why

<!-- The root cause, not just the symptom. If this fixes a bug, explain
     what was actually wrong -- not just what you changed. -->

## How was this verified?

<!-- A failing test that now passes, a real pipeline run, a before/after
     screenshot of generated output, etc. "It looks right" is not enough --
     see CONTRIBUTING.md. -->

- [ ] `python -m pytest tests/ -m "not slow" -q` passes locally
- [ ] Added/updated a regression test for this change
- [ ] Ran the pipeline end-to-end if this touches `run.py`, `pipeline_runner.py`,
      or any science/viz engine
- [ ] No new "validated"/"production-ready" claims added without evidence
      (see the Status section of [README.md](../README.md))

## Related issue

<!-- Closes #... -->
