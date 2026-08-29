"""
================================================================================
CEREBRO-X | DDS METRICS EXTRACTOR
================================================================================
Single source of truth for normalising DDS-record metrics across every
HTML5 visualization (H05, H10, H11, H13, H20 …) and every other consumer.

The bug this module fixes
-------------------------
The H-functions in `cerebro_html5_engine.py` were looking up dict keys
that did NOT exist in the DataFrame produced by `_run_dds_from_yaml`:

    expected by H-funcs              actually produced by run.py
    ---------------------            ------------------------------
    BBB_Enhanced_Pct                 BBB_Engineering_Score   (0-100)
    CNS_Bioavailability_Pct          (not computed — derive)
    Endosomal_Escape_Eff             PgP_Escape_Coeff        (0-1)
    Stealth_Index                    (derive from PEGylation)
    Payload_Efficiency_Pct           encapsulation_efficiency_pct
    Composite_Score                  Principle_Composite_Score
                                       OR  Composite_Score_Raw
                                       OR  BBB_Engineering_Score

Because every `d.get(missing_key) or 0` returned 0, every cell rendered
as 0% — the screenshot the user reported.

Design
------
Each metric has a list of ALIAS column names tried in priority order, plus
a fallback DERIVATION rule that synthesises a value from related columns.
This means future schema changes (column renames, additions, ML modules
contributing alternative scores) won't break the dashboard — just add the
new alias to the alias list.

Usage
-----
    from src.viz._dds_metrics import (
        extract_metric, METRIC_DEFS, get_score, get_pct, normalize_row
    )

    bbb_pct = extract_metric(dds_record, "BBB%")
    score   = get_score(dds_record)
    norm    = normalize_row(dds_record)        # all 6 metrics, 0-1 scale
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Union

# ── Type aliases ────────────────────────────────────────────────────────────
Number   = Union[int, float]
Record   = dict[str, Any]
DDSRows  = list[Record]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _to_float(x: Any) -> float | None:
    """Best-effort coercion: returns None for unrecognised / empty / NaN."""
    if x is None:
        return None
    if isinstance(x, (int, float)):
        # Reject NaN — pandas to_dict("records") emits raw float('nan') which
        # is != itself but still a float.
        if x != x:
            return None
        return float(x)
    s = str(x).strip()
    if not s or s.lower() in ("nan", "none", "null", "n/a", "#n/a"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _first_non_null(rec: Record, aliases: Sequence[str]) -> float | None:
    """Return the first numeric value found among aliases, else None."""
    for k in aliases:
        v = _to_float(rec.get(k))
        if v is not None:
            return v
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Metric definitions
# ─────────────────────────────────────────────────────────────────────────────
# Each metric:
#   key       : the public label used by H-functions ("BBB%", "Score", …)
#   aliases   : column names to try in priority order (highest fidelity first)
#   scale     : the natural scale ("pct" = 0-100, "frac" = 0-1, "raw" = absolute)
#   derive_fn : optional callable rec → float for synthetic derivation
#               when no alias is populated
#
# The extractor returns a value already on the 0-100 percentage scale
# (suitable for table cells), and a 0-1 normalised value (suitable for
# heatmap colour mapping / radar plots).
# ─────────────────────────────────────────────────────────────────────────────

# ── Derivation rules (used as last-resort) ──────────────────────────────────
def _derive_cns_bioavail(rec: Record) -> float | None:
    """CNS bioavailability ≈ (BBB-crossing fraction) × (1 − off-target liver loss)."""
    bbb = _first_non_null(rec, ("BBB_Engineering_Score", "BBB_Enhanced_Pct",
                                "BBB_Crossing_Pct"))
    liver = _first_non_null(rec, ("Off_Target_Liver_pct",))
    if bbb is None:
        return None
    bbb_frac = bbb / 100.0 if bbb > 1.0 else bbb
    off_frac = (liver or 30.0) / 100.0
    return max(0.0, min(100.0, 100.0 * bbb_frac * (1.0 - off_frac)))


def _derive_stealth(rec: Record) -> float | None:
    """Stealth quality from PEGylation degree.
    Optimal PEG % is 2-7 (mol%); follows a triangular profile centred at 5%.
    Returns 0-100.

    _first_non_null only returns the matched VALUE, not which alias
    supplied it — this used to guess the interpretation purely from the
    value's magnitude ("<= 1.0 => must be a 0-1 Stealth_Index fraction"),
    which silently misread any genuinely low-but-real PEGylation mol%
    (e.g. a formulation with 0.5 mol% PEG, a legitimate light-PEGylation
    value) as if it were a pre-normalised Stealth_Index of 0.5 (i.e.
    "50% stealth") — verified directly: {"pegylation_degree_mol_pct": 0.5}
    and {"Stealth_Index": 0.5} both scored exactly 50.0, even though
    0.5 mol% PEG is far from the 5% optimum and should score low under
    the function's own documented triangular profile. Fixed to check
    each alias explicitly so the interpretation depends on which column
    actually supplied the value, not on the value's magnitude.

    Also fixed the ascending branch's discontinuity: peg=0 returned 0.0
    exactly, but peg=0.001 jumped straight to ~30 (30.0 + 14.0*peg) —
    not the smooth triangular ramp the docstring describes. Replaced
    with a straight line from (0, 0) to (5, 100).
    """
    mol_pct = _first_non_null(rec, ("pegylation_degree_mol_pct",
                                     "PEGylation_Degree_mol_pct",
                                     "PEG_Degree_pct"))
    if mol_pct is not None:
        peg = mol_pct
    else:
        stealth_idx = _first_non_null(rec, ("Stealth_Index",))
        if stealth_idx is None:
            return None
        if 0 <= stealth_idx <= 1.0:
            return stealth_idx * 100.0
        peg = stealth_idx  # already on a percent-like scale

    # Triangular: peak at 5%, zero outside [0, 12]
    if peg <= 0:           return 0.0
    if peg >= 12:          return 20.0
    if peg <= 5:           return min(100.0, 20.0 * peg)                 # 0 → 100
    return max(0.0, 100.0 - (peg - 5.0) * 11.4)                          # 100 → ~20


def _derive_escape(rec: Record) -> float | None:
    """Endosomal/P-gp escape efficiency. Already 0-1 in PgP_Escape_Coeff."""
    v = _first_non_null(rec, ("PgP_Escape_Coeff", "Endosomal_Escape_Eff",
                                "Escape_Eff", "Endo_Escape"))
    if v is None:
        return None
    return v * 100.0 if v <= 1.0 else min(100.0, v)


def _derive_payload(rec: Record) -> float | None:
    """Payload efficiency = encapsulation efficiency."""
    return _first_non_null(rec, ("encapsulation_efficiency_pct",
                                   "Encapsulation_Efficiency_pct",
                                   "Payload_Efficiency_Pct", "EE_pct", "EE%"))


def _derive_score(rec: Record) -> float | None:
    """Composite ranking score. Try richer score first (62-principle),
    then BBB engineering score."""
    return _first_non_null(rec, (
        "Principle_Composite_Score",          # v21+ — 62-principle weighted
        "Composite_Score_Raw",                # raw before normalisation
        "Composite_Score",                    # legacy generic name
        "BBB_Engineering_Score",              # original BBB-only score
    ))


def _derive_bbb(rec: Record) -> float | None:
    return _first_non_null(rec, (
        "BBB_Enhanced_Pct",
        "BBB_Engineering_Score",
        "BBB_Crossing_Pct", "BBB_Score",
    ))


# ── Master metric registry ──────────────────────────────────────────────────
METRIC_DEFS: dict[str, dict[str, Any]] = {
    "BBB%": {
        "label": "BBB%",
        "long":  "BBB Engineering Score",
        "extractor": _derive_bbb,
        "out_scale": 100.0,    # extractor already returns 0-100
    },
    "CNS BA%": {
        "label": "CNS BA%",
        "long":  "CNS Bioavailability",
        "extractor": _derive_cns_bioavail,
        "out_scale": 100.0,
    },
    "Escape": {
        "label": "Escape",
        "long":  "Endosomal/P-gp Escape Efficiency",
        "extractor": _derive_escape,
        "out_scale": 100.0,
    },
    "Stealth": {
        "label": "Stealth",
        "long":  "Stealth (PEG quality)",
        "extractor": _derive_stealth,
        "out_scale": 100.0,
    },
    "Payload%": {
        "label": "Payload%",
        "long":  "Payload Efficiency (Encapsulation %)",
        "extractor": _derive_payload,
        "out_scale": 100.0,
    },
    "Score": {
        "label": "Score",
        "long":  "Composite Ranking Score",
        "extractor": _derive_score,
        "out_scale": 100.0,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────
def extract_metric(rec: Record, key: str, default: float = 0.0) -> float:
    """Return the metric for `key` (e.g. "BBB%") on a 0-100 scale.
    Returns `default` if both alias lookup AND derivation fail."""
    spec = METRIC_DEFS.get(key)
    if spec is None:
        # Key not registered — try direct lookup + alias-as-given
        v = _to_float(rec.get(key))
        return v if v is not None else float(default)
    v = spec["extractor"](rec)
    return float(v) if v is not None else float(default)


def normalize_row(rec: Record, metrics: list[str] | None = None) -> list[float]:
    """Return all metrics as a 0-1 vector (for heatmaps / radar fills)."""
    keys = metrics or list(METRIC_DEFS.keys())
    out: list[float] = []
    for k in keys:
        v = extract_metric(rec, k)
        scale = METRIC_DEFS[k]["out_scale"] if k in METRIC_DEFS else 100.0
        out.append(round(min(1.0, max(0.0, v / scale)), 4))
    return out


def get_pct(rec: Record, key: str) -> float:
    """Convenience: return the metric on the 0-100 percentage scale."""
    return extract_metric(rec, key, 0.0)


def get_score(rec: Record) -> float:
    """Convenience: return the best available composite ranking score."""
    return extract_metric(rec, "Score", 0.0)


def get_bbb(rec: Record) -> float:
    """Convenience: BBB-Engineering Score on 0-100."""
    return extract_metric(rec, "BBB%", 0.0)


def backfill_legacy_aliases(rec: Record, mol_profile: Record | None = None) -> Record:
    """Return a copy of `rec` with the legacy DDS key names populated from
    real, derived values instead of being absent entirely.

    Several visualization/report modules across the codebase
    (cerebro_advanced_modules_2.py, cerebro_science_modules.py,
    cerebro_video_engine_v2.py, cerebro_canvas_engine.py,
    cerebro_html5_engine.py, final_report_unified.py) read a DDS record
    directly via `top_dds.get("BBB_Enhanced_Pct", 30)`,
    `top_dds.get("Endosomal_Escape_Eff", 0.5)`, `top_dds.get("Stealth_Index",
    0.5)`, `top_dds.get("CNS_Bioavailability_Pct", 10)` -- names that
    `_run_dds_from_yaml`/`evaluate_all_dds_62` never produce, so every one
    of those lookups was silently returning the same hardcoded constant for
    every drug on every run, regardless of the formulation actually scored.
    This backfills the real values under those legacy names so any caller
    that still uses the old `.get()` pattern gets correct, per-drug data
    instead of a shared default.

    `Endosomal_Escape_Eff` and `Stealth_Index` are consumed everywhere as
    0-1 fractions (e.g. `escape*100` for display, `.2f`-formatted values
    like "0.65"), unlike `BBB%`/`Escape`/`Stealth` in METRIC_DEFS which are
    all on the 0-100 scale -- divide by 100 here to match the legacy
    callers' expectation. `CNS_Bioavailability_Pct` is consumed as a 0-100
    percentage everywhere (`.1f` + "%", or explicitly `/100` at call sites
    that need the fraction), matching `get_pct(rec, "CNS BA%")` directly.

    `BBB_Native_Pct` (BBB crossing WITHOUT any delivery system) is not a
    DDS-formulation property at all -- it comes from the molecule's own
    LogBB-based permeability estimate (`BBB_permeability_pct`, computed in
    molecule_engine.py from TPSA/LogP via the Young 1988 regression), so it
    is read from `mol_profile` rather than derived from `rec`.
    """
    out = dict(rec)
    out["BBB_Enhanced_Pct"] = extract_metric(rec, "BBB%")
    out["Endosomal_Escape_Eff"] = extract_metric(rec, "Escape") / 100.0
    out["Stealth_Index"] = extract_metric(rec, "Stealth") / 100.0
    out["CNS_Bioavailability_Pct"] = extract_metric(rec, "CNS BA%")
    native = mol_profile.get("BBB_permeability_pct") if mol_profile else None
    out["BBB_Native_Pct"] = float(native) if native is not None else 3.0
    return out


def coverage(rec: Record, threshold: float = 0.0) -> int:
    """How many of the 6 standard metrics have a real (>threshold) value?"""
    return sum(1 for k in METRIC_DEFS
                  if extract_metric(rec, k, -1.0) > threshold)


def diagnose(records: DDSRows) -> dict[str, Any]:
    """Return a small diagnostic report — useful when a dashboard
    looks suspicious (e.g. all-zero heatmap)."""
    if not records:
        return {"ok": False, "reason": "empty input"}
    n = len(records)
    populated = {k: 0 for k in METRIC_DEFS}
    for rec in records:
        for k in METRIC_DEFS:
            if extract_metric(rec, k, -1.0) > 0:
                populated[k] += 1
    avg_cov = sum(coverage(r) for r in records) / n
    return {
        "ok":          avg_cov >= 3,
        "n_records":   n,
        "populated":   populated,
        "avg_coverage": round(avg_cov, 2),
        "available_columns": sorted(set().union(*(set(r.keys()) for r in records))),
    }


__all__ = [
    "METRIC_DEFS",
    "backfill_legacy_aliases",
    "coverage",
    "diagnose",
    "extract_metric",
    "get_bbb",
    "get_pct",
    "get_score",
    "normalize_row",
]
