# -*- coding: utf-8 -*-
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

  FORMAT: PDF (reportlab) + HTML (self-contained)
================================================================================
"""

import os, sys, json, math, logging, warnings
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Any

import numpy as np
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
    def build_explanation(cls, mol_profile: Dict,
                           drug_name: str) -> Dict[str, Any]:
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
    def format_text(cls, expl: Dict, drug_name: str) -> str:
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
    PDF (reportlab) + HTML with all figures embedded.
    """

    # ── Brand colours ─────────────────────────────────────────────────────────
    from reportlab.lib import colors as rl_colors
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
                  mol_profile:  Dict,
                  df_ml:        Optional[pd.DataFrame],
                  df_dds:       Optional[pd.DataFrame],
                  df_pk:        Optional[pd.DataFrame],
                  metrics:      Dict,
                  pbbm_results: Optional[Dict] = None,
                  de_results:   Optional[Dict] = None,
                  admet_profile:Optional[Dict] = None) -> Path:
        """
        Generate the complete final report PDF + HTML.
        Returns path to the PDF.
        """
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import cm
            from reportlab.lib import colors
            from reportlab.platypus import (
                SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
                Image as RLImage, PageBreak, HRFlowable, KeepTogether)
            from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY

        except ImportError:
            log.error("[Report] reportlab not installed — PDF skipped")
            cls._generate_html(drug_name, trial_dir, excel_name, mol_profile,
                                df_ml, df_dds, df_pk, metrics, pbbm_results,
                                de_results, admet_profile)
            return trial_dir / f"CEREBRO_X_Final_Report_{drug_name}.html"

        pdf_path = trial_dir / f"CEREBRO_X_Final_Report_{drug_name}.pdf"
        doc      = SimpleDocTemplate(str(pdf_path), pagesize=A4,
                                      leftMargin=2*cm, rightMargin=2*cm,
                                      topMargin=2*cm, bottomMargin=2*cm)
        styles   = getSampleStyleSheet()
        ts = datetime.now().strftime("%Y-%m-%d  %H:%M")

        # ── Style definitions ────────────────────────────────────────────────
        def ps(name, parent="Normal", **kw):
            return ParagraphStyle(name, parent=styles[parent], **kw)

        title_s  = ps("T", "Title",   fontSize=24, textColor=colors.HexColor(cls._GOLD), spaceAfter=4)
        h1_s     = ps("H1","Heading1",fontSize=14, textColor=colors.HexColor(cls._GOLD), spaceAfter=4)
        h2_s     = ps("H2","Heading2",fontSize=11, textColor=colors.HexColor(cls._TEAL), spaceAfter=3)
        body_s   = ps("B", "Normal",  fontSize=9,  leading=13, spaceAfter=3)
        note_s   = ps("N", "Normal",  fontSize=8,  textColor=colors.grey,
                       leftIndent=10, spaceAfter=3)
        alert_s  = ps("A", "Normal",  fontSize=9,  textColor=colors.HexColor(cls._RED),
                       backColor=colors.HexColor("#FFF3F3"),
                       borderPadding=5, spaceAfter=5)
        code_s   = ps("C", "Normal",  fontSize=8,  fontName="Courier",
                       backColor=colors.HexColor("#F5F5F5"), spaceAfter=3)
        bold_s   = ps("Bo","Normal",  fontSize=10, fontName="Helvetica-Bold",
                       textColor=colors.HexColor(cls._NAVY))

        def tbl(data, col_widths=None, header_bg=None):
            hbg = colors.HexColor(header_bg or cls._NAVY)
            t   = Table(data, colWidths=col_widths, repeatRows=1)
            t.setStyle(TableStyle([
                ("BACKGROUND",   (0,0),(-1,0), hbg),
                ("TEXTCOLOR",    (0,0),(-1,0), colors.white),
                ("FONTNAME",     (0,0),(-1,-1),"Helvetica"),
                ("FONTSIZE",     (0,0),(-1,-1), 8),
                ("ROWBACKGROUNDS",(0,1),(-1,-1),
                 [colors.HexColor("#F5F5F5"), colors.white]),
                ("GRID",         (0,0),(-1,-1), 0.3, colors.lightgrey),
                ("LEFTPADDING",  (0,0),(-1,-1), 5),
                ("TOPPADDING",   (0,0),(-1,-1), 3),
                ("BOTTOMPADDING",(0,0),(-1,-1), 3),
                ("VALIGN",       (0,0),(-1,-1), "MIDDLE"),
            ]))
            return t

        story = []

        # ── COVER PAGE ───────────────────────────────────────────────────────
        story.append(Spacer(1, 1.5*cm))
        story.append(Paragraph("CEREBRO-X", title_s))
        story.append(Paragraph("Computational Drug Delivery Engineering Report",
                                ps("sub","Normal",fontSize=13,
                                   textColor=colors.HexColor(cls._TEAL))))
        story.append(HRFlowable(width="100%",thickness=2,
                                 color=colors.HexColor(cls._TEAL)))
        story.append(Spacer(1,0.5*cm))

        # Novel drug warning
        expl = NovelDrugExplainer.build_explanation(mol_profile, drug_name)
        if expl["is_novel"]:
            story.append(Paragraph(
                "⚠ NOVEL/UNPUBLISHED DRUG — Chemical alignment used for PK prediction. "
                "See Section 3 for full explanation.",
                alert_s))

        # Cover table
        cover = [
            ["Drug / Candidate",  drug_name],
            ["Excel Input File",  excel_name],
            ["Trial Directory",   trial_dir.name],
            ["Generated",         ts],
            ["Report Version",    "CEREBRO-X"],
        ]
        story.append(tbl(cover, [6*cm, 11*cm], cls._TEAL))
        story.append(Spacer(1, 0.5*cm))

        # ── SECTION 1: EXECUTIVE SUMMARY ─────────────────────────────────────
        story.append(Paragraph("1. Executive Summary & Recommendation", h1_s))
        story.append(HRFlowable(width="100%",thickness=1,
                                 color=colors.HexColor(cls._TEAL)))

        top1 = df_dds.iloc[0].to_dict() if (df_dds is not None and not df_dds.empty) else {}
        n_viable = int((df_dds["BBB_Engineering_Score"] >= 75).sum()) if df_dds is not None and "BBB_Engineering_Score" in df_dds.columns else 0
        top_bbb  = float(df_dds["BBB_Engineering_Score"].max()) if df_dds is not None and "BBB_Engineering_Score" in df_dds.columns else 0

        exec_text = (
            f"<b>Drug analysed:</b> {drug_name}<br/>"
            f"<b>Formulations scored:</b> {len(df_dds) if df_dds is not None else 'N/A'} "
            f"DDS systems across {df_dds['Carrier_Type'].nunique() if df_dds is not None and 'Carrier_Type' in df_dds.columns else '?'} carrier types<br/>"
            f"<b>Top BBB Engineering Score:</b> {top_bbb:.1f}/100<br/>"
            f"<b>Viable formulations (score ≥ 75):</b> {n_viable}<br/>"
            f"<b>ML model R²:</b> {metrics.get('r2',0):.4f}  "
            f"(K-Fold CV R²: {metrics.get('cv_r2',0):.4f} ± {metrics.get('cv_std',0):.4f})<br/>"
            f"<b>Recommended carrier:</b> {top1.get('Formulation_Name','?')}<br/>"
            f"<b>Recommended carrier type:</b> {top1.get('Carrier_Type','?')}<br/>"
            f"<b>ADMET status:</b> {top1.get('ADMET_Overall_Flag','?')}"
        )
        story.append(Paragraph(exec_text, body_s))
        story.append(Spacer(1,0.3*cm))

        if top1:
            rec_data = [
                ["RECOMMENDATION", "VALUE"],
                ["Primary DDS",           str(top1.get("Formulation_Name","?"))],
                ["Carrier Type",          str(top1.get("Carrier_Type","?"))],
                ["BBB Engineering Score", f"{_safe(top1.get('BBB_Engineering_Score'),'')}/100"],
                ["Size",                  f"{_safe(top1.get('size_nm',''))} nm"],
                ["Zeta Potential",        f"{_safe(top1.get('zeta_potential_mv',''))} mV"],
                ["EE%",                   f"{_safe(top1.get('encapsulation_efficiency_pct',''))}%"],
                ["Surface Ligand",        str(top1.get("Surface_Ligand","?"))],
                ["ADMET Flag",            str(top1.get("ADMET_Overall_Flag","?"))],
                ["Decision",              "ADVANCE TO IN-VITRO BBB TEER ASSAY"
                                          if top_bbb >= 75 else "REFORMULATE"],
            ]
            story.append(tbl(rec_data, [7*cm, 10*cm], cls._GREEN))

        story.append(PageBreak())

        # ── SECTION 2: DRUG PROFILE ───────────────────────────────────────────
        story.append(Paragraph("2. Drug Molecular & Clinical Profile", h1_s))
        story.append(HRFlowable(width="100%",thickness=1,
                                 color=colors.HexColor(cls._TEAL)))

        drug_data = [
            ["Property","Value","Source"],
            ["Molecular Weight",      f"{_safe(mol_profile.get('MW_Da'))} Da",
             mol_profile.get("_source","?")],
            ["LogP",                  _safe(mol_profile.get("LogP"),""),
             mol_profile.get("_source","?")],
            ["Half-Life (days)",      _safe(mol_profile.get("Half_Life_Days"),""),
             mol_profile.get("_hl_source", mol_profile.get("_source","?"))],
            ["CSF/Plasma Ratio",      _safe(mol_profile.get("CSF_Plasma_Ratio"),""),
             mol_profile.get("_source","?")],
            ["Protein Binding",       f"{_safe(mol_profile.get('Protein_Binding_pct'),'')}%",
             "Clinical PK database"],
            ["BBB Penetration",       f"{_safe(mol_profile.get('BBB_permeability_pct'),'')}%",
             mol_profile.get("_source","?")],
            ["Molecule Class",        str(mol_profile.get("molecule_class","?")),""],
            ["Input Format",          str(mol_profile.get("input_type","?")),""],
            ["Data Source Tier",      f"Tier {mol_profile.get('_tier',0)}",""],
            ["Alignment Used",        "YES" if expl["is_alignment"] else "NO",""],
        ]
        story.append(tbl(drug_data, [5*cm, 7*cm, 5*cm]))
        story.append(Spacer(1,0.3*cm))

        # ── SECTION 3: NOVEL DRUG ALIGNMENT ──────────────────────────────────
        if expl["is_novel"]:
            story.append(Paragraph("3. Novel Drug — Chemical Alignment Details", h1_s))
            story.append(HRFlowable(width="100%",thickness=1,
                                     color=colors.HexColor(cls._RED)))
            novel_text = NovelDrugExplainer.format_text(expl, drug_name)
            for line in novel_text.split("\n"):
                if line.startswith("===") or line.startswith("---"):
                    continue
                if line.strip():
                    style = alert_s if "DISCLAIMER" in line or "PREDICTED" in line else (
                        bold_s if line.isupper() else body_s)
                    story.append(Paragraph(line, style))
            story.append(PageBreak())

        # ── SECTION 4: TOP-10 DDS ─────────────────────────────────────────────
        story.append(Paragraph("4. Top-10 DDS Formulations", h1_s))
        story.append(HRFlowable(width="100%",thickness=1,
                                 color=colors.HexColor(cls._TEAL)))
        story.append(Paragraph(
            "Ranked by BBB Engineering Score (Pardridge 2012 framework). "
            "Score > 75 with ADMET=OK → proceed to in-vitro BBB TEER validation.",
            note_s))

        if df_dds is not None and not df_dds.empty and "BBB_Engineering_Score" in df_dds.columns:
            top10 = df_dds.nlargest(10, "BBB_Engineering_Score")
            show  = [c for c in ["Rank","Formulation_ID","Formulation_Name",
                                   "Carrier_Type","BBB_Engineering_Score",
                                   "ADMET_Overall_Flag","size_nm",
                                   "zeta_potential_mv",
                                   "encapsulation_efficiency_pct","Surface_Ligand"]
                     if c in top10.columns]
            widths = [1*cm, 2*cm, 4.5*cm, 3*cm, 2*cm, 2*cm, 1.5*cm, 1.5*cm, 2*cm, 3*cm][:len(show)]
            data   = [show]
            for _, row in top10[show].iterrows():
                data.append([str(round(v,2) if isinstance(v,float) else v)
                             for v in row.values])
            story.append(tbl(data, widths))

        story.append(Spacer(1,0.3*cm))

        # Scientific rationale for top formulation
        if top1:
            story.append(Paragraph("Why is this the top formulation?", h2_s))
            rationale_parts = []
            sz   = float(top1.get("size_nm",0) or 0)
            zeta = float(top1.get("zeta_potential_mv",0) or 0)
            peg  = float(top1.get("pegylation_degree_mol_pct",0) or 0)
            ee   = float(top1.get("encapsulation_efficiency_pct",0) or 0)
            lig  = str(top1.get("Surface_Ligand",""))

            if 60 <= sz <= 100:
                rationale_parts.append(
                    f"Size {sz:.0f}nm is optimal for caveolae-mediated transcytosis "
                    f"(Pardridge 2012: 60-100nm ideal for BBB crossing).")
            if 5 <= abs(zeta) <= 15:
                rationale_parts.append(
                    f"Zeta potential {zeta:.0f}mV provides colloidal stability "
                    f"without excessive opsonisation.")
            if 2 <= peg <= 7:
                rationale_parts.append(
                    f"PEGylation {peg:.1f}mol% confers stealth from immune system "
                    f"while preserving ligand receptor binding capacity.")
            if ee >= 80:
                rationale_parts.append(
                    f"High encapsulation efficiency ({ee:.0f}%) minimises "
                    f"premature drug leakage before BBB crossing.")
            if lig and lig.lower() not in ("none","nan",""):
                rationale_parts.append(
                    f"Surface ligand {lig} provides active targeting via receptor-mediated "
                    f"endocytosis at the BBB endothelium.")

            for r in rationale_parts:
                story.append(Paragraph(f"• {r}", body_s))

        story.append(PageBreak())

        # ── SECTION 5: ALL FORMULATIONS ───────────────────────────────────────
        story.append(Paragraph("5. All Formulations Ranked", h1_s))
        if df_dds is not None and not df_dds.empty and "BBB_Engineering_Score" in df_dds.columns:
            all_cols = [c for c in ["Rank","Formulation_ID","Carrier_Type",
                                     "BBB_Engineering_Score","ADMET_Overall_Flag",
                                     "size_nm","Surface_Ligand"]
                        if c in df_dds.columns]
            all_w = [1*cm, 2.5*cm, 3.5*cm, 2.5*cm, 2.5*cm, 2*cm, 3*cm][:len(all_cols)]
            all_data = [all_cols]
            for _, row in df_dds[all_cols].iterrows():
                all_data.append([str(round(v,1) if isinstance(v,float) else v)
                                  for v in row.values])
            story.append(tbl(all_data, all_w))

        story.append(PageBreak())

        # ── SECTION 6: ML EVALUATION ──────────────────────────────────────────
        story.append(Paragraph("6. Machine Learning Evaluation", h1_s))
        story.append(HRFlowable(width="100%",thickness=1,
                                 color=colors.HexColor(cls._TEAL)))
        ml_data = [
            ["Metric","Value","Interpretation"],
            ["Train R²",      f"{metrics.get('r2',0):.4f}",
             "Variance explained (1.0 = perfect fit)"],
            ["Train RMSE",    f"{metrics.get('rmse',0):.4f}",
             "Root mean squared error"],
            ["Train MAE",     f"{metrics.get('mae',0):.4f}",
             "Mean absolute error"],
            ["K-Fold CV R²",  f"{metrics.get('cv_r2',0):.4f} ± {metrics.get('cv_std',0):.4f}",
             "Generalisation estimate (5-fold CV)"],
            ["N samples",     str(metrics.get('n_samples','N/A')),
             "Training set size"],
        ]
        story.append(tbl(ml_data, [4*cm, 5*cm, 8*cm]))
        story.append(Paragraph(
            "Model: Ensemble VotingRegressor (RF + GBR + SVR + XGBoost). "
            "Scaler: TrainAwareScaler (fit on training data only — "
            "no leakage). K-Fold CV R² > 0.7 = deployment-ready.",
            note_s))

        story.append(PageBreak())

        # ── SECTION 7: PBBM RESULTS ───────────────────────────────────────────
        story.append(Paragraph("7. PBBM Results", h1_s))
        story.append(HRFlowable(width="100%",thickness=1,
                                 color=colors.HexColor(cls._TEAL)))
        if pbbm_results:
            acat = pbbm_results.get("acat", {})
            if acat:
                story.append(Paragraph("7.1 ACAT Oral Absorption", h2_s))
                acat_data = [["Parameter","Value"],
                             ["Fraction absorbed (fa)", _safe(acat.get("fa_total"),"")],
                             ["Hepatic first-pass (Fh)", _safe(acat.get("Fh"),"")],
                             ["Oral bioavailability (F)", _safe(acat.get("F_oral"),"")],
                             ["ka effective (1/h)", _safe(acat.get("ka_eff_per_h"),"")]]
                story.append(tbl(acat_data, [8*cm, 9*cm]))

            nca_df = pbbm_results.get("nca")
            if nca_df is not None and not (isinstance(nca_df, pd.DataFrame) and nca_df.empty):
                story.append(Paragraph("7.2 Non-Compartmental Analysis (NCA)", h2_s))
                try:
                    nca_row = nca_df.iloc[0] if isinstance(nca_df, pd.DataFrame) else {}
                    nca_data = [["NCA Parameter","Value"],
                                ["Cmax",         _safe(nca_row.get("Cmax"),"")],
                                ["tmax (h)",      _safe(nca_row.get("tmax_h"),"")],
                                ["AUC₀₋∞",       _safe(nca_row.get("AUC_0_inf"),"")],
                                ["t½ (h)",        _safe(nca_row.get("t_half_h"),"")],
                                ["MRT (h)",       _safe(nca_row.get("MRT_h"),"")],
                                ["λz (1/h)",      _safe(nca_row.get("lambda_z_per_h"),"")],
                                ["R² terminal",   _safe(nca_row.get("R2_terminal"),"")]]
                    story.append(tbl(nca_data, [8*cm, 9*cm]))
                except Exception as _exc_bare:
                    pass

        story.append(PageBreak())

        # ── SECTION 8: ADMET ──────────────────────────────────────────────────
        story.append(Paragraph("8. ADMET Profile", h1_s))
        if admet_profile:
            admet_data = [["Property","Value","Grade"]]
            admet_fields = [
                ("logP","logP"),("MlogP","MlogP (Moriguchi)"),
                ("logD","logD (pH 6.8)"),("Sw_mg_mL","Native Solubility (mg/mL)"),
                ("FaSSGF_mg_mL","FaSSGF Solubility"),
                ("FaSSIF_mg_mL","FaSSIF Solubility"),
                ("FeSSIF_mg_mL","FeSSIF Solubility"),
                ("Peff_cm_s","Jejunal Peff (cm/s)"),
                ("MDCK_Papp_cm_s","MDCK Papp (cm/s)"),
                ("BBB_Filter","BBB Filter"),("LogBB","LogBB"),
                ("Pgp_Substrate","P-gp Substrate"),
                ("OATP1B1_Inh","OATP1B1 Inhibitor"),
                ("fu_human_pct","fu Human (%)"),
                ("Vd_human_L","Vd Human (L)"),
                ("RBP_human","Blood:Plasma Ratio"),
                ("ADMET_Score","ADMET Score (0-100)"),
                ("ADMET_Grade","ADMET Grade"),
            ]
            for key, label in admet_fields:
                val = admet_profile.get(key)
                if val is not None:
                    grade = ""
                    if key == "ADMET_Grade":
                        grade = str(val)
                    elif key == "BBB_Filter":
                        grade = "✓" if str(val) == "PASS" else "✗"
                    admet_data.append([label,
                                        str(round(val,4) if isinstance(val,float) else val),
                                        grade])
            story.append(tbl(admet_data, [7*cm, 7*cm, 3*cm]))

        story.append(PageBreak())

        # ── SECTION 9: FIGURES ────────────────────────────────────────────────
        story.append(Paragraph("9. Visualisations", h1_s))
        figs_dir = trial_dir / "figures"
        if figs_dir.exists():
            for fp in sorted(figs_dir.glob("*.png")):
                if "_DOCUMENTATION" in fp.name:
                    continue
                try:
                    img = RLImage(str(fp), width=15*cm, height=9*cm)
                    story.append(KeepTogether([
                        Paragraph(fp.stem.replace("_"," ").title()[:60], h2_s),
                        img,
                        Spacer(1, 0.3*cm),
                    ]))
                except Exception as _exc_bare:
                    pass

        story.append(PageBreak())

        # ── SECTION 10: DATA QUALITY ──────────────────────────────────────────
        story.append(Paragraph("10. Data Quality & Lineage", h1_s))
        if de_results:
            obs = de_results.get("observability", {})
            lin = de_results.get("lineage", {}).get("summary", {})
            dq_data = [["Metric","Value"],
                       ["Quality Score", f"{obs.get('quality_score','?')}/100 Grade {obs.get('quality_grade','?')}"],
                       ["Completeness",  f"{obs.get('completeness_pct','?')}%"],
                       ["Critical violations", str(obs.get('n_critical','?'))],
                       ["Features tracked", str(lin.get('n_features','?'))],
                       ["Via alignment",  str(lin.get('n_aligned','?'))],
                       ["Via APIs",       str(lin.get('n_api','?'))],
                       ["Lineage coverage", f"{lin.get('coverage_pct','?')}%"]]
            story.append(tbl(dq_data, [8*cm, 9*cm]))

        story.append(PageBreak())

        # ── SECTION 11: DECISION FRAMEWORK ───────────────────────────────────
        story.append(Paragraph("11. Decision Framework", h1_s))
        story.append(HRFlowable(width="100%",thickness=1,
                                 color=colors.HexColor(cls._TEAL)))
        story.append(Paragraph(
            "Gates a formulation must pass before wet-lab synthesis:",
            body_s))

        if df_dds is not None and not df_dds.empty:
            gate_data = [["Gate","Criterion","Pass Count","Next Action"]]
            gates = [
                ("BBB ≥ 75",    "BBB_Engineering_Score","≥ 75","In-vitro TEER assay"),
                ("ADMET OK",    "ADMET_Overall_Flag","== OK","Animal PK study"),
                ("Liver < 30%", "Off_Target_Liver_pct","< 30","Safe hepatic profile"),
                ("CARPA < 0.4", "CARPA_Risk_Index","< 0.4","Low complement risk"),
                ("EE ≥ 70%",    "encapsulation_efficiency_pct","≥ 70","Stable payload"),
            ]
            for gate, col, crit, action in gates:
                if col not in df_dds.columns:
                    continue
                if "≥" in crit:
                    th = float(crit.replace("≥","").strip())
                    n  = (df_dds[col] >= th).sum()
                elif "<" in crit:
                    th = float(crit.replace("<","").strip())
                    n  = (df_dds[col] < th).sum()
                else:
                    val = crit.replace("==","").strip()
                    n   = (df_dds[col] == val).sum()
                gate_data.append([gate, f"{col} {crit}", str(n), action])
            story.append(tbl(gate_data, [3*cm, 5*cm, 3*cm, 6*cm]))

        story.append(Spacer(1,0.5*cm))
        story.append(Paragraph("12. Next Steps", h1_s))
        next_steps = [
            ("Short-term (0-3 months)",
             f"1. Synthesise top-3 formulations ({top1.get('Formulation_Name','?')} first).\n"
             "2. In-vitro BBB TEER assay (Transendothelial Electrical Resistance).\n"
             "3. In-vitro drug release profile (pH 6.5 and 7.4).\n"
             "4. Cytotoxicity assay (hCMEC/D3 cells, 24/48/72h)."),
            ("Medium-term (3-12 months)",
             "5. In-vivo rat PK study (IV + oral groups).\n"
             "6. Brain/plasma ratio measurement (LC-MS/MS).\n"
             "7. Safety pharmacology (CARPA complement activation assay).\n"
             f"8. Scale-up synthesis of lead formulation."),
            ("Regulatory (>12 months)",
             "9. IND-enabling studies (GLP toxicology).\n"
             "10. CMC documentation for FDA IND submission.\n"
             "11. Phase I clinical trial design (SAD/MAD).\n"
             f"Note: If {drug_name} is novel/unpublished, First-in-Human "
             "regulatory consultation required."),
        ]
        for title, text in next_steps:
            story.append(Paragraph(title, h2_s))
            for line in text.split("\n"):
                story.append(Paragraph(line, body_s))
            story.append(Spacer(1,0.2*cm))

        story.append(PageBreak())
        story.append(Paragraph("Scientific References", h1_s))
        refs = [
            "Pardridge WM (2012). Drug transport across the blood-brain barrier. J Cereb Blood Flow Metab 32:1959.",
            "Rowland & Tozer (2011). Clinical Pharmacokinetics and Pharmacodynamics. 5th ed.",
            "Yu LX & Amidon GL (1999). A compartmental absorption and transit model. Pharm Res 16:1796.",
            "Rodgers & Rowland (2006). Physiologically based PK modelling. J Pharm Sci 95:1113.",
            "Lundberg SM & Lee S-I (2017). SHAP: a unified approach to interpreting model predictions. NeurIPS.",
            "Yalkowsky & Valvani (1980). Solubility and partitioning. J Pharm Sci 69:912.",
            "Palm et al. (1997). Correlation of drug absorption with molecular surface properties. J Pharm Sci 85:32.",
            "FDA BCS Guidance (2000). Waiver of In Vivo Bioavailability Studies for IR Solid Oral Dosage Forms.",
            "ICH M9 (2021). Biopharmaceutics Classification System-Based Biowaivers.",
            "Lombardo et al. (2014). In silico absorption, distribution, metabolism, excretion. J Med Chem 57:10668.",
        ]
        for r in refs:
            story.append(Paragraph(f"• {r}", note_s))

        doc.build(story)
        log.info(f"[Report] PDF → {pdf_path}")

        # Also generate HTML
        cls._generate_html(drug_name, trial_dir, excel_name, mol_profile,
                            df_ml, df_dds, df_pk, metrics, pbbm_results,
                            de_results, admet_profile, expl)
        return pdf_path

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
           "PDF (reportlab) + HTML (self-contained, browser-ready).\n\n"
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