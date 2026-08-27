"""
================================================================================
CEREBRO-X |  UNIFIED PDF REPORT ENGINE
================================================================================
Created by: Muhammad Talaat -- CEREBRO-X

Generates ONE comprehensive PDF report containing ALL 62 module outputs.
Structure:
  Cover + Executive Summary
  Section 1:  Drug Molecular Profile (auto-fetched data, no assumptions)
  Section 2:  Drug Delivery Problems Identified (auto-detected)
  Section 3:  DDS Ranking & Selection (Composite Score methodology)
  Section 4:  PBPK-CNS Digital Twin (6-compartment ODE results)
  Section 5:  Drug Release Kinetics
  Section 6:  Colloidal Stability (DLVO + Protein Corona)
  Section 7:  Nanotoxicity & Immunogenicity
  Section 8:  Off-Target QSAR (50-receptor panel)
  Section 9:  Shelf-Life & Degradation (Arrhenius)
  Section 10: Advanced Modules (Competitive Landscape, Quantum, Patient Strat.)
  Section 11: Synthetic Clinical Trial (N=500)
  Section 12: Regulatory Compliance (FDA 21 CFR Part 11)
  Section 13: Supply Chain Risk
  Section 14: Literature Citations (PubMed live)
  Section 15: All Figures Summary
================================================================================
"""

from __future__ import annotations

import datetime
import logging
from pathlib import Path

import pandas as pd

log = logging.getLogger("CEREBRO-PDF")

# ─────────────────────────────────────────────────────────────────────────────
# COLOUR CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────
NAVY   = (0.11, 0.23, 0.42)   # #0f2040
TEAL   = (0.05, 0.43, 0.43)   # #0D6E6E
GOLD   = (0.79, 0.66, 0.30)   # #C9A84C
RED_C  = (0.91, 0.30, 0.24)   # #C62828
GREEN  = (0.15, 0.68, 0.38)   # #0D6E6E
ORANGE = (0.91, 0.47, 0.14)   # #F57C00
GREY   = (0.94, 0.94, 0.94)
WHITE  = (1, 1, 1)
BLACK  = (0, 0, 0)


def _rl_color(t): 
    from reportlab.lib import colors
    return colors.Color(*t)


def _safe(v, fmt=".2f", default="N/A") -> str:
    try: return format(float(v), fmt) if v is not None else default
    except: return str(v) if v else default


def _sev_color(sev: str):
    from reportlab.lib import colors
    return {"CRITICAL": colors.Color(*RED_C),
            "HIGH":     colors.Color(*ORANGE),
            "MODERATE": colors.Color(0.95,0.77,0.06),
            "LOW":      colors.Color(*GREEN)}.get(sev.upper(), colors.grey)


class UnifiedPDFReport:
    """Generates the single unified CEREBRO-X PDF report."""

    @classmethod
    def generate(cls,
                  drug_name:       str,
                  trial_dir:       Path,
                  mol_profile:     dict,
                  df_dds:          pd.DataFrame | None,
                  top_dds:         dict,
                  science_results: dict,
                  df_ml:           pd.DataFrame | None = None,
                  df_pk:           pd.DataFrame | None = None,
                  pbbm_results:    dict | None = None,
                  # v22 — C+ Flow data
                  dds_principle_breakdown: list | None = None,
                  dds_principle_matrix: list | None = None,
                  deep_results:    dict | None = None,
                  deep_summary:    dict | None = None,
                  translational:   dict | None = None,
                  fallback_chain:  list | None = None) -> Path | None:
        """
        Build and save the unified PDF report.
        All sections driven by actual computed data. No placeholders.
        """
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
            from reportlab.lib.units import cm
            from reportlab.platypus import (
                HRFlowable,
                KeepTogether,
                PageBreak,
                Paragraph,
                SimpleDocTemplate,
                Spacer,
                Table,
                TableStyle,
            )
        except ImportError:
            log.warning("[PDF] reportlab not installed")
            return None

        W, H = A4
        out_path = trial_dir / f"CEREBRO_X_Final_Report_{drug_name}.pdf"

        doc = SimpleDocTemplate(str(out_path), pagesize=A4,
                                 topMargin=1.8*cm, bottomMargin=1.8*cm,
                                 leftMargin=1.8*cm, rightMargin=1.8*cm)

        # ── Styles ────────────────────────────────────────────────────────────
        base = getSampleStyleSheet()
        def S(name, **kw):
            return ParagraphStyle(name, parent=base["Normal"], **kw)

        NAVY_RL  = _rl_color(NAVY)
        TEAL_RL  = _rl_color(TEAL)
        GOLD_RL  = _rl_color(GOLD)
        GREEN_RL = _rl_color(GREEN)
        RED_RL   = _rl_color(RED_C)
        ORANGE_RL= _rl_color(ORANGE)

        h1 = S("H1",  fontSize=14, fontName="Helvetica-Bold",
                textColor=GOLD_RL,  spaceAfter=6,  spaceBefore=14)
        h2 = S("H2",  fontSize=11, fontName="Helvetica-Bold",
                textColor=TEAL_RL,  spaceAfter=4,  spaceBefore=8)
        h3 = S("H3",  fontSize=10, fontName="Helvetica-Bold",
                textColor=_rl_color(NAVY), spaceAfter=3, spaceBefore=5)
        body = S("B",  fontSize=9,  fontName="Helvetica",
                 textColor=colors.HexColor("#2A2A2A"), spaceAfter=3, leading=14)
        mono = S("M",  fontSize=8,  fontName="Courier",
                 textColor=colors.HexColor("#1A1A1A"), spaceAfter=2, leading=12)
        note = S("N",  fontSize=7.5, fontName="Helvetica-Oblique",
                 textColor=colors.grey, spaceAfter=2)
        warn = S("W",  fontSize=8.5, fontName="Helvetica-Bold",
                 textColor=RED_RL, spaceAfter=3)

        # ── Helper: table factory ─────────────────────────────────────────────
        def tbl(data, col_widths, hdr_bg=None):
            t = Table(data, colWidths=col_widths, repeatRows=1)
            bg = hdr_bg or NAVY
            style = TableStyle([
                ("BACKGROUND",   (0,0), (-1,0), _rl_color(bg)),
                ("TEXTCOLOR",    (0,0), (-1,0), colors.white),
                ("FONTNAME",     (0,0), (-1,0), "Helvetica-Bold"),
                ("FONTSIZE",     (0,0), (-1,0), 8.5),
                ("FONTNAME",     (0,1), (-1,-1), "Helvetica"),
                ("FONTSIZE",     (0,1), (-1,-1), 8),
                ("ROWBACKGROUNDS",(0,1),(-1,-1), [colors.white, colors.Color(.96,.97,.99)]),
                ("TEXTCOLOR",    (0,1), (-1,-1), colors.HexColor("#222222")),
                ("GRID",         (0,0), (-1,-1), 0.4, colors.HexColor("#DDDDDD")),
                ("ALIGN",        (0,0), (-1,-1), "LEFT"),
                ("VALIGN",       (0,0), (-1,-1), "MIDDLE"),
                ("LEFTPADDING",  (0,0), (-1,-1), 5),
                ("RIGHTPADDING", (0,0), (-1,-1), 5),
                ("TOPPADDING",   (0,0), (-1,-1), 4),
                ("BOTTOMPADDING",(0,0), (-1,-1), 4),
            ])
            t.setStyle(style)
            return t

        # ── Helper: metric box row ─────────────────────────────────────────────
        def metric_row(items):
            """Items = list of (label, value, color_tuple)."""
            from reportlab.platypus import Table as RLTable
            from reportlab.platypus import TableStyle as RLTableStyle
            cells = []
            for lbl, val, col in items:
                cells.append(
                    Paragraph(f'<b><font color="#{int(col[0]*255):02x}{int(col[1]*255):02x}{int(col[2]*255):02x}">'
                               f'{val}</font></b><br/><font size="7">{lbl}</font>', body))
            t = RLTable([cells], colWidths=[W / (len(items)+0.1)] * len(items))
            t.setStyle(RLTableStyle([
                ("BOX",    (0,0),(-1,-1), 0.5, _rl_color(TEAL)),
                ("INNERGRID",(0,0),(-1,-1), 0.3, colors.HexColor("#CCCCCC")),
                ("ALIGN",  (0,0),(-1,-1),"CENTER"),
                ("VALIGN", (0,0),(-1,-1),"MIDDLE"),
                ("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#F7F9FC")),
                ("TOPPADDING",(0,0),(-1,-1),6),
                ("BOTTOMPADDING",(0,0),(-1,-1),6),
            ]))
            return t

        story = []

        # ══════════════════════════════════════════════════════════════════════
        # COVER PAGE
        # ══════════════════════════════════════════════════════════════════════
        story.append(Spacer(1, 2*cm))
        cover_style = ParagraphStyle("cover", fontSize=26, fontName="Helvetica-Bold",
                                      textColor=GOLD_RL, alignment=1, spaceAfter=12)
        story.append(Paragraph("CEREBRO-X", cover_style))
        story.append(Paragraph(
            "<font color='#0f2040'>Computational Drug-DDS Engineering Report</font>",
            ParagraphStyle("sub", fontSize=16, fontName="Helvetica", alignment=1,
                            textColor=NAVY_RL, spaceAfter=8)))
        story.append(HRFlowable(width="100%", thickness=2, color=GOLD_RL))
        story.append(Spacer(1, 0.4*cm))

        # Drug + DDS summary box
        carrier = top_dds.get("Carrier_Type", "DDS") if top_dds else "N/A"
        ligand  = top_dds.get("Surface_Ligand", "N/A") if top_dds else "N/A"
        bbb_enh = _safe(top_dds.get("BBB_Enhanced_Pct"), ".1f") if top_dds else "N/A"
        composite = _safe(top_dds.get("Composite_Score") or top_dds.get("BBB_Engineering_Score"), ".1f") if top_dds else "N/A"

        cover_data = [
            ["Field", "Value"],
            ["Drug Name",          drug_name],
            ["Molecular Class",    mol_profile.get("molecule_class","N/A")],
            ["Molecular Weight",   f"{_safe(mol_profile.get('MW_Da'),'.1f')} Da"],
            ["Recommended DDS",    str(top_dds.get("Formulation_Name","N/A")) if top_dds else "N/A"],
            ["Carrier Type",       carrier],
            ["Surface Ligand",     ligand],
            ["BBB Enhancement",    f"{bbb_enh}%"],
            ["Composite Score",    f"{composite}/100"],
            ["Disease Indication", mol_profile.get("indication", "CNS")],
            ["Report Generated",   datetime.datetime.now().strftime("%Y-%m-%d %H:%M UTC")],
            ["Created by",         "Muhammad Talaat | CEREBRO-X"],
            ["Modules Completed",  f"{len(science_results)}/62 science modules"],
        ]
        story.append(tbl(cover_data, [6*cm, 10.5*cm], NAVY))
        story.append(Spacer(1, 0.5*cm))
        story.append(Paragraph(
            "⚠ This report is generated from computational models. "
            "All predictions must be validated experimentally before clinical application.",
            note))
        story.append(PageBreak())

        # ══════════════════════════════════════════════════════════════════════
        # SECTION 1: DRUG MOLECULAR PROFILE
        # ══════════════════════════════════════════════════════════════════════
        story.append(Paragraph("1. Drug Molecular Profile", h1))
        story.append(HRFlowable(width="100%", thickness=1, color=GOLD_RL))

        mp = mol_profile or {}
        drug_data = [
            ["Property", "Value", "Source / Method"],
            ["Name",                    drug_name,                                "Input"],
            ["MW (Da)",                 _safe(mp.get("MW_Da"), ".1f"),            "ChEMBL / UniProt"],
            ["LogP",                    _safe(mp.get("LogP"), ".2f"),             "ADMET predictor"],
            ["Half-life (days)",        _safe(mp.get("Half_Life_Days"), ".3f"),   "PubMed NLP"],
            ["Protein Binding (%)",     _safe(mp.get("Protein_Binding_pct"), ".1f"), "Calculated"],
            ["BBB Penetration (%)",     _safe(mp.get("BBB_permeability_pct"), ".2f"), "Pardridge 2012"],
            ["Molecule Class",          mp.get("molecule_class","N/A"),           "Input / inferred"],
            ["Aqueous Solubility",      mp.get("logSw","N/A"),                    "ADMET"],
            ["P-gp Substrate",          str(mp.get("Pgp_Substrate","Unknown")),   "QSAR panel"],
            ["ADMET Score",             str(mp.get("ADMET_Score","N/A")),         "Multi-endpoint"],
            ["ADMET Grade",             str(mp.get("ADMET_Grade","N/A")),         "A-F scale"],
        ]
        story.append(tbl(drug_data, [5.5*cm, 5*cm, 6*cm]))
        story.append(Spacer(1, 0.3*cm))

        # Drug problems - most important section
        problems = science_results.get("drug_problems", [])
        if problems:
            story.append(Paragraph("1a. Drug Delivery Barriers Identified (Auto-detected)", h2))
            story.append(Paragraph(
                f"The pipeline automatically identified {len(problems)} delivery barriers "
                f"based on molecular data. Each is resolved by the recommended DDS.", body))
            story.append(Spacer(1, 0.2*cm))

            for p in problems:
                sev = str(p.get("severity",""))
                sev_c = _sev_color(sev)
                data = [
                    [Paragraph(f'<b>[{sev}] {p.get("problem","")}</b>', body), ""],
                    ["Evidence:",    str(p.get("evidence",""))[:100]],
                    ["Without DDS:", str(p.get("without_dds",""))[:100]],
                    ["With DDS:",    str(p.get("with_dds",""))[:100]],
                    ["DDS Solution:",str(p.get("dds_solution",""))[:80]],
                    ["Scientific basis:", str(p.get("why",""))[:120]],
                ]
                pt = Table(data, colWidths=[3.5*cm, 13*cm])
                pt.setStyle(TableStyle([
                    ("SPAN",       (0,0),(1,0)),
                    ("BACKGROUND", (0,0),(1,0), sev_c),
                    ("TEXTCOLOR",  (0,0),(1,0), colors.white),
                    ("FONTNAME",   (0,0),(1,0), "Helvetica-Bold"),
                    ("FONTSIZE",   (0,0),(1,-1), 8.5),
                    ("GRID",       (0,0),(-1,-1), 0.3, colors.lightgrey),
                    ("FONTNAME",   (0,1),(0,-1), "Helvetica-Bold"),
                    ("TEXTCOLOR",  (0,1),(0,-1), _rl_color(NAVY)),
                    ("VALIGN",     (0,0),(-1,-1), "TOP"),
                    ("TOPPADDING", (0,0),(-1,-1), 3),
                    ("BOTTOMPADDING",(0,0),(-1,-1), 3),
                    ("LEFTPADDING",(0,0),(-1,-1), 5),
                ]))
                story.append(pt)
                story.append(Spacer(1, 0.1*cm))

        story.append(PageBreak())

        # ══════════════════════════════════════════════════════════════════════
        # SECTION 2: DDS RANKING
        # ══════════════════════════════════════════════════════════════════════
        story.append(Paragraph("2. DDS Ranking — Composite Score Methodology", h1))
        story.append(HRFlowable(width="100%", thickness=1, color=GOLD_RL))
        story.append(Paragraph(
            "All DDS formulations ranked by Composite Score = weighted combination of "
            "DLVO colloidal stability, transcytosis driving force, endosomal escape, "
            "stealth index, BBB receptor affinity, and CNS bioavailability. "
            "Scores are physics-derived — not estimated.", body))
        story.append(Spacer(1, 0.2*cm))

        if df_dds is not None and not df_dds.empty:
            score_col = ("Composite_Score" if "Composite_Score" in df_dds.columns
                          else "BBB_Engineering_Score")
            top10 = df_dds.nlargest(min(10, len(df_dds)), score_col)
            dds_display_cols = [
                ("Formulation_Name",         "DDS Name"),
                ("Carrier_Type",             "Carrier"),
                ("Surface_Ligand",           "Ligand"),
                (score_col,                  "Score"),
                ("BBB_Enhanced_Pct",         "BBB%"),
                ("CNS_Bioavailability_Pct",  "CNS BA%"),
                ("Endosomal_Escape_Eff",     "Escape"),
                ("Stealth_Index",            "Stealth"),
                ("DLVO_V_total_kT",          "DLVO kT"),
            ]
            avail = [(c, h) for c, h in dds_display_cols if c in df_dds.columns]
            if avail:
                cols, hdrs = zip(*avail)
                rows = [list(hdrs)]
                for _, row in top10.iterrows():
                    r = []
                    for c in cols:
                        v = row.get(c, "")
                        try: r.append(f"{float(v):.2f}")
                        except: r.append(str(v)[:20])
                    rows.append(r)
                widths = [4.5*cm] + [2.2*cm] * (len(cols)-1)
                story.append(tbl(rows, widths, NAVY))

        story.append(Spacer(1, 0.3*cm))

        # Top DDS detail box
        if top_dds:
            story.append(Paragraph("2a. Recommended DDS — Detailed Profile", h2))
            top_detail = [
                ["Parameter", "Value", "Biophysical Meaning"],
                ["Composite Score",        _safe(top_dds.get("Composite_Score") or top_dds.get("BBB_Engineering_Score"), ".1f"), "Overall Drug+DDS suitability (0-100)"],
                ["BBB Enhancement",        _safe(top_dds.get("BBB_Enhanced_Pct"),".1f") + "%",  "% of dose crossing BBB via receptor transcytosis"],
                ["CNS Bioavailability",    _safe(top_dds.get("CNS_Bioavailability_Pct"),".1f") + "%", "% dose reaching brain as free drug"],
                ["DLVO Stability",         _safe(top_dds.get("DLVO_V_total_kT"),".1f") + " kT",  ">25kT = colloidally stable in blood"],
                ["Endosomal Escape",       _safe(top_dds.get("Endosomal_Escape_Eff"),".2f"),     "Fraction escaping lysosomes (0-1)"],
                ["Stealth Index",          _safe(top_dds.get("Stealth_Index"),".2f"),             "MPS evasion (0=opsonised, 1=invisible)"],
                ["Protein Corona",         _safe(top_dds.get("Protein_Corona_nm"),".1f") + " nm", "Corona thickness; thicker = faster clearance"],
                ["MPS Clearance",          _safe(top_dds.get("MPS_Clearance_h"),".0f") + " h",   "Hours before liver/spleen removes DDS"],
                ["Payload Efficiency",     _safe(top_dds.get("Payload_Efficiency_Pct"),".1f") + "%", "% dose delivered as active drug to CNS"],
                ["CARPA Risk",             _safe(top_dds.get("CARPA_Risk_Index"),".2f"),          "Complement activation risk (0=safe)"],
            ]
            story.append(tbl(top_detail, [5.5*cm, 4*cm, 7*cm], NAVY))

        story.append(PageBreak())

        # ══════════════════════════════════════════════════════════════════════
        # SECTION 3: PBPK DIGITAL TWIN
        # ══════════════════════════════════════════════════════════════════════
        pbpk = science_results.get("pbpk_cns", {})
        story.append(Paragraph("3. PBPK-CNS Digital Twin — 6-Compartment Simulation", h1))
        story.append(HRFlowable(width="100%", thickness=1, color=GOLD_RL))
        story.append(Paragraph(
            "Physiologically Based Pharmacokinetic model solved with scipy Radau ODE integrator "
            "(stiff system). Compartments: Plasma, BBB endothelium, Brain ISF, Brain cells, "
            "CSF, Peripheral. All parameters from molecular data — not estimated. "
            "Reference: Pardridge 2012; Bhatt 2013.", body))
        story.append(Spacer(1, 0.2*cm))

        if pbpk and not pbpk.get("error"):
            # ── Schema adapter: supports both SmallMol PBPK and BiologicPBPK ─
            _pbpk_model = pbpk.get("model","PBPK")
            _is_bio_pbpk = "Biologic" in _pbpk_model or "TwoCompartment" in _pbpk_model
            if _is_bio_pbpk:
                # BiologicPBPK key mapping
                _cmax_brain = pbpk.get("Cmax_brain_ug_mL", 0)
                _auc_brain  = pbpk.get("AUC_CNS_day_ug_mL", 0) * 24   # day→h
                _auc_plasma = pbpk.get("AUC_plasma_day_ug_mL", 0) * 24
                # AUC ratio, not Cmax ratio — matches the Kp_brain definition
                # used everywhere else in this codebase (pbbm_engine.py,
                # science_engines.py, cerebro_science_modules.py all define
                # Kp_brain = AUC_brain/AUC_plasma). This branch previously
                # computed it from Cmax instead, so a biologic's "Kp,brain"
                # in this exact table wasn't comparable to a small
                # molecule's "Kp,brain" two rows of logic below, even
                # though both render under the identical column label.
                _kp_brain   = _auc_brain / max(_auc_plasma, 1e-9)
                _t_half     = pbpk.get("T_half_effective_days", 0) * 24  # days→h
                _bbb_pct    = pbpk.get("BBB_transcytosis_pct", 0)
                _model_note = f"BiologicPBPK (FcRn + CNS transcytosis) | T½={_t_half:.1f}h"
            else:
                _cmax_brain = pbpk.get("Cmax_brain_ug_mL", 0)
                _auc_brain  = pbpk.get("AUC_brain_ugh_mL", 0)
                _auc_plasma = pbpk.get("AUC_plasma_ugh_mL", 0)
                _kp_brain   = pbpk.get("Kp_brain", 0)
                _t_half     = pbpk.get("t_half_h", 0)
                _bbb_pct    = pbpk.get("BBB_permeability_pct", 0)
                _model_note = "6-compartment ODE (Radau stiff solver) | Pardridge 2012"

            pbpk_data = [
                ["PK Metric", "Value", "Compartment", "Source"],
                ["Model", _model_note, "—", pbpk.get("_reference","CEREBRO-X PBPK")[:60]],
                ["Cmax (brain)", f"{_cmax_brain:.6f} µg/mL", "Brain/CNS", "Peak brain concentration"],
                ["AUC (brain)",  f"{_auc_brain:.5f} µg·h/mL",  "Brain/CNS", "Total brain exposure"],
                ["AUC (plasma)", f"{_auc_plasma:.3f} µg·h/mL", "Plasma",    "Systemic exposure"],
                ["Kp,brain",     f"{_kp_brain:.5f}",            "Brain/Plasma","Partition coefficient"],
                ["BBB penetration", f"{_bbb_pct:.4f}%",         "BBB",        pbpk.get("_source","")[:50]],
                ["Kp,uu brain",     _safe(pbpk.get('Kpuu_brain'), '.5f'),                      "Unbound",   "Unbound Kp (pharmacodynamically relevant)"],
                ["t_above 10%Cmax", f"{_safe(pbpk.get('t_above_10pct_h'), '.1f')} h",          "Brain ISF", "Duration above therapeutic threshold"],
                ["Glymphatic t1/2", f"{_safe(pbpk.get('t_half_glymphatic_h'), '.1f')} h",      "Brain",     "Clearance half-life in brain"],
                ["BBB PS_in",       f"{_safe(pbpk.get('PS_in_mL_h'), '.3f')} mL/h",            "BBB",       "Permeability-surface area product"],
                ["BBB PS_out",      f"{_safe(pbpk.get('PS_out_mL_h'), '.3f')} mL/h",           "BBB",       "Efflux transport rate"],
                ["Disease state",   pbpk.get("disease_state","healthy"),                        "BBB",       "BBB integrity modifier applied"],
            ]
            story.append(tbl(pbpk_data, [4.5*cm, 4*cm, 3.5*cm, 4.5*cm], NAVY))

            # Time course table (sampled) — array-safe truth check
            # `t_h`/`C_plasma`/`C_brain_ISF` may be lists, numpy arrays, or
            # pandas Series. The naïve `if t_arr:` raises ValueError on
            # arrays (truth value of an array is ambiguous). Convert and
            # check length explicitly.
            t_arr = pbpk.get("t_h", [])
            Cp    = pbpk.get("C_plasma", [])
            Cisf  = pbpk.get("C_brain_ISF", [])
            try:
                _n = len(t_arr)
            except TypeError:
                _n = 0
            if _n > 0:
                story.append(Spacer(1, 0.3*cm))
                story.append(Paragraph("3a. PBPK Time-Course (sampled points)", h3))
                sample_pts = [int(i*(_n-1)/11) for i in range(12)]
                tc_data = [["t (h)", "Plasma (µg/mL)", "Brain ISF (µg/mL)", "Ratio (Kp)"]]
                for idx in sample_pts:
                    t_v = float(t_arr[idx]); cp_v = float(Cp[idx]); cisf_v = float(Cisf[idx])
                    tc_data.append([f"{t_v:.1f}", f"{cp_v:.4f}", f"{cisf_v:.5f}",
                                     f"{cisf_v/max(cp_v,1e-10):.5f}"])
                story.append(tbl(tc_data, [3*cm, 4.5*cm, 4.5*cm, 4.5*cm], TEAL))
        else:
            story.append(Paragraph("⚠ PBPK simulation not available for this trial.", warn))
        story.append(PageBreak())

        # ══════════════════════════════════════════════════════════════════════
        # SECTION 4: DRUG RELEASE KINETICS
        # ══════════════════════════════════════════════════════════════════════
        release = science_results.get("release", {})
        story.append(Paragraph("4. In-Silico Drug Release Profile", h1))
        story.append(HRFlowable(width="100%", thickness=1, color=GOLD_RL))

        if release and not release.get("error"):
            story.append(Paragraph(
                f"Release model: {release.get('release_model','').replace('_',' ').title()} | "
                f"Release order: {release.get('release_order','')} | "
                f"Max EE: {release.get('max_release_pct',0):.0f}%", body))
            rel_data = [
                ["Metric", "Blood (pH 7.4)", "Endosomal (pH 5.5)", "Significance"],
                ["t50 (50% release)", f"{_safe(release.get('t50_blood_h'),'.1f')} h",
                  f"{_safe(release.get('t50_endosomal_h'),'.1f')} h", "Faster endo = better escape"],
                ["t90 (90% release)", f"{_safe(release.get('t90_blood_h'),'.1f')} h",
                  "N/A", "Complete release window"],
                ["Rate constant k", f"{_safe(release.get('k_blood_per_h'),'.4f')} /h",
                  f"{_safe(release.get('k_endosomal_per_h'),'.4f')} /h", "Higher endo = pH-responsive"],
                ["Max released", f"{_safe(release.get('max_release_pct'),'.0f')}%",
                  f"{_safe(release.get('max_release_pct'),'.0f')}%", "= encapsulation efficiency"],
            ]
            story.append(tbl(rel_data, [4.5*cm, 4*cm, 4*cm, 4*cm], NAVY))
        story.append(Spacer(1, 0.3*cm))

        # Section 5: Shelf-life
        shelf = science_results.get("shelf_life", {})
        story.append(Paragraph("5. Shelf-Life & Degradation Predictor", h2))
        if shelf and not shelf.get("error"):
            story.append(Paragraph(
                f"Grade: {shelf.get('shelf_life_grade','')} | "
                f"t90 = {shelf.get('t90_shelf_life_days','?'):.0f} days | "
                f"Dominant pathway: {shelf.get('dominant_degradation','')} | "
                f"Storage: {shelf.get('recommended_storage','')}", body))
            shelf_data = [
                ["Pathway", "Rate (k, /day)", "Relative %"],
                ["Hydrolysis",   _safe(shelf.get('k_hydrolysis_per_day'),".6f"),
                  f"{shelf.get('k_hydrolysis_per_day',0)/max(shelf.get('k_total_per_day',0.001),1e-10)*100:.0f}%"],
                ["Oxidation",    _safe(shelf.get('k_oxidation_per_day'),".6f"),
                  f"{shelf.get('k_oxidation_per_day',0)/max(shelf.get('k_total_per_day',0.001),1e-10)*100:.0f}%"],
                ["Aggregation",  _safe(shelf.get('k_aggregation_per_day'),".6f"),
                  f"{shelf.get('k_aggregation_per_day',0)/max(shelf.get('k_total_per_day',0.001),1e-10)*100:.0f}%"],
                ["Drug leakage", _safe(shelf.get('k_leakage_per_day'),".6f"),
                  f"{shelf.get('k_leakage_per_day',0)/max(shelf.get('k_total_per_day',0.001),1e-10)*100:.0f}%"],
            ]
            story.append(tbl(shelf_data, [5*cm, 5*cm, 5*cm], TEAL))

        story.append(PageBreak())

        # ══════════════════════════════════════════════════════════════════════
        # SECTION 6: COLLOIDAL STABILITY
        # ══════════════════════════════════════════════════════════════════════
        story.append(Paragraph("6. Colloidal Stability — DLVO Theory + Protein Corona", h1))
        story.append(HRFlowable(width="100%", thickness=1, color=GOLD_RL))

        if top_dds:
            dlvo_stable = top_dds.get("DLVO_stable", False)
            story.append(Paragraph(
                f"DLVO potential energy V_total = {_safe(top_dds.get('DLVO_V_total_kT'),'.1f')} kT "
                f"({'STABLE ✓' if dlvo_stable else 'UNSTABLE ✗ — REFORMULATE'}) | "
                f"Threshold: >25 kT prevents aggregation in blood. "
                f"Reference: Verwey & Overbeek 1948; Derjaguin 1987.", body))
            dlvo_data = [
                ["Parameter", "Value", "Equation", "Significance"],
                ["DLVO V_total (kT)",    _safe(top_dds.get("DLVO_V_total_kT"),".1f"),    "V_vdW + V_EDL",   ">25kT = stable"],
                ["V_vdW (attraction)",   _safe(top_dds.get("DLVO_V_vdW_kT"),".2f"),       "-A·R/(12h)",       "Hamaker constant"],
                ["V_EDL (repulsion)",    _safe(top_dds.get("DLVO_V_EDL_kT"),".2f"),       "64π ε R γ² e^-κh", "Zeta potential"],
                ["Debye length (nm)",    _safe(top_dds.get("Debye_length_nm"),".2f"),     "1/κ",              "Ionic screening"],
                ["Protein corona (nm)",  _safe(top_dds.get("Protein_Corona_nm"),".1f"),   "Langmuir model",   "Stealth reduction"],
                ["Opsonin index",        _safe(top_dds.get("Opsonin_Index"),".3f"),        "IgG + C3b binding","<0.3 = good"],
                ["Stealth index",        _safe(top_dds.get("Stealth_Index"),".3f"),        "PEG brush model",  "0.6+ = good"],
                ["MPS clearance (h)",    _safe(top_dds.get("MPS_Clearance_h"),".0f"),     "Michaelis-Menten", ">12h adequate"],
            ]
            story.append(tbl(dlvo_data, [4.5*cm, 3*cm, 4*cm, 5*cm], NAVY))

        story.append(Spacer(1, 0.3*cm))

        # ══════════════════════════════════════════════════════════════════════
        # SECTION 7: NANOTOXICITY
        # ══════════════════════════════════════════════════════════════════════
        nanotox = science_results.get("nanotoxicity", {})
        story.append(Paragraph("7. Nanotoxicity & Immunogenicity Screening", h2))
        if nanotox and not nanotox.get("error"):
            grade = nanotox.get("Immunogenicity_grade","")
            grade_color = RED_RL if "RISK" in grade else (ORANGE_RL if "CAUTION" in grade else GREEN_RL)
            story.append(Paragraph(
                f'Immunogenicity grade: <b>{grade}</b> | '
                f'Score: {_safe(nanotox.get("Overall_imm_score"),".0f")}/100', body))
            tox_data = [
                ["Test", "Score / Result", "Risk", "Threshold"],
                ["CARPA (complement)",    _safe(nanotox.get("CARPA_score"),".3f"),      nanotox.get("CARPA_risk",""), ">0.6 = HIGH"],
                ["Anti-PEG antibody",     _safe(nanotox.get("AntiPEG_ABC_score"),".3f"),nanotox.get("AntiPEG_risk",""), "0.5+ = caution"],
                ["MPS uptake",            _safe(nanotox.get("MPS_uptake_score"),".3f"), "—", ">0.6 = rapid clearance"],
                ["Cytokine storm",        "—",                                           nanotox.get("Cytokine_storm_risk",""), "Charge-dependent"],
                ["Platelet activation",   "—",                                           nanotox.get("Platelet_risk",""), "Cationic >200nm"],
            ]
            story.append(tbl(tox_data, [5*cm, 4*cm, 4*cm, 3.5*cm], TEAL))
            if nanotox.get("Mitigations"):
                story.append(Spacer(1, 0.2*cm))
                story.append(Paragraph("Mitigations:", h3))
                for m in nanotox.get("Mitigations",[]):
                    story.append(Paragraph(f"→ {m}", body))

        story.append(PageBreak())

        # ══════════════════════════════════════════════════════════════════════
        # SECTION 8: OFF-TARGET QSAR
        # ══════════════════════════════════════════════════════════════════════
        qsar = science_results.get("qsar_toxicity", {})
        story.append(Paragraph("8. Off-Target Toxicity — 50-Receptor QSAR Panel", h1))
        story.append(HRFlowable(width="100%", thickness=1, color=GOLD_RL))

        if qsar and not qsar.get("error"):
            n_high = qsar.get("n_high_risk_targets", 0)
            overall = qsar.get("overall_off_target","")
            story.append(Paragraph(
                f"Overall: {overall} | Cardiac risk: {'YES ⚠' if qsar.get('cardiac_risk') else 'NO ✓'} | "
                f"Hepatic risk: {'YES ⚠' if qsar.get('hepatic_risk') else 'NO ✓'} | "
                f"CNS off-target: {'YES ⚠' if qsar.get('CNS_off_target_risk') else 'NO ✓'}", body))
            story.append(Spacer(1, 0.2*cm))

            panel = qsar.get("receptor_panel", {})
            qsar_rows = [["Receptor", "Free Drug Score", "In-DDS Score", "Risk"]]
            for rec, data in list(panel.items())[:20]:
                qsar_rows.append([
                    rec, _safe(data.get("score_free_drug"),".3f"),
                    _safe(data.get("score_in_DDS"),".3f"), data.get("risk","")
                ])
            story.append(tbl(qsar_rows, [5*cm, 4*cm, 4*cm, 3.5*cm], NAVY))

            if qsar.get("flags"):
                story.append(Spacer(1, 0.2*cm))
                story.append(Paragraph(f"High-risk flags ({len(qsar.get('flags',[]))}):", h3))
                for flag in qsar.get("flags",[])[:8]:
                    story.append(Paragraph(f"⚠ {flag}", warn))

        story.append(PageBreak())

        # ══════════════════════════════════════════════════════════════════════
        # SECTION 9: ADVANCED MODULES SUMMARY
        # ══════════════════════════════════════════════════════════════════════
        story.append(Paragraph("9. Advanced Science Modules — Key Outputs", h1))
        story.append(HRFlowable(width="100%", thickness=1, color=GOLD_RL))

        # 9a: Competitive Landscape
        comp = science_results.get("competitive_landscape", {})
        if comp and not comp.get("error"):
            story.append(Paragraph("9a. Competitive DDS Landscape (ClinicalTrials.gov)", h2))
            story.append(Paragraph(
                f"Our DDS: BBB Score = {comp.get('our_BBB_score',0):.0f} | "
                f"Position: {comp.get('competitive_position','')} | "
                f"Active trials found: {comp.get('n_trials_found',0)}", body))
            trials = comp.get("active_trials", [])[:5]
            if trials:
                t_data = [["NCT ID","Title","Phase","N"]]
                for tr in trials:
                    t_data.append([tr.get("nct_id",""),tr.get("title","")[:45],
                                    tr.get("phase",""),str(tr.get("n",""))])
                story.append(tbl(t_data, [3*cm, 8*cm, 3*cm, 2.5*cm], TEAL))
            story.append(Spacer(1, 0.2*cm))

        # 9b: Patient Stratification
        strat = science_results.get("patient_stratifier", {})
        if strat and not strat.get("error"):
            story.append(Paragraph("9b. Patient Subgroup Stratification", h2))
            story.append(Paragraph(
                f"Overall response: {strat.get('overall_response_prob',0):.1f}% | "
                f"Best: {strat.get('best_subgroup','')} ({strat.get('best_response_pct',0):.0f}%) | "
                f"Worst: {strat.get('worst_subgroup','')} ({strat.get('worst_response_pct',0):.0f}%) | "
                f"Recommendation: {strat.get('recommendation','')[:80]}", body))
            sgs = strat.get("subgroups", [])
            if sgs:
                sg_data = [["Subgroup","Pop. Freq.","CNS Bioavail","Response%","Tox Risk","Dose Adj."]]
                for sg in sgs:
                    sg_data.append([sg.get("subgroup",""),sg.get("frequency",""),
                                     f"{sg.get('CNS_bioavail_pct',0):.1f}%",
                                     f"{sg.get('response_prob',0):.1f}%",
                                     sg.get("toxicity_risk",""),sg.get("rec_dose","")])
                story.append(tbl(sg_data, [3.8*cm,2.5*cm,3*cm,3*cm,2.5*cm,2.5*cm], NAVY))
            story.append(Spacer(1, 0.2*cm))

        # 9c: Quantum Transport
        qt = science_results.get("quantum_transport", {})
        if qt and qt.get("applicable") and not qt.get("error"):
            story.append(Paragraph("9c. Quantum Coherence Transport Model", h2))
            story.append(Paragraph(
                f"WKB tunneling probability = {qt.get('tunneling_prob','N/A')} | "
                f"Barrier = {_safe(qt.get('barrier_kcal_mol'),'.2f')} kcal/mol | "
                f"Classical prob = {qt.get('classical_prob','N/A')} | "
                f"{qt.get('interpretation',''[:80])}", body))

        # 9d: Lyosomal Trafficking
        lyso = science_results.get("lysosomal_trafficking", {})
        if lyso and not lyso.get("error"):
            story.append(Paragraph("9d. Lysosomal Trafficking Predictor", h2))
            story.append(Paragraph(
                f"Cytosolic route: {lyso.get('prob_cytosol_pct',0):.0f}% | "
                f"Lysosomal degradation: {lyso.get('prob_lysosomal_pct',0):.0f}% | "
                f"Nuclear entry: {lyso.get('prob_nuclear_pct',0):.0f}% | "
                f"Concern: {lyso.get('lysosomal_concern','')} | "
                f"Mitigation: {lyso.get('mitigation',''[:60])}", body))

        # 9e: LNP Ionization
        ion = science_results.get("lnp_ionization", {})
        if ion and ion.get("applicable") and not ion.get("error"):
            story.append(Paragraph("9e. LNP Ionization State", h2))
            story.append(Paragraph(
                f"Estimated pKa = {_safe(ion.get('estimated_pKa'),'.1f')} | "
                f"Endosomal escape prediction = {ion.get('endosomal_escape_pred',0):.0f}% | "
                f"{ion.get('recommendation','')[:80]}", body))

        story.append(PageBreak())

        # ══════════════════════════════════════════════════════════════════════
        # SECTION 10: SYNTHETIC CLINICAL TRIAL
        # ══════════════════════════════════════════════════════════════════════
        synth = science_results.get("synthetic_clinical", {})
        story.append(Paragraph("10. Synthetic Clinical Trial — N=500 Virtual Patients", h1))
        story.append(HRFlowable(width="100%", thickness=1, color=GOLD_RL))
        story.append(Paragraph(
            "Monte Carlo simulation of Phase 1 trial. Patient covariates: age, weight, "
            "CYP3A4 genotype, renal function, BBB integrity by age. "
            "Pharmacokinetics computed per-patient from PBPK model. "
            "Reference: FDA PBPK guidance 2018; Lalonde 2007.", body))

        if synth and not synth.get("error"):
            dec = synth.get("go_no_go","?")
            story.append(Spacer(1, 0.2*cm))
            story.append(metric_row([
                ("Go/No-Go",         dec,                         GREEN if "GO"==dec else RED_C),
                ("Response Rate",    f"{synth.get('overall_response_pct',0):.1f}%",   TEAL),
                ("Severe AE",        f"{synth.get('AE_severe_pct',0):.1f}%",           ORANGE if synth.get('AE_severe_pct',0)>5 else GREEN),
                ("Optimal Dose",     f"{synth.get('optimal_dose_mg_kg',0):.2f} mg/kg", NAVY),
                ("N Patients",       str(synth.get("n_patients",0)),                   NAVY),
            ]))
            story.append(Spacer(1, 0.2*cm))
            trial_data = [
                ["Endpoint",             "Result",  "Benchmark", "Status"],
                ["Overall response rate",f"{synth.get('overall_response_pct',0):.1f}%",">60% = GO","✓" if synth.get('overall_response_pct',0)>60 else "✗"],
                ["Severe AE rate",       f"{synth.get('AE_severe_pct',0):.1f}%",      "<5% = GO", "✓" if synth.get('AE_severe_pct',0)<5 else "✗"],
                ["Young adults (<65)",   f"{synth.get('responders_young_pct',0):.1f}%", "—",       "—"],
                ["Elderly (>65)",        f"{synth.get('responders_elderly_pct',0):.1f}%","—",      "—"],
                ["Mild AE",              f"{synth.get('AE_mild_pct',0):.1f}%",         "—",        "—"],
                ["Renal AE",             f"{synth.get('renal_AE_pct',0):.1f}%",        "<15%",     "✓" if synth.get('renal_AE_pct',0)<15 else "✗"],
            ]
            story.append(tbl(trial_data, [5*cm, 3.5*cm, 4*cm, 4*cm], NAVY))
            story.append(Spacer(1, 0.2*cm))
            story.append(Paragraph(f"Recommendation: {synth.get('trial_recommendation','')}", body))

        story.append(PageBreak())

        # ══════════════════════════════════════════════════════════════════════
        # SECTION 11: MANUFACTURING & STERILIZATION
        # ══════════════════════════════════════════════════════════════════════
        story.append(Paragraph("11. Manufacturing & Sterilization Modules", h1))
        story.append(HRFlowable(width="100%", thickness=1, color=GOLD_RL))

        sterile = science_results.get("sterilization", {})
        lyophi  = science_results.get("lyophilization", {})
        cryo    = science_results.get("cryo_excursion", {})
        stress  = science_results.get("stress_test", {})

        if sterile and not sterile.get("error"):
            story.append(Paragraph("11a. Terminal Sterilization Survivability", h2))
            story.append(Paragraph(
                f"Recommended method: {sterile.get('recommended_method','')} | "
                f"Cost implication: {sterile.get('cost_implication','')} | "
                f"Feasible methods: {', '.join(sterile.get('feasible_methods',[]))}", body))
            meth_data = [["Method", "Survives?", "Detail"]]
            for meth, res in (sterile.get("sterilization_methods",{}) or {}).items():
                meth_data.append([meth.replace("_"," "),
                                    "YES ✓" if res.get("survives") else "NO ✗",
                                    str(res.get("detail",""))[:60]])
            story.append(tbl(meth_data, [5.5*cm, 3*cm, 8*cm], TEAL))
            story.append(Spacer(1, 0.2*cm))

        if lyophi and not lyophi.get("error"):
            story.append(Paragraph("11b. Lyophilization Cycle Optimizer", h2))
            rec = lyophi.get("recommended_cycle", {})
            lyo_data = [
                ["Parameter", "Value", "Standard"],
                ["Tg' (cryo.",       f"{lyophi.get('Tg_prime_C','?')}°C",          "Formulation-specific"],
                ["Primary drying T", f"{lyophi.get('T_primary_drying_C','?')}°C",  "Must be < Tg'"],
                ["Primary P",        f"{lyophi.get('P_primary_mbar','?')} mbar",    "0.5×P_ice"],
                ["Primary time",     f"{lyophi.get('t_primary_drying_h','?')} h",   "Pikal 2002 model"],
                ["Secondary T",      f"{lyophi.get('T_secondary_drying_C','?')}°C", "+25°C"],
                ["Cycle total",      f"{lyophi.get('total_cycle_h','?')} h",         "Include ramp time"],
                ["Cake collapse",    lyophi.get("cake_collapse_risk",""), "Must say OK"],
            ]
            story.append(tbl(lyo_data, [5*cm, 3.5*cm, 8*cm], TEAL))
            story.append(Spacer(1, 0.2*cm))

        if cryo and not cryo.get("error"):
            story.append(Paragraph("11c. Cryo-Chain Excursion Predictor", h2))
            story.append(Paragraph(
                f"Excursion: {cryo.get('excursion_temp_C','?')}°C for {cryo.get('excursion_duration_h','?')}h | "
                f"EE: {cryo.get('EE_before_pct','?')}% → {cryo.get('EE_after_excursion_pct','?')}% "
                f"(loss: {cryo.get('EE_loss_pct','?')}%) | "
                f"Decision: {cryo.get('batch_decision','')} | "
                f"Confidence: {cryo.get('confidence_pct','')}%", body))
            story.append(Spacer(1, 0.2*cm))

        if stress and not stress.get("error"):
            story.append(Paragraph("11d. Adversarial Stress-Testing", h2))
            story.append(Paragraph(
                f"Grade: {stress.get('stress_grade','')} | "
                f"{stress.get('n_pass',0)}/{stress.get('n_total',5)} scenarios passed.", body))
            sc_data = [["Scenario", "Pass/Fail", "Detail"]]
            for sc_name, sc in (stress.get("scenarios",{}) or {}).items():
                sc_data.append([sc_name.replace("_"," ").title(),
                                  "PASS ✓" if sc.get("pass") else "FAIL ✗",
                                  str(sc.get("detail",""))[:70]])
            story.append(tbl(sc_data, [5.5*cm, 3*cm, 8*cm], NAVY))

        story.append(PageBreak())

        # ══════════════════════════════════════════════════════════════════════
        # SECTION 12: REGULATORY & SUPPLY CHAIN
        # ══════════════════════════════════════════════════════════════════════
        story.append(Paragraph("12. Regulatory Compliance & Supply Chain", h1))
        story.append(HRFlowable(width="100%", thickness=1, color=GOLD_RL))

        fda = science_results.get("fda_compliance", {})
        sc  = science_results.get("supply_chain", {})

        if fda:
            story.append(Paragraph("12a. FDA 21 CFR Part 11 Compliance", h2))
            story.append(Paragraph(
                f"Status: {fda.get('compliance_status','')} | "
                f"Audit entries: {fda.get('n_audit_entries',0)} | "
                f"Data integrity: {fda.get('data_integrity','SHA-256')}", body))

        if sc and not sc.get("error"):
            story.append(Spacer(1, 0.2*cm))
            story.append(Paragraph("12b. Geopolitical Supply-Chain Risk Assessment", h2))
            story.append(Paragraph(
                f"Overall supply risk: {sc.get('overall_supply_risk','')} | "
                f"Supply chain score: {sc.get('supply_chain_score',0):.0f}/100 | "
                f"Recommendation: {sc.get('recommendation','')[:80]}", body))
            mat_rows = sc.get("materials_analyzed", [])
            if mat_rows:
                m_data = [["Material", "Risk", "Source", "HHI Index", "Mitigation"]]
                for m in mat_rows:
                    m_data.append([m.get("material",""),m.get("risk_level",""),
                                    m.get("source","")[:30],str(m.get("HHI_index","")),
                                    m.get("mitigation","")[:40]])
                story.append(tbl(m_data, [4*cm, 3*cm, 4.5*cm, 2.5*cm, 2.5*cm], TEAL))

        # Pharmacovigilance
        pv = science_results.get("pharmacovigilance", {})
        if pv and not pv.get("error"):
            story.append(Spacer(1, 0.2*cm))
            story.append(Paragraph("12c. Digital Pharmacovigilance — Post-Elimination Fate", h2))
            story.append(Paragraph(
                f"Unchanged excretion: {_safe(pv.get('unchanged_excretion_pct'),'.1f')}% | "
                f"Eco-persistence: {_safe(pv.get('eco_persistence_days'),'.1f')} days | "
                f"Environmental risk: {pv.get('environmental_risk','')} | "
                f"Renal dose adjustment: {pv.get('dose_adj_renal_failure','')}", body))

        story.append(PageBreak())

        # ══════════════════════════════════════════════════════════════════════
        # SECTION 13: LITERATURE CITATIONS
        # ══════════════════════════════════════════════════════════════════════
        lit = science_results.get("literature_mining", [])
        story.append(Paragraph("13. Literature Citations — PubMed Auto-Mined", h1))
        story.append(HRFlowable(width="100%", thickness=1, color=GOLD_RL))
        story.append(Paragraph(
            "Top relevant publications retrieved live from PubMed E-utilities API "
            "based on drug name + carrier type. These papers confirm or contextualize "
            "the computational predictions above.", body))
        story.append(Spacer(1, 0.2*cm))

        if lit:
            for i, paper in enumerate(lit[:5], 1):
                citation = paper.get("citation", paper.get("title",""))
                story.append(Paragraph(
                    f"[{i}] {citation}", body))
        else:
            story.append(Paragraph("Literature mining results not available for this run.", note))

        # ══════════════════════════════════════════════════════════════════════
        # SECTION 14: FEP BINDING + GLYMPHATIC + MICROGLIAL
        # ══════════════════════════════════════════════════════════════════════
        fep  = science_results.get("fep_binding", {})
        glyph= science_results.get("glymphatic", {})
        micr = science_results.get("microglial_activation", {})
        fus  = science_results.get("fus_responsive", {})

        story.append(Spacer(1, 0.3*cm))
        story.append(Paragraph("14. Biophysical Binding & CNS-Specific Modules", h1))
        story.append(HRFlowable(width="100%", thickness=1, color=GOLD_RL))

        if fep and not fep.get("error"):
            story.append(Paragraph("14a. FEP+ Binding Affinity (LIE approximation)", h2))
            story.append(Paragraph(
                f"Ligand: {fep.get('ligand','')} | "
                f"ΔG_single = {_safe(fep.get('dG_single_ligand_kcal'),'.2f')} kcal/mol | "
                f"ΔG_avidity = {_safe(fep.get('dG_avidity_kcal'),'.2f')} kcal/mol | "
                f"Kd = {_safe(fep.get('Kd_nM'),'.0f')} nM ({fep.get('Kd_class','')}) | "
                f"n_ligands = {_safe(fep.get('n_ligands_on_surface'),'.0f')} | "
                f"Residence time = {_safe(fep.get('residence_time_s'),'.1f')} s", body))

        if glyph and not glyph.get("error"):
            story.append(Paragraph("14b. Glymphatic Clearance Simulation", h2))
            story.append(Paragraph(
                f"ECM binding index = {_safe(glyph.get('ECM_binding_index'),'.3f')} | "
                f"t½ waking = {_safe(glyph.get('t_half_waking_h'),'.1f')} h | "
                f"t90 clearance = {_safe(glyph.get('t90_clearance_h'),'.1f')} h | "
                f"{glyph.get('recommendation','')[:80]}", body))

        if micr and not micr.get("error"):
            story.append(Paragraph("14c. Microglial Activation & Neuroinflammation", h2))
            story.append(Paragraph(
                f"Neuroinflammation score = {_safe(micr.get('neuroinflammation_score'),'.3f')} | "
                f"Risk: {micr.get('risk_level','')} | "
                f"IL-6 fold-change = {_safe(micr.get('IL6_fold_change'),'.1f')}× | "
                f"TNF-α = {_safe(micr.get('TNFalpha_fold_change'),'.1f')}×", body))
            if micr.get("mitigations"):
                for m in micr["mitigations"][:3]:
                    story.append(Paragraph(f"→ {m}", body))

        if fus and not fus.get("error"):
            story.append(Paragraph("14d. FUS-Responsive Nanocarrier Design", h2))
            story.append(Paragraph(
                f"Frequency = {fus.get('freq_MHz','?')} MHz | "
                f"MI target = {_safe(fus.get('MI_target'),'.2f')} | "
                f"BBB open window = {_safe(fus.get('BBB_open_window_min'),'.0f')} min | "
                f"FUS uptake = {_safe(fus.get('carrier_FUS_uptake_pct'),'.1f')}% | "
                f"{fus.get('recommendation','')[:80]}", body))

        story.append(PageBreak())

        # ══════════════════════════════════════════════════════════════════════
        # SECTION 14e [v22]: 62-PRINCIPLE C+ FLOW SUMMARY
        # Surface ALL C+ Flow results — surrogate, deep, translational, fallback.
        # Per Muhammad's mandate: visible in EVERY output without exception.
        # ══════════════════════════════════════════════════════════════════════
        story.append(Paragraph("14e. 62-Principle C+ Flow — Class A Surrogate (Top-1 DDS)", h1))
        story.append(HRFlowable(width="100%", thickness=1, color=GOLD_RL))
        if dds_principle_breakdown:
            top1_brk = dds_principle_breakdown[0]
            story.append(Paragraph(
                f"<b>Top-1 DDS</b>: {top1_brk.get('dds_name','?')} &nbsp;&nbsp; "
                f"<b>Composite</b>: {top1_brk.get('composite',0):.1f}/100 &nbsp;&nbsp; "
                f"<b>Verdict</b>: {top1_brk.get('verdict','?')}", body))
            story.append(Paragraph(top1_brk.get("narrative",""), body))

            # CNS principle group rollups
            grp_data = [["CNS Group", "Score (0-100)"]]
            for g, s in top1_brk.get("group_scores", {}).items():
                grp_data.append([g.replace("_"," "), f"{s:.1f}"])
            story.append(Spacer(1, 0.3*cm))
            story.append(Paragraph("CNS Principle Group Rollups", h3))
            story.append(tbl(grp_data, [9*cm, 4*cm], TEAL))

            # Top strengths + weak spots
            story.append(Spacer(1, 0.3*cm))
            story.append(Paragraph("Top Strengths (Class A Surrogate)", h3))
            str_data = [["Principle", "Score", "Method", "Reference"]]
            for s in top1_brk.get("top_strengths", [])[:5]:
                str_data.append([s["principle"], f"{s['score']:.1f}",
                                  (s.get("method","") or "")[:50],
                                  (s.get("reference","") or "")[:35]])
            story.append(tbl(str_data, [2*cm, 2*cm, 7*cm, 5*cm], GREEN))

            story.append(Spacer(1, 0.3*cm))
            story.append(Paragraph("Weak Spots (Below 60)", h3))
            wk_data = [["Principle", "Score", "Method", "Reference"]]
            for w in top1_brk.get("weak_spots", [])[:5]:
                wk_data.append([w["principle"], f"{w['score']:.1f}",
                                 (w.get("method","") or "")[:50],
                                 (w.get("reference","") or "")[:35]])
            if len(wk_data) > 1:
                story.append(tbl(wk_data, [2*cm, 2*cm, 7*cm, 5*cm], RED_C))
            else:
                story.append(Paragraph("(no weak spots — all principles ≥60)", body))

            # ── FULL 62-PRINCIPLE SCOREBOARD (P01→P62) ──────────────────────
            # Merge all three pipeline stages into one ordered table.
            story.append(PageBreak())
            story.append(Paragraph(
                "14e-ii. Complete 62-Principle Scoreboard (P01 → P62)", h1))
            story.append(HRFlowable(width="100%", thickness=1, color=GOLD_RL))
            story.append(Paragraph(
                "All 62 principles in canonical order, covering "
                "<font color='#0D6E6E'>Class A (Surrogate)</font>, "
                "<font color='#7C4DFF'>Class B (Deep Physics)</font>, and "
                "<font color='#F57C00'>Class C (Translational)</font>.", body))
            story.append(Spacer(1, 0.3*cm))

            try:
                from cerebro_62_principles_catalog import PRINCIPLES_62 as _P62
            except Exception:
                _P62 = {}

            # Get surrogate data
            _surr = {}
            if dds_principle_matrix:
                _surr = dds_principle_matrix[0].get("principles", {})

            _class_labels = {
                "A_surrogate": "A", "B_deep": "B", "C_translational": "C"}

            full_data = [["P#", "Cls", "Title", "Score", "Conf.", "Method"]]
            for _i in range(1, 63):
                _pid = f"P{_i:02d}"
                _cat = _P62.get(_pid, {})
                _cls = _class_labels.get(_cat.get("class",""), "?")
                _title = _cat.get("title_en", "—")[:38]
                _sc = 0.0; _cf = "—"; _mt = ""

                if _pid in _surr:
                    _r = _surr[_pid]
                    _sc = _r.get("score", 0)
                    _cf = _r.get("confidence", "—")
                    _mt = (_r.get("method","") or "")[:50]
                elif deep_results and _pid in deep_results:
                    _r = deep_results[_pid]
                    _sc = _r.get("score", 0)
                    _cf = _r.get("confidence", "—")
                    _mt = (_r.get("method","") or "")[:50]
                elif translational and _pid in translational:
                    _r = translational[_pid]
                    _sc_raw = (_r.get("compliance_score")
                               or _r.get("fto_score")
                               or _r.get("patentability_score") or 0)
                    try: _sc = float(_sc_raw)
                    except (TypeError, ValueError): _sc = 0.0
                    _cf = "—"
                    _mt = (_r.get("status","") or "")[:50]

                full_data.append([
                    _pid, _cls, _title, f"{_sc:.1f}",
                    str(_cf)[:8], _mt])

            story.append(tbl(full_data,
                [1.3*cm, 1*cm, 5.5*cm, 1.5*cm, 1.5*cm, 6*cm], NAVY))
            story.append(Spacer(1, 0.2*cm))
            story.append(Paragraph(
                f"<i>62 principles evaluated. Composite: "
                f"{top1_brk.get('composite',0):.1f}/100 "
                f"({top1_brk.get('verdict','?')})</i>", note))
        else:
            story.append(Paragraph("(no surrogate breakdown available)", note))
        story.append(PageBreak())

        # ══════════════════════════════════════════════════════════════════════
        # SECTION 14f [v22]: CLASS B DEEP PHYSICS VALIDATION (Top-1)
        # ══════════════════════════════════════════════════════════════════════
        story.append(Paragraph("14f. Class B Deep Physics Validation (Top-1 DDS)", h1))
        story.append(HRFlowable(width="100%", thickness=1, color=GOLD_RL))
        if deep_summary:
            verdict = deep_summary.get("verdict","NOT RUN")
            verdict_color = {"PASSED":"#0D6E6E", "MARGINAL":"#F57C00",
                             "FAILED":"#C62828"}.get(verdict, "#0f2040")
            story.append(Paragraph(
                f"<b>Verdict</b>: <font color='{verdict_color}'>{verdict}</font> &nbsp;&nbsp; "
                f"<b>Pass rate</b>: {deep_summary.get('pct',0)}% "
                f"({deep_summary.get('passed_count',0)}/{deep_summary.get('total',0)} "
                f"principles validated, threshold 70%)", body))
            story.append(Paragraph(deep_summary.get("narrative",""), body))
        if deep_results:
            story.append(Spacer(1, 0.3*cm))
            story.append(Paragraph("Per-principle deep validation", h3))
            d_data = [["P#", "Validated", "Score", "Value", "Conf.", "Method"]]
            for pid, r in sorted(deep_results.items()):
                d_data.append([
                    pid,
                    "✓" if r.get("validated") else "✗",
                    f"{r.get('score',0):.1f}",
                    str(r.get("value",""))[:14],
                    r.get("confidence","")[:8],
                    (r.get("method","") or "")[:55],
                ])
            story.append(tbl(d_data, [1.3*cm, 1.7*cm, 1.5*cm, 2.2*cm, 1.7*cm, 8*cm], NAVY))
        else:
            story.append(Paragraph("(no deep validation results — Top-1 not yet validated)", note))
        story.append(PageBreak())

        # ══════════════════════════════════════════════════════════════════════
        # SECTION 14g [v22]: CLASS C TRANSLATIONAL DELIVERABLES
        # ══════════════════════════════════════════════════════════════════════
        story.append(Paragraph("14g. Class C Translational Deliverables", h1))
        story.append(HRFlowable(width="100%", thickness=1, color=GOLD_RL))
        if translational:
            t_data = [["Principle", "Title", "Status", "Score / Outcome"]]
            for pid, t in sorted(translational.items()):
                score = (t.get("compliance_score") or t.get("fto_score")
                          or t.get("patentability_score")
                          or t.get("recommendation","") or "—")
                t_data.append([pid,
                                (t.get("title","") or "")[:34],
                                (t.get("status","") or "")[:24],
                                str(score)[:24]])
            story.append(tbl(t_data, [2*cm, 7*cm, 4.5*cm, 4*cm], TEAL))
            story.append(Spacer(1, 0.3*cm))
            story.append(Paragraph("Narratives", h3))
            for pid, t in sorted(translational.items()):
                story.append(Paragraph(
                    f"<b>{pid}</b>: {(t.get('narrative','') or '—')[:300]}", body))
            story.append(Paragraph(
                "v23: structured outlines for Pre-IND, Grant, Patent will be "
                "rendered as fully formatted Word/PDF deliverables.", note))
        else:
            story.append(Paragraph(
                "(no translational deliverables — Top-1 may have failed deep validation)",
                note))
        story.append(PageBreak())

        # ══════════════════════════════════════════════════════════════════════
        # SECTION 14h [v22]: TOP-N FALLBACK AUDIT TRAIL
        # ══════════════════════════════════════════════════════════════════════
        story.append(Paragraph("14h. Top-N Fallback Audit Trail", h1))
        story.append(HRFlowable(width="100%", thickness=1, color=GOLD_RL))
        story.append(Paragraph(
            "If the Top-1 DDS fails deep validation (≥70% threshold), the "
            "orchestrator falls back to Top-2, then Top-3. Each candidate's "
            "outcome and the explicit transition reasoning are recorded below.",
            body))
        if fallback_chain:
            f_data = [["Rank", "DDS Name", "Verdict", "Pass %", "Promoted?"]]
            for entry in fallback_chain:
                f_data.append([
                    f"#{entry['rank']}",
                    entry["dds_name"][:24],
                    entry["verdict"],
                    f"{entry['deep_passed_pct']}%",
                    "✓ YES" if entry.get("promoted") else "—",
                ])
            story.append(tbl(f_data, [1.5*cm, 7*cm, 3*cm, 2.5*cm, 3.5*cm], NAVY))
            story.append(Spacer(1, 0.3*cm))
            for entry in fallback_chain:
                story.append(Paragraph(
                    f"<b>#{entry['rank']} {entry['dds_name']}</b> &mdash; {entry['verdict']}",
                    h3))
                story.append(Paragraph(
                    f"<b>Failure reason</b>: {entry.get('failure_reason','—')}", body))
                story.append(Paragraph(
                    f"<b>Transition reason</b>: {entry.get('transition_reason','—')}", body))
                if entry.get("failed_principles"):
                    fp_str = ", ".join(p["principle"] for p in entry["failed_principles"][:8])
                    story.append(Paragraph(
                        f"<b>Failed principles</b>: {fp_str}", body))
                story.append(Spacer(1, 0.15*cm))
        else:
            story.append(Paragraph("(no fallback chain — Top-1 passed on first attempt)", note))
        story.append(PageBreak())

        # ══════════════════════════════════════════════════════════════════════
        # SECTION 15: EXECUTIVE DECISION FRAMEWORK
        # ══════════════════════════════════════════════════════════════════════
        story.append(Paragraph("15. Executive Decision Framework", h1))
        story.append(HRFlowable(width="100%", thickness=1, color=GOLD_RL))

        # Summary decision table
        _clinical_go   = (synth.get("go_no_go","") == "GO" if synth else True)
        _dlvo_ok       = (top_dds.get("DLVO_stable") if top_dds else True)
        _no_cardiac    = not (qsar.get("cardiac_risk") if qsar else False)
        go_dec = "GO" if (_clinical_go and _dlvo_ok and _no_cardiac) else "CONDITIONAL GO"

        # Evidence text must reflect which criterion actually failed —
        # this previously hardcoded "Proceed to IND-enabling studies"
        # regardless of go_dec, so even a synthetic trial that explicitly
        # returned "NO-GO / REFORMULATE" (a real possible value from
        # cerebro_advanced_modules_2.py) still showed up in the executive
        # decision framework — the single most consequential section of
        # the report — recommending IND-enabling progression.
        if go_dec == "GO":
            _decision_evidence = "Proceed to IND-enabling studies"
        else:
            _failed = []
            if not _clinical_go:
                _failed.append(f"synthetic trial returned "
                                f"'{synth.get('go_no_go','?') if synth else '?'}'")
            if not _dlvo_ok:
                _failed.append("colloidal instability (DLVO)")
            if not _no_cardiac:
                _failed.append("cardiac off-target flag")
            _decision_evidence = ("Reformulate/re-evaluate before IND-enabling "
                                   f"studies — failed: {'; '.join(_failed) or 'see criteria above'}")

        decision_data = [
            ["Criterion",               "Status",  "Evidence"],
            ["DLVO colloidal stability", "PASS ✓" if (top_dds.get("DLVO_stable") if top_dds else False) else "FAIL ✗",
              f"V_total = {_safe(top_dds.get('DLVO_V_total_kT') if top_dds else None, '.0f')} kT"],
            ["BBB penetration >10%",    "PASS ✓" if float(top_dds.get("BBB_Enhanced_Pct",0) or 0) > 10 else "FAIL ✗",
              f"DDS BBB = {_safe(top_dds.get('BBB_Enhanced_Pct') if top_dds else None, '.1f')}%"],
            ["Cardiac off-target",      "PASS ✓" if not qsar.get("cardiac_risk") else "FLAG ⚠",
              "hERG/Nav/Cav QSAR"],
            ["Clinical trial GO",       synth.get("go_no_go","N/A") if synth else "N/A",
              f"Response {synth.get('overall_response_pct',0):.0f}% | AE {synth.get('AE_severe_pct',0):.1f}%" if synth else ""],
            ["Sterilization feasible",  f"{sterile.get('n_feasible',0) if sterile else 0} method(s)",
              sterile.get("recommended_method","N/A") if sterile else "N/A"],
            ["Supply chain",            sc.get("overall_supply_risk","N/A") if sc else "N/A",
              f"Score {sc.get('supply_chain_score',0):.0f}/100" if sc else ""],
            ["OVERALL DECISION",        go_dec, _decision_evidence],
        ]
        story.append(tbl(decision_data, [6*cm, 3.5*cm, 7*cm], NAVY))

        story.append(Spacer(1, 0.5*cm))
        story.append(Paragraph(
            "NOTE: All results are computational predictions. "
            "Required wet-lab validation: DLS/Zeta (physical stability), "
            "HPLC/NMR (drug content), BBB TEER assay, in vivo PK in rodent model.",
            note))
        story.append(Spacer(1, 0.2*cm))
        story.append(Paragraph(
            f"CEREBRO-X | Muhammad Talaat | "
            f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d')}", note))

        # ── Build PDF ─────────────────────────────────────────────────────────
        doc.build(story)
        size_kb = out_path.stat().st_size // 1024
        log.info(f"[PDF] Unified report: {out_path.name} ({size_kb} KB)")
        return out_path
