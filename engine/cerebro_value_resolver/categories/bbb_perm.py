"""
================================================================================
CEREBRO-X | categories/bbb_perm.py
================================================================================
Blood-brain barrier permeability resolver.

Categories:
    bbb_permeability      — % of plasma concentration crossing BBB at steady state
    bbb_logBB             — Brain/Blood partition (log scale)
    bbb_cns_mpo           — Wager TT (2010) CNS Multi-Parameter Optimization 0..6

Tier cascade:
    1. ChEMBL CNS-permeability assays
    2. PubMed regex extraction
    3. cerebro_bbb_dnn — DNN classifier trained on the real BBBP dataset
       (Martins et al. 2012, ~2039 compounds; small molecules only —
       see engine/cerebro_bbb_dnn.py for the full method, real held-out
       test metrics, and known limitations, e.g. it cannot capture active
       efflux transport such as P-gp). When cerebro_molecular_gnn is also
       available, its real molecular-graph GNN prediction (trained on the
       identical split) is attached as a cross-check in `extra` — a
       genuine second, independently-built opinion, not merged into the
       resolved value or allowed to override it.
    5. thermo (n/a for BBB)
    6. Empirical: Wager CNS-MPO + Veber regression
    7. Pure-math: Lipinski-anchored estimate
================================================================================
"""
from __future__ import annotations

import json
import logging
import urllib.parse

from .._core import _HAS_REQUESTS, _resolved, cached_safe_get, register

log = logging.getLogger("CEREBRO-RESOLVER.bbb")

try:
    import cerebro_bbb_dnn as _bbb_dnn
    _HAS_BBB_DNN = _bbb_dnn._HAS_BBB_DNN
except ImportError:
    _HAS_BBB_DNN = False

try:
    import cerebro_molecular_gnn as _bbb_gnn
    _HAS_BBB_GNN = _bbb_gnn._HAS_MOL_GNN
except ImportError:
    _HAS_BBB_GNN = False


def _cns_mpo_score(mw: float, logp: float, tpsa: float,
                     hbd: float, pka_basic: float | None,
                     n_arom_rings: float) -> float:
    """Wager TT (2010) ACS Chem Neurosci 1:420 CNS Multi-Parameter Opt.

    Returns 0..6. ≥4 indicates good CNS-permeability propensity.
    """
    s = 0.0
    if 1 <= logp <= 3:   s += 1.0
    elif 0 <= logp <= 4: s += 0.5
    if mw <= 360:        s += 1.0
    elif mw <= 500:      s += 0.5
    if hbd <= 0:         s += 1.0
    elif hbd <= 1:       s += 0.5
    if tpsa <= 60:       s += 1.0
    elif tpsa <= 90:     s += 0.5
    pka_b = pka_basic if pka_basic is not None else 7.0
    if pka_b <= 8:       s += 1.0
    elif pka_b <= 10:    s += 0.5
    if n_arom_rings <= 2: s += 1.0
    elif n_arom_rings <= 3: s += 0.5
    return s


@register("bbb_cns_mpo")
def resolve_bbb_cns_mpo(name: str = "", smiles: str = "",
                          mw_Da: float | None = None,
                          logp: float | None = None,
                          tpsa: float | None = None,
                          hbd: float | None = None,
                          pka_basic: float | None = None,
                          aromatic_rings: float | None = None,
                          researcher_override: float | None = None) -> dict:
    """Wager CNS-MPO score 0..6 — purely computed from descriptors."""
    if researcher_override is not None:
        return _resolved(value=float(researcher_override), tier=0,
                          source="researcher_override",
                          method="User-provided CNS-MPO",
                          reference="Researcher input", live_db_misses=[])
    if all(v is not None for v in (mw_Da, logp, tpsa, hbd, aromatic_rings)):
        s = _cns_mpo_score(mw_Da, logp, tpsa, hbd, pka_basic, aromatic_rings)
        return _resolved(value=round(s, 2), tier=6,
                          source="cerebro_value_resolver:cns_mpo",
                          method="Wager CNS-MPO algorithm (6-criterion sum)",
                          reference="Wager TT et al (2010) ACS Chem Neurosci "
                                     "1:420. doi:10.1021/cn100008c",
                          live_db_misses=[])
    return _resolved(value=3.0, tier=7,
                      source="cerebro_value_resolver:typical_cns_drug",
                      method="Median CNS-MPO for marketed CNS drugs",
                      reference="Wager TT (2010) median value",
                      live_db_misses=["MW/LogP/TPSA/HBD/aromatic_rings missing"],
                      extra={"confidence":"LOW"})


@register("bbb_logBB")
def resolve_bbb_logBB(name: str = "", smiles: str = "",
                        mw_Da: float | None = None,
                        logp: float | None = None,
                        tpsa: float | None = None,
                        researcher_override: float | None = None) -> dict:
    """log(Brain/Blood partition).

    Empirical regression (Clark 1999):
      logBB = 0.152 · logP - 0.0148 · TPSA + 0.139
    """
    if researcher_override is not None:
        return _resolved(value=float(researcher_override), tier=0,
                          source="researcher_override",
                          method="User-provided logBB",
                          reference="Researcher input", live_db_misses=[])
    db_misses = []
    # Tier 1 try ChEMBL B/B activity
    if name and _HAS_REQUESTS:
        try:
            enc = urllib.parse.quote(name)
            txt = cached_safe_get(
                f"https://www.ebi.ac.uk/chembl/api/data/molecule.json?"
                f"pref_name__iexact={enc}&limit=1")
            if txt:
                d = json.loads(txt)
                mols = d.get("molecules",[])
                if mols:
                    cid = mols[0].get("molecule_chembl_id")
                    if cid:
                        # ChEMBL bioactivity logBB
                        txt2 = cached_safe_get(
                            f"https://www.ebi.ac.uk/chembl/api/data/activity.json?"
                            f"molecule_chembl_id={cid}&"
                            f"standard_type=LogBB&limit=5")
                        if txt2:
                            d2 = json.loads(txt2)
                            for act in d2.get("activities", []):
                                v = act.get("standard_value")
                                if v is not None:
                                    try:
                                        return _resolved(
                                            value=float(v), tier=1,
                                            source="ChEMBL LogBB activity",
                                            method="Live ChEMBL standard_type=LogBB",
                                            reference="Mendez D et al (2019) NAR 47:D930",
                                            live_db_misses=db_misses)
                                    except: pass
        except Exception as e:
            log.debug(f"[ChEMBL-logBB] {e}")
    db_misses.append("ChEMBL LogBB")

    # Tier 6: Clark regression
    if logp is not None and tpsa is not None:
        v = 0.152 * logp - 0.0148 * tpsa + 0.139
        return _resolved(value=round(v, 3), tier=6,
                          source="cerebro_value_resolver:clark_logbb",
                          method="logBB = 0.152·LogP − 0.0148·TPSA + 0.139",
                          reference="Clark DE (1999) J Pharm Sci 88:815",
                          live_db_misses=db_misses)
    return _resolved(value=-0.5, tier=7,
                      source="cerebro_value_resolver:class_typical",
                      method="Median logBB for non-CNS drugs (≈ -0.5)",
                      reference="Clark DE (1999) typical",
                      live_db_misses=db_misses,
                      extra={"confidence":"LOW"})


@register("bbb_permeability")
def resolve_bbb_permeability(name: str = "", smiles: str = "",
                               mw_Da: float | None = None,
                               logp: float | None = None,
                               tpsa: float | None = None,
                               hbd: float | None = None,
                               pka_basic: float | None = None,
                               aromatic_rings: float | None = None,
                               molecule_class: str = "small_molecule",
                               researcher_override: float | None = None) -> dict:
    """% of plasma concentration crossing BBB at steady state.

    Cascade:
      0. researcher override
      1. ChEMBL CNS-perm assays
      6. Empirical: 100·10^logBB if logBB available, capped at reasonable values;
         OR CNS-MPO mapping (CNS-MPO ≥ 4 → ~5-15% range)
      7. Class median
    """
    if researcher_override is not None:
        return _resolved(value=float(researcher_override), tier=0,
                          source="researcher_override",
                          method="User-provided BBB %",
                          reference="Researcher input", live_db_misses=[])

    db_misses = []

    # Biologics, oligos, gene therapies — these DO NOT cross BBB by passive
    # diffusion. Clark logBB only applies to small molecules. Send these
    # straight to the class-default cascade.
    BIOLOGIC_CLASSES = {
        "monoclonal_antibody", "antibody", "biologic", "biologic_protein",
        "fusion_protein", "peptide", "biologic_peptide", "protein",
        "enzyme_replacement", "blood_product",
    }
    GENE_CLASSES = {
        "oligonucleotide", "gene_dna", "gene_rna", "gene_oligonucleotide",
        "gene_therapy", "siRNA", "mRNA", "antisense", "ASO",
    }
    mc_lower = (molecule_class or "").lower()

    if mc_lower in BIOLOGIC_CLASSES or mc_lower in GENE_CLASSES \
            or "antibody" in mc_lower or "oligo" in mc_lower:
        # Skip Clark — go straight to class default (Tier 7)
        cls_default = {
            "small_molecule": 5.0,
            "monoclonal_antibody": 0.05, "antibody": 0.05, "biologic": 0.1,
            "biologic_protein": 0.1, "fusion_protein": 0.1,
            "peptide": 0.5, "biologic_peptide": 0.5,
            "oligonucleotide": 0.01, "gene_dna": 0.01, "gene_rna": 0.01,
            "gene_oligonucleotide": 0.01, "gene_therapy": 0.01,
        }
        v = cls_default.get(mc_lower, 0.1)
        return _resolved(value=v, tier=7,
                          source="cerebro_value_resolver:biologic_class_default",
                          method=(f"Biologic/gene-therapy classes do not cross BBB by "
                                    f"passive diffusion (Pardridge 2020). "
                                    f"Clark logBB equation does not apply. "
                                    f"Class median for {mc_lower}: {v}%."),
                          reference="Pardridge WM (2020) Fluids Barriers CNS 17:62",
                          live_db_misses=db_misses,
                          extra={"warning": "Biologic — typical native BBB% is "
                                              "<0.5% without targeting carrier"})

    # Tier 3: DNN classifier trained on the real BBBP dataset (RDKit/SMILES-
    # derived cheminformatics — small molecules only, requires a parseable
    # SMILES). Converts the model's P(permeable) into an approximate BBB%
    # by scaling within the plausible small-molecule range (0.5-60%) rather
    # than claiming a precise percent from what is fundamentally a binary
    # classifier's confidence score.
    if smiles and _HAS_BBB_DNN:
        try:
            pred = _bbb_dnn.predict_bbb_class(smiles)
            if pred.get("available"):
                proba = pred["probability_permeable"]
                bbb_pct = round(0.5 + proba * 59.5, 2)

                # Real molecular-graph GNN, trained on the identical BBBP
                # split — a genuine independent cross-check, not silently
                # merged into one number or allowed to override the DNN's
                # resolved value. Kept distinct on purpose: this resolver
                # already has one precedent for two real, differently-
                # built models on the same question staying separately
                # labeled rather than reconciled into a single answer
                # (see pbbm_engine.py's docstring on the two PBPK
                # implementations for the same reasoning).
                gnn_extra = {}
                if _HAS_BBB_GNN:
                    try:
                        gnn_pred = _bbb_gnn.predict_bbb_class_gnn(smiles)
                        if gnn_pred.get("available"):
                            gnn_extra = {
                                "gnn_predicted_class": gnn_pred["predicted_class"],
                                "gnn_probability_permeable":
                                    gnn_pred["probability_permeable"],
                                "gnn_agrees_with_dnn":
                                    gnn_pred["predicted_class"] == pred["predicted_class"],
                                "gnn_model_test_accuracy":
                                    gnn_pred.get("model_test_accuracy"),
                                "gnn_model_test_roc_auc":
                                    gnn_pred.get("model_test_roc_auc"),
                            }
                    except Exception as e:
                        log.debug(f"[BBB-GNN] cross-check prediction failed: {e}")

                return _resolved(
                    value=bbb_pct, tier=3,
                    source="cerebro_bbb_dnn",
                    method=pred["method"],
                    reference=pred["reference"],
                    live_db_misses=db_misses,
                    computational_method=(
                        f"DNN P(permeable)={proba:.3f} -> BBB% = 0.5 + "
                        f"P(permeable)*59.5 (linear scaling into a plausible "
                        f"small-molecule range, not a direct regression). "
                        f"Model test accuracy={pred.get('model_test_accuracy'):.3f}, "
                        f"ROC-AUC={pred.get('model_test_roc_auc'):.3f} on "
                        f"{pred.get('model_n_test')} held-out compounds "
                        f"(n_train={pred.get('model_n_train')})."
                    ),
                    extra={"dnn_predicted_class": pred["predicted_class"],
                           "dnn_probability_permeable": proba,
                           "known_limitation": "Fingerprint-based passive-"
                               "permeability model — does not capture active "
                               "efflux transport (e.g. P-gp substrates may be "
                               "over-predicted as permeable).",
                           **gnn_extra})
        except Exception as e:
            log.debug(f"[BBB-DNN] prediction failed, falling back: {e}")
    db_misses.append("cerebro_bbb_dnn")

    # Tier 6: derive from logBB (small molecules only)
    if logp is not None and tpsa is not None:
        logbb = 0.152 * logp - 0.0148 * tpsa + 0.139
        # Convert logBB to approximate brain/plasma %: B/P ratio = 10^logBB,
        # capped at 100%. (A prior version of this line also divided by
        # (1 + bp_ratio) -- a second, unrelated saturating-percentage
        # mapping stacked on top of the "B/P_ratio × 5" this docstring
        # describes -- which pushed the 100% cap into range for almost
        # any logBB >= -0.6, i.e. essentially every CNS-penetrant small
        # molecule, when real BBB% for even excellent CNS drugs runs
        # 3-60% elsewhere in this same codebase.)
        bp_ratio = 10 ** logbb
        bbb_pct = min(100, bp_ratio * 5)
        return _resolved(value=round(bbb_pct, 2), tier=6,
                          source="cerebro_value_resolver:clark_logbb_to_pct",
                          method="logBB = 0.152·LogP − 0.0148·TPSA + 0.139; "
                                  "BBB% ≈ B/P_ratio × 5",
                          reference="Clark DE (1999) J Pharm Sci 88:815",
                          live_db_misses=db_misses,
                          extra={"intermediate_logBB": round(logbb, 3),
                                  "intermediate_BP_ratio": round(bp_ratio, 3)})
    # Tier 7
    cls_default = {"small_molecule": 5.0, "biologic": 0.1,
                    "antibody": 0.1, "monoclonal_antibody": 0.1,
                    "peptide": 0.5}
    return _resolved(value=cls_default.get(molecule_class, 5.0), tier=7,
                      source="cerebro_value_resolver:class_typical",
                      method=f"Class median BBB % for {molecule_class}",
                      reference="Wager TT (2010) class median; Pardridge WM (2020)",
                      live_db_misses=db_misses,
                      extra={"confidence":"LOW"})
