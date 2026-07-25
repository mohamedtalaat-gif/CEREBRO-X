"""
================================================================================
CEREBRO-X — Static Figures, Merged PDF, and Trial Documentation Writers
================================================================================
File: report_fallbacks.py

Extracted from run.py (was Sections 8, 9: "STATIC FIGURES", "MERGED PDF
REPORT") as part of splitting run.py's mixed responsibilities — see
docs/AUDIT_REPORT.md section 13.

These are the basic/fallback report generators (matplotlib PNGs + a single
merged reportlab PDF + plain-text trial documentation) — distinct from the
richer per-drug HTML5 dashboards and PDF reports generated elsewhere in the
pipeline (see engine/cerebro_html5_engine.py, src/core/final_report.py,
src/core/final_report_unified.py).
================================================================================
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from trial_manager import _excel_hash

log = logging.getLogger("CEREBRO-REPORTS")



def _make_static_figures(df_ml, df_dds, df_pk, trial_dir: Path) -> None:
    """Generate all static PNG figures for the trial."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figs = trial_dir / "figures"
    figs.mkdir(parents=True, exist_ok=True)

    # ── 1. BBB Score ranking bar chart ────────────────────────────────────
    if df_dds is not None and not df_dds.empty:
        top20 = df_dds.head(20).copy()
        fig, ax = plt.subplots(figsize=(12, 8))
        colours = ["#0D6E6E" if i == 0 else "#0f2040"
                   for i in range(len(top20))]
        bars = ax.barh(top20["Formulation_Name"].str[:28],
                       top20["BBB_Engineering_Score"],
                       color=colours[::-1], edgecolor="white", height=0.7)
        ax.set_xlim(0, 100)
        ax.axvline(75, color="#C9A84C", linestyle="--", lw=1.5,
                   label="Target score ≥ 75")
        ax.set_xlabel("BBB Engineering Score (0–100)", fontsize=11)
        ax.set_title("CEREBRO-X  |  DDS Formulation Rankings — Top 20",
                     fontweight="bold", fontsize=13)
        for bar, val in zip(bars, top20["BBB_Engineering_Score"].tolist()[::-1]):
            ax.text(val + 0.5, bar.get_y() + bar.get_height() / 2,
                    f"{val:.1f}", va="center", fontsize=8)
        ax.legend()
        ax.grid(True, axis="x", alpha=0.3)
        plt.tight_layout()
        fig.savefig(figs / "01_BBB_Score_Ranking.png", dpi=150)
        plt.close(fig)
        _write_fig_doc(figs / "01_BBB_Score_Ranking.png",
            "BBB Engineering Score ranking for top-20 DDS formulations.",
            "Formulations with score > 75 are candidates for in-vitro TEER validation.",
            "BBB Engineering Score = Pardridge 2012 multi-parameter function of "
            "size (60–100nm optimal), zeta (±5–15mV), PEGylation (2–7mol%), "
            "surface ligand affinity, encapsulation efficiency, P-gp escape, "
            "CARPA risk, and liver off-target penalty.")

    # ── 2. PK/PD concentration kinetics ──────────────────────────────────
    if df_pk is not None and not df_pk.empty and "Drug" in df_pk.columns:
        fig, ax = plt.subplots(figsize=(11, 6))
        for drug, grp in df_pk.groupby("Drug"):
            ax.plot(grp["Day"], grp["Concentration_Pct"],
                    label=drug, lw=2.5)
        ax.axhline(50, color="red", ls="--", lw=1.5, label="50% threshold")
        ax.fill_between(df_pk["Day"].unique(), 50, 100,
                        color="green", alpha=0.05)
        ax.set_xlabel("Days Post-Administration")
        ax.set_ylabel("Brain Concentration (%)")
        ax.set_title("Brain PK/PD Concentration Kinetics",
                     fontweight="bold")
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        fig.savefig(figs / "02_PKPD_Kinetics.png", dpi=150)
        plt.close(fig)
        _write_fig_doc(figs / "02_PKPD_Kinetics.png",
            "Brain drug concentration kinetics for all candidates.",
            "Candidate with longest time above 50% threshold requires fewest re-doses.",
            "C(t) = C₀·e^(−kt), k=ln2/t½, C₀=100·(150kDa/MW_Da). "
            "One-compartment first-order model (Rowland & Tozer 2011).")

    # ── 3. ADMET overview ─────────────────────────────────────────────────
    if df_ml is not None and not df_ml.empty and "ADMET_Overall_Flag" in df_ml.columns:
        counts = df_ml["ADMET_Overall_Flag"].value_counts()
        fig, ax = plt.subplots(figsize=(6, 5))
        ax.pie(counts.values, labels=counts.index,
               colors=["#0D6E6E","#F57C00"],
               autopct="%1.0f%%", startangle=90)
        ax.set_title("ADMET Screening Summary", fontweight="bold")
        plt.tight_layout()
        fig.savefig(figs / "03_ADMET_Summary.png", dpi=150)
        plt.close(fig)

    # ── 4. Carrier type distribution ──────────────────────────────────────
    if df_dds is not None and "Carrier_Type" in df_dds.columns:
        ct_avg = (df_dds.groupby("Carrier_Type")["BBB_Engineering_Score"]
                  .mean().sort_values(ascending=False))
        fig, ax = plt.subplots(figsize=(9, 5))
        ct_avg.plot.bar(ax=ax, color="#0f2040", edgecolor="white")
        ax.set_ylabel("Mean BBB Score")
        ax.set_title("Mean BBB Score by Carrier Type", fontweight="bold")
        ax.tick_params(axis="x", rotation=30)
        ax.grid(True, axis="y", alpha=0.3)
        plt.tight_layout()
        fig.savefig(figs / "04_Carrier_Type_Comparison.png", dpi=150)
        plt.close(fig)
        _write_fig_doc(figs / "04_Carrier_Type_Comparison.png",
            "Mean BBB Engineering Score by carrier type.",
            "Carrier type with highest mean score is the recommended platform.",
            "Grouped mean of individual formulation scores within each carrier category.")

    # ── 5. Zeta vs BBB scatter ────────────────────────────────────────────
    if df_dds is not None and "zeta_potential_mv" in df_dds.columns:
        fig, ax = plt.subplots(figsize=(8, 6))
        sc = ax.scatter(df_dds["zeta_potential_mv"],
                        df_dds["BBB_Engineering_Score"],
                        c=df_dds["size_nm"], cmap="viridis",
                        s=60, alpha=0.7, edgecolors="white", lw=0.5)
        plt.colorbar(sc, ax=ax, label="Size (nm)")
        ax.set_xlabel("Zeta Potential (mV)")
        ax.set_ylabel("BBB Engineering Score")
        ax.set_title("Zeta Potential vs. BBB Score (colour = size)",
                     fontweight="bold")
        ax.axvline(-15, color="gold", ls="--", lw=1, alpha=0.7)
        ax.axvline(-5, color="gold", ls="--", lw=1, alpha=0.7,
                   label="Optimal zeta zone")
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        fig.savefig(figs / "05_Zeta_vs_BBB.png", dpi=150)
        plt.close(fig)

    log.info(f"[FIGURES] Saved to {figs}")


def _write_fig_doc(path: Path, overview: str,
                   decision: str, science: str) -> None:
    """Write _DOCUMENTATION.txt for a figure file."""
    sep = "=" * 70
    txt = (f"{sep}\n  CEREBRO-X |  FILE DOCUMENTATION\n"
           f"  File      : {path.name}\n"
           f"  Generated : {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}\n"
           f"{sep}\n\n"
           f"{'─'*70}\n  OVERVIEW\n{'─'*70}\n{overview}\n\n"
           f"{'─'*70}\n  STRATEGIC DECISION\n{'─'*70}\n{decision}\n\n"
           f"{'─'*70}\n  THEORETICAL & PRACTICAL SCIENCE\n{'─'*70}\n{science}\n\n"
           f"{sep}\n")
    (str(path) + "_DOCUMENTATION.txt").replace("//", "/")
    with open(str(path) + "_DOCUMENTATION.txt", "w", encoding="utf-8") as f:
        f.write(txt)


# ─────────────────────────────────────────────────────────────────────────────
# 9.  MERGED PDF REPORT  (decision-ready — in-memory → file)
# ─────────────────────────────────────────────────────────────────────────────

def _generate_merged_pdf(df_ml, df_dds, df_pk, metrics: dict,
                          mol_profile: dict, trial_dir: Path,
                          drug_name: str) -> None:
    """
    Generate a single decision-ready PDF combining:
      - Executive summary + drug profile
      - ML metrics table
      - Top-10 DDS formulations table
      - All static PNG figures
      - ADMET summary
      - PK/PD kinetics
      - Strategic recommendation
    """
    try:
        import base64
        import io

        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            HRFlowable,
            PageBreak,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
        from reportlab.platypus import Image as RLImage
    except ImportError:
        log.warning("[PDF] reportlab not installed — PDF skipped")
        return

    pdf_path = trial_dir / f"CEREBRO_X_Report_{drug_name}.pdf"
    doc      = SimpleDocTemplate(str(pdf_path), pagesize=A4,
                                  leftMargin=2*cm, rightMargin=2*cm,
                                  topMargin=2*cm, bottomMargin=2*cm)
    styles   = getSampleStyleSheet()

    C_NAVY   = colors.HexColor("#0f2040")   # void panel — for backgrounds
    C_TEAL   = colors.HexColor("#0D6E6E")   # neuro-positive — section divider, success
    C_GOLD   = colors.HexColor("#C9A84C")   # signature gold — TITLES & primary accent
    C_ORANGE = colors.HexColor("#F57C00")   # molecule orange — small-molecule tagging

    # Brand spec: titles in GOLD, section H1 in GOLD (light-tracked),
    # H2/body in dark text. Navy is panel background, not title fill.
    title_s  = ParagraphStyle("T", parent=styles["Title"],
                               fontSize=22, textColor=C_GOLD, spaceAfter=6,
                               fontName="Helvetica-Bold")
    h1_s     = ParagraphStyle("H1", parent=styles["Heading1"],
                               fontSize=13, textColor=C_GOLD, spaceAfter=4,
                               fontName="Helvetica-Bold")
    h2_s     = ParagraphStyle("H2", parent=styles["Heading2"],
                               fontSize=11, textColor=C_TEAL, spaceAfter=3,
                               fontName="Helvetica-Bold")
    body_s   = ParagraphStyle("B", parent=styles["Normal"],
                               fontSize=9, leading=13, spaceAfter=3)
    note_s   = ParagraphStyle("N", parent=styles["Normal"],
                               fontSize=8, textColor=colors.grey,
                               leftIndent=15, spaceAfter=3)
    bold_s   = ParagraphStyle("Bo", parent=styles["Normal"],
                               fontSize=10, fontName="Helvetica-Bold",
                               textColor=C_NAVY, spaceAfter=4)

    def tbl(data, col_widths=None, header_bg=C_NAVY):
        t = Table(data, colWidths=col_widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), header_bg),
            ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
            ("FONTNAME",   (0,0), (-1,-1), "Helvetica"),
            ("FONTSIZE",   (0,0), (-1,-1), 8),
            ("ROWBACKGROUNDS", (0,1),(-1,-1),
             [colors.HexColor("#F5F5F5"), colors.white]),
            ("GRID", (0,0),(-1,-1), 0.3, colors.lightgrey),
            ("LEFTPADDING",(0,0),(-1,-1), 5),
            ("TOPPADDING", (0,0),(-1,-1), 3),
            ("BOTTOMPADDING",(0,0),(-1,-1), 3),
        ]))
        return t

    story = []
    ts = datetime.now().strftime("%Y-%m-%d  %H:%M")

    # ── Cover ─────────────────────────────────────────────────────────────
    story.append(Paragraph("CEREBRO-X", title_s))
    story.append(Paragraph("Brain Drug Delivery Analysis Report", h1_s))
    story.append(HRFlowable(width="100%", thickness=2, color=C_TEAL))
    story.append(Spacer(1, 0.3*cm))

    cover_data = [
        ["Drug / Candidate",    drug_name],
        ["Trial Folder",        trial_dir.name],
        ["Generated",           ts],
        ["Formulations Scored", str(len(df_dds) if df_dds is not None else "N/A")],
        ["ML R²",               f"{metrics.get('r2',0):.4f}"],
        ["ML RMSE",             f"{metrics.get('rmse',0):.4f}"],
        ["K-Fold CV R²",        f"{metrics.get('cv_r2',0):.4f} ± {metrics.get('cv_std',0):.4f}"],
        ["Drug MW (Da)",        str(mol_profile.get("MW_Da","N/A"))],
        ["Drug LogP",           str(mol_profile.get("LogP","N/A"))],
        ["Half-Life (days)",    str(mol_profile.get("Half_Life_Days","N/A"))],
        ["BBB Permeability %",  str(mol_profile.get("BBB_permeability_pct","N/A"))],
        ["Data Source",         str(mol_profile.get("_source","cascade"))],
    ]
    story.append(tbl(cover_data, col_widths=[7*cm, 10*cm],
                     header_bg=C_TEAL))
    story.append(Spacer(1, 0.5*cm))

    # ── Executive Recommendation ──────────────────────────────────────────
    story.append(Paragraph("Executive Recommendation", h1_s))
    if df_dds is not None and not df_dds.empty:
        top1 = df_dds.iloc[0]
        top3 = df_dds.head(3)
        rec_text = (
            f"<b>Recommended Carrier:</b> {top1.get('Formulation_Name','')}<br/>"
            f"<b>Carrier Type:</b> {top1.get('Carrier_Type','')}<br/>"
            f"<b>BBB Engineering Score:</b> {top1.get('BBB_Engineering_Score',0):.1f}/100<br/>"
            f"<b>Size:</b> {top1.get('size_nm','')} nm  |  "
            f"<b>Zeta:</b> {top1.get('zeta_potential_mv','')} mV  |  "
            f"<b>EE%:</b> {top1.get('encapsulation_efficiency_pct','')}%<br/>"
            f"<b>ADMET Flag:</b> {top1.get('ADMET_Overall_Flag','')}<br/>"
            f"<b>Surface Ligand:</b> {top1.get('Surface_Ligand','')}"
        )
        story.append(Paragraph(rec_text, body_s))
        story.append(Spacer(1, 0.2*cm))
        story.append(Paragraph(
            "Decision basis: BBB Engineering Score (0–100) combines size optimality "
            "(60–100 nm target), zeta stability (±5–15 mV), PEGylation stealth, "
            "surface ligand receptor affinity, encapsulation efficiency, P-gp evasion, "
            "CARPA immunogenicity risk, and liver off-target penalty. "
            "Formulations scoring > 75 with ADMET=OK proceed to in-vitro BBB model "
            "(TEER assay) and then in-vivo PK study.", note_s))

    story.append(PageBreak())

    # ── Top-10 DDS Table ──────────────────────────────────────────────────
    story.append(Paragraph("Top 10 DDS Formulations", h1_s))
    if df_dds is not None and not df_dds.empty:
        SHOW_COLS = ["Rank","Formulation_ID","Formulation_Name","Carrier_Type",
                     "BBB_Engineering_Score","ADMET_Overall_Flag",
                     "size_nm","zeta_potential_mv",
                     "encapsulation_efficiency_pct","Surface_Ligand"]
        top10 = df_dds.head(10)[[c for c in SHOW_COLS if c in df_dds.columns]]
        col_w = [1.2*cm,1.8*cm,4.0*cm,3.0*cm,1.8*cm,2.0*cm,
                 1.4*cm,1.5*cm,1.8*cm,2.5*cm][:len(top10.columns)]
        t_data = [list(top10.columns)]
        for _, row in top10.iterrows():
            t_data.append([str(round(v, 2) if isinstance(v, float) else v)
                           for v in row.values])
        story.append(tbl(t_data, col_widths=col_w))
        story.append(Spacer(1, 0.3*cm))

    # ── All 100 formulations ──────────────────────────────────────────────
    story.append(Paragraph("Complete Formulation Rankings (all 100)", h1_s))
    if df_dds is not None and not df_dds.empty:
        COLS2 = ["Rank","Formulation_ID","Carrier_Type","BBB_Engineering_Score",
                 "ADMET_Overall_Flag","surface_ligand" if "surface_ligand" in df_dds.columns
                 else "Surface_Ligand"]
        avail2 = [c for c in ["Rank","Formulation_ID","Formulation_Name",
                               "Carrier_Type","BBB_Engineering_Score",
                               "ADMET_Overall_Flag"] if c in df_dds.columns]
        cw2 = [1.0*cm, 2.0*cm, 4.5*cm, 3.0*cm, 2.2*cm, 2.0*cm][:len(avail2)]
        t2_data = [avail2]
        for _, row in df_dds[avail2].iterrows():
            t2_data.append([str(round(v,2) if isinstance(v,float) else v)
                            for v in row.values])
        story.append(tbl(t2_data, col_widths=cw2))

    story.append(PageBreak())

    # ── ML Metrics ────────────────────────────────────────────────────────
    story.append(Paragraph("Machine Learning Evaluation", h1_s))
    # Format ML metrics — show N/A for NaN/None, not 0.0000
    def _fmt_metric(v, decimals=4):
        """Format numeric metric; return 'N/A' if None, nan, or invalid."""
        import math
        if v is None: return "N/A"
        try:
            f = float(v)
            if math.isnan(f) or math.isinf(f): return "N/A"
            return f"{f:.{decimals}f}"
        except (TypeError, ValueError): return "N/A"

    n_samp  = metrics.get("n_samples", "?")
    is_synth= int(n_samp) > 1 if str(n_samp).isdigit() else False
    cv_note = ("N/A — insufficient samples for cross-validation"
               if _fmt_metric(metrics.get("cv_r2")) == "N/A"
               else f"{_fmt_metric(metrics.get('cv_r2'))} ± "
                    f"{_fmt_metric(metrics.get('cv_std'))}")

    ml_data = [
        ["Metric", "Value", "Notes"],
        ["Train R²",    _fmt_metric(metrics.get("r2")),
         "Variance explained on training set (1.0=perfect)"],
        ["Train RMSE",  _fmt_metric(metrics.get("rmse")),
         "Root mean squared error (lower=better)"],
        ["Train MAE",   _fmt_metric(metrics.get("mae")),
         "Mean absolute error"],
        ["K-Fold CV R²",cv_note,
         f"Generalisation (≥6 samples needed; n={n_samp})"],
        ["N samples",   str(n_samp),
         "Rows used for training" + (" (includes synthetic augmentation)" if is_synth else "")],
        ["Data source",
         metrics.get("_source","CascadeDataEngine → API cascade"),
         "Where training data originated"],
    ]
    story.append(tbl(ml_data, col_widths=[4*cm, 4*cm, 9*cm]))
    story.append(Spacer(1, 0.2*cm))
    story.append(Paragraph(
        "Model: Ensemble VotingRegressor (RF + GBR + SVR + XGBoost). "
        "Scaler: TrainAwareScaler (fit on train only → transform for inference — "
        "leakage-free). K-Fold CV R² > 0.7 = deployment-ready. "
        "SHAP XAI feature importances saved in models/shap_feature_importance.csv.", note_s))

    story.append(PageBreak())

    # ── Figures ───────────────────────────────────────────────────────────
    story.append(Paragraph("Visualisations", h1_s))
    figs_dir = trial_dir / "figures"
    fig_files = sorted(figs_dir.glob("*.png")) if figs_dir.exists() else []
    for fp in fig_files:
        if "_DOCUMENTATION" in fp.name:
            continue
        try:
            img = RLImage(str(fp), width=15*cm, height=9*cm)
            story.append(Paragraph(fp.stem.replace("_"," ").title(), h2_s))
            story.append(img)
            story.append(Spacer(1, 0.3*cm))
        except Exception as _exc_silenced:
            # FIXED: was silent — now logged
            import logging as _elog
            _elog.getLogger("CEREBRO").warning(f"[SUPPRESSED] {_exc_silenced!r} — in run.py")
            del _exc_silenced

    story.append(PageBreak())

    # ── Drug Profile ──────────────────────────────────────────────────────
    story.append(Paragraph("Drug Profile", h1_s))
    dp_data = [["Property","Value"]]
    for k, v in mol_profile.items():
        if k.startswith("_") or v is None:
            continue
        if isinstance(v, dict):
            v = str(v)
        dp_data.append([str(k), str(v)[:80]])
    if len(dp_data) > 1:
        story.append(tbl(dp_data, col_widths=[7*cm, 10*cm]))

    story.append(PageBreak())

    # ── Science background ────────────────────────────────────────────────
    story.append(Paragraph("Scientific Methodology", h1_s))
    sci_paras = [
        ("BBB Engineering Score",
         "Computed from Pardridge 2012 multi-parameter framework. Baseline 50. "
         "Size bonus: up to +20 for 60–100 nm (optimal caveolae-mediated transcytosis). "
         "Zeta bonus: up to +15 for ±5–15 mV (Debye stability without opsonisation). "
         "PEG bonus: up to +10 for 2–7 mol% (stealth without blocking ligand–receptor docking). "
         "Ligand bonus: +20 RVG29, +22 ApoE3, +18 Angiopep-2, +16 Transferrin. "
         "Density Goldilocks zone 0.5–1.5/nm²: +8. EE ≥ 80%: +8. "
         "P-gp evasion: ±10. Tm penalty: −20 if Tm ≤ 37°C. "
         "CARPA penalty: up to −15. Liver penalty: −0.15 per % above 20%."),
        ("Molecule Engine",
         "Accepts SMILES → RDKit+PubChem, FASTA → BioPython+UniProt, "
         "PDB ID → RCSB PDB, HELM → Pistoia Alliance, InChIKey → PubChem, "
         "Drug Name → 5-Tier Cascade (DrugBank→ChEMBL→UniProt→PubChem→PubMed). "
         "All properties fetched live — no synthetic defaults."),
        ("Data Integrity",
         "Strict Rejection: any drug record missing MW or Half-Life is excluded "
         "from ML training (logged to Missing_Data_Log.txt). "
         "IterativeImputer (ExtraTreesRegressor) is used ONLY for secondary "
         "formulation parameters — never for core drug identity fields. "
         "Every imputed field is documented in the output CSV."),
        ("ML Architecture",
         "VotingRegressor ensemble: RF (n=200, max_depth=8) + GBR (n=150, lr=0.05) "
         "+ SVR (RBF kernel, C=10) + XGBoost (n=150, lr=0.05). "
         "K-Fold CV (k=5, shuffle). GridSearchCV HPT on RF. "
         "TrainAwareScaler: fit ONCE on training predictions only — "
         "new molecules use .transform() to prevent data leakage. "
         "SHAP TreeExplainer for XAI. Model saved as .pkl with scaler state."),
        ("PK/PD Model",
         "One-compartment first-order model: C(t) = C₀·e^(−kt), "
         "k = ln2/t½, C₀ = 100·(150kDa/MW_Da). "
         "Time range 0–60 days, 500 points. "
         "Reference: van Dyck et al. NEJM 2023 (lecanemab CSF PK)."),
        ("Trial Versioning",
         "Each new or modified Excel file is hashed (SHA-256). "
         "Unknown hash → new Trial_N directory. All outputs are isolated. "
         "trial_index.db records hash, drug, timestamp, output path. "
         "Cache is invalidated per trial — no stale data can contaminate results."),
    ]
    for title, text in sci_paras:
        story.append(Paragraph(title, h2_s))
        story.append(Paragraph(text, body_s))
        story.append(Spacer(1, 0.15*cm))

    story.append(PageBreak())

    # ── Recommendations ───────────────────────────────────────────────────
    story.append(Paragraph("Decision Framework", h1_s))
    if df_dds is not None and not df_dds.empty:
        ok   = df_dds[df_dds.get("ADMET_Overall_Flag","OK") == "OK"] if "ADMET_Overall_Flag" in df_dds.columns else df_dds
        high = ok[ok["BBB_Engineering_Score"] >= 75] if "BBB_Engineering_Score" in ok.columns else ok.head(5)
        story.append(Paragraph(
            f"{len(high)} formulations scored ≥ 75 and passed ADMET screening. "
            f"These are recommended for in-vitro BBB model (TEER assay) validation. "
            f"The top candidate ({df_dds.iloc[0].get('Formulation_Name','')}) "
            f"with BBB score {df_dds.iloc[0].get('BBB_Engineering_Score',0):.1f} "
            f"represents the primary recommendation for wet-lab synthesis.", body_s))

        decision_data = [["Gate", "Criterion", "Pass Count", "Action"]]
        for gate, criterion, col, threshold, action in [
            ("BBB ≥ 75",    "BBB_Engineering_Score",    "BBB_Engineering_Score", 75,
             "In-vitro TEER assay"),
            ("ADMET OK",    "ADMET_Overall_Flag",       "ADMET_Overall_Flag",    None,
             "Advance to animal PK"),
            ("Liver < 30%", "Off_Target_Liver_pct",     "Off_Target_Liver_pct",  30,
             "Safe hepatic profile"),
            ("CARPA < 0.4", "CARPA_Risk_Index",         "CARPA_Risk_Index",      0.4,
             "Low complement risk"),
        ]:
            if col not in df_dds.columns:
                continue
            if threshold is None:
                n = (df_dds[col] == "OK").sum()
            elif col in ["Off_Target_Liver_pct"] or col in ["CARPA_Risk_Index"]:
                n = (df_dds[col] <= threshold).sum()
            else:
                n = (df_dds[col] >= threshold).sum()
            decision_data.append([gate, criterion, str(n), action])
        story.append(tbl(decision_data, col_widths=[3*cm, 5*cm, 3*cm, 6*cm]))

    doc.build(story)
    log.info(f"[PDF] Report → {pdf_path}")
    _write_pdf_doc(pdf_path, drug_name)


def _write_pdf_doc(path: Path, drug_name: str) -> None:
    sep = "=" * 70
    txt = (f"{sep}\n  CEREBRO-X |  FILE DOCUMENTATION\n"
           f"  File      : {path.name}\n"
           f"  Generated : {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}\n"
           f"{sep}\n\n"
           f"{'─'*70}\n  OVERVIEW\n{'─'*70}\n"
           f"Decision-ready PDF report for {drug_name} BBB drug delivery analysis.\n\n"
           f"Contents:\n"
           f"  1. Cover / Executive Summary\n"
           f"  2. Executive Recommendation (top formulation)\n"
           f"  3. Top-10 DDS Formulations table\n"
           f"  4. All 100 formulations ranked\n"
           f"  5. ML Evaluation metrics\n"
           f"  6. All static PNG visualisations\n"
           f"  7. Drug molecular profile\n"
           f"  8. Scientific methodology documentation\n"
           f"  9. Decision framework (gates + pass counts)\n\n"
           f"{'─'*70}\n  HOW TO USE THIS REPORT\n{'─'*70}\n"
           f"  1. Read 'Executive Recommendation' — single best carrier system.\n"
           f"  2. Check 'Decision Framework' table — how many systems pass each gate.\n"
           f"  3. Formulations with BBB_Score >= 75 AND ADMET=OK go to wet-lab.\n"
           f"  4. Full CSV data in dds_analysis/formulation_ranking.csv\n"
           f"{sep}\n")
    with open(str(path) + "_DOCUMENTATION.txt", "w", encoding="utf-8") as f:
        f.write(txt)


def _write_dds_doc(path: Path, drug_name: str, n: int) -> None:
    sep = "=" * 70
    txt = (f"{sep}\n  CEREBRO-X |  FILE DOCUMENTATION\n"
           f"  File      : {path.name}\n"
           f"  Generated : {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}\n"
           f"{sep}\n\n"
           f"{'─'*70}\n  OVERVIEW\n{'─'*70}\n"
           f"Complete ranking of {n} DDS formulations for {drug_name} BBB delivery,\n"
           f"scored by CEREBRO-X BBB Engineering Score (0–100).\n\n"
           f"{'─'*70}\n  SCORING FORMULA\n{'─'*70}\n"
           f"Score = 50 (baseline)\n"
           f"  + size_bonus     (max +20 for 60–100 nm)\n"
           f"  + zeta_bonus     (max +15 for ±5–15 mV)\n"
           f"  + peg_bonus      (max +10 for 2–7 mol%)\n"
           f"  + ligand_bonus   (RVG29 +20, ApoE3 +22, Angiopep-2 +18)\n"
           f"  + density_bonus  (+8 for 0.5–1.5 per nm²)\n"
           f"  + EE_bonus       (+8 for EE ≥ 80%)\n"
           f"  + pgp_escape     (±10)\n"
           f"  − Tm_penalty     (−20 if Tm ≤ 37°C)\n"
           f"  − CARPA_penalty  (max −15)\n"
           f"  − liver_penalty  (−0.15 per % above 20%)\n\n"
           f"{'─'*70}\n  STRATEGIC DECISION\n{'─'*70}\n"
           f"Formulations with BBB_Score > 75 AND ADMET=OK → in-vitro TEER assay.\n"
           f"Top-3 → wet-lab vexosome/LNP preparation and BBB-on-chip testing.\n"
           f"{sep}\n")
    with open(str(path) + "_DOCUMENTATION.txt", "w", encoding="utf-8") as f:
        f.write(txt)


def _write_trial_doc(trial_dir: Path, excel_path: Path,
                      drug_name: str, n_forms: int,
                      metrics: dict, df_dds) -> None:
    """Write a comprehensive documentation file for the entire trial."""
    top = df_dds.iloc[0] if (df_dds is not None and not df_dds.empty) else {}
    sep = "=" * 70
    txt = (f"{sep}\n"
           f"  CEREBRO-X |  TRIAL DOCUMENTATION\n"
           f"  Trial     : {trial_dir.name}\n"
           f"  Generated : {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}\n"
           f"{sep}\n\n"
           f"{'─'*70}\n  INPUT\n{'─'*70}\n"
           f"  Excel file  : {excel_path.name}\n"
           f"  Excel hash  : {_excel_hash(excel_path)[:16]}...\n"
           f"  Drug        : {drug_name}\n"
           f"  Formulations: {n_forms}\n\n"
           f"{'─'*70}\n  ML RESULTS\n{'─'*70}\n"
           f"  Train R²  : {metrics.get('r2',0):.4f}\n"
           f"  RMSE      : {metrics.get('rmse',0):.4f}\n"
           f"  MAE       : {metrics.get('mae',0):.4f}\n"
           f"  K-Fold R² : {metrics.get('cv_r2',0):.4f} ± {metrics.get('cv_std',0):.4f}\n"
           f"  N samples : {metrics.get('n_samples','N/A')}\n\n"
           f"{'─'*70}\n  TOP RECOMMENDATION\n{'─'*70}\n"
           f"  #{top.get('Rank',1)}  {top.get('Formulation_Name','')}\n"
           f"  BBB Score : {top.get('BBB_Engineering_Score',0):.1f}/100\n"
           f"  ADMET     : {top.get('ADMET_Overall_Flag','')}\n\n"
           f"{'─'*70}\n  OUTPUT FILES\n{'─'*70}\n"
           f"  dds_analysis/formulation_ranking.csv  — all {n_forms} systems ranked\n"
           f"  dds_analysis/top10_formulations.csv   — shortlist\n"
           f"  dds_config.yaml                        — converted from Excel\n"
           f"  figures/*.png                          — static visualisations\n"
           f"  CEREBRO_X_Report_{drug_name}.pdf       — merged decision report\n"
           f"  trial_index.db                         — (root) trial registry\n\n"
           f"{'─'*70}\n  REPRODUCIBILITY\n{'─'*70}\n"
           f"  To reproduce this exact trial:\n"
           f"  1. Place the same Excel file (same content) in SCRIPT_DIR\n"
           f"  2. Delete its entry from outputs/trial_index.db\n"
           f"  3. python run.py --pipeline-only\n\n"
           f"{sep}\n")
    with open(trial_dir / "TRIAL_DOCUMENTATION.txt", "w", encoding="utf-8") as f:
        f.write(txt)

    log.info(f"[DOC] Trial documentation → {trial_dir / 'TRIAL_DOCUMENTATION.txt'}")

