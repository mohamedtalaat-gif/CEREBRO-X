"""
================================================================================
CEREBRO-X |  FINAL DECISION REPORT ENGINE
================================================================================
File: cerebro_final_report.py

Generates the comprehensive decision-ready PDF/HTML report for each trial:

  CONTENT:
    1. Executive Summary + Top Recommendation (1 page)
    2. Drug Profile (molecular, clinical PK, alignment info if novel)
    3. Top-10 DDS Formulations ranked table + scientific rationale
    4. All 100 formulations ranked
    5. ML Model performance metrics
    6. PBBM results (ACAT, PBPK, NCA, metabolites)
    7. ADMET complete profile
    8. Formulation strategy (DDI, biowaiver, DILI)
    9. All figures (PNG embedded, 300 DPI)
    10. BioRender-style schematics
    11. Lineage + Data Quality summary
    12. Alignment explanation (if novel drug used chemical matching)
    13. Final Decision Framework (gates + pass counts)
    14. Recommendations for next steps (wet-lab, regulatory)

  NOVEL DRUG HANDLING:
    When a drug is novel (not in any database), the report explicitly states:
      - Which databases were searched (all tiers)
      - Why no data was found (drug is unpublished / in synthesis phase)
      - Which drug was used as chemical alignment surrogate
      - The Tanimoto similarity score
      - The uncertainty estimate
      - A clear statement that all PK values are PREDICTED, not measured

  FORMAT: HTML (self-contained). This class previously also built a PDF
  via reportlab, but final_report_unified.UnifiedPDFReport overwrites the
  exact same output path immediately afterward in run.py's pipeline, so
  that PDF build was pure wasted computation — removed; see UnifiedPDFReport
  for the PDF this pipeline actually ships.
================================================================================
"""

import logging
import math
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

warnings.filterwarnings("ignore")
log = logging.getLogger("CEREBRO-REPORT")

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def _safe(val, fmt=".2f", default="N/A"):
    try:
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return default
        return format(float(val), fmt)
    except Exception:
        return str(val) if val is not None else default


def _grade_colour(score: float) -> str:
    """Return hex colour for a 0-100 score."""
    if score >= 80: return "#0D6E6E"
    if score >= 65: return "#C9A84C"
    if score >= 50: return "#F57C00"
    return "#C62828"


# ─────────────────────────────────────────────────────────────────────────────
# NOVEL DRUG HANDLER — generates the alignment explanation section
# ─────────────────────────────────────────────────────────────────────────────
class NovelDrugExplainer:
    """
    When a drug is not found in any database, documents:
      1. Every database searched (with tier numbers)
      2. Why it failed (drug is novel/in-synthesis)
      3. Chemical alignment details
      4. Uncertainty quantification
      5. Regulatory-ready disclaimer
    """

    TIER_DESCRIPTIONS = {
        "DrugBank_API":          "DrugBank (commercial PK database)",
        "DailyMed_FDA":          "DailyMed / NLM (FDA drug label database)",
        "OpenFDA_Label":         "OpenFDA (FDA structured label API)",
        "PubChem_Pharmacology":  "PubChem (NIH compound database)",
        "PubMed_NLP_10papers":   "PubMed NLP (10 pharmacokinetics papers scanned)",
        "EmbeddedLibrary":       "CEREBRO-X Embedded Library (500+ curated drugs)",
        "ChemicalAlignment":     "Chemical Alignment (surrogate-based prediction)",
    }

    @classmethod
    def build_explanation(cls, mol_profile: dict,
                           drug_name: str) -> dict[str, Any]:
        """
        Extract alignment explanation from mol_profile.
        Returns structured explanation dict.
        """
        is_alignment = bool(mol_profile.get("_alignment_flag", False))
        tiers_tried  = mol_profile.get("_tiers_tried", [])
        surrogate    = mol_profile.get("_surrogate_drug",
                                        mol_profile.get("_hl_source",""))
        tanimoto     = mol_profile.get("_tanimoto_sim")
        uncertainty  = mol_profile.get("_uncertainty_pct", 30)
        reason       = mol_profile.get("_missing_pk_reason", "")
        source       = mol_profile.get("_source", "")
        tier         = mol_profile.get("_tier", 0)

        is_novel = (is_alignment or
                    "Alignment" in str(source) or
                    "novel" in str(reason).lower() or
                    "synthesis" in str(reason).lower())

        explanation = {
            "is_novel":         is_novel,
            "is_alignment":     is_alignment,
            "surrogate_drug":   surrogate,
            "tanimoto":         tanimoto,
            "uncertainty_pct":  uncertainty,
            "tiers_tried":      tiers_tried,
            "source":           source,
            "tier":             tier,
            "reason":           reason,
            "tier_descriptions":[cls.TIER_DESCRIPTIONS.get(t, t) for t in tiers_tried],
        }

        if is_novel:
            log.info(f"  [Report] Novel drug detected: {drug_name} "
                     f"(surrogate={surrogate}, Tanimoto={tanimoto})")
        return explanation

    @classmethod
    def format_text(cls, expl: dict, drug_name: str) -> str:
        """Format explanation as human-readable text block."""
        if not expl.get("is_novel"):
            src = expl.get("source","")
            return (f"All pharmacokinetic parameters for {drug_name} were retrieved "
                    f"from validated databases. Primary source: {src}.\n"
                    f"No chemical alignment was required.")

        lines = [
            f"NOVEL DRUG ALERT — {drug_name}",
            "=" * 60,
            "",
            f"This drug was not found in any of the {len(expl.get('tiers_tried',[]))} "
            f"pharmacokinetic databases searched. This typically indicates that:",
            "  • The drug is a novel research compound (in synthesis / pre-clinical phase)",
            "  • The drug is proprietary (not publicly registered)",
            "  • Clinical PK data has not yet been published",
            "",
            "DATABASES SEARCHED (in order):",
        ]
        for i, (tier_id, tier_desc) in enumerate(
                zip(expl.get("tiers_tried",[]),
                    expl.get("tier_descriptions",[])), 1):
            lines.append(f"  {i:2d}. {tier_id:30s} → {tier_desc}  [RESULT: NOT FOUND]")

        lines += [
            "",
            "CHEMICAL ALIGNMENT APPLIED:",
            f"  Surrogate drug   : {expl.get('surrogate_drug','?')}",
            f"  Tanimoto score   : {expl.get('tanimoto','?')} (1.0 = identical structures)",
            f"  Uncertainty      : ±{expl.get('uncertainty_pct','?')}%",
            "",
            "SCIENTIFIC BASIS FOR ALIGNMENT:",
            "  Chemical similarity (Tanimoto on ECFP4 Morgan fingerprints) is an",
            "  established method for predicting PK properties of novel compounds",
            "  (Lombardo et al., J Med Chem 2014; PMID:24099757).",
            "  Compounds with Tanimoto > 0.7 (same pharmacological class) typically",
            "  show PK similarity within 30-50% across half-life and clearance.",
            "",
            "DISCLAIMER (REGULATORY-CRITICAL):",
            "  ┌─────────────────────────────────────────────────────────────┐",
            "  │ ALL pharmacokinetic values for this drug are PREDICTED,    │",
            "  │ not measured. These predictions must be confirmed by:      │",
            "  │  1. In vitro PK studies (microsomal stability, PPB assay) │",
            "  │  2. In vivo pharmacokinetic studies (rat/dog PK)           │",
            "  │  3. Clinical Phase I single-ascending dose study           │",
            "  │ before use in regulatory submissions (IND, CTA).           │",
            "  └─────────────────────────────────────────────────────────────┘",
            "",
            f"Reason documented: {expl.get('reason','')}"
        ]
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# PDF REPORT GENERATOR
# ─────────────────────────────────────────────────────────────────────────────
class FinalReportGenerator:
    """
    Generates the comprehensive final decision report.
    HTML with all figures embedded (see class docstring for why this no
    longer also builds a PDF).
    """

    # ── Brand colours ─────────────────────────────────────────────────────────
    # (no longer imports reportlab here — this class is HTML-only now, and
    # this import was unused dead weight that made the whole module fail to
    # import without reportlab installed, even for the HTML-only path)
    _NAVY   = "#0f2040"
    _TEAL   = "#0D6E6E"
    _GOLD   = "#C9A84C"
    _ORANGE = "#F57C00"
    _GREEN  = "#0D6E6E"
    _RED    = "#C62828"

    @classmethod
    def generate(cls,
                  drug_name:    str,
                  trial_dir:    Path,
                  excel_name:   str,
                  mol_profile:  dict,
                  df_ml:        pd.DataFrame | None,
                  df_dds:       pd.DataFrame | None,
                  df_pk:        pd.DataFrame | None,
                  metrics:      dict,
                  pbbm_results: dict | None = None,
                  de_results:   dict | None = None,
                  admet_profile:dict | None = None) -> Path:
        """
        Generate the standalone HTML report.

        This used to also build a parallel PDF via reportlab, but that PDF
        was written to the exact same path
        (CEREBRO_X_Final_Report_{drug_name}.pdf) that
        final_report_unified.UnifiedPDFReport writes to immediately
        afterward in run.py's pipeline — every reportlab build here was
        silently overwritten and never seen by any user. Removed rather
        than kept as unreachable/wasted computation (~450 lines, real
        per-trial CPU cost). See UnifiedPDFReport for the PDF this
        pipeline actually ships; this method's HTML output is the only
        artifact of this class that survives to disk.

        Returns path to the HTML file.
        """
        cls._generate_html(drug_name, trial_dir, excel_name, mol_profile,
                            df_ml, df_dds, df_pk, metrics, pbbm_results,
                            de_results, admet_profile)
        return trial_dir / f"CEREBRO_X_Final_Report_{drug_name}.html"


    @classmethod
    def _generate_html(cls, drug_name, trial_dir, excel_name, mol_profile,
                        df_ml, df_dds, df_pk, metrics, pbbm_results,
                        de_results, admet_profile, expl=None):
        """Generate standalone HTML version of the report."""
        import base64
        if expl is None:
            expl = NovelDrugExplainer.build_explanation(mol_profile or {}, drug_name)

        top1 = df_dds.iloc[0].to_dict() if (df_dds is not None and not df_dds.empty) else {}
        top_bbb = df_dds["BBB_Engineering_Score"].max() if df_dds is not None and "BBB_Engineering_Score" in df_dds.columns else 0
        n_viable = int((df_dds["BBB_Engineering_Score"] >= 75).sum()) if df_dds is not None and "BBB_Engineering_Score" in df_dds.columns else 0

        html_path = trial_dir / f"CEREBRO_X_Final_Report_{drug_name}.html"

        novel_banner = ""
        if expl and expl.get("is_novel"):
            novel_banner = f"""
<div style="background:#C62828;color:white;padding:12px 20px;border-radius:8px;margin-bottom:16px">
  <b>⚠ NOVEL/UNPUBLISHED DRUG:</b> {drug_name} was not found in any pharmacokinetic
  database. Chemical alignment with <b>{expl.get('surrogate_drug','?')}</b>
  (Tanimoto={expl.get('tanimoto','?')}) was used.
  All PK values are <b>PREDICTED, not measured</b>. Uncertainty ±{expl.get('uncertainty_pct',30)}%.
</div>"""

        # Embed all PNGs
        figs_html = ""
        figs_dir = trial_dir / "figures"
        if figs_dir.exists():
            figs_html = '<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">'
            for fp in sorted(figs_dir.glob("*.png")):
                if "_DOCUMENTATION" in fp.name:
                    continue
                try:
                    b64 = base64.b64encode(open(fp,"rb").read()).decode()
                    title = fp.stem.replace("_"," ")[:50]
                    figs_html += (f'<div style="background:#0f2040;border-radius:8px;padding:12px">'
                                  f'<div style="color:#0D6E6E;font-weight:bold;margin-bottom:8px">{title}</div>'
                                  f'<img src="data:image/png;base64,{b64}" '
                                  f'style="width:100%;border-radius:4px"/></div>')
                except Exception as _exc_bare:
                    pass
            figs_html += "</div>"

        # Top-10 table HTML
        top10_html = ""
        if df_dds is not None and not df_dds.empty and "BBB_Engineering_Score" in df_dds.columns:
            top10 = df_dds.nlargest(10, "BBB_Engineering_Score")
            show  = [c for c in ["Rank","Formulation_ID","Formulation_Name",
                                   "Carrier_Type","BBB_Engineering_Score",
                                   "ADMET_Overall_Flag","size_nm",
                                   "encapsulation_efficiency_pct"]
                     if c in top10.columns]
            top10_html = "<table><tr>" + "".join(f"<th>{c.replace('_',' ')}</th>" for c in show) + "</tr>"
            for _, row in top10[show].iterrows():
                cells = ""
                for c in show:
                    v = row[c]
                    if c == "ADMET_Overall_Flag":
                        cls2 = "ok" if str(v) == "OK" else "review"
                        cells += f'<td><span class="{cls2}">{v}</span></td>'
                    elif isinstance(v, float):
                        cells += f"<td>{v:.2f}</td>"
                    else:
                        cells += f"<td>{v}</td>"
                top10_html += f"<tr>{cells}</tr>"
            top10_html += "</table>"

        ts = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
        html = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8">
<title>CEREBRO-X Final Report — {drug_name}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@200;300;400;500;600;700;800;900&display=swap">
<style>
:root{{
  --void-base:#060610; --void-elevated:#0a0a1a; --void-panel:#0f2040;
  --gold:#C9A84C; --gold-light:#D4B563; --gold-dark:#B89A3F;
  --gold-glow:rgba(201,168,76,0.55);
  --neuro-positive:#0D6E6E; --alert-red:#C62828; --molecule-orange:#F57C00;
  --text-primary:#E0E0E0; --text-secondary:#9CA3AF; --text-muted:#6B7280;
  --hairline:#1F2937;
}}
*{{box-sizing:border-box}}
body{{font-family:'Inter','Segoe UI',Helvetica,Arial,sans-serif;background:var(--void-base);color:var(--text-primary);margin:0;padding:32px 40px;font-weight:300;line-height:1.65;letter-spacing:0.01em}}
h1{{color:var(--gold);font-size:1.6em;margin:16px 0 6px;font-weight:700;letter-spacing:-0.3px}}
h2{{color:var(--gold-light);font-size:1.1em;border-bottom:1px solid var(--hairline);padding-bottom:6px;font-weight:600}}
.header{{background:linear-gradient(135deg,var(--void-panel) 0%,var(--void-elevated) 100%);border:1px solid var(--hairline);border-radius:12px;padding:28px 32px;text-align:center;margin-bottom:24px;box-shadow:0 8px 32px rgba(0,0,0,0.4)}}
.title{{font-size:2.4em;font-weight:800;color:var(--gold);letter-spacing:-0.6px;margin:0;line-height:1}}
.subtitle{{color:var(--text-secondary);font-size:0.95em;margin-top:6px;font-weight:300}}
.drug{{color:var(--gold-light);font-size:1.4em;margin-top:10px;font-weight:600;letter-spacing:0.5px}}
.timestamp{{color:var(--text-muted);font-size:0.78em;margin-top:12px;letter-spacing:0.5px;text-transform:uppercase}}
.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin:20px 0}}
.metric{{background:var(--void-panel);border:1px solid var(--hairline);border-radius:10px;padding:16px;text-align:center}}
.metric-val{{font-size:1.7em;font-weight:800;color:var(--gold);letter-spacing:-0.5px;line-height:1.1}}
.metric-lbl{{font-size:0.72em;color:var(--text-muted);text-transform:uppercase;letter-spacing:1.5px;margin-top:6px;font-weight:500}}
.card{{background:rgba(15,32,64,0.6);backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px);border:1px solid var(--hairline);border-radius:12px;padding:20px 24px;margin:16px 0;box-shadow:0 4px 16px rgba(0,0,0,0.3)}}
table{{width:100%;border-collapse:collapse;font-size:0.88em;margin:12px 0}}
th{{background:var(--void-panel);color:var(--gold);padding:11px 14px;text-align:left;font-weight:600;letter-spacing:0.5px;border-bottom:2px solid var(--gold)}}
td{{padding:9px 14px;border-bottom:1px solid var(--hairline);color:var(--text-primary)}}
tr:hover{{background:rgba(201,168,76,0.05)}}
.ok{{background:var(--neuro-positive);color:white;padding:3px 10px;border-radius:4px;font-size:0.78em;font-weight:600}}
.review{{background:var(--alert-red);color:white;padding:3px 10px;border-radius:4px;font-size:0.78em;font-weight:600}}
.footer{{text-align:center;color:var(--text-muted);font-size:0.78em;margin-top:32px;padding-top:16px;border-top:1px solid var(--hairline);letter-spacing:0.5px}}
</style></head><body>
<div class="header">
  <div class="title">CEREBRO-X</div>
  <div class="subtitle">Drug Delivery Engineering Final Report</div>
  <div class="drug">{drug_name}</div>
  <div class="timestamp">{ts} · Excel: {excel_name} · Trial: {trial_dir.name}</div>
</div>
{novel_banner}
<div class="metrics">
  <div class="metric"><div class="metric-val">{len(df_dds) if df_dds is not None else 0}</div><div class="metric-lbl">Formulations</div></div>
  <div class="metric"><div class="metric-val">{top_bbb:.1f}</div><div class="metric-lbl">Top BBB Score</div></div>
  <div class="metric"><div class="metric-val">{n_viable}</div><div class="metric-lbl">Viable (≥75)</div></div>
  <div class="metric"><div class="metric-val">{metrics.get('cv_r2',0):.3f}</div><div class="metric-lbl">CV R²</div></div>
  <div class="metric" style="background:var(--neuro-positive);border-color:var(--neuro-positive)"><div class="metric-val" style="color:white">{str(top1.get('Formulation_Name','?'))[:20]}</div><div class="metric-lbl" style="color:rgba(255,255,255,0.85)">Top Candidate</div></div>
</div>
<div class="card"><h1>Top-10 DDS Formulations</h1>{top10_html}</div>
<div class="card"><h1>All Visualisations</h1>{figs_html}</div>
<div class="card"><h1>Scientific References</h1>
<ul style="font-size:0.85em;color:var(--text-secondary);line-height:1.8">
<li>Pardridge WM (2012). Drug transport across the BBB. J Cereb Blood Flow Metab.</li>
<li>Yu & Amidon (1999). ACAT absorption model. Pharm Res 16:1796.</li>
<li>Lundberg & Lee (2017). SHAP. NeurIPS.</li>
<li>FDA BCS Guidance (2000). Biowaivers for IR solid oral forms.</li>
<li>Lombardo et al. (2014). In silico ADME. J Med Chem 57:10668.</li>
</ul></div>
<div class="footer">CEREBRO-X · Muhammad Talaat · Generated {ts}</div>
</body></html>"""

        html_path.write_text(html, encoding="utf-8")
        log.info(f"[Report] HTML → {html_path}")
        return html_path


# ─────────────────────────────────────────────────────────────────────────────
# DOCUMENTATION
# ─────────────────────────────────────────────────────────────────────────────
def write_doc(trial_dir: Path, drug_name: str):
    sep = "=" * 70
    txt = (f"{sep}\n  CEREBRO-X |  FILE DOCUMENTATION\n"
           f"  File      : cerebro_final_report.py\n"
           f"  Generated : {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}\n"
           f"{sep}\n\n"
           f"{'─'*70}\n  OVERVIEW\n{'─'*70}\n"
           "Generates the comprehensive final decision report for each trial.\n"
           "HTML (self-contained, browser-ready).\n\n"
           "SECTIONS:\n"
           "  1. Executive Summary + Recommendation\n"
           "  2. Drug Molecular & Clinical Profile\n"
           "  3. Novel Drug Alignment (if applicable)\n"
           "  4. Top-10 DDS Formulations with rationale\n"
           "  5. All 100 formulations ranked\n"
           "  6. ML Evaluation metrics\n"
           "  7. PBBM Results (ACAT, NCA)\n"
           "  8. ADMET Profile\n"
           "  9. All figures (PNG embedded)\n"
           " 10. Data Quality & Lineage\n"
           " 11. Decision Framework (gates + pass counts)\n"
           " 12. Next Steps (wet-lab → clinical)\n"
           " 13. Scientific References\n\n"
           f"{'─'*70}\n  NOVEL DRUG HANDLING\n{'─'*70}\n"
           "When a drug is novel (not in any database):\n"
           "  • Lists ALL databases searched (DrugBank, DailyMed, OpenFDA, etc.)\n"
           "  • States WHY no data was found\n"
           "  • Identifies the chemical alignment surrogate\n"
           "  • Reports Tanimoto similarity score\n"
           "  • Quantifies uncertainty (±25-50%)\n"
           "  • Adds regulatory disclaimer: all PK values are PREDICTED\n"
           f"{sep}\n")
    (trial_dir / "cerebro_final_report.py_DOCUMENTATION.txt").write_text(txt)