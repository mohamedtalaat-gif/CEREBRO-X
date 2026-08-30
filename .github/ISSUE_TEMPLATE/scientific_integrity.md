---
name: Scientific-integrity issue
about: A claim in the code, docs, or a generated report overstates what's
  actually computed
title: "[INTEGRITY] "
labels: scientific-integrity
assignees: ''
---

**Where is the claim?**
File/function, or the exact section of a generated PDF/HTML report, or a
line in the README/docs.

**What does it claim?**
Quote the exact wording if possible.

**What does the code actually do?**
Trace through the actual computation — is it a real independent method, a
heuristic re-labeled with a real technique's name, a circular check, or a
placeholder value presented as measured?

**Suggested fix**
Relabel to describe what's actually computed, replace with a real
implementation, or remove the claim — whichever applies.

This project treats this class of issue as seriously as a functional bug —
see [docs/AUDIT_REPORT.md](../../docs/AUDIT_REPORT.md) for the standard it
holds itself to.
