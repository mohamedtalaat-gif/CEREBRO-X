"""
================================================================================
CEREBRO-X |  cerebro_dds_inverse_design.py  —  DDS Formulation Optimizer
================================================================================
Created by: Muhammad Talaat — CEREBRO-X

WHAT THIS IS
------------
A genetic-algorithm search over the drug-delivery-system (DDS) FORMULATION
PARAMETER space (carrier type, ligand, size, zeta potential, PEGylation,
etc. — the same columns as the "2_DDS_Formulations" Excel sheet), using
CEREBRO-X's own existing composite scoring function
(cerebro_62_orchestrator.evaluate_all_dds_62) as the fitness function.

Given a drug, it searches for combinations of formulation parameters that
score highly against CEREBRO-X's 62-criterion rubric, and returns the
best candidates that were NOT present in the researcher's original input
list — i.e. combinations the search proposes rather than combinations the
researcher manually typed in.

WHAT THIS IS NOT — read before describing this to anyone
----------------------------------------------------------
- This is NOT a discovery of "novel drug delivery systems that never
  existed before." It recombines and interpolates within a parameter
  space the researcher already defines (the same Carrier_Type/Surface_
  Ligand/Size_nm/etc. ranges used everywhere else in this pipeline). It
  cannot propose a delivery mechanism outside that space (e.g. it cannot
  invent a new carrier chemistry), and it has NOT been checked against
  the patent/publication literature for whether a given combination has
  already been tried — that would require the FTO/prior-art search this
  project has flagged elsewhere as not yet implemented (see
  cerebro_62_translational_engine.py's trans_P32 patent-search TODOs).
- It optimizes against CEREBRO-X's OWN scoring rubric — which, per
  cerebro_62_principles_catalog.py's module docstring, is an in-house,
  not-independently-validated set of heuristics/correlations. A
  high-scoring candidate is a candidate CEREBRO-X's own rubric likes, not
  a candidate proven to work in a real formulation.
- It was NOT trained or validated on any pharma-company-scale or
  proprietary dataset — no such dataset is available to this project (as
  of 2026-07-25, confirmed with the project owner). It searches using the
  same public-benchmark/heuristic scoring already documented throughout
  this codebase.
- The correct, honest framing for any external description: "a
  computational tool that proposes candidate formulations for further
  wet-lab evaluation, by searching the formulation-parameter space against
  CEREBRO-X's internal scoring rubric" — NOT "an AI that discovers novel
  drug delivery systems."

METHOD
------
A standard genetic algorithm (tournament selection, uniform crossover,
per-gene mutation, elitism) — a well-established black-box optimization
technique, applied here to a search space that mixes categorical
(Carrier_Type, Surface_Ligand, Release_Kinetics, Scale_Up_Readiness) and
continuous (Size_nm, Zeta_Potential_mV, PDI, ...) genes, which is why a GA
was chosen over gradient-based or standard Bayesian optimization (both of
which handle mixed categorical/continuous spaces less naturally).
================================================================================
"""
from __future__ import annotations

import logging
import random

log = logging.getLogger("CEREBRO-DDS-INVERSE")

# ─────────────────────────────────────────────────────────────────────────────
# Search space — same domain as the "2_DDS_Formulations" Excel sheet /
# README's DDS input table. Ranges are illustrative defaults grounded in
# the example values already used throughout this project's demo inputs,
# not fitted from any dataset.
# ─────────────────────────────────────────────────────────────────────────────
CATEGORICAL_SPACE: dict[str, list[str]] = {
    "Carrier_Type": ["liposome", "plga", "lnp", "solid_lipid", "micelle",
                      "dendrimer", "aav9", "aav"],
    "Surface_Ligand": ["Transferrin", "RVG29", "ApoE", "Lactoferrin",
                        "GalNAc", ""],
    "Release_Kinetics": ["sustained", "burst", "pH_triggered", "thermal_triggered"],
    "Scale_Up_Readiness": ["lab", "pilot", "clinical"],
}
CONTINUOUS_SPACE: dict[str, tuple[float, float]] = {
    "Size_nm":                     (20.0, 300.0),
    "Zeta_Potential_mV":           (-40.0, 20.0),
    "PDI":                         (0.05, 0.40),
    "Encapsulation_Efficiency_pct": (40.0, 95.0),
    "Drug_Loading_Pct":            (1.0, 30.0),
    "pH_Trigger":                  (5.0, 7.4),
    "Phase_Transition_Temp_C":     (37.0, 45.0),
    "PEGylation_Degree_mol_pct":   (0.0, 10.0),
    "Endosomal_Escape_Eff":        (0.0, 1.0),
    "Elasticity_kPa":              (0.1, 5.0),
}
ALL_PARAMS = list(CATEGORICAL_SPACE) + list(CONTINUOUS_SPACE)


def _random_individual(rng: random.Random, idx: int) -> dict:
    ind = {"Formulation_ID": f"GA{idx:04d}", "Formulation_Name": f"Generated_{idx:04d}"}
    for k, choices in CATEGORICAL_SPACE.items():
        ind[k] = rng.choice(choices)
    for k, (lo, hi) in CONTINUOUS_SPACE.items():
        ind[k] = round(rng.uniform(lo, hi), 3)
    return ind


def _crossover(a: dict, b: dict, rng: random.Random) -> dict:
    child = {"Formulation_ID": "", "Formulation_Name": ""}
    for k in ALL_PARAMS:
        child[k] = a[k] if rng.random() < 0.5 else b[k]
    return child


def _mutate(ind: dict, rng: random.Random, rate: float = 0.15) -> dict:
    out = dict(ind)
    for k in ALL_PARAMS:
        if rng.random() < rate:
            if k in CATEGORICAL_SPACE:
                out[k] = rng.choice(CATEGORICAL_SPACE[k])
            else:
                lo, hi = CONTINUOUS_SPACE[k]
                out[k] = round(rng.uniform(lo, hi), 3)
    return out


def _dedupe_key(ind: dict) -> tuple:
    return tuple(ind[k] for k in ALL_PARAMS)


def generate_candidate_formulations(
    drug_bundle: dict,
    drug_name: str = "",
    existing_formulations: object | None = None,  # pandas.DataFrame, optional
    n_generations: int = 15,
    population_size: int = 24,
    top_k: int = 5,
    seed: int | None = 42,
) -> dict:
    """
    Search the DDS formulation-parameter space for high-scoring candidates,
    using cerebro_62_orchestrator.evaluate_all_dds_62 as the fitness
    function (the SAME scoring pipeline used everywhere else in
    CEREBRO-X — no separate/hidden scoring logic).

    Returns a dict with:
      - "candidates": top_k candidate formulations (dicts), each carrying
        its real Principle_Composite_Score and full per-principle
        breakdown from the real orchestrator run that produced it
      - "n_evaluated": total formulations actually scored across all
        generations (real count, not estimated)
      - "novel_vs_input": for each candidate, whether its parameter tuple
        differs from every row in existing_formulations (if provided) —
        i.e. "not something the researcher already typed in", the only
        novelty claim this function is entitled to make
      - "disclaimer": the honest-framing text from this module's docstring,
        repeated here so it travels with the output into reports
      - "search_seed": for exact reproducibility

    This will call the real scoring pipeline n_generations times (once per
    generation, batch-scoring the whole population) — for population_size=24,
    n_generations=15 that's ~360 real formulation evaluations through the
    same 57-principle surrogate engine used for real Excel input, so this is
    not fast (expect tens of seconds), but every score is real.
    """
    import pandas as pd
    from cerebro_62_orchestrator import evaluate_all_dds_62

    rng = random.Random(seed)
    drug_name = drug_name or drug_bundle.get("_meta", {}).get("name", "drug")

    population = [_random_individual(rng, i) for i in range(population_size)]
    n_evaluated = 0
    best_ever: list[dict] = []

    for gen in range(n_generations):
        df = pd.DataFrame(population)
        result = evaluate_all_dds_62(drug_bundle, df, drug_name=drug_name)
        ranked = result["ranked_df"]
        n_evaluated += len(df)

        scored = ranked.to_dict("records")
        scored.sort(key=lambda r: r.get("Principle_Composite_Score", 0), reverse=True)
        best_ever.extend(scored[:max(3, population_size // 4)])

        log.info(f"[DDS-GA] {drug_name} gen {gen+1}/{n_generations}: "
                 f"best={scored[0].get('Principle_Composite_Score', 0):.2f} "
                 f"mean={sum(r.get('Principle_Composite_Score', 0) for r in scored)/len(scored):.2f}")

        if gen == n_generations - 1:
            break

        # Elitism + tournament selection + crossover + mutation
        elites = scored[:max(2, population_size // 6)]
        next_pop = [{k: e[k] for k in ["Formulation_ID", "Formulation_Name"] + ALL_PARAMS} for e in elites]

        def tournament() -> dict:
            a, b = rng.sample(scored, 2)
            winner = a if a.get("Principle_Composite_Score", 0) >= b.get("Principle_Composite_Score", 0) else b
            return {k: winner[k] for k in ALL_PARAMS}

        while len(next_pop) < population_size:
            p1, p2 = tournament(), tournament()
            child = _crossover(p1, p2, rng)
            child = _mutate(child, rng)
            idx = len(next_pop)
            child["Formulation_ID"] = f"GA_g{gen+1}_{idx:04d}"
            child["Formulation_Name"] = f"Generated_g{gen+1}_{idx:04d}"
            next_pop.append(child)
        population = next_pop

    # Deduplicate best_ever by parameter tuple, keep highest score per unique tuple
    by_key: dict[tuple, dict] = {}
    for r in best_ever:
        key = _dedupe_key(r)
        if key not in by_key or r.get("Principle_Composite_Score", 0) > by_key[key].get("Principle_Composite_Score", 0):
            by_key[key] = r
    top = sorted(by_key.values(), key=lambda r: r.get("Principle_Composite_Score", 0), reverse=True)[:top_k]

    existing_keys = set()
    if existing_formulations is not None and len(existing_formulations) > 0:
        for _, row in existing_formulations.iterrows():
            try:
                existing_keys.add(tuple(row.get(k) for k in ALL_PARAMS))
            except Exception:
                pass

    for r in top:
        r["novel_vs_input"] = _dedupe_key(r) not in existing_keys

    disclaimer = (
        "Computational candidates from a genetic-algorithm search of "
        "CEREBRO-X's own formulation-parameter space, scored by CEREBRO-X's "
        "own (not independently validated) 62-criterion rubric. These are "
        "hypotheses for wet-lab evaluation, not validated novel delivery "
        "systems, and have not been checked against the patent/publication "
        "literature for prior art."
    )
    return {
        "candidates": top,
        "n_evaluated": n_evaluated,
        "n_generations": n_generations,
        "population_size": population_size,
        "search_seed": seed,
        "disclaimer": disclaimer,
        "method": "Genetic algorithm (tournament selection, uniform crossover, "
                  "per-gene mutation, elitism) over cerebro_62_orchestrator.evaluate_all_dds_62",
    }
