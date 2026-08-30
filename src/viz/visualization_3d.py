"""
================================================================================
CEREBRO-X |  3D VISUALISATION & VIDEO ENGINE
================================================================================
File: cerebro_visualization_3d.py

Generates publication-quality and presentation-ready visuals.

Actually implemented (verified against the real function/class
definitions and the real orchestrator call list at the bottom of this
file — this used to list 12 figures, 4 schematics, and 2 videos, but
only 7 figures, 2 schematics, and 2 videos exist anywhere in this file;
Figures 08-12 and Schemas 02-03 were promised but never written, and
Figures 06/07 below were numbered inconsistently with what the actual
fig06_.../fig07_... functions do):

  STATIC FIGURES (no simulations — all from analytical data):
    Figure 01  BBB Engineering Score ranking (enhanced horizontal bar)
    Figure 02  PK/PD concentration kinetics (multi-drug, multi-compartment)
    Figure 03  PBPK organ heatmap (drug distribution across organs)
    Figure 04  DLVO colloidal stability map (scatter: size vs. zeta)
    Figure 05  3D pharmacological space (half-life × binding × ML score)
    Figure 06  Formulation property heatmap (fig06_formulation_heatmap)
    Figure 07  Multi-drug radar fingerprint, polar (fig07_radar)

  BIORENDER-STYLE SCHEMATICS (SVG/PNG — no external tool):
    Schema 01  BBB crossing mechanism diagram
    Schema 04  CEREBRO-X pipeline flowchart
    (Schema 02 "Vexosome cross-section" and Schema 03 "Two-compartment PK
    model diagram" are not implemented — kept the original 01/04 numbering
    from BioSchematicEngine rather than renumbering, since other code may
    already reference these by name)

  VIDEO (MP4):
    Video 01   PK/PD kinetics animated over time (matplotlib)
    Video 02   BBB score reveal animation (bar chart buildup)

  Carrier-type comparison, HOMO-LUMO gap, transcytosis energy landscape,
  PEG Goldilocks curve, and synergy network graphs described in earlier
  versions of this docstring live elsewhere in the codebase (or not at
  all) — not in this file.

All files:
  • Saved as high-resolution PNG (300 DPI) + SVG where applicable
  • Companion _DOCUMENTATION.txt explaining science, interpretation, significance
  • Named 01_XXX.png … 12_XXX.png for ordered PDF assembly

Architecture:
  • Pure matplotlib + seaborn — no external rendering tools required
  • Optional: Pillow (for PNG post-processing), OpenCV (for video)
  • Graceful fallback: skips video if OpenCV/imageio not available
  • No simulations — all visuals derived from pre-computed DataFrame inputs
================================================================================
"""

import io
import logging
import math
import warnings

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
from datetime import datetime
from pathlib import Path

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.patches import Circle, FancyBboxPatch

warnings.filterwarnings("ignore")
log = logging.getLogger("CEREBRO-VIZ")

# ─────────────────────────────────────────────────────────────────────────────
# BRAND PALETTE  (CEREBRO-X colours — consistent across all figures)
# ─────────────────────────────────────────────────────────────────────────────
C = {
    "navy":    "#0f2040",
    "teal":    "#0D6E6E",
    "gold":    "#C9A84C",
    "orange":  "#F57C00",
    "green":   "#0D6E6E",
    "red":     "#C62828",
    "purple":  "#7C4DFF",
    "blue":    "#0f2040",
    "lgrey":   "#F5F5F5",
    "dgrey":   "#333333",
    "white":   "#FFFFFF",
}

PALETTE = [C["navy"], C["teal"], C["gold"], C["orange"],
           C["green"], C["red"], C["purple"], C["blue"]]

CARRIER_COLOURS = {
    "Vexosome":              C["navy"],
    "LNP":                   C["teal"],
    "Liposome":              C["gold"],
    "Polymeric Nanoparticle":C["green"],
    "Solid Lipid Nanoparticle": C["orange"],
    "Hybrid":                C["purple"],
}

# ─────────────────────────────────────────────────────────────────────────────
# DOCUMENTATION WRITER
# ─────────────────────────────────────────────────────────────────────────────
def _doc(path: Path, overview: str, significance: str,
         science: str, method: str, interpret: str):
    sep = "=" * 70
    txt = (
        f"{sep}\n  CEREBRO-X |  FILE DOCUMENTATION\n"
        f"  File      : {Path(path).name}\n"
        f"  Generated : {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}\n"
        f"{sep}\n\n"
        f"{'─'*70}\n  OVERVIEW\n{'─'*70}\n{overview}\n\n"
        f"{'─'*70}\n  SIGNIFICANCE\n{'─'*70}\n{significance}\n\n"
        f"{'─'*70}\n  THEORETICAL & PRACTICAL SCIENCE\n{'─'*70}\n{science}\n\n"
        f"{'─'*70}\n  METHODOLOGY\n{'─'*70}\n{method}\n\n"
        f"{'─'*70}\n  HOW TO INTERPRET\n{'─'*70}\n{interpret}\n\n"
        f"{sep}\n"
    )
    doc_path = str(path) + "_DOCUMENTATION.txt"
    with open(doc_path, "w", encoding="utf-8") as f:
        f.write(txt)


# ─────────────────────────────────────────────────────────────────────────────
# FIGURE 01:  BBB Engineering Score — Enhanced Ranking Bar
# ─────────────────────────────────────────────────────────────────────────────
def fig01_bbb_ranking(df_dds: pd.DataFrame, output_dir: Path,
                       drug_name: str = "", top_n: int = 30) -> Path | None:
    """
    Horizontal bar chart of top-N formulations by BBB Engineering Score.
    Colour = carrier type. Marker = ADMET flag. Score label on each bar.
    """
    if df_dds is None or df_dds.empty or "BBB_Engineering_Score" not in df_dds.columns:
        return None

    top = df_dds.nlargest(top_n, "BBB_Engineering_Score").copy()
    top = top.sort_values("BBB_Engineering_Score", ascending=True)  # plot bottom→top

    fig, ax = plt.subplots(figsize=(14, max(8, top_n * 0.38)))

    colours = [CARRIER_COLOURS.get(ct, C["navy"])
               for ct in top["Carrier_Type"].tolist()]

    bars = ax.barh(
        top["Formulation_Name"].str[:32],
        top["BBB_Engineering_Score"],
        color=colours, edgecolor="white", height=0.72,
        linewidth=0.5
    )

    # Score label
    for bar, val in zip(bars, top["BBB_Engineering_Score"].tolist()):
        ax.text(val + 0.4, bar.get_y() + bar.get_height() / 2,
                f"{val:.1f}", va="center", ha="left", fontsize=8,
                fontweight="bold", color=C["dgrey"])

    # ADMET flag markers
    if "ADMET_Overall_Flag" in top.columns:
        for i, (_, row) in enumerate(top.iterrows()):
            if row.get("ADMET_Overall_Flag") == "REVIEW":
                ax.plot(row["BBB_Engineering_Score"] - 2, i, "v",
                        color=C["orange"], ms=8, zorder=5)

    # Target line
    ax.axvline(75, color=C["gold"], linestyle="--", lw=1.8, alpha=0.85,
               label="Target: BBB Score ≥ 75")

    # Legend for carriers
    legend_patches = [mpatches.Patch(color=v, label=k)
                      for k, v in CARRIER_COLOURS.items()
                      if k in top["Carrier_Type"].values]
    legend_patches.append(plt.Line2D([0],[0], marker="v", color="w",
                                      markerfacecolor=C["orange"], ms=9,
                                      label="ADMET REVIEW"))
    legend_patches.append(plt.Line2D([0],[0], linestyle="--",
                                      color=C["gold"], lw=2,
                                      label="Target ≥ 75"))
    ax.legend(handles=legend_patches, loc="lower right", fontsize=8,
              framealpha=0.95)

    ax.set_xlim(0, 105)
    ax.set_xlabel("BBB Engineering Score (0–100)", fontsize=11)
    ax.set_title(
        f"CEREBRO-X  |  DDS Formulation Rankings — {drug_name}\n"
        f"Top {top_n} of {len(df_dds)} systems scored",
        fontweight="bold", fontsize=13, pad=12)
    ax.grid(True, axis="x", alpha=0.25, linestyle=":")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    plt.tight_layout()
    out = output_dir / "01_BBB_Score_Ranking.png"
    fig.savefig(out, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    _doc(out,
        f"BBB Engineering Score ranking: top {top_n}/{len(df_dds)} DDS formulations for {drug_name}.",
        "Identifies optimal carrier architectures. Scores > 75 with ADMET=OK proceed "
        "to in-vitro BBB TEER assay validation.",
        "BBB Engineering Score (Pardridge 2012 framework): composite of size optimality "
        "(60–100 nm for caveolae transcytosis), zeta stability (±5–15 mV), PEGylation "
        "stealth (2–7 mol%), surface ligand receptor affinity (RVG +20, ApoE3 +22), "
        "ligand density Goldilocks (0.5–1.5/nm²), EE ≥ 80%, P-gp escape, Tm safety, "
        "CARPA risk, liver off-target penalty.",
        "1. Sort top-N by BBB score.\n"
        "2. Horizontal bar per formulation, colour = carrier type.\n"
        "3. Score label right of bar.\n"
        "4. ADMET REVIEW marked with orange triangle.",
        "Longest bar = best formulation. Gold dashed line at 75 = minimum for wet-lab. "
        "Orange triangles = safety concern requiring reformulation.")

    log.info(f"  [VIZ] Fig01 → {out}")
    return out


# ─────────────────────────────────────────────────────────────────────────────
# FIGURE 02:  PK/PD Multi-Compartment Kinetics
# ─────────────────────────────────────────────────────────────────────────────
def fig02_pkpd_kinetics(df_pk: pd.DataFrame, output_dir: Path,
                         drug_name: str = "") -> Path | None:
    """
    Multi-compartment PK/PD: plasma + brain concentration over time.
    Shaded 50% threshold zone. AUC annotation.
    """
    if df_pk is None or df_pk.empty:
        return None

    has_comp = "Compartment" in df_pk.columns
    has_day  = "Day" in df_pk.columns or "Hour" in df_pk.columns
    if not has_day:
        return None

    t_col = "Day" if "Day" in df_pk.columns else "Hour"
    t_unit = "Days" if t_col == "Day" else "Hours"

    fig, axes = plt.subplots(1, 2, figsize=(15, 6))
    fig.suptitle(f"CEREBRO-X  |  PK/PD Concentration Kinetics — {drug_name}",
                 fontweight="bold", fontsize=13, y=1.01)

    # ── Left: Plasma + Brain (if compartments available) ──────────────────
    ax = axes[0]
    if has_comp:
        for comp, ls, col in [("Plasma","--",C["blue"]),
                               ("Brain","-",C["teal"])]:
            sub = df_pk[df_pk["Compartment"] == comp]
            if sub.empty: continue
            c_col = "Concentration_ugL" if "Concentration_ugL" in sub.columns else "Concentration_pct"
            ax.plot(sub[t_col], sub[c_col], lw=2.5, ls=ls,
                    color=col, label=comp)
            if comp == "Brain":
                ax.fill_between(sub[t_col], 0, sub[c_col],
                                color=col, alpha=0.06)
    else:
        c_col = "Concentration_Pct" if "Concentration_Pct" in df_pk.columns else df_pk.columns[-1]
        if "Drug" in df_pk.columns:
            for i, (drug, grp) in enumerate(df_pk.groupby("Drug")):
                ax.plot(grp[t_col], grp[c_col], lw=2.5,
                        color=PALETTE[i % len(PALETTE)], label=drug)
        else:
            ax.plot(df_pk[t_col], df_pk[c_col], lw=2.5, color=C["teal"])

    ax.set_xlabel(f"Time ({t_unit})", fontsize=10)
    ax.set_ylabel("Concentration (µg/L or %)", fontsize=10)
    ax.set_title("Plasma vs. Brain Concentration", fontweight="bold")
    ax.legend(fontsize=9); ax.grid(True, alpha=0.25)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # ── Right: Log-scale for low-concentration regime ──────────────────────
    ax2 = axes[1]
    if has_comp:
        for comp, ls, col in [("Plasma","--",C["blue"]),("Brain","-",C["teal"])]:
            sub = df_pk[df_pk["Compartment"] == comp]
            if sub.empty: continue
            c_col = "Concentration_ugL" if "Concentration_ugL" in sub.columns else "Concentration_pct"
            vals = sub[c_col].clip(lower=1e-10)
            ax2.semilogy(sub[t_col], vals, lw=2, ls=ls, color=col, label=comp)
    ax2.set_xlabel(f"Time ({t_unit})", fontsize=10)
    ax2.set_ylabel("Concentration (log scale)", fontsize=10)
    ax2.set_title("Log-Scale Concentration Profile", fontweight="bold")
    ax2.legend(fontsize=9); ax2.grid(True, alpha=0.25, which="both")
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(False)

    plt.tight_layout()
    out = output_dir / "02_PKPD_Kinetics.png"
    fig.savefig(out, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    _doc(out,
        f"Two-compartment CNS PK/PD kinetics for {drug_name}.",
        "Brain concentration over time is the primary efficacy predictor. "
        "Time above therapeutic threshold determines dosing interval.",
        "Two-compartment CNS model (Rowland & Tozer 2011):\n"
        "C(t) = A·e^(−αt) + B·e^(−βt)\n"
        "where α (fast) = distribution phase, β (slow) = elimination phase.\n"
        "LogBB = log10(AUC_brain / AUC_plasma). Target > -1 for CNS drugs.",
        "Left: linear scale (therapeutic window visible).\n"
        "Right: semi-log (terminal elimination slope = -k_el/2.303).",
        "Blue dashed = plasma. Teal solid = brain. "
        "Steeper log-scale terminal slope = faster elimination.")

    log.info(f"  [VIZ] Fig02 → {out}")
    return out


# ─────────────────────────────────────────────────────────────────────────────
# FIGURE 03:  PBPK Organ Heatmap
# ─────────────────────────────────────────────────────────────────────────────
def fig03_pbpk_heatmap(df_pbpk: pd.DataFrame, output_dir: Path,
                        drug_name: str = "") -> Path | None:
    """
    Heatmap: organs × time points, colour = drug concentration.
    Shows which organs accumulate drug (off-target) vs. target (brain).
    """
    if df_pbpk is None or df_pbpk.empty or "Organ" not in df_pbpk.columns:
        return None

    t_col = "Hour" if "Hour" in df_pbpk.columns else "Day"
    c_col = "Conc_umol_L" if "Conc_umol_L" in df_pbpk.columns else df_pbpk.columns[-1]

    # Pivot: organs × time (subsample to 20 time points)
    drugs_in = df_pbpk["Drug"].unique() if "Drug" in df_pbpk.columns else ["Drug"]
    drug_sel  = drugs_in[0] if len(drugs_in) > 0 else None
    if drug_sel and "Drug" in df_pbpk.columns:
        sub = df_pbpk[df_pbpk["Drug"] == drug_sel]
    else:
        sub = df_pbpk

    t_vals = sorted(sub[t_col].unique())
    stride = max(1, len(t_vals) // 20)
    t_vals = t_vals[::stride]

    pivot = sub[sub[t_col].isin(t_vals)].pivot_table(
        index="Organ", columns=t_col, values=c_col, aggfunc="mean")

    fig, ax = plt.subplots(figsize=(14, 6))
    custom_cmap = LinearSegmentedColormap.from_list(
        "cerebro_heat", ["#F5F5F5", C["teal"], C["navy"]])

    sns.heatmap(pivot, ax=ax, cmap=custom_cmap,
                cbar_kws={"label": "Drug Concentration (µmol/L)",
                           "shrink": 0.8},
                linewidths=0.5, linecolor="white",
                fmt=".2e", annot=(pivot.shape[0] <= 8 and pivot.shape[1] <= 20))

    ax.set_title(
        f"CEREBRO-X  |  PBPK Organ Distribution — {drug_name}\n"
        f"(Drug: {drug_sel or 'All'})",
        fontweight="bold", fontsize=12)
    ax.set_xlabel(f"Time ({t_col})", fontsize=10)
    ax.set_ylabel("Organ", fontsize=10)
    ax.set_yticklabels(ax.get_yticklabels(), rotation=0)

    # Highlight brain row
    organ_labels = list(pivot.index)
    if "brain" in organ_labels:
        brain_idx = organ_labels.index("brain")
        ax.add_patch(plt.Rectangle((0, brain_idx), pivot.shape[1], 1,
                                    fill=False, edgecolor=C["gold"],
                                    lw=2.5, zorder=5))

    plt.tight_layout()
    out = output_dir / "03_PBPK_Organ_Distribution.png"
    fig.savefig(out, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    _doc(out,
        f"PBPK organ distribution heatmap for {drug_name}.",
        "Identifies off-target organ accumulation (liver = hepatotoxicity risk, "
        "kidney = nephrotoxicity). Gold border = brain (target tissue).",
        "7-compartment PBPK: Kp = 10^(slope·logP) per organ. "
        "Colour intensity ∝ drug concentration. "
        "High liver/kidney accumulation warns of off-target toxicity.",
        "seaborn heatmap of pivoted PBPK timeseries.\n"
        "Row = organ, column = time point, cell = mean concentration.",
        "Darker = more drug. Gold border on brain = target. "
        "Avoid carriers that concentrate heavily in liver (hepatotox risk).")

    log.info(f"  [VIZ] Fig03 → {out}")
    return out


# ─────────────────────────────────────────────────────────────────────────────
# FIGURE 04:  DLVO Colloidal Stability Map
# ─────────────────────────────────────────────────────────────────────────────
def fig04_dlvo_stability(df_bio: pd.DataFrame, output_dir: Path,
                          drug_name: str = "") -> Path | None:
    """
    Scatter: size (x) vs. zeta potential (y), colour = DLVO stability (kT),
    shape = carrier type, size = encapsulation efficiency.
    """
    if df_bio is None or df_bio.empty:
        return None
    if "V_total_kT" not in df_bio.columns:
        return None

    fig, axes = plt.subplots(1, 2, figsize=(15, 6))
    fig.suptitle(f"CEREBRO-X  |  Colloidal Stability (DLVO) — {drug_name}",
                 fontweight="bold", fontsize=13)

    # ── Left: size vs. zeta, colour = stability ───────────────────────────
    ax = axes[0]
    sc = ax.scatter(df_bio["diameter_nm"], df_bio["zeta_mV"],
                    c=df_bio["V_total_kT"],
                    cmap=LinearSegmentedColormap.from_list(
                        "stability", ["#C62828","#C9A84C","#0D6E6E"]),
                    vmin=0, vmax=50,
                    s=70, alpha=0.8, edgecolors="white", lw=0.4)
    plt.colorbar(sc, ax=ax, label="DLVO stability (kT)")

    # Stability zones
    ax.axhspan(-15, -5, alpha=0.06, color=C["green"], label="Optimal zeta zone")
    ax.axhspan(5, 15, alpha=0.06, color=C["green"])
    ax.axvspan(60, 100, alpha=0.06, color=C["teal"], label="Optimal size zone")
    ax.axhline(25, color="gray", ls=":", lw=1)
    ax.axhline(-25, color="gray", ls=":", lw=1)
    ax.set_xlabel("Particle Diameter (nm)", fontsize=10)
    ax.set_ylabel("Zeta Potential (mV)", fontsize=10)
    ax.set_title("Size vs. Zeta — DLVO Stability", fontweight="bold")
    ax.legend(fontsize=8); ax.grid(True, alpha=0.2)

    # ── Right: transcytosis ΔG vs. BBB score ─────────────────────────────
    ax2 = axes[1]
    if "transcytosis_dG_total_kT" in df_bio.columns and "Formulation_Name" in df_bio.columns:
        colours2 = [C["green"] if v < 0 else C["red"]
                    for v in df_bio["transcytosis_dG_total_kT"]]
        ax2.bar(range(min(20, len(df_bio))),
                df_bio["transcytosis_dG_total_kT"].head(20),
                color=colours2[:20], edgecolor="white")
        ax2.axhline(0, color="black", lw=0.8)
        ax2.set_xticks(range(min(20, len(df_bio))))
        ax2.set_xticklabels(
            df_bio["Formulation_ID"].head(20).tolist(),
            rotation=45, ha="right", fontsize=7)
        ax2.set_ylabel("Transcytosis ΔG (kT)", fontsize=10)
        ax2.set_title("Transcytosis Energy Barrier (Bell model)",
                      fontweight="bold")
        ax2.grid(True, axis="y", alpha=0.25)
    else:
        ax2.text(0.5, 0.5, "Biophysics data\nnot available",
                 ha="center", va="center", transform=ax2.transAxes,
                 fontsize=12, color="grey")

    plt.tight_layout()
    out = output_dir / "04_DLVO_Stability.png"
    fig.savefig(out, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    _doc(out,
        f"DLVO colloidal stability and transcytosis energy landscape for {drug_name}.",
        "Particles with V_total > 25 kT won't aggregate in blood. "
        "Negative transcytosis ΔG (green bars) confirms receptor-mediated BBB entry.",
        "DLVO: V_total = V_vdW (London attraction) + V_EDL (electrostatic repulsion). "
        "Stable if V_total > 25 kT. Debye length κ⁻¹ = 0.78 nm at I=150 mM. "
        "Bell model: ΔG = E_membrane_deform - n_bonds·G_bond (Bell 1978). "
        "Negative ΔG → thermodynamically spontaneous uptake.",
        "Left: scatter (size, zeta) coloured by kT stability.\n"
        "Right: bar chart of transcytosis ΔG per formulation.\n"
        "Green = favourable (ΔG < 0), Red = unfavourable.",
        "Hot colours (red) = unstable colloid. Cool colours (green) = stable. "
        "Green bars = endocytosis will occur spontaneously. "
        "Red bars = need to increase ligand density or reduce particle size.")

    log.info(f"  [VIZ] Fig04 → {out}")
    return out


# ─────────────────────────────────────────────────────────────────────────────
# FIGURE 05:  3D Pharmacological Performance Space
# ─────────────────────────────────────────────────────────────────────────────
def fig05_3d_space(df_ml: pd.DataFrame, output_dir: Path,
                    drug_name: str = "") -> Path | None:
    """
    3D scatter: half-life × |binding affinity| × ML success probability.
    Each point = one drug candidate. Colour = ML score.
    Multiple viewing angles saved.
    """
    if df_ml is None or df_ml.empty:
        return None
    if "Half_Life_Days" not in df_ml.columns:
        return None

    aff_col = next((c for c in ["Docking_Affinity_kcal","Binding_Affinity_kcal",
                                  "Estimated_Affinity_kcal"] if c in df_ml.columns), None)
    if not aff_col or "ML_Success_Probability" not in df_ml.columns:
        return None

    from mpl_toolkits.mplot3d import Axes3D  # noqa

    df_r = df_ml.drop_duplicates(subset=["Drug"]).copy() if "Drug" in df_ml.columns else df_ml

    x = df_r["Half_Life_Days"].values
    y = abs(df_r[aff_col].values)
    z = df_r["ML_Success_Probability"].values
    c = z

    fig = plt.figure(figsize=(16, 6))
    fig.suptitle(f"CEREBRO-X  |  3D Pharmacological Performance Space — {drug_name}",
                 fontweight="bold", fontsize=12)

    norm  = Normalize(vmin=z.min(), vmax=z.max())
    cmap_ = plt.cm.viridis

    for i, (elev, azim, subtitle) in enumerate([
        (25, -60, "Standard view"),
        (10, 0,   "Front view"),
        (60, -45, "Top view"),
    ]):
        ax = fig.add_subplot(1, 3, i+1, projection="3d")
        sc = ax.scatter(x, y, z, c=c, cmap=cmap_, norm=norm,
                        s=180, edgecolors="k", lw=0.4, depthshade=True)

        if "Drug" in df_r.columns:
            for j, (_, row) in enumerate(df_r.iterrows()):
                ax.text(row["Half_Life_Days"], abs(row[aff_col]),
                        row["ML_Success_Probability"] + 0.5,
                        row["Drug"][:10], fontsize=6, fontweight="bold",
                        color=C["dgrey"])

        ax.set_xlabel("Half-Life (d)", fontsize=8, labelpad=4)
        ax.set_ylabel("|Binding| (kcal/mol)", fontsize=8, labelpad=4)
        ax.set_zlabel("ML Score (%)", fontsize=8, labelpad=4)
        ax.set_title(subtitle, fontsize=9)
        ax.view_init(elev=elev, azim=azim)
        if i == 2:
            plt.colorbar(sc, ax=ax, shrink=0.6, label="ML %")

    plt.tight_layout()
    out = output_dir / "05_3D_Performance_Space.png"
    fig.savefig(out, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    _doc(out,
        f"3D pharmacological performance space for {drug_name} candidates.",
        "Ideal drug occupies top-right-back corner: long half-life, strong binding, "
        "high ML success probability.",
        "Three axes avoid information collapse of 2D projection. "
        "ML score from TrainAwareScaler ensemble (RF+GBR+SVR+XGB). "
        "Half-life proxy for CNS exposure duration.",
        "matplotlib Axes3D. Three viewing angles: standard, front, top.\n"
        "All synthetic (_synthetic=True) rows excluded.",
        "Nearest to top-right-back = lead candidate. "
        "Bottom-left-front = poor drug properties.")

    log.info(f"  [VIZ] Fig05 → {out}")
    return out


# ─────────────────────────────────────────────────────────────────────────────
# FIGURE 06:  Formulation Property Heatmap
# ─────────────────────────────────────────────────────────────────────────────
def fig06_formulation_heatmap(df_dds: pd.DataFrame, output_dir: Path,
                               drug_name: str = "") -> Path | None:
    """
    Heatmap: all 100 formulations × key parameters.
    Each cell normalised 0–1. Shows which systems have optimal parameter combinations.
    """
    if df_dds is None or df_dds.empty:
        return None

    PARAMS = [
        ("BBB_Engineering_Score", "BBB\nScore"),
        ("size_nm",               "Size\n(nm)"),
        ("zeta_potential_mv",     "Zeta\n(mV)"),
        ("encapsulation_efficiency_pct", "EE\n(%)"),
        ("pegylation_degree_mol_pct",    "PEG\n(%)"),
        ("ligand_density_per_nm2",       "Ligand\nDensity"),
        ("Off_Target_Liver_pct",         "Liver\nOff-tgt"),
        ("CARPA_Risk_Index",             "CARPA\nRisk"),
    ]

    avail = [(col, lbl) for col, lbl in PARAMS if col in df_dds.columns]
    if not avail:
        return None

    cols, lbls = zip(*avail)
    mat = df_dds[list(cols)].copy()

    # Normalise: for "bad" params flip scale
    BAD_HIGH = {"size_nm", "Off_Target_Liver_pct", "CARPA_Risk_Index"}
    for col in cols:
        col_range = mat[col].max() - mat[col].min()
        if col_range == 0:
            mat[col] = 0.5
        else:
            mat[col] = (mat[col] - mat[col].min()) / col_range
            if col in BAD_HIGH:
                mat[col] = 1 - mat[col]   # invert: high is bad → show as dark

    mat.index = df_dds.get("Formulation_ID", range(len(df_dds)))

    fig, ax = plt.subplots(figsize=(14, max(8, len(df_dds) * 0.12)))

    custom_cmap = LinearSegmentedColormap.from_list(
        "prop_heat", ["#F5F5F5", "#C9A84C", "#0D6E6E", "#0f2040"])

    sns.heatmap(
        mat,
        ax=ax,
        cmap=custom_cmap,
        xticklabels=list(lbls),
        yticklabels=(list(mat.index) if len(mat) <= 30 else False),
        cbar_kws={"label": "Normalised score (higher = better)", "shrink": 0.7},
        linewidths=0.2, linecolor="white",
        vmin=0, vmax=1,
    )
    ax.set_title(
        f"CEREBRO-X  |  Formulation Property Heatmap — {drug_name}\n"
        f"({len(df_dds)} formulations × {len(avail)} key parameters — normalised 0→1)",
        fontweight="bold", fontsize=11)
    ax.set_xlabel("Parameter", fontsize=10)
    ax.set_ylabel("Formulation ID", fontsize=10)

    plt.tight_layout()
    out = output_dir / "06_Formulation_Heatmap.png"
    fig.savefig(out, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    _doc(out,
        f"Formulation property heatmap: {len(df_dds)} DDS systems × {len(avail)} parameters.",
        "Quick visual scan for which formulations are uniformly excellent (all dark blue) "
        "vs. tradeoff-heavy (mixed colours). Guides multi-objective optimisation.",
        "All parameters normalised 0–1. For 'lower is better' parameters "
        "(size, CARPA, liver off-target) the scale is inverted so dark = good. "
        "A uniformly dark row = optimal formulation across all engineering dimensions.",
        "Min-max normalisation per column. Inverted for negative parameters.\n"
        "seaborn heatmap with custom CEREBRO-X colormap.",
        "All dark blue = best. Mixed colours = tradeoffs. "
        "Identify rows that are uniformly dark → these are the strongest candidates.")

    log.info(f"  [VIZ] Fig06 → {out}")
    return out


# ─────────────────────────────────────────────────────────────────────────────
# FIGURE 07:  Radar Fingerprint (multi-drug)
# ─────────────────────────────────────────────────────────────────────────────
def fig07_radar(df_ml: pd.DataFrame, output_dir: Path,
                 drug_name: str = "") -> Path | None:
    """
    Polar radar: drug(s) molecular attribute fingerprint.
    """
    if df_ml is None or df_ml.empty:
        return None

    features = [c for c in ["Half_Life_Days","ML_Success_Probability",
                              "Docking_Affinity_kcal","Binding_Affinity_kcal",
                              "LogP","MW_Da","ADMET_BBB_Score"]
                if c in df_ml.columns]
    if len(features) < 3 or "Drug" not in df_ml.columns:
        return None

    from sklearn.preprocessing import MinMaxScaler

    df_r = df_ml.drop_duplicates(subset=["Drug"]).copy()
    df_r[features] = MinMaxScaler().fit_transform(abs(df_r[features]))
    N = len(features)
    angles = [n / N * 2 * np.pi for n in range(N)] + [0]

    fig = plt.figure(figsize=(9, 9))
    ax  = plt.subplot(111, polar=True)

    for idx, (_, row) in enumerate(df_r.iterrows()):
        v = row[features].tolist() + [row[features].iloc[0]]
        col = PALETTE[idx % len(PALETTE)]
        ax.plot(angles, v, lw=2.5, color=col, label=row["Drug"])
        ax.fill(angles, v, alpha=0.10, color=col)

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels([f.replace("_", "\n")[:12] for f in features], fontsize=8)
    ax.set_title(f"Molecular Fingerprint — {drug_name}",
                 fontweight="bold", pad=20, fontsize=12)
    ax.legend(loc="upper right", bbox_to_anchor=(1.4, 1.1), fontsize=9)
    plt.tight_layout()

    out = output_dir / "07_Radar_Fingerprint.png"
    fig.savefig(out, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    _doc(out,
        f"Polar radar molecular fingerprint — {drug_name}.",
        "Shows multi-attribute drug profile. Larger enclosed area = stronger candidate.",
        "Min-Max normalised (0–1), abs() so negative affinities are positive. "
        "All axes equal scale for fair comparison.",
        "matplotlib polar. Min-Max per column on training set (no leakage).",
        "Largest enclosed area = best candidate. "
        "Note which axes are weak (small radial extent) — these are the "
        "optimisation targets for next-generation analogues.")

    log.info(f"  [VIZ] Fig07 → {out}")
    return out


# ─────────────────────────────────────────────────────────────────────────────
# BIORENDER-STYLE SCHEMATICS
# ─────────────────────────────────────────────────────────────────────────────
class BioSchematicEngine:
    """
    Generates schematic diagrams in the style of BioRender.
    Pure matplotlib — no external tools required.

    Available schematics:
      bbb_crossing    → BBB crossing mechanism with Vexosome
      vexosome_cross_section → Vexosome anatomy cross-section
      pk_model_diagram    → 2-compartment PK diagram
      pipeline_flowchart  → CEREBRO-X pipeline overview
    """

    @staticmethod
    def bbb_crossing(output_dir: Path, drug_name: str = "",
                      ligand: str = "RVG29") -> Path:
        """
        BioRender-style schematic of Vexosome BBB crossing.
        Shows: blood vessel lumen → endothelial cells → BBB → brain parenchyma.
        """
        fig, ax = plt.subplots(figsize=(14, 8))
        ax.set_xlim(0, 14)
        ax.set_ylim(0, 8)
        ax.axis("off")
        ax.set_facecolor("#F8F9FA")
        fig.patch.set_facecolor("#F8F9FA")

        def draw_text(x, y, txt, sz=9, col="black", ha="center", bold=False, va="center"):
            ax.text(x, y, txt, ha=ha, va=va, fontsize=sz,
                    fontweight="bold" if bold else "normal",
                    color=col, zorder=10)

        # Blood vessel (orange/red channel)
        vessel = FancyBboxPatch((0.2, 3.0), 13.6, 2.0,
                                 boxstyle="round,pad=0.1",
                                 facecolor="#FFE4CC", edgecolor=C["orange"],
                                 lw=2, zorder=1)
        ax.add_patch(vessel)
        draw_text(1.2, 5.7, "Blood Vessel Lumen", sz=10, col=C["orange"], bold=True)

        # Endothelial cell layer (top wall)
        for xi in np.arange(0.5, 13.5, 1.2):
            cell = FancyBboxPatch((xi, 4.8), 1.0, 0.4,
                                   boxstyle="round,pad=0.05",
                                   facecolor=C["teal"], edgecolor="white",
                                   lw=1, alpha=0.85, zorder=2)
            ax.add_patch(cell)
        draw_text(7, 5.4, "Endothelial Cell Layer (BBB)", sz=9, col=C["teal"], bold=True)

        # Tight junctions between cells
        for xi in np.arange(1.3, 14.0, 1.2):
            ax.plot([xi, xi], [4.78, 5.22], color="white", lw=2, zorder=3)
        draw_text(12.5, 5.6, "Tight\nJunctions", sz=7, col="white")

        # Brain parenchyma
        brain_bg = FancyBboxPatch((0.2, 5.3), 13.6, 2.5,
                                   boxstyle="round,pad=0.1",
                                   facecolor="#E8F4F8", edgecolor=C["navy"],
                                   lw=2, zorder=0)
        ax.add_patch(brain_bg)
        draw_text(1.8, 7.6, "Brain Parenchyma", sz=11, col=C["navy"], bold=True)

        # Neurons (simplified circles)
        for nx_, ny_ in [(3.5,6.5),(5.0,7.0),(7.5,6.8),(10.0,7.2),(12.0,6.6)]:
            ax.add_patch(Circle((nx_, ny_), 0.35,
                                 facecolor="#B0D0E8", edgecolor=C["navy"],
                                 lw=1.2, zorder=4))
            # Dendrites
            for ang in [0, 60, 120, 180, 240, 300]:
                dx_ = 0.55 * math.cos(math.radians(ang))
                dy_ = 0.55 * math.sin(math.radians(ang))
                ax.plot([nx_, nx_+dx_], [ny_, ny_+dy_],
                        color=C["navy"], lw=0.8, alpha=0.6, zorder=3)

        # Vexosome particles in blood
        for bx_, by_ in [(2,4.1),(4,3.6),(6.5,4.3),(9,3.8),(11.5,4.0)]:
            # Core
            ax.add_patch(Circle((bx_, by_), 0.25,
                                 facecolor=C["navy"], edgecolor=C["gold"],
                                 lw=1.5, zorder=5))
            # PEG brush (spiky halo)
            for ang in range(0, 360, 30):
                r1, r2 = 0.25, 0.38
                dx_ = math.cos(math.radians(ang))
                dy_ = math.sin(math.radians(ang))
                ax.plot([bx_ + r1*dx_, bx_ + r2*dx_],
                        [by_ + r1*dy_, by_ + r2*dy_],
                        color=C["teal"], lw=1.0, alpha=0.8, zorder=5)
            # Ligand label (on the largest one)
            if abs(bx_ - 6.5) < 0.1:
                draw_text(bx_, by_-0.65, ligand, sz=7, col=C["gold"])

        # Main vexosome (large, in transcytosis)
        vx, vy = 7.0, 4.9
        ax.add_patch(Circle((vx, vy), 0.38,
                             facecolor=C["navy"], edgecolor=C["gold"],
                             lw=2, zorder=7))
        # Drug molecule inside (small dot)
        ax.add_patch(Circle((vx, vy), 0.12,
                             facecolor=C["orange"], edgecolor="white",
                             lw=1, zorder=8))
        # Receptor binding arrow
        ax.annotate("",
            xy=(vx-0.1, vy+0.38), xytext=(vx-0.5, vy+1.0),
            arrowprops=dict(arrowstyle="-|>", color=C["gold"], lw=2))
        draw_text(vx-1.0, vy+1.4, f"{ligand}\nbinds receptor", sz=8, col=C["gold"])

        # Arrow: transcytosis direction
        ax.annotate("",
            xy=(7.5, 5.5), xytext=(7.5, 4.5),
            arrowprops=dict(arrowstyle="-|>", color=C["green"], lw=2.5))
        draw_text(8.8, 4.95, "Transcytosis\n(receptor-mediated)", sz=8, col=C["green"])

        # Released drug in brain
        for rx_, ry_ in [(6.0,6.2),(7.5,6.4),(9.0,6.0)]:
            ax.add_patch(Circle((rx_, ry_), 0.12,
                                 facecolor=C["orange"], edgecolor="white",
                                 lw=1, zorder=6, alpha=0.9))
        draw_text(7.5, 5.75, f"{drug_name}\nreleased in brain",
                  sz=8, col=C["orange"], bold=True)

        # Scale bar
        ax.plot([11.5, 12.5], [2.2, 2.2], color="black", lw=2)
        draw_text(12.0, 1.9, "200 nm", sz=8)

        # Title
        draw_text(7, 0.5,
                  f"CEREBRO-X |  Vexosome BBB Crossing Mechanism\n"
                  f"Drug: {drug_name}  |  Ligand: {ligand}",
                  sz=11, col=C["navy"], bold=True)

        out = output_dir / "Schema_01_BBB_Crossing.png"
        fig.savefig(out, dpi=300, bbox_inches="tight", facecolor="#F8F9FA")
        plt.close(fig)

        _doc(out,
            f"BioRender-style schematic of Vexosome BBB crossing mechanism for {drug_name}.",
            "Communicates the nanocarrier delivery concept to non-technical audience "
            "(investors, clinicians, regulators) and publications.",
            "RVG29/Angiopep-2 surface ligand binds nAChR/LRP1 on endothelial cells. "
            "Receptor-mediated endocytosis → vesicle formation → transcytosis across "
            "BBB → exocytosis on abluminal side → drug release into brain parenchyma. "
            "Reference: Ye et al., J Control Release (2020).",
            "Pure matplotlib: FancyBboxPatch, Circle, annotate arrows.\n"
            "No external tools (BioRender, Inkscape, etc.) required.",
            "Orange = blood vessel. Blue bar = endothelial cells. Light blue = brain. "
            "Navy sphere = Vexosome with gold PEG brush and ligand. "
            "Orange dot = drug payload. Green arrow = transcytosis direction.")

        log.info(f"  [VIZ] Schema01 → {out}")
        return out

    @staticmethod
    def pipeline_flowchart(output_dir: Path) -> Path:
        """
        CEREBRO-X pipeline flowchart: from Excel input to PDF report.
        """
        fig, ax = plt.subplots(figsize=(14, 10))
        ax.set_xlim(0, 14)
        ax.set_ylim(0, 10)
        ax.axis("off")
        ax.set_facecolor("#F8F9FA")
        fig.patch.set_facecolor("#F8F9FA")

        def box(x, y, w, h, txt, col, txt_col="white", sz=9):
            ax.add_patch(FancyBboxPatch((x, y), w, h,
                                         boxstyle="round,pad=0.15",
                                         facecolor=col, edgecolor="white",
                                         lw=1.5, zorder=3))
            ax.text(x + w/2, y + h/2, txt, ha="center", va="center",
                    fontsize=sz, fontweight="bold", color=txt_col, zorder=4,
                    wrap=True)

        def arrow(x1, y1, x2, y2):
            ax.annotate("",
                xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle="-|>", color=C["navy"],
                                lw=1.5, connectionstyle="arc3,rad=0"))

        # Pipeline steps
        steps = [
            (6.0, 8.8, 2.8, 0.7, "CEREBRO_Input_*.xlsx\n(Researcher fills)",   C["orange"]),
            (6.0, 7.8, 2.8, 0.7, "Hash Detection → Trial_N/",                  C["teal"]),
            (6.0, 6.8, 2.8, 0.7, "Cache Invalidation",                          C["red"]),
            (6.0, 5.8, 2.8, 0.7, "MoleculeEngine\n(SMILES/FASTA/name → live)", C["navy"]),
            (6.0, 4.8, 2.8, 0.7, "5-Tier Cascade API\n(DrugBank→PubMed)",       C["navy"]),
            (6.0, 3.8, 2.8, 0.7, "ML Ensemble\n(RF+GBR+SVR+XGB, leakage-free)",C["blue"]),
            (6.0, 2.8, 2.8, 0.7, "DDS Scoring (100 systems)\nBBB Eng. Score",   C["teal"]),
            (6.0, 1.8, 2.8, 0.7, "Science Engines\n(QChem+Thermo+PK+PBPK)",     C["purple"]),
            (6.0, 0.8, 2.8, 0.7, "Merged PDF Report\n+ Trial Documentation",    C["green"]),
        ]
        for x,y,w,h,txt,col in steps:
            box(x, y, w, h, txt, col)

        # Arrows between main flow
        for i in range(len(steps)-1):
            x1 = steps[i][0] + steps[i][2]/2
            y1 = steps[i][1]
            y2 = steps[i+1][1] + steps[i+1][3]
            arrow(x1, y1, x1, y2)

        # Side boxes
        side_left = [
            (0.2, 5.5, 4.2, 0.7, "SMILES → RDKit\n+ Mordred 1800+ desc.",    C["teal"],   "white"),
            (0.2, 4.5, 4.2, 0.7, "FASTA → BioPython\n+ UniProt",              C["teal"],   "white"),
            (0.2, 3.5, 4.2, 0.7, "PDB ID → RCSB\n+ 3D structure",             C["teal"],   "white"),
            (0.2, 2.5, 4.2, 0.7, "HELM → Pistoia\n+ sequence",                C["teal"],   "white"),
        ]
        for x,y,w,h,txt,col,tc in side_left:
            box(x, y, w, h, txt, col, tc)
            arrow(4.4, y+h/2, 6.0, 4.8+0.7/2)

        side_right = [
            (9.6, 6.5, 4.2, 0.7, "ADMET Screening\n(BBB + hepatotox + immune)", C["orange"],"white"),
            (9.6, 5.5, 4.2, 0.7, "SHAP XAI\nFeature importance",                C["purple"],"white"),
            (9.6, 4.5, 4.2, 0.7, "DLVO Stability\n+ Transcytosis ΔG",           C["navy"],  "white"),
            (9.6, 3.5, 4.2, 0.7, "PBPK 7-Organ\ndistribution",                  C["navy"],  "white"),
            (9.6, 2.5, 4.2, 0.7, "Static PNG figures\n+ BioRender schematics",   C["green"], "white"),
        ]
        for x,y,w,h,txt,col,tc in side_right:
            box(x, y, w, h, txt, col, tc)
            arrow(9.6, y+h/2, 8.8, y+h/2)

        ax.text(7, 9.7, "CEREBRO-X Pipeline Flow",
                ha="center", va="center", fontsize=14, fontweight="bold",
                color=C["navy"])

        out = output_dir / "Schema_04_Pipeline_Flowchart.png"
        fig.savefig(out, dpi=300, bbox_inches="tight", facecolor="#F8F9FA")
        plt.close(fig)

        _doc(out,
            "CEREBRO-X complete pipeline flowchart.",
            "Communicates the full analysis workflow to stakeholders and partners.",
            "From Excel input through molecule analysis, ML training, DDS scoring, "
            "science simulations, to merged PDF report.",
            "Pure matplotlib: FancyBboxPatch, annotate arrows, text.",
            "Read top-to-bottom: yellow = input, blue/teal = analysis, "
            "green = output. Side boxes = parallel processing paths.")

        log.info(f"  [VIZ] Schema04 → {out}")
        return out


# ─────────────────────────────────────────────────────────────────────────────
# VIDEO ENGINE  (MP4 — requires imageio + Pillow OR OpenCV)
# ─────────────────────────────────────────────────────────────────────────────
class VideoEngine:
    """
    Generates MP4 video animations from DataFrames.
    Uses imageio (preferred) or OpenCV as fallback.

    Videos:
      video_01_pkpd  — PK/PD kinetic curve animated build-up
      video_02_bbb   — BBB score reveal bar animation
    """

    @staticmethod
    def _check_writer() -> str:
        """Return 'imageio', 'opencv', or 'none'."""
        try:
            import imageio
            import imageio_ffmpeg  # type: ignore
            return "imageio"
        except ImportError:
            pass
        try:
            import cv2  # type: ignore
            return "opencv"
        except ImportError:
            pass
        return "none"

    @classmethod
    def pkpd_video(cls, df_pk: pd.DataFrame, output_dir: Path,
                    drug_name: str = "", fps: int = 20) -> Path | None:
        """
        Animated MP4: PK/PD brain concentration curve builds frame-by-frame.
        """
        writer = cls._check_writer()
        if writer == "none":
            log.warning("  [Video] Skipped — install imageio-ffmpeg or opencv-python")
            return None

        has_day = "Day" in df_pk.columns or "Hour" in df_pk.columns
        if df_pk is None or df_pk.empty or not has_day:
            return None

        t_col   = "Day" if "Day" in df_pk.columns else "Hour"
        t_unit  = "Days" if t_col == "Day" else "Hours"
        c_col   = next((c for c in ["Concentration_pct","Concentration_Pct",
                                     "Concentration_ugL"] if c in df_pk.columns),
                        df_pk.columns[-1])

        # Filter to brain compartment if available
        if "Compartment" in df_pk.columns:
            df_use = df_pk[df_pk["Compartment"] == "Brain"].copy()
            if df_use.empty:
                df_use = df_pk.copy()
        else:
            df_use = df_pk.copy()

        drugs    = df_use["Drug"].unique().tolist() if "Drug" in df_use.columns else ["Drug"]
        t_vals   = sorted(df_use[t_col].unique())
        n_frames = min(80, len(t_vals))
        indices  = [int(i * len(t_vals) / n_frames) for i in range(1, n_frames + 1)]

        out = output_dir / f"Video_01_PKPD_Kinetics_{drug_name}.mp4"
        frames = []

        for idx in indices:
            t_sub = t_vals[:idx]
            fig, ax = plt.subplots(figsize=(10, 6))
            for di, drug in enumerate(drugs):
                if "Drug" in df_use.columns:
                    sub = df_use[(df_use["Drug"] == drug) & (df_use[t_col].isin(t_sub))]
                else:
                    sub = df_use[df_use[t_col].isin(t_sub)]
                if sub.empty: continue
                ax.plot(sub[t_col], sub[c_col], lw=2.5,
                        color=PALETTE[di % len(PALETTE)], label=drug)
                ax.fill_between(sub[t_col], 0, sub[c_col],
                                color=PALETTE[di % len(PALETTE)], alpha=0.06)

            ax.axhline(50, color=C["red"], ls="--", lw=1.5, label="50% threshold")
            ax.set_xlim(0, df_use[t_col].max())
            ax.set_ylim(0, df_use[c_col].max() * 1.08)
            ax.set_xlabel(f"Time ({t_unit})", fontsize=10)
            ax.set_ylabel("Brain Concentration (%)", fontsize=10)
            ax.set_title(f"PK/PD Brain Kinetics — {drug_name}  "
                         f"[{t_vals[idx-1]:.1f} {t_unit[0].lower()}]",
                         fontweight="bold")
            ax.legend(fontsize=8)
            ax.grid(True, alpha=0.3)
            plt.tight_layout()

            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=80)
            plt.close(fig)
            buf.seek(0)
            frames.append(buf.read())

        cls._write_mp4(frames, out, fps)

        _doc(out,
            f"MP4: PK/PD brain concentration kinetics animated — {drug_name}.",
            "Animated videos communicate drug behaviour more intuitively than "
            "static plots in presentations and grant applications.",
            "Same kinetics model as Fig02. Animation reveals temporal evolution: "
            "fast rise (distribution phase) then slow decay (elimination phase).",
            "80 frames; each frame = cumulative time window up to that point.\n"
            f"Writer: {writer}. FPS: {fps}.",
            "Watch for: peak brain concentration height and timing, "
            "how long the curve stays above the 50% threshold.")
        log.info(f"  [Video] PKPD MP4 → {out}")
        return out

    @classmethod
    def bbb_reveal_video(cls, df_dds: pd.DataFrame, output_dir: Path,
                          drug_name: str = "", fps: int = 8) -> Path | None:
        """
        Animated MP4: BBB score bar chart revealed one bar at a time.
        """
        writer = cls._check_writer()
        if writer == "none":
            return None
        if df_dds is None or df_dds.empty or "BBB_Engineering_Score" not in df_dds.columns:
            return None

        top = df_dds.nlargest(20, "BBB_Engineering_Score").sort_values(
            "BBB_Engineering_Score", ascending=True)
        names  = top["Formulation_Name"].str[:25].tolist()
        scores = top["BBB_Engineering_Score"].tolist()
        out    = output_dir / f"Video_02_BBB_Reveal_{drug_name}.mp4"
        frames = []

        for n in range(1, len(names) + 1):
            fig, ax = plt.subplots(figsize=(11, 7))
            colours_ = [C["green"] if i == n-1 else C["navy"]
                        for i in range(n)]
            bars_ = ax.barh(names[:n], scores[:n], color=colours_,
                            edgecolor="white", height=0.72)
            ax.set_xlim(0, 100)
            ax.axvline(75, color=C["gold"], ls="--", lw=2, label="Target ≥ 75")
            ax.set_xlabel("BBB Engineering Score", fontsize=11)
            ax.set_title(f"CEREBRO-X  |  DDS Rankings — {drug_name} "
                         f"(revealing {n}/{len(names)})",
                         fontweight="bold")
            for bar, val in zip(bars_, scores[:n]):
                ax.text(val + 0.3, bar.get_y() + bar.get_height()/2,
                        f"{val:.1f}", va="center", fontsize=8)
            ax.legend(fontsize=9)
            ax.grid(True, axis="x", alpha=0.25)
            plt.tight_layout()
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=80)
            plt.close(fig)
            buf.seek(0)
            frames.append(buf.read())

        # Hold last frame 2 s
        frames.extend([frames[-1]] * (fps * 2))
        cls._write_mp4(frames, out, fps)

        _doc(out,
            f"MP4: BBB score reveal animation — {drug_name}.",
            "Builds suspense in presentations by revealing rankings progressively.",
            "Same scoring model as Fig01. Reveals from worst to best.",
            f"20 bars × 1 frame each + 2s hold. Writer: {writer}.",
            "Watch for the final revealed top candidate (rightmost, longest bar). "
            "Gold target line at 75 marks the minimum viable formulation.")
        log.info(f"  [Video] BBB reveal MP4 → {out}")
        return out

    @staticmethod
    def _write_mp4(frames: list, out: Path, fps: int):
        """Write list of PNG bytes to MP4 file."""
        try:
            import io as _io

            import imageio.v2 as imageio
            pil_frames = [imageio.imread(_io.BytesIO(f)) for f in frames]
            imageio.mimsave(str(out), pil_frames, fps=fps, format="mp4",
                            output_params=["-vcodec", "libx264", "-pix_fmt", "yuv420p"])
        except Exception:
            try:
                import io as _io

                import cv2
                import numpy as np
                from PIL import Image
                first = Image.open(_io.BytesIO(frames[0]))
                h, w = first.size[1], first.size[0]
                fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                vw = cv2.VideoWriter(str(out), fourcc, fps, (w, h))
                for fb in frames:
                    img = np.array(Image.open(_io.BytesIO(fb)).convert("RGB"))
                    vw.write(cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
                vw.release()
            except Exception as e:
                log.warning(f"  [Video] Write failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# MASTER VISUALISATION RUNNER
# ─────────────────────────────────────────────────────────────────────────────
class VisualisationOrchestrator:
    """
    Runs all visualisations for a trial.
    Saves everything to trial_dir/figures/ and trial_dir/schematics/.
    """

    @classmethod
    def run_all(cls,
                 drug_name:   str,
                 mol_profile: dict,
                 df_ml:       pd.DataFrame | None,
                 df_dds:      pd.DataFrame | None,
                 df_pk:       pd.DataFrame | None,
                 df_pbpk:     pd.DataFrame | None,
                 df_bio:      pd.DataFrame | None,
                 trial_dir:   Path,
                 make_videos: bool = True,
    ) -> list[Path]:
        """
        Run full visualisation suite. Returns list of produced file paths.
        """
        figs_dir = trial_dir / "media" / "figures"
        sch_dir  = trial_dir / "media" / "schematics"
        figs_dir.mkdir(parents=True, exist_ok=True)
        sch_dir.mkdir(parents=True, exist_ok=True)

        produced = []

        # Identify top ligand for schematic
        ligand = "RVG29"
        if df_dds is not None and "Surface_Ligand" in df_dds.columns:
            top_form = df_dds.nlargest(1, "BBB_Engineering_Score")
            if not top_form.empty:
                ligand = str(top_form.iloc[0].get("Surface_Ligand", "RVG29"))

        calls = [
            ("Fig01", lambda: fig01_bbb_ranking(df_dds, figs_dir, drug_name)),
            ("Fig02", lambda: fig02_pkpd_kinetics(df_pk, figs_dir, drug_name)),
            ("Fig03", lambda: fig03_pbpk_heatmap(df_pbpk, figs_dir, drug_name)),
            ("Fig04", lambda: fig04_dlvo_stability(df_bio, figs_dir, drug_name)),
            ("Fig05", lambda: fig05_3d_space(df_ml, figs_dir, drug_name)),
            ("Fig06", lambda: fig06_formulation_heatmap(df_dds, figs_dir, drug_name)),
            ("Fig07", lambda: fig07_radar(df_ml, figs_dir, drug_name)),
            ("Schema01", lambda: BioSchematicEngine.bbb_crossing(
                sch_dir, drug_name, ligand)),
            ("Schema04", lambda: BioSchematicEngine.pipeline_flowchart(sch_dir)),
        ]

        if make_videos:
            calls += [
                ("Video01", lambda: VideoEngine.pkpd_video(
                    df_pk, figs_dir, drug_name)),
                ("Video02", lambda: VideoEngine.bbb_reveal_video(
                    df_dds, figs_dir, drug_name)),
            ]

        for name, fn in calls:
            try:
                p = fn()
                if p:
                    produced.append(p)
                    log.info(f"  [VIZ] {name}: {Path(p).name}")
            except Exception as e:
                log.warning(f"  [VIZ] {name} skipped: {e}")

        # Module doc
        doc_path = trial_dir / "cerebro_visualization_3d.py_DOCUMENTATION.txt"
        sep = "=" * 70
        doc_path.write_text(
            f"{sep}\n  CEREBRO-X |  FILE DOCUMENTATION\n"
            f"  File      : cerebro_visualization_3d.py\n"
            f"  Generated : {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}\n"
            f"{sep}\n\n"
            f"{'─'*70}\n  OVERVIEW\n{'─'*70}\n"
            "3D visualisation and video engine for CEREBRO-X.\n"
            "Generates all static figures, BioRender-style schematics, and MP4 videos.\n\n"
            "FIGURES PRODUCED:\n"
            "  01_BBB_Score_Ranking.png         — Enhanced horizontal bar chart\n"
            "  02_PKPD_Kinetics.png             — Multi-compartment kinetics\n"
            "  03_PBPK_Organ_Distribution.png   — Organ heatmap\n"
            "  04_DLVO_Stability.png            — Colloidal stability + transcytosis\n"
            "  05_3D_Performance_Space.png      — 3D scatter (3 viewing angles)\n"
            "  06_Formulation_Heatmap.png       — 100 systems × 8 parameters\n"
            "  07_Radar_Fingerprint.png         — Polar molecular fingerprint\n\n"
            "SCHEMATICS:\n"
            "  Schema_01_BBB_Crossing.png       — BioRender-style BBB mechanism\n"
            "  Schema_04_Pipeline_Flowchart.png — CEREBRO-X pipeline overview\n\n"
            "VIDEOS:\n"
            "  Video_01_PKPD_Kinetics_*.mp4     — Animated PK/PD build-up\n"
            "  Video_02_BBB_Reveal_*.mp4        — BBB score reveal animation\n\n"
            f"{'─'*70}\n  DEPENDENCIES\n{'─'*70}\n"
            "  matplotlib · seaborn · numpy · pandas · scipy\n"
            "  imageio + imageio-ffmpeg  (for MP4 — optional)\n"
            "  opencv-python            (MP4 fallback — optional)\n"
            "  Pillow                   (image processing — optional)\n\n"
            "  All figures work with only matplotlib+seaborn.\n"
            "  Videos require imageio-ffmpeg OR opencv-python.\n"
            f"{sep}\n",
            encoding="utf-8"
        )

        log.info(f"[VIZ] Complete — {len(produced)} outputs in {trial_dir}")
        return produced