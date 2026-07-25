# LinkedIn post copy — CEREBRO-X carousel

Upload `slide_1.png` → `slide_4.png` as a 4-image carousel (LinkedIn reorders
by filename/upload order, so add them in that sequence). Suggested caption:

---

I've been building CEREBRO-X in the open: a computational pipeline that screens
CNS drug-delivery formulations — PBPK, colloidal stability (DLVO), docking,
QSAR off-target panels — before anyone touches a bench.

The thing I care about most isn't the feature list. It's that every number in
the reports it generates is a live computation against real ChEMBL/PubChem/
UniProt data — not a fixture, not a lookup table dressed up as a model. I've
spent a good chunk of this week specifically hunting for places where that
wasn't true yet, and fixing them when I found them:

→ A report panel was labeled "1000 bootstrap resamples" but wasn't actually
resampling anything — found it, replaced it with a real bootstrap over each
formulation's own real sub-scores.

→ For biologics (antibodies, oligonucleotides — anything without a small-
molecule SMILES structure), a resolver was silently falling back to using the
drug's own NAME as if it were a chemical structure. Found it, fixed it
generically, verified across several different biologics.

Both bugs were caught by actually running the pipeline end-to-end and
chasing anomalies in the output, not by code review alone. That's the standard
I'm holding this to: if I can't reproduce a number from a real run, it doesn't
go in a report.

It's a research prototype — not a clinical tool, and the audit trail in the
repo says so explicitly, including where it currently falls short. Swipe
through for what a real run actually looks like, and the repo's linked below
if you want to run it, break it, or tell me what's wrong with it.

🔗 github.com/mohamedtalaat-gif/CEREBRO-X

#DrugDelivery #ComputationalPharmaceutics #OpenSource #CNS #Cheminformatics

---

## Notes for whoever posts this
- All 4 numbers on slide 3 (38 receptor models, R² values) came directly from
  a real regeneration run on 2026-07-25 — see /tmp logs are gone now, but the
  same numbers are reproducible by re-running `python run.py` against any
  input in `inputs/`.
- If asked "what's the 75% accuracy claim" or similar — there isn't one live
  anymore; that was flagged and addressed in docs/AUDIT_REPORT.md §4.6/§0.1.
  Point people to the audit report directly if pressed; don't improvise a
  number.
