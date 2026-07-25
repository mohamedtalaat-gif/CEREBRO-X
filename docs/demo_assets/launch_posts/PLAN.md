# Launch plan — Hacker News + Reddit (Task 12)

Not posted anywhere yet. These are drafts for you to review, edit, and post
yourself (or tell me to post, with explicit go-ahead — public posts on your
behalf are a one-shot, irreversible action I won't take without you saying so
each time).

## Timing

Post Hacker News and Reddit on **different days**, not simultaneously — if
both take off at once you can't give either thread the attention it needs
in the first hour, which is when most of a post's fate is decided. Suggested
order: Reddit first (lower stakes, gives you a rehearsal for the FAQ),
Hacker News a few days later once you've seen what questions actually come up.

Best HN posting window: **weekday, ~9-11am US Eastern** (peaks when both US
and Europe are awake). Avoid Friday afternoon/weekend — lower traffic.

---

## Hacker News

### Title (pick one)

1. `Show HN: CEREBRO-X – open-source CNS drug-delivery screening, with a public audit trail of its own bugs`
2. `Show HN: I audited my own drug-delivery pipeline and published everything wrong with it`
3. `Show HN: CEREBRO-X – computational screening for CNS drug delivery formulations`

**Recommendation: #2.** HN's front page rewards intellectual honesty and
"here's what's actually true" framing far more than feature lists — a title
that leads with self-audit is unusual enough to earn a click, and it's
literally what happened this week (two real bugs found and fixed by running
the pipeline, not by review). #3 is the safe fallback if #2 reads as
attention-baiting to you.

### The link
Point the submission at the **GitHub repo**, not the live demo pages — HN
skews toward wanting to read code first, demo second.

### Required: your first comment (post this immediately after submitting)

HN's own convention is that a Show HN's context belongs in the OP's own
top-level comment, since the post itself is just a title + link.

```
Author here. CEREBRO-X screens computational drug-delivery-system formulations
for CNS drugs — PBPK simulation, DLVO colloidal stability, AutoDock Vina
docking, QSAR off-target panels — before anyone touches a bench.

The part I actually want feedback on isn't the feature list, it's the audit
process: docs/AUDIT_REPORT.md is a full engineering + scientific-integrity
review I ran against my own codebase, and I've been updating it every time
I find (and fix) something wrong, not just when it's convenient. This week
that included finding a report panel that fabricated a "1000 bootstrap
resamples" statistic (it wasn't resampling anything) and a resolver that
silently used a drug's plain name as if it were a chemical structure for
any biologic input. Both were caught by actually running the pipeline
end-to-end and chasing anomalies in the output, not by code review.

It's a research prototype, not a clinical tool — most drugs run through its
own internal scoring so far land at MARGINAL, not PASS, and the README says
so up front rather than in fine print. I'd rather have people point out
what's still wrong than pretend it's finished.

Happy to answer anything about the architecture, the QSAR panel, or why I
think publishing your own audit findings is worth the reputational risk.
```

### FAQ — likely HN questions, answered in advance so you're not improvising

- **"Is this just an LLM-generated wrapper around RDKit?"** → No — be ready
  to point at specific real computation: AutoDock Vina docking, real PBPK ODE
  integration (scipy), real ChEMBL-trained QSAR models (not lookup tables).
  Link `docs/AUDIT_REPORT.md` directly; it documents where things are still
  heuristic vs. genuinely computed and doesn't hide the difference.
- **"What's the actual accuracy?"** → There is no external validation
  benchmark yet — say so directly. Point to §4.7 of the audit report, which
  says this explicitly. Do not improvise a number.
- **"Why should I trust a self-reported audit?"** → You shouldn't, fully —
  that's an honest answer HN respects. Invite them to read the code and the
  audit's methodology section, not just the conclusion.
- **"License?"** → MIT (confirmed from the repo's LICENSE file, copyright
  Muhammad Talaat 2026).

---

## Reddit

Three subreddits, each needs its **own** post — cross-posting the identical
text reads as spam and gets removed/downvoted on all three. Check each
subreddit's rules for self-promotion limits before posting (several cap
self-promo at a fraction of your total post history — post something else
there first if you're a new account).

### r/bioinformatics (~150k members — biggest, most relevant, most technical)

**Title:** `Open-sourced my CNS drug-delivery screening pipeline, including a public audit of my own bugs`

**Body:**
```
Been building this for a while and finally pushed it public: CEREBRO-X, a
computational pipeline for screening CNS drug-delivery formulations —
PBPK, DLVO colloidal stability, docking (AutoDock Vina), QSAR off-target
panels, all against live ChEMBL/PubChem/UniProt data rather than fixtures.

What might actually be useful to this sub specifically: I keep a running
engineering + scientific-integrity audit in the repo
(docs/AUDIT_REPORT.md), including things I got wrong and fixed — a report
panel that fabricated a bootstrap-CI statistic, a resolver that silently
substituted a drug's name for its SMILES string when SMILES resolution
failed for biologics. Both found by actually running the pipeline and
chasing anomalies, not by code review.

Research prototype, not clinical — happy to get torn apart on the QSAR
methodology or anything else. Repo: github.com/mohamedtalaat-gif/CEREBRO-X
```

### r/cheminformatics (smaller, but exactly the target audience for the QSAR/docking angle)

**Title:** `CEREBRO-X: real-time QSAR + docking + PBPK for CNS drug-delivery formulation screening (open source)`

**Body:**
```
Sharing a project I've been building: a pipeline that scores candidate
drug-delivery-system formulations (liposomes, PLGA nanoparticles, etc.)
for CNS drugs, combining real AutoDock Vina docking, ChEMBL-trained QSAR
off-target panels, DLVO colloidal-stability physics, and PBPK simulation.

I'd genuinely like methodology criticism from this sub in particular —
the 62-criterion scoring rubric it uses is my own internal framework, not
an externally validated standard, and I say so explicitly in the repo
(it was previously mislabeled as a "validation framework" and I fixed
that framing once it was pointed out). If something in the QSAR panel or
the DLVO implementation looks wrong to someone who does this for a living,
I want to hear it before it goes further, not after.

github.com/mohamedtalaat-gif/CEREBRO-X — MIT licensed, runs locally or via
Docker.
```

### r/opensource (general audience — frame around the transparency practice, not the pharma domain)

**Title:** `I publish a running audit of my own project's bugs in the repo — sharing the practice, not just the tool`

**Body:**
```
Not asking anyone here to care about computational pharmaceutics
specifically (the project — CEREBRO-X — screens CNS drug-delivery
formulations). What I think might be worth discussing here is the
practice: docs/AUDIT_REPORT.md in the repo is a full engineering audit
I ran against my own code, and I update it every time I find something
wrong — including two bugs found this week by actually running the
pipeline and chasing anomalies in real output, not by code review alone.

Curious whether others do something similar — a living, versioned audit
trail instead of a one-time README disclaimer — and whether it's actually
useful to readers or just noise. Repo, if the domain interests you too:
github.com/mohamedtalaat-gif/CEREBRO-X
```

---

## Before posting anywhere

- [ ] Re-read `docs/AUDIT_REPORT.md` §0.4 (the honest bottom line) — make
      sure nothing in these drafts overstates where the project actually is.
- [ ] Have the GitHub repo's issues enabled and watched — both HN and Reddit
      threads move fast in the first few hours.
- [ ] Decide who's answering technical QSAR/docking questions if they get
      specific — that's you, not me; I can help you draft a reply but
      shouldn't post as you.
