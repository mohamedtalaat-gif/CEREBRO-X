# -*- coding: utf-8 -*-
"""
================================================================================
CEREBRO-X | cerebro_cinematic_engine.py
================================================================================
Created by: Muhammad Talaat (BPharm) — CEREBRO-X
Date: 2026-04-30

CINEMATIC MEDIA GENERATION — Drug+DDS-customized professional animations.

Mandate (project owner directive 2026-04-30):
    "متنساش إن شغل الميديا والفيديوهات للى بنعملها عايزينه يكون customized
     حسب الدواء وحسب الDDS يعنى للى يتعمل مره ميتكررش تانى وبشكل cinematic
     وprofessional ومنافس لشغل Simulation plus مثلا مش يبقى مجرد canva
     level فمحتاجين يكون الميديا فعلا مستوى يليق بالنشر الاكاديمى
     والتعليمى والصناعى."

Design level reference: Simulation Plus — meaning:
    • Multi-layer parallax depth-of-field
    • Scientifically-accurate biological anatomy (BBB tight junctions,
      endothelial cell membranes, claudin-5 gap structure)
    • Smooth 60fps rendering with cinematic easing
    • Glassmorphic broadcast-quality typography
    • Drug+DDS-specific narration that changes per molecule
    • Outputs fit for academic publication, industrial presentation,
      investor demo

Per drug+DDS pair, 5 scenes are generated:
    C01 — Identity Card     (drug structure + DDS morphology, animated)
    C02 — BBB Crossing      (anatomically-accurate barrier model)
    C03 — PK Profile         (animated pharmacokinetic time course)
    C04 — Release Mechanics  (carrier-specific release dynamics)
    C05 — Therapeutic Effect (composite-score-driven outcome viz)

Each scene is a fully self-contained HTML5 file (~25–45 KB) using Canvas
for rendering. No external dependencies, no ffmpeg, no install required.
Plays in any modern browser at 60fps.

Usage:
    from cerebro_cinematic_engine import generate_cinematic_suite
    paths = generate_cinematic_suite(drug_bundle, dds_bundle, top_dds, out_dir)
================================================================================
"""
from __future__ import annotations
import json, hashlib, logging
from pathlib import Path
from typing import Dict, Any, List, Optional

from cerebro_cinematic_primitives import (
    DRUG_VISUAL_PROFILES, DDS_VISUAL_PROFILES, LIGAND_RECEPTOR_MAP,
    BASE_CSS, JS_DRAW_PRIMITIVES,
    get_drug_profile, get_dds_profile, get_ligand_info,
)

log = logging.getLogger("CEREBRO-CINEMATIC")


# ──────────────────────────────────────────────────────────────────────────
# Helper functions
# ──────────────────────────────────────────────────────────────────────────
def _b_value(bundle: Dict, cat: str, default: Any = None) -> Any:
    """Pull resolved value from bundle, defaulting if missing."""
    if not isinstance(bundle, dict): return default
    rec = bundle.get(cat)
    if not isinstance(rec, dict): return default
    v = rec.get("value")
    return default if v is None else v


def _b_tier(bundle: Dict, cat: str) -> int:
    if not isinstance(bundle, dict): return 7
    rec = bundle.get(cat)
    return rec.get("tier", 7) if isinstance(rec, dict) else 7


def _hash_id(drug: str, dds: str, scene: str) -> str:
    return hashlib.md5(f"{drug}|{dds}|{scene}".encode()).hexdigest()[:8]


def _safe_filename(s: str) -> str:
    """Sanitize a string for use in a filename."""
    return "".join(c if c.isalnum() or c in ("-", "_") else "_"
                    for c in (s or "x"))[:40]


def _write_html(out_path: Path, body: str) -> Path:
    """Write a full HTML5 document with body content."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body, encoding="utf-8")
    return out_path


def _drug_class_narrative(drug_type: str) -> Dict[str, str]:
    """Drug-class-specific scientific narrative for BBB scenes.

    Returns a dict with `permeability`, `mechanism_detail`, `barrier_challenge`,
    and `pharmacology_note` strings — these are injected into C02/C03/C04
    scenes so each drug class gets pharmacologically-accurate captions
    rather than a generic template.

    References embedded in the strings:
      - Pardridge WM (2012) NeuroRx 2:3-14 (BBB pharmacology canonical review)
      - Banks WA (2016) Nat Rev Drug Discov 15:275 (CNS delivery)
      - Vlieghe P, Khrestchatisky M (2013) Med Res Rev 33:457 (peptides)
      - Crooke ST (2017) Cell Metab 26:34 (oligonucleotide PK)
    """
    dt = (drug_type or "small_molecule").lower()
    if "monoclonal" in dt or "antibody" in dt or "mab" in dt:
        return {
            "permeability":      "0.01–0.1% native BBB transit (size + charge exclusion)",
            "mechanism_detail":  "Receptor-mediated transcytosis (RMT) via FcRn or transferrin receptor",
            "barrier_challenge": "150 kDa IgG cannot diffuse across endothelium · Fc engineering required for FcRn-mediated recycling",
            "pharmacology_note": "Bivalent antigen binding · Fc-mediated effector functions · 14-21 day half-life from FcRn salvage",
            "delivery_strategy": "PEG-liposome with anti-TfR or anti-CD98hc Fab for active transcytosis",
            "clinical_example":  "Lecanemab (Leqembi 2023) · Aducanumab · Donanemab",
        }
    if "fusion_protein" in dt or "biologic_protein" in dt or "protein" in dt:
        return {
            "permeability":      "0.5–2% native BBB transit (highly variable by structure)",
            "mechanism_detail":  "Receptor-mediated transcytosis via target-specific receptor",
            "barrier_challenge": "Folded tertiary structure susceptible to denaturation · short circulation t½",
            "pharmacology_note": "Domain-engineered for receptor specificity · CSF stability constraint",
            "delivery_strategy": "Stealth-PEGylated liposome or AAV-encoded gene therapy",
            "clinical_example":  "Iduronate-2-sulfatase · Cerliponase alfa (Brineura) · TfR-fusion BBB shuttles",
        }
    if "peptide" in dt:
        return {
            "permeability":      "1–8% transit · highly sequence-dependent",
            "mechanism_detail":  "Carrier-assisted (LAT1, PEPT2) or enzymatic susceptibility-limited diffusion",
            "barrier_challenge": "Aminopeptidase / endopeptidase degradation in serum · plasma t½ <30 min",
            "pharmacology_note": "Cyclic constraint extends t½ · D-amino acid substitution improves stability",
            "delivery_strategy": "Cell-penetrating peptide (CPP) conjugate or stabilized cyclic peptide nanocarrier",
            "clinical_example":  "Octreotide · Semaglutide · Glatiramer · Bremelanotide",
        }
    if ("oligonucleotide" in dt or "antisense" in dt or "sirna" in dt
          or "aso" in dt or "mirna" in dt):
        return {
            "permeability":      "<0.01% transit · intrathecal admin generally required",
            "mechanism_detail":  "Endocytic uptake post-LNP encapsulation; ionizable lipid endosomal escape",
            "barrier_challenge": "Polyanionic backbone repels cell membrane · nuclease degradation · CSF efflux",
            "pharmacology_note": "2'-MOE phosphorothioate stabilization · GalNAc conjugation for hepatic uptake (CNS uses LNP)",
            "delivery_strategy": "Ionizable LNP (DLin-MC3-DMA / SM-102) or AAV-delivered shRNA",
            "clinical_example":  "Nusinersen (Spinraza) · Patisiran (Onpattro) · Tofersen (Qalsody) · Inotersen",
        }
    if "gene_therapy" in dt or "gene_dna" in dt or "gene_rna" in dt or "mrna" in dt:
        return {
            "permeability":      "0% as naked nucleic acid · vector-dependent transit",
            "mechanism_detail":  "AAV capsid → receptor-mediated endocytosis → nuclear import",
            "barrier_challenge": "Pre-existing anti-AAV neutralizing antibodies in 30–70% of population",
            "pharmacology_note": "Single-dose persistent expression · AAV9 crosses BBB; AAV5/AAVrh10 are CNS-targeted",
            "delivery_strategy": "AAV9 IV or intrathecal · LNP-encapsulated mRNA for transient expression",
            "clinical_example":  "Onasemnogene abeparvovec (Zolgensma) · Voretigene · Etranacogene",
        }
    # Default: small molecule
    return {
        "permeability":      "5–60% transit · LogP and TPSA driven",
        "mechanism_detail":  "Passive transcellular diffusion (Lipinski Ro5 compliant) ± P-gp efflux",
        "barrier_challenge": "P-gp / BCRP efflux pumps return drug to plasma · CYP3A4 metabolism in endothelium",
        "pharmacology_note": "Lipophilic + low MW + few HBD favors transit · Wager CNS-MPO ≥4 ideal",
        "delivery_strategy": "Stealth liposome / SLN for sustained release · PLGA for protected delivery",
        "clinical_example":  "Donepezil · Temozolomide · Memantine · Rivastigmine · Selegiline",
    }


# ──────────────────────────────────────────────────────────────────────────
# C01 — Identity Card (drug + DDS, animated, glassmorphic broadcast quality)
# ──────────────────────────────────────────────────────────────────────────
def make_c01_identity(drug_bundle: Dict, dds_bundle: Dict,
                         top_dds: Dict, out_dir: Path) -> Path:
    """C01: Animated identity card.

    Layout:
        Header bar with brand mark
        Centered: drug particle cluster ↔ connecting beam ↔ DDS carrier
        Footer: 2 glassmorphic panels with drug + DDS metadata
    """
    drug_name = drug_bundle.get("_meta", {}).get("name", "Drug")
    drug_type = drug_bundle.get("_meta", {}).get("drug_type", "small_molecule")
    dds_name  = top_dds.get("Formulation_Name", "DDS")
    carrier   = top_dds.get("Carrier_Type", "polymer")

    dp = get_drug_profile(drug_type)
    sp = get_dds_profile(carrier)

    mw       = _b_value(drug_bundle, "drug_mw", 0)
    logp     = _b_value(drug_bundle, "drug_logp", 0)
    pka      = _b_value(drug_bundle, "drug_pka_basic", 0)
    bbb      = _b_value(drug_bundle, "bbb_permeability", 0)
    half_life = _b_value(drug_bundle, "pk_halflife", 0)
    tpsa     = _b_value(drug_bundle, "drug_tpsa", 0)

    size_nm  = top_dds.get("Size_nm", 100)
    zeta     = top_dds.get("Zeta_Potential_mV", -10)
    pdi      = top_dds.get("PDI", 0.2)
    ligand   = top_dds.get("Surface_Ligand", "") or "—"

    # Phase 5 enhancement (2026-04-30): pathway-compatibility narrative
    # Pulled from orchestrator if available; otherwise generic.
    compat_reason = (top_dds.get("Compat_Reason") or
                       top_dds.get("compat_reason") or
                       "Pathway compatibility computed by orchestrator")
    compat_mult   = (top_dds.get("Compat_Multiplier") or
                       top_dds.get("compat_multiplier") or 1.0)
    composite_score = top_dds.get("Principle_Composite_Score") or top_dds.get("Composite_Score") or 0
    composite_raw   = top_dds.get("Composite_Score_Raw") or composite_score
    verdict_label   = top_dds.get("Verdict", "")

    uid = _hash_id(drug_name, dds_name, "C01")
    out_path = out_dir / f"C01_Identity_{_safe_filename(drug_name)}_{_safe_filename(dds_name)}.html"

    def fmt(v, suffix="", prec=2):
        if isinstance(v, (int, float)) and v != 0:
            return f"{v:.{prec}f}{suffix}" if isinstance(v, float) else f"{v}{suffix}"
        return "—"

    body = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CEREBRO-X · C01 Identity · {drug_name} + {dds_name}</title>
<style>{BASE_CSS}
.stage{{position:fixed;top:56px;left:0;right:0;bottom:160px}}
.footer-cards{{position:fixed;bottom:32px;left:32px;right:32px;
  display:grid;grid-template-columns:1fr 1fr;gap:16px;z-index:50}}
.footer-cards .info-card{{padding:18px 22px}}
.footer-cards .info-card.drug{{--accent:{dp["primary"]}}}
.footer-cards .info-card.dds{{--accent:{sp["outer"]}}}
.metric-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:10px}}
.metric{{padding:6px 0}}
.metric .v{{font-size:14px;font-weight:500;color:#F8FAFC;font-feature-settings:'tnum'}}
.metric .l{{font-size:9px;letter-spacing:1.5px;color:#64748B;text-transform:uppercase;
  margin-top:2px}}
</style></head><body>
<div class="cere-header">
  <div class="logo">CEREBRO-X<span class="badge">v22.1</span></div>
  <div class="scene-label">C01 · IDENTITY</div>
</div>
<canvas id="c{uid}" class="stage"></canvas>

<div style="position:fixed;bottom:230px;left:50%;transform:translateX(-50%);
              max-width:680px;z-index:60">
  <div class="info-card glass fade-in-3"
        style="--accent:{dp["primary"]};padding:14px 22px;text-align:center">
    <div style="font-size:11px;color:{dp["primary"]};letter-spacing:3px;
                  font-weight:700;text-transform:uppercase;margin-bottom:6px">
      Pathway Compatibility · Composite {composite_score:.1f} · Verdict {verdict_label}
    </div>
    <div style="font-size:11px;color:#CBD5E1;line-height:1.5">
      {compat_reason} · raw score {composite_raw:.1f} × {compat_mult:.2f}
    </div>
  </div>
</div>

<div class="footer-cards">
  <div class="info-card glass accent-left fade-in drug">
    <div class="eyebrow">Drug · {dp["narrative"]}</div>
    <div class="title">{drug_name}</div>
    <div class="body">{dp["subtitle"]}</div>
    <div class="metric-grid">
      <div class="metric"><div class="v">{fmt(mw," Da",1)}</div><div class="l">MW</div></div>
      <div class="metric"><div class="v">{fmt(logp,"")}</div><div class="l">LogP</div></div>
      <div class="metric"><div class="v">{fmt(half_life," d")}</div><div class="l">t½</div></div>
      <div class="metric"><div class="v">{fmt(pka,"")}</div><div class="l">pKa</div></div>
      <div class="metric"><div class="v">{fmt(tpsa," Å²",0)}</div><div class="l">TPSA</div></div>
      <div class="metric"><div class="v">{fmt(bbb,"%",2)}</div><div class="l">BBB</div></div>
    </div>
  </div>
  <div class="info-card glass accent-right fade-in-2 dds">
    <div class="eyebrow">Carrier · {sp["label"]}</div>
    <div class="title">{dds_name}</div>
    <div class="body">{sp["subtitle"]}</div>
    <div class="metric-grid">
      <div class="metric"><div class="v">{size_nm}</div><div class="l">Size (nm)</div></div>
      <div class="metric"><div class="v">{zeta}</div><div class="l">ζ (mV)</div></div>
      <div class="metric"><div class="v">{pdi}</div><div class="l">PDI</div></div>
      <div class="metric" style="grid-column:span 3"><div class="v" style="font-size:12px">{ligand.title()}</div><div class="l">Surface ligand</div></div>
    </div>
  </div>
</div>
<script>{JS_DRAW_PRIMITIVES}
const {{cnv,ctx,getW,getH}} = setupCanvas('c{uid}');
const DRUG = {{
  shape:    "{dp["shape"]}",
  size:     {dp["size_px"]},
  primary:  "{dp["primary"]}",
  secondary:"{dp["secondary"]}",
  glow:     "{dp["glow"]}"
}};
const DDS = {{
  shape:    "{sp["shape"]}",
  outer:    "{sp["outer"]}",
  inner:    "{sp["inner"]}",
  highlight:"{sp["highlight"]}"
}};

let t0 = performance.now();
function loop(){{
  const t = performance.now() - t0;
  const W = getW(); const H = getH();

  // Background gradient wash
  const bg = ctx.createRadialGradient(W*0.5, H*0.5, 0, W*0.5, H*0.5, Math.max(W,H));
  bg.addColorStop(0, "#0a1628");
  bg.addColorStop(1, "#020817");
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, W, H);

  // Atmosphere — depth illusion
  drawAtmosphere(ctx, W, H, t, 60);

  // Layout
  const cy = H * 0.50;
  const drugX = W * 0.30;
  const ddsX  = W * 0.70;

  // Drug particle CLUSTER on left (rotating around center)
  // Cluster builds in over first 1.5s, then orbits gently.
  const clusterTime = Math.min(1.5, t/1000);
  const clusterReveal = easeOutCubic(clusterTime / 1.5);
  ctx.globalAlpha = clusterReveal;
  for(let i = 0; i < 10; i++){{
    const a = i*Math.PI*2/10 + t*0.0005;
    const r = 60 + Math.sin(t*0.001 + i)*10;
    drawDrug(ctx, DRUG.shape, drugX + Math.cos(a)*r, cy + Math.sin(a)*r,
              DRUG.size*0.85, DRUG.primary, DRUG.secondary, DRUG.glow, t,
              i*0.3 + t*0.001);
  }}
  // Central drug particle (larger, with halo)
  const haloR = 28 + Math.sin(t*0.002)*4;
  const halo = ctx.createRadialGradient(drugX, cy, 0, drugX, cy, haloR*1.8);
  halo.addColorStop(0, DRUG.glow);
  halo.addColorStop(1, "transparent");
  ctx.fillStyle = halo;
  ctx.beginPath(); ctx.arc(drugX, cy, haloR*1.8, 0, Math.PI*2); ctx.fill();
  drawDrug(ctx, DRUG.shape, drugX, cy, DRUG.size*1.4,
            DRUG.primary, DRUG.secondary, DRUG.glow, t, t*0.0008);
  ctx.globalAlpha = 1;

  // DDS CARRIER on right (with subtle pulse + soft rotation if applicable)
  const carrierAlpha = Math.min(1, Math.max(0, (t - 800)/1000));    // appears ~0.8s in
  ctx.globalAlpha = carrierAlpha;
  const ddsR = Math.min(95, W*0.085) * (1 + 0.025*Math.sin(t*0.0015));
  drawDDS(ctx, DDS.shape, ddsX, cy, ddsR,
           DDS.outer, DDS.inner, DDS.highlight, t);
  ctx.globalAlpha = 1;

  // Connecting beam (drug → DDS encapsulation)
  const beamAlpha = Math.min(0.8, Math.max(0, (t - 1600)/1500));
  if(beamAlpha > 0.05){{
    ctx.strokeStyle = DRUG.primary + Math.floor(beamAlpha*180).toString(16).padStart(2,'0');
    ctx.lineWidth = 1.5;
    ctx.setLineDash([5, 7]);
    ctx.lineDashOffset = -t*0.04;
    ctx.beginPath();
    ctx.moveTo(drugX + 60, cy);
    ctx.lineTo(ddsX - ddsR - 8, cy);
    ctx.stroke();
    ctx.setLineDash([]);

    // Encapsulation flow — small drug particles streaming toward DDS
    if(beamAlpha > 0.5){{
      for(let i = 0; i < 4; i++){{
        const u = ((t*0.0003 + i*0.25) % 1);
        const x = drugX + 60 + (ddsX - ddsR - 8 - drugX - 60) * u;
        const fade = Math.sin(u*Math.PI);
        ctx.fillStyle = DRUG.primary;
        ctx.globalAlpha = fade * 0.8;
        ctx.beginPath();
        ctx.arc(x, cy, 2.5, 0, Math.PI*2);
        ctx.fill();
      }}
      ctx.globalAlpha = 1;
    }}
  }}

  // Section labels
  ctx.fillStyle = "#475569";
  ctx.font = "10px 'Inter', sans-serif";
  ctx.textAlign = "center";
  ctx.fillText("DRUG", drugX, cy + 110);
  ctx.fillText("CARRIER", ddsX, cy + ddsR + 28);
  ctx.fillStyle = DRUG.primary + "AA";
  ctx.font = "9px 'Inter', sans-serif";
  ctx.fillText("encapsulation", (drugX + ddsX)/2, cy - 10);

  requestAnimationFrame(loop);
}}
loop();
</script></body></html>"""
    return _write_html(out_path, body)


# ──────────────────────────────────────────────────────────────────────────
# C02 — BBB Crossing (anatomically accurate barrier model)
# ──────────────────────────────────────────────────────────────────────────
def make_c02_bbb_crossing(drug_bundle: Dict, dds_bundle: Dict,
                              top_dds: Dict, out_dir: Path) -> Path:
    """C02: BBB crossing scene with anatomically-accurate barrier.

    Features:
        • Endothelial cell membrane (true bilayer, ~50 nm scale ratio)
        • Tight junction proteins (claudin-5, occludin, ZO-1) visualized
        • Astrocyte foot processes on brain side
        • Drug particles attempt crossing — succeed or bounce based on
          ligand-mediated uptake efficiency from LIGAND_RECEPTOR_MAP
        • Mechanism narrative changes based on drug type + ligand
    """
    drug_name = drug_bundle.get("_meta", {}).get("name", "Drug")
    drug_type = drug_bundle.get("_meta", {}).get("drug_type", "small_molecule")
    dds_name  = top_dds.get("Formulation_Name", "DDS")
    carrier   = top_dds.get("Carrier_Type", "polymer")
    ligand    = top_dds.get("Surface_Ligand", "") or ""

    dp = get_drug_profile(drug_type)
    sp = get_dds_profile(carrier)
    li = get_ligand_info(ligand)
    # Phase 5 enhancement (2026-04-30): drug-class scientific narrative
    nrv = _drug_class_narrative(drug_type)

    bbb_native = _b_value(drug_bundle, "bbb_permeability", 5.0)
    if not isinstance(bbb_native, (int, float)): bbb_native = 5.0

    # Compute carrier-enhanced BBB% (native + ligand boost)
    boost = li["uptake_efficiency"] * 100
    bbb_enhanced = min(95, bbb_native + boost)
    success_rate = min(0.95, bbb_enhanced / 100)

    uid = _hash_id(drug_name, dds_name, "C02")
    out_path = out_dir / f"C02_BBB_{_safe_filename(drug_name)}_{_safe_filename(dds_name)}.html"

    body = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CEREBRO-X · C02 BBB · {drug_name} + {dds_name}</title>
<style>{BASE_CSS}
.stage{{position:fixed;top:56px;left:0;right:0;bottom:140px}}
.left-info{{position:fixed;top:80px;left:32px;max-width:340px;z-index:50;
  --accent:{dp["primary"]}}}
.right-info{{position:fixed;top:80px;right:32px;max-width:300px;z-index:50;
  --accent:{sp["outer"]};text-align:right}}
.right-info .info-card{{border-right:2px solid var(--accent);border-left:none}}
.stat-row.bottom{{bottom:90px}}
.mech-banner{{position:fixed;bottom:32px;left:32px;right:32px;z-index:50}}
.mech-banner .info-card{{padding:14px 22px;text-align:center;
  --accent:{dp["primary"]};border:1px solid {dp["primary"]}30}}
.mech-banner .mech-title{{font-size:13px;color:{dp["primary"]};letter-spacing:3px;
  text-transform:uppercase;font-weight:600;margin-bottom:4px}}
.mech-banner .mech-body{{font-size:11px;color:#94A3B8;line-height:1.5}}
.mech-banner .mech-body em{{color:#CBD5E1;font-style:normal;font-weight:500}}
</style></head><body>
<div class="cere-header">
  <div class="logo">CEREBRO-X<span class="badge">v22.1</span></div>
  <div class="scene-label">C02 · BBB CROSSING</div>
</div>

<canvas id="c{uid}" class="stage"></canvas>

<div class="left-info">
  <div class="info-card glass accent-left fade-in">
    <div class="eyebrow">Approaching Side · Blood</div>
    <div class="title">{drug_name}</div>
    <div class="body">Native BBB <b>{bbb_native:.2f}%</b> · with carrier <b style="color:{dp["primary"]}">{bbb_enhanced:.1f}%</b><br/>
    Mechanism: {li["mechanism"]}</div>
  </div>
</div>

<div class="right-info">
  <div class="info-card glass accent-right fade-in-2">
    <div class="eyebrow">Target Side · Brain</div>
    <div class="title">CNS Parenchyma</div>
    <div class="body">Receptor: <b>{li["receptor"]}</b><br/>
    Astrocyte end-feet · Pericytes · Neuron targeting</div>
  </div>
</div>

<div class="stat-row bottom fade-in-3">
  <div class="stat-pill">Tight junctions<b>Claudin-5 · Occludin · ZO-1</b></div>
  <div class="stat-pill">Endothelium<b>~ 50 nm thick</b></div>
  <div class="stat-pill">Surface ligand<b>{ligand or '—'}</b></div>
  <div class="stat-pill">Uptake efficiency<b>{li["uptake_efficiency"]*100:.0f}%</b></div>
</div>

<div class="mech-banner fade-in-3">
  <div class="info-card glass">
    <div class="mech-title">Pathway-Specific Crossing Mechanism</div>
    <div class="mech-body">
      <em>Native permeability:</em> {nrv["permeability"]}<br/>
      <em>Mechanism:</em> {nrv["mechanism_detail"]}<br/>
      <em>Barrier challenge:</em> {nrv["barrier_challenge"]}<br/>
      <em>Delivery strategy:</em> {nrv["delivery_strategy"]}<br/>
      <em>Ligand uptake:</em> {li["mechanism"]} · {li["literature"]}<br/>
      <em>Clinical analogs:</em> {nrv["clinical_example"]}
    </div>
  </div>
</div>

<script>{JS_DRAW_PRIMITIVES}
const {{cnv,ctx,getW,getH}} = setupCanvas('c{uid}');
const DRUG = {{
  shape:"{dp["shape"]}", size:{dp["size_px"]},
  primary:"{dp["primary"]}", secondary:"{dp["secondary"]}", glow:"{dp["glow"]}"
}};
const DDS = {{outer:"{sp["outer"]}", inner:"{sp["inner"]}", highlight:"{sp["highlight"]}"}};
const SUCCESS_RATE = {success_rate:.4f};
const SPEED = {dp["speed"]:.2f};
const N_PARTICLES = {min(50, dp["n_particles"])};

// Particle pool
const particles = [];
for(let i=0; i<N_PARTICLES; i++){{
  particles.push({{
    x: -30 - Math.random()*200,
    y: 0,                // set after canvas sizes
    vx: 0.6 + Math.random()*1.4,
    vy: 0,
    size: DRUG.size*(0.85 + Math.random()*0.3),
    state: 'approaching',     // approaching | bouncing | crossing | drifting
    bounceVy: 0,
    fade: 1.0,
    phase: Math.random()*Math.PI*2,
    rot: Math.random()*Math.PI*2,
  }});
}}

// Draw BBB anatomy: blood ↔ endothelium bilayer ↔ basement membrane ↔ astrocytes ↔ brain
function drawBBBAnatomy(t){{
  const W = getW(); const H = getH();
  const bbbX = W*0.5;          // center of barrier
  const bbbW = 80;              // total barrier width on screen

  // Region backgrounds
  // Blood side (left) — warm red wash
  const bloodGrad = ctx.createLinearGradient(0,0,bbbX,0);
  bloodGrad.addColorStop(0, "rgba(239,68,68,0.04)");
  bloodGrad.addColorStop(1, "rgba(239,68,68,0.08)");
  ctx.fillStyle = bloodGrad;
  ctx.fillRect(0, 0, bbbX, H);
  // Brain side (right) — cool blue wash
  const brainGrad = ctx.createLinearGradient(bbbX,0,W,0);
  brainGrad.addColorStop(0, "rgba(59,130,246,0.06)");
  brainGrad.addColorStop(1, "rgba(59,130,246,0.04)");
  ctx.fillStyle = brainGrad;
  ctx.fillRect(bbbX, 0, W, H);

  // Endothelial cell layer (the actual BBB)
  const endoX1 = bbbX - bbbW/2;
  const endoX2 = bbbX + bbbW/2;
  // Outer membrane (apical, blood side)
  const apicalGrad = ctx.createLinearGradient(endoX1, 0, endoX1+10, 0);
  apicalGrad.addColorStop(0, "rgba(255,255,255,0.05)");
  apicalGrad.addColorStop(1, "rgba(255,255,255,0.18)");
  ctx.fillStyle = apicalGrad;
  ctx.fillRect(endoX1, 0, 10, H);
  // Cell cytoplasm
  ctx.fillStyle = "rgba(148,163,184,0.05)";
  ctx.fillRect(endoX1+10, 0, bbbW-20, H);
  // Inner membrane (basolateral, brain side)
  const basoGrad = ctx.createLinearGradient(endoX2-10, 0, endoX2, 0);
  basoGrad.addColorStop(0, "rgba(255,255,255,0.18)");
  basoGrad.addColorStop(1, "rgba(255,255,255,0.05)");
  ctx.fillStyle = basoGrad;
  ctx.fillRect(endoX2-10, 0, 10, H);

  // Tight junction interlocks (every 60 px vertically)
  ctx.strokeStyle = "{sp["outer"]}";
  ctx.lineWidth = 1.5;
  for(let y = 30; y < H-30; y += 60){{
    // Claudin-5 zigzag interlock
    ctx.beginPath();
    ctx.moveTo(endoX1+12, y);
    ctx.lineTo(bbbX-3, y+8);
    ctx.lineTo(bbbX+3, y+16);
    ctx.lineTo(endoX2-12, y+24);
    ctx.stroke();
  }}

  // Endothelial cell nuclei (every 200 px)
  for(let y = 100; y < H-100; y += 200){{
    const nucX = bbbX + Math.sin(y*0.05 + t*0.0005)*8;
    ctx.fillStyle = "rgba(96,165,250,0.18)";
    ctx.beginPath();
    ctx.ellipse(nucX, y, 8, 12, 0, 0, Math.PI*2);
    ctx.fill();
    ctx.strokeStyle = "rgba(96,165,250,0.35)";
    ctx.lineWidth = 1;
    ctx.stroke();
  }}

  // Astrocyte end-feet (brain side, at endoX2)
  ctx.strokeStyle = "rgba(167,139,250,0.25)";
  ctx.lineWidth = 1.2;
  for(let y = 0; y < H; y += 25){{
    ctx.beginPath();
    ctx.moveTo(endoX2 + 2, y);
    ctx.lineTo(endoX2 + 18 + Math.sin(y*0.3 + t*0.001)*4, y + 10);
    ctx.stroke();
  }}

  // Labels
  ctx.fillStyle = "rgba(239,68,68,0.55)";
  ctx.font = "10px 'Inter', sans-serif";
  ctx.textAlign = "left";
  ctx.fillText("BLOOD · arterial side", 32, 80);
  ctx.fillStyle = "rgba(59,130,246,0.55)";
  ctx.textAlign = "right";
  ctx.fillText("BRAIN · CNS parenchyma", W-32, 80);
  ctx.textAlign = "center";
  ctx.fillStyle = "rgba(255,255,255,0.45)";
  ctx.font = "9px 'Inter', sans-serif";
  ctx.save();
  ctx.translate(bbbX + 40, H*0.18);
  ctx.rotate(-Math.PI/2);
  ctx.fillText("Endothelial bilayer · TJ proteins", 0, 0);
  ctx.restore();
}}

let t0 = performance.now();
function loop(){{
  const t = performance.now() - t0;
  const W = getW(); const H = getH();
  // Trail-fade background
  ctx.fillStyle = "rgba(2,8,23,0.18)";
  ctx.fillRect(0, 0, W, H);

  drawBBBAnatomy(t);
  drawAtmosphere(ctx, W, H, t, 25);

  // Update and draw particles
  particles.forEach((p, i) => {{
    if(p.y === 0) p.y = H*0.25 + Math.random()*H*0.5;     // initial position
    const bbbX = W*0.5;
    const bbbW = 80;

    if(p.state === 'approaching'){{
      p.x += p.vx*SPEED;
      p.y += Math.sin(p.phase + t*0.002)*0.6;
      p.rot += 0.005;
      // Decision at BBB entry
      if(p.x >= bbbX - bbbW/2 - 2){{
        if(Math.random() < SUCCESS_RATE){{
          p.state = 'crossing';
          p.crossingT = t;
        }} else {{
          p.state = 'bouncing';
          p.vx = -1.0 - Math.random()*0.5;
          p.bounceVy = (Math.random() - 0.5) * 1.2;
        }}
      }}
    }} else if(p.state === 'bouncing'){{
      p.x += p.vx*SPEED;
      p.y += p.bounceVy;
      p.fade *= 0.995;
      if(p.x < -50 || p.fade < 0.1){{
        // Reset to start
        p.x = -30 - Math.random()*200;
        p.y = H*0.25 + Math.random()*H*0.5;
        p.vx = 0.6 + Math.random()*1.4;
        p.state = 'approaching';
        p.fade = 1.0;
      }}
    }} else if(p.state === 'crossing'){{
      // Slow pass through endothelium
      const u = Math.min(1, (t - p.crossingT)/2000);     // 2s to cross
      p.x = bbbX - bbbW/2 + bbbW * easeInOutCubic(u);
      p.y += Math.sin(p.phase + t*0.001)*0.2;
      if(u >= 1){{
        p.state = 'drifting';
        p.vx = 0.8 + Math.random()*0.6;
      }}
    }} else if(p.state === 'drifting'){{
      p.x += p.vx*SPEED*0.5;
      p.y += Math.sin(p.phase + t*0.001)*0.4;
      p.fade *= 0.998;
      if(p.x > W+50 || p.fade < 0.1){{
        p.x = -30 - Math.random()*200;
        p.y = H*0.25 + Math.random()*H*0.5;
        p.vx = 0.6 + Math.random()*1.4;
        p.state = 'approaching';
        p.fade = 1.0;
      }}
    }}

    ctx.globalAlpha = p.fade;
    drawDrug(ctx, DRUG.shape, p.x, p.y, p.size,
              DRUG.primary, DRUG.secondary, DRUG.glow, t, p.rot);
    ctx.globalAlpha = 1;
  }});

  requestAnimationFrame(loop);
}}
loop();
</script></body></html>"""
    return _write_html(out_path, body)


# ──────────────────────────────────────────────────────────────────────────
# C03 — PK Profile (animated time course)
# ──────────────────────────────────────────────────────────────────────────
def make_c03_pk_profile(drug_bundle: Dict, dds_bundle: Dict,
                            top_dds: Dict, out_dir: Path) -> Path:
    """C03: Pharmacokinetic time course with plasma + brain ISF curves."""
    import math
    drug_name = drug_bundle.get("_meta", {}).get("name", "Drug")
    drug_type = drug_bundle.get("_meta", {}).get("drug_type", "small_molecule")
    dds_name  = top_dds.get("Formulation_Name", "DDS")

    dp = get_drug_profile(drug_type)
    nrv = _drug_class_narrative(drug_type)
    half_life = _b_value(drug_bundle, "pk_halflife", 1.0)
    if not isinstance(half_life, (int, float)) or half_life <= 0:
        half_life = 1.0

    bbb_pct = _b_value(drug_bundle, "bbb_permeability", 5.0)
    if not isinstance(bbb_pct, (int, float)): bbb_pct = 5.0

    # Synthesize PBPK-like time course (1st-order absorption + elimination)
    n_pts = 200
    t_max_h = float(half_life) * 24 * 3
    ka = 1.5
    ke = math.log(2) / max(0.5, half_life * 24)
    times = [t_max_h * i / (n_pts - 1) for i in range(n_pts)]
    dose = 100.0
    if abs(ka - ke) > 1e-6:
        plasma = [dose * ka / (ka - ke) * (math.exp(-ke*t) - math.exp(-ka*t))
                    for t in times]
    else:
        plasma = [dose * t * math.exp(-ke*t) for t in times]
    # Brain ISF: lag-shifted & scaled by BBB%
    brain_ratio = max(0.005, bbb_pct/100.0)
    brain = []
    for i, t in enumerate(times):
        # Lag of 0.5h, dampened
        eff_t = max(0, t - 0.5)
        lag_factor = 1 - math.exp(-eff_t * 0.4)
        bv = plasma[i] * brain_ratio * lag_factor * 4
        brain.append(bv)

    cmax_p = max(plasma) if plasma else 1
    cmax_b = max(brain) if brain else 0.001
    auc_p = sum(plasma) * (t_max_h / n_pts)
    auc_b = sum(brain) * (t_max_h / n_pts)

    uid = _hash_id(drug_name, dds_name, "C03")
    out_path = out_dir / f"C03_PK_{_safe_filename(drug_name)}_{_safe_filename(dds_name)}.html"

    body = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CEREBRO-X · C03 PK · {drug_name} + {dds_name}</title>
<style>{BASE_CSS}
.stage{{position:fixed;top:56px;left:0;right:0;bottom:120px}}
.legend{{position:fixed;bottom:32px;left:32px;right:32px;display:flex;
  gap:32px;justify-content:center;align-items:center;flex-wrap:wrap;z-index:50}}
.legend-item{{display:flex;align-items:center;gap:10px;font-size:12px;color:#CBD5E1}}
.legend-item .swatch{{width:22px;height:3px;border-radius:2px}}
.legend-item b{{color:#F8FAFC;font-weight:500}}
.pk-stats{{position:fixed;top:80px;right:32px;z-index:50;max-width:280px}}
.pk-stats .info-card{{padding:14px 18px;--accent:{dp["primary"]}}}
.pk-stats table{{width:100%;font-size:11px;color:#CBD5E1;
  border-collapse:collapse;margin-top:6px;font-feature-settings:'tnum'}}
.pk-stats td{{padding:4px 0}}
.pk-stats td:last-child{{text-align:right;color:#F8FAFC;font-weight:500}}
.pk-title{{position:fixed;top:80px;left:32px;z-index:50;max-width:340px}}
.pk-title .info-card{{padding:14px 18px;--accent:{dp["primary"]}}}
</style></head><body>
<div class="cere-header">
  <div class="logo">CEREBRO-X<span class="badge">v22.1</span></div>
  <div class="scene-label">C03 · PHARMACOKINETICS</div>
</div>

<div class="pk-title">
  <div class="info-card glass accent-left fade-in">
    <div class="eyebrow">Time Course · {dp["narrative"]}</div>
    <div class="title">{drug_name} + {dds_name}</div>
    <div class="body">First-order absorption + elimination<br/>Brain ISF lagged + BBB%-scaled</div>
  </div>
</div>

<div class="pk-stats">
  <div class="info-card glass accent-right fade-in-2">
    <div class="eyebrow">PK Parameters</div>
    <table>
      <tr><td>Half-life</td><td>{half_life:.2f} d</td></tr>
      <tr><td>Plasma C_max</td><td>{cmax_p:.2f} μg/mL</td></tr>
      <tr><td>Brain C_max</td><td>{cmax_b:.4f} μg/mL</td></tr>
      <tr><td>AUC plasma</td><td>{auc_p:.1f}</td></tr>
      <tr><td>AUC brain</td><td>{auc_b:.2f}</td></tr>
      <tr><td>Brain/Plasma</td><td>{(auc_b/max(auc_p,1e-9))*100:.2f}%</td></tr>
    </table>
  </div>
</div>

<canvas id="c{uid}" class="stage"></canvas>

<div class="legend">
  <div class="legend-item"><div class="swatch" style="background:#EF4444"></div><b>Plasma</b> (systemic)</div>
  <div class="legend-item"><div class="swatch" style="background:{dp["primary"]}"></div><b>Brain ISF</b> (CNS)</div>
  <div class="legend-item"><div class="swatch" style="background:#94A3B8;opacity:0.5"></div>Therapeutic threshold</div>
</div>

<div style="position:fixed;top:54%;left:50%;transform:translate(-50%,0);
              max-width:580px;z-index:30">
  <div class="info-card glass accent-left fade-in-3"
        style="--accent:{dp["primary"]};padding:14px 18px;font-size:11px;
                color:#94A3B8;line-height:1.5">
    <div style="font-size:12px;color:{dp["primary"]};letter-spacing:2px;
                  font-weight:600;margin-bottom:6px;text-transform:uppercase">
      Pharmacokinetic Notes — {nrv["delivery_strategy"][:60]}
    </div>
    <em style="color:#CBD5E1;font-style:normal">{nrv["pharmacology_note"]}</em>
  </div>
</div>

<script>{JS_DRAW_PRIMITIVES}
const {{cnv,ctx,getW,getH}} = setupCanvas('c{uid}');
const TIMES  = {json.dumps([round(t,3) for t in times])};
const PLASMA = {json.dumps([round(p,4) for p in plasma])};
const BRAIN  = {json.dumps([round(b,5) for b in brain])};
const TMAX   = {t_max_h:.2f};
const CMAX   = {max(cmax_p, 0.01):.4f};
const DRUG_COLOR = "{dp["primary"]}";
const DRUG_GLOW  = "{dp["glow"]}";

let progress = 0;
let cycleCount = 0;

function loop(){{
  const t = performance.now();
  // Linear ramp 0→1 over 4s, then loop
  progress = Math.min(1, progress + 0.0042);

  const W = getW(); const H = getH();
  ctx.fillStyle = "rgba(2,8,23,0.18)";
  ctx.fillRect(0, 0, W, H);
  drawAtmosphere(ctx, W, H, t, 30);

  // Plot box
  const padL = 90, padR = 50, padT = 30, padB = 50;
  const pW = W - padL - padR;
  const pH = H - padT - padB;

  // Grid
  ctx.strokeStyle = "rgba(148,163,184,0.08)";
  ctx.lineWidth = 1;
  for(let i=0; i<=10; i++){{
    const x = padL + pW*i/10;
    ctx.beginPath(); ctx.moveTo(x, padT); ctx.lineTo(x, padT+pH); ctx.stroke();
    const y = padT + pH*i/10;
    ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(padL+pW, y); ctx.stroke();
  }}

  // Therapeutic threshold (dashed at 40% Cmax)
  const therY = padT + pH*0.6;
  ctx.setLineDash([5, 5]);
  ctx.strokeStyle = "rgba(148,163,184,0.45)";
  ctx.lineWidth = 1.2;
  ctx.beginPath(); ctx.moveTo(padL, therY); ctx.lineTo(padL+pW, therY); ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = "rgba(148,163,184,0.55)";
  ctx.font = "9px 'Inter', sans-serif";
  ctx.textAlign = "left";
  ctx.fillText("threshold (40% Cmax)", padL + 8, therY - 4);

  // Axis labels
  ctx.fillStyle = "#64748B";
  ctx.font = "10px 'Inter', sans-serif";
  ctx.textAlign = "center";
  for(let i=0; i<=5; i++){{
    const tv = TMAX * i/5;
    const x = padL + pW*i/5;
    ctx.fillText(tv.toFixed(1) + " h", x, padT + pH + 18);
  }}
  ctx.textAlign = "right";
  for(let i=0; i<=5; i++){{
    const cv = CMAX * (1 - i/5);
    const y = padT + pH*i/5;
    ctx.fillText(cv.toFixed(2), padL - 10, y + 3);
  }}
  ctx.textAlign = "center";
  ctx.fillStyle = "#94A3B8";
  ctx.fillText("Time (hours)", padL + pW/2, padT + pH + 38);
  ctx.save();
  ctx.translate(20, padT + pH/2);
  ctx.rotate(-Math.PI/2);
  ctx.fillText("Concentration (μg/mL)", 0, 0);
  ctx.restore();

  // Compute n_visible from progress
  const nVis = Math.floor(TIMES.length * progress);

  // Plasma curve (red)
  ctx.strokeStyle = "#EF4444";
  ctx.lineWidth = 2.5;
  ctx.shadowColor = "rgba(239,68,68,0.5)";
  ctx.shadowBlur = 8;
  ctx.beginPath();
  for(let i=0; i<nVis; i++){{
    const x = padL + pW * TIMES[i]/TMAX;
    const y = padT + pH * (1 - PLASMA[i]/CMAX);
    if(i===0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }}
  ctx.stroke();
  ctx.shadowBlur = 0;

  // Brain area fill
  ctx.fillStyle = DRUG_COLOR + "20";
  ctx.beginPath();
  ctx.moveTo(padL, padT + pH);
  for(let i=0; i<nVis; i++){{
    const x = padL + pW * TIMES[i]/TMAX;
    const y = padT + pH * (1 - BRAIN[i]/CMAX);
    ctx.lineTo(x, y);
  }}
  if(nVis > 0){{
    ctx.lineTo(padL + pW * TIMES[nVis-1]/TMAX, padT + pH);
  }}
  ctx.closePath();
  ctx.fill();

  // Brain curve (drug color)
  ctx.strokeStyle = DRUG_COLOR;
  ctx.lineWidth = 2.5;
  ctx.shadowColor = DRUG_GLOW;
  ctx.shadowBlur = 8;
  ctx.beginPath();
  for(let i=0; i<nVis; i++){{
    const x = padL + pW * TIMES[i]/TMAX;
    const y = padT + pH * (1 - BRAIN[i]/CMAX);
    if(i===0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }}
  ctx.stroke();
  ctx.shadowBlur = 0;

  // Tip markers (current point)
  if(nVis > 0){{
    const i = nVis - 1;
    const x = padL + pW * TIMES[i]/TMAX;
    // Plasma marker
    const yp = padT + pH * (1 - PLASMA[i]/CMAX);
    ctx.fillStyle = "#EF4444";
    ctx.shadowColor = "rgba(239,68,68,0.8)";
    ctx.shadowBlur = 12;
    ctx.beginPath(); ctx.arc(x, yp, 4, 0, Math.PI*2); ctx.fill();
    // Brain marker
    const yb = padT + pH * (1 - BRAIN[i]/CMAX);
    ctx.fillStyle = DRUG_COLOR;
    ctx.shadowColor = DRUG_GLOW;
    ctx.beginPath(); ctx.arc(x, yb, 4, 0, Math.PI*2); ctx.fill();
    ctx.shadowBlur = 0;
  }}

  // Cycle counter
  if(progress >= 1){{
    progress = 0;
    cycleCount++;
  }}

  requestAnimationFrame(loop);
}}
loop();
</script></body></html>"""
    return _write_html(out_path, body)


# ──────────────────────────────────────────────────────────────────────────
# C04 — Release Mechanics (carrier-specific dynamics)
# ──────────────────────────────────────────────────────────────────────────
def make_c04_release(drug_bundle: Dict, dds_bundle: Dict,
                       top_dds: Dict, out_dir: Path) -> Path:
    """C04: Release mechanics scene with carrier-specific kinetics."""
    drug_name = drug_bundle.get("_meta", {}).get("name", "Drug")
    drug_type = drug_bundle.get("_meta", {}).get("drug_type", "small_molecule")
    dds_name  = top_dds.get("Formulation_Name", "DDS")
    carrier   = top_dds.get("Carrier_Type", "polymer")
    rel_kin   = (top_dds.get("Release_Kinetics", "sustained") or "sustained").lower()
    drug_load = top_dds.get("Drug_Loading_Pct", 10)
    ph_trig   = top_dds.get("pH_Trigger", 7.0)

    dp = get_drug_profile(drug_type)
    sp = get_dds_profile(carrier)

    # Compute release time constant (s) based on kinetics
    if "burst" in rel_kin: tau_s = 2.0
    elif "sustained" in rel_kin: tau_s = 12.0
    elif "pulsatile" in rel_kin or "ph" in rel_kin: tau_s = 6.0
    else: tau_s = 8.0

    uid = _hash_id(drug_name, dds_name, "C04")
    out_path = out_dir / f"C04_Release_{_safe_filename(drug_name)}_{_safe_filename(dds_name)}.html"

    body = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CEREBRO-X · C04 Release · {drug_name} + {dds_name}</title>
<style>{BASE_CSS}
.stage{{position:fixed;top:56px;left:0;right:0;bottom:140px}}
.left-info{{position:fixed;top:80px;left:32px;max-width:320px;z-index:50;
  --accent:{sp["outer"]}}}
.right-info{{position:fixed;top:80px;right:32px;max-width:280px;z-index:50;
  --accent:{dp["primary"]};text-align:right}}
.right-info .info-card{{border-right:2px solid var(--accent);border-left:none;
  text-align:left}}
.bottom-bar{{position:fixed;bottom:32px;left:32px;right:32px;z-index:50}}
.bottom-bar .info-card{{padding:14px 22px;--accent:{dp["primary"]};
  border:1px solid {dp["primary"]}30}}
.bottom-bar .mech-text{{font-size:12px;color:#CBD5E1;line-height:1.6;font-style:italic}}
.bottom-bar .mech-tag{{font-size:10px;letter-spacing:3px;color:{dp["primary"]};
  text-transform:uppercase;font-weight:600;margin-bottom:6px}}
</style></head><body>
<div class="cere-header">
  <div class="logo">CEREBRO-X<span class="badge">v22.1</span></div>
  <div class="scene-label">C04 · RELEASE MECHANICS</div>
</div>

<div class="left-info">
  <div class="info-card glass accent-left fade-in">
    <div class="eyebrow">{sp["label"]}</div>
    <div class="title">{dds_name}</div>
    <div class="body">{sp["mech_subtitle"]}<br/>
    Drug load <b>{drug_load}% w/w</b> · Trigger pH <b>{ph_trig}</b></div>
  </div>
</div>

<div class="right-info">
  <div class="info-card glass fade-in-2">
    <div class="eyebrow">Payload</div>
    <div class="title" style="color:{dp["primary"]}">{drug_name}</div>
    <div class="body">{dp["narrative"]}<br/>Kinetics: <b>{rel_kin}</b></div>
  </div>
</div>

<canvas id="c{uid}" class="stage"></canvas>

<div class="bottom-bar fade-in-3">
  <div class="info-card glass">
    <div class="mech-tag">Release Mechanism · {sp["release"]}</div>
    <div class="mech-text">{sp["release_text"]}</div>
  </div>
</div>

<script>{JS_DRAW_PRIMITIVES}
const {{cnv,ctx,getW,getH}} = setupCanvas('c{uid}');
const DRUG = {{
  shape:"{dp["shape"]}", size:{dp["size_px"]},
  primary:"{dp["primary"]}", secondary:"{dp["secondary"]}", glow:"{dp["glow"]}"
}};
const DDS = {{
  shape:"{sp["shape"]}", outer:"{sp["outer"]}", inner:"{sp["inner"]}",
  highlight:"{sp["highlight"]}"
}};
const TAU_MS = {tau_s * 1000:.0f};
const N_PARTICLES = 50;
let particles = [];
let cycleStart = performance.now();

function spawnParticles(cx, cy, R){{
  particles = [];
  for(let i=0; i<N_PARTICLES; i++){{
    const a = Math.random()*Math.PI*2;
    const r = Math.sqrt(Math.random()) * R*0.65;
    particles.push({{
      x: cx + Math.cos(a)*r, y: cy + Math.sin(a)*r,
      orbit_a: a, orbit_r: r,
      vx: 0, vy: 0,
      released: false,
      releaseT: 0,
      fade: 1,
      phase: Math.random()*Math.PI*2,
      rot: Math.random()*Math.PI*2,
    }});
  }}
}}

function loop(){{
  const t = performance.now();
  const W = getW(); const H = getH();
  ctx.fillStyle = "rgba(2,8,23,0.16)";
  ctx.fillRect(0, 0, W, H);
  drawAtmosphere(ctx, W, H, t, 35);

  const cx = W/2;
  const cy = H/2;
  const R = Math.min(140, W*0.13);

  if(particles.length === 0) spawnParticles(cx, cy, R);

  const elapsed = t - cycleStart;
  const cycleProgress = Math.min(1, elapsed / TAU_MS);

  // Carrier morphology — pulsing breath
  const pulse = 1 + 0.04*Math.sin(t*0.0012);
  drawDDS(ctx, DDS.shape, cx, cy, R*pulse,
           DDS.outer, DDS.inner, DDS.highlight, t);

  // Update + draw particles
  particles.forEach(p => {{
    if(!p.released){{
      // Release probability ramps up with cycle progress
      const releaseProb = cycleProgress*0.04;
      if(Math.random() < releaseProb){{
        p.released = true;
        p.releaseT = t;
        // Radial outward velocity
        const a = Math.atan2(p.y - cy, p.x - cx);
        const speed = 0.6 + Math.random()*1.4;
        p.vx = Math.cos(a)*speed;
        p.vy = Math.sin(a)*speed;
      }} else {{
        // Slight breathing motion within carrier
        p.orbit_a += 0.005;
        const r2 = p.orbit_r * pulse;
        p.x = cx + Math.cos(p.orbit_a)*r2 + Math.sin(p.phase + t*0.001)*1.5;
        p.y = cy + Math.sin(p.orbit_a)*r2 + Math.cos(p.phase + t*0.001)*1.5;
      }}
    }} else {{
      // Released — drift outward
      p.x += p.vx;
      p.y += p.vy;
      p.rot += 0.01;
      p.fade *= 0.992;
      // Distance from center
      const dx = p.x - cx, dy = p.y - cy;
      const d = Math.sqrt(dx*dx + dy*dy);
      if(d > Math.max(W, H)*0.6 || p.fade < 0.05){{
        // Reset back inside carrier (cycling)
        const a = Math.random()*Math.PI*2;
        const r = Math.sqrt(Math.random())*R*0.65;
        p.x = cx + Math.cos(a)*r;
        p.y = cy + Math.sin(a)*r;
        p.orbit_a = a; p.orbit_r = r;
        p.released = false;
        p.fade = 1.0;
      }}
    }}
    ctx.globalAlpha = p.fade;
    drawDrug(ctx, DRUG.shape, p.x, p.y, DRUG.size*0.85,
              DRUG.primary, DRUG.secondary, DRUG.glow, t, p.rot);
    ctx.globalAlpha = 1;
  }});

  // Cycle reset every TAU_MS + 5s buffer
  if(elapsed > TAU_MS + 5000){{
    cycleStart = t;
  }}

  // Progress text
  const releasedPct = (particles.filter(p => p.released).length/N_PARTICLES)*100;
  ctx.fillStyle = "rgba(148,163,184,0.65)";
  ctx.font = "11px 'Inter', sans-serif";
  ctx.textAlign = "center";
  ctx.fillText("Released: " + releasedPct.toFixed(0) + "%", cx, cy + R + 30);

  requestAnimationFrame(loop);
}}
loop();
</script></body></html>"""
    return _write_html(out_path, body)


# ──────────────────────────────────────────────────────────────────────────
# C05 — Therapeutic Effect
# ──────────────────────────────────────────────────────────────────────────
def make_c05_therapeutic(drug_bundle: Dict, dds_bundle: Dict,
                            top_dds: Dict, out_dir: Path) -> Path:
    """C05: Target receptor binding scene driven by composite score."""
    drug_name = drug_bundle.get("_meta", {}).get("name", "Drug")
    drug_type = drug_bundle.get("_meta", {}).get("drug_type", "small_molecule")
    dds_name  = top_dds.get("Formulation_Name", "DDS")
    composite = top_dds.get("Principle_Composite_Score",
                              top_dds.get("Composite_Score", 50))
    if not isinstance(composite, (int, float)): composite = 50

    dp = get_drug_profile(drug_type)

    if composite >= 80:
        verdict = "STRONG THERAPEUTIC RESPONSE"
        verdict_color = "#22C55E"
    elif composite >= 60:
        verdict = "MODERATE RESPONSE"
        verdict_color = "#F59E0B"
    else:
        verdict = "INSUFFICIENT — RECONSIDER FORMULATION"
        verdict_color = "#EF4444"

    # Indication-driven target description
    indication = top_dds.get("Indication", "") or "CNS disease"
    target_desc = "active receptors in target tissue"

    uid = _hash_id(drug_name, dds_name, "C05")
    out_path = out_dir / f"C05_Therapeutic_{_safe_filename(drug_name)}_{_safe_filename(dds_name)}.html"

    body = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CEREBRO-X · C05 Therapeutic · {drug_name}</title>
<style>{BASE_CSS}
.stage{{position:fixed;top:56px;left:0;right:0;bottom:175px}}
.stage-title{{position:fixed;top:80px;left:50%;transform:translateX(-50%);
  z-index:50;text-align:center;max-width:480px}}
.stage-title .info-card{{padding:12px 24px;--accent:{dp["primary"]}}}
.verdict-block{{position:fixed;bottom:0;left:0;right:0;z-index:50}}
.score-num{{color:{verdict_color}}}
.verdict-text-cls{{color:{verdict_color}}}
</style></head><body>
<div class="cere-header">
  <div class="logo">CEREBRO-X<span class="badge">v22.1</span></div>
  <div class="scene-label">C05 · THERAPEUTIC EFFECT</div>
</div>

<div class="stage-title">
  <div class="info-card glass fade-in">
    <div class="eyebrow">Target Engagement · {drug_name} + {dds_name}</div>
    <div class="body">Composite-score-driven binding probability to {target_desc}</div>
  </div>
</div>

<canvas id="c{uid}" class="stage"></canvas>

<div class="verdict-block">
  <div class="verdict glass-strong">
    <div class="score score-num">{composite:.1f}<sup>/100</sup></div>
    <div class="verdict-text verdict-text-cls">{verdict}</div>
    <div class="meta">62-principle composite score · CNS delivery confidence</div>
  </div>
</div>

<script>{JS_DRAW_PRIMITIVES}
const {{cnv,ctx,getW,getH}} = setupCanvas('c{uid}');
const SCORE = {composite:.2f};
const DRUG_COLOR = "{dp["primary"]}";
const DRUG_GLOW = "{dp["glow"]}";

// Target ring
const N_TARGETS = 24;
const targets = [];
for(let i=0; i<N_TARGETS; i++){{
  const a = i*Math.PI*2/N_TARGETS;
  targets.push({{
    a:a,
    bound:false,
    boundT:0,
    pulse:Math.random()*Math.PI*2,
  }});
}}

let drugWaves = [];
let lastWave = 0;
function spawnWave(){{
  drugWaves.push({{r:0, alpha:1, t0:performance.now()}});
}}

let t0 = performance.now();
function loop(){{
  const t = performance.now() - t0;
  const W = getW(); const H = getH();

  // Background
  ctx.fillStyle = "rgba(2,8,23,0.18)";
  ctx.fillRect(0, 0, W, H);
  drawAtmosphere(ctx, W, H, t, 30);

  const cx = W/2;
  const cy = H/2;
  const targetR = Math.min(180, Math.min(W, H)*0.32);

  // Spawn wave every 1.5s
  if(t - lastWave > 1500){{
    spawnWave();
    lastWave = t;
  }}

  // Update + draw waves
  drugWaves = drugWaves.filter(w => {{
    const age = (performance.now() - w.t0) / 1000;
    w.r = age * 110;
    w.alpha = Math.max(0, 1 - age/3.5);
    if(w.alpha <= 0) return false;

    // Wave ring
    ctx.strokeStyle = DRUG_COLOR + Math.floor(w.alpha*180).toString(16).padStart(2,'0');
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(cx, cy, w.r, 0, Math.PI*2);
    ctx.stroke();

    // Wave reaches target ring → binding
    targets.forEach(tgt => {{
      if(!tgt.bound && Math.abs(w.r - targetR) < 12){{
        // Binding probability proportional to composite score
        if(Math.random() < (SCORE/100) * 0.30){{
          tgt.bound = true;
          tgt.boundT = t;
        }}
      }}
    }});
    return true;
  }});

  // Draw targets
  let nBound = 0;
  targets.forEach(tgt => {{
    const x = cx + Math.cos(tgt.a)*targetR;
    const y = cy + Math.sin(tgt.a)*targetR;
    if(tgt.bound){{
      const age = (t - tgt.boundT) / 1000;
      const fade = Math.max(0, 1 - age/4);
      ctx.shadowColor = DRUG_GLOW;
      ctx.shadowBlur = 18;
      ctx.fillStyle = DRUG_COLOR;
      ctx.globalAlpha = fade;
      ctx.beginPath();
      ctx.arc(x, y, 9, 0, Math.PI*2);
      ctx.fill();
      ctx.globalAlpha = 1;
      ctx.shadowBlur = 0;
      // Ripple ring on each bound target
      const rippleR = 9 + age*8;
      ctx.strokeStyle = DRUG_COLOR + Math.floor(fade*120).toString(16).padStart(2,'0');
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(x, y, rippleR, 0, Math.PI*2);
      ctx.stroke();
      if(age > 4){{ tgt.bound = false; }}    // unbind to keep cycling
      else nBound++;
    }} else {{
      // Unbound: small dim circle
      const breathe = 1 + 0.15*Math.sin(t*0.002 + tgt.pulse);
      ctx.fillStyle = "rgba(148,163,184,0.20)";
      ctx.beginPath();
      ctx.arc(x, y, 5*breathe, 0, Math.PI*2);
      ctx.fill();
      ctx.strokeStyle = "rgba(148,163,184,0.35)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(x, y, 5*breathe, 0, Math.PI*2);
      ctx.stroke();
    }}
  }});

  // Center: drug source — pulsing
  const srcR = 11 + Math.sin(t*0.003)*3;
  const srcGlow = ctx.createRadialGradient(cx, cy, 0, cx, cy, srcR*4);
  srcGlow.addColorStop(0, DRUG_COLOR);
  srcGlow.addColorStop(0.5, DRUG_GLOW);
  srcGlow.addColorStop(1, "transparent");
  ctx.fillStyle = srcGlow;
  ctx.beginPath();
  ctx.arc(cx, cy, srcR*4, 0, Math.PI*2);
  ctx.fill();
  ctx.fillStyle = DRUG_COLOR;
  ctx.beginPath();
  ctx.arc(cx, cy, srcR, 0, Math.PI*2);
  ctx.fill();

  // Bound count display
  ctx.fillStyle = "rgba(203,213,225,0.7)";
  ctx.font = "12px 'Inter', sans-serif";
  ctx.textAlign = "center";
  ctx.fillText("Active receptors engaged: " + nBound + " / " + N_TARGETS,
                  cx, H - 24);

  requestAnimationFrame(loop);
}}
loop();
</script></body></html>"""
    return _write_html(out_path, body)


# ──────────────────────────────────────────────────────────────────────────
# Public API: master generator
# ──────────────────────────────────────────────────────────────────────────
def generate_cinematic_suite(drug_bundle: Dict, dds_bundle: Dict,
                                  top_dds: Dict, out_dir: Path
                                  ) -> List[Path]:
    """Generate all 5 cinematic scenes for a drug+DDS combination.

    Args:
        drug_bundle:  resolved drug bundle from cerebro_resolved_bundles
        dds_bundle:   resolved DDS bundle from cerebro_resolved_bundles
        top_dds:      dict-form record from ranked_df.iloc[0].to_dict()
                        — must contain Formulation_Name, Carrier_Type,
                        Composite_Score, Surface_Ligand, etc.
        out_dir:      directory for output HTML files

    Returns:
        list of Path objects pointing to the 5 generated scene files
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    drug_name = drug_bundle.get("_meta", {}).get("name", "Drug")
    dds_name  = top_dds.get("Formulation_Name", "DDS")

    log.info(f"[CINEMATIC] Generating suite: {drug_name} × {dds_name} → {out_dir}")

    paths: List[Path] = []
    generators = [
        ("C01 Identity",          make_c01_identity),
        ("C02 BBB Crossing",       make_c02_bbb_crossing),
        ("C03 PK Profile",         make_c03_pk_profile),
        ("C04 Release Mechanics",  make_c04_release),
        ("C05 Therapeutic Effect", make_c05_therapeutic),
    ]
    for label, fn in generators:
        try:
            p = fn(drug_bundle, dds_bundle, top_dds, out_dir)
            paths.append(p)
            log.info(f"[CINEMATIC]   ✓ {label}: {p.name} "
                      f"({p.stat().st_size:,} bytes)")
        except Exception as e:
            log.warning(f"[CINEMATIC]   ✗ {label} failed: {e}")
            import traceback
            log.debug(traceback.format_exc())

    log.info(f"[CINEMATIC] Complete: {len(paths)}/5 scenes generated")
    return paths


# ──────────────────────────────────────────────────────────────────────────
# CLI entry point (for ad-hoc use during development)
# ──────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent))

    from cerebro_resolved_bundles import resolve_drug_bundle, resolve_dds_bundle
    logging.basicConfig(level=logging.INFO)

    # Demo with Temozolomide + PLGA
    drug_b = resolve_drug_bundle(name="Temozolomide",
        smiles="CN1N=Nc2c(C(N)=O)ncn2C1=O",
        molecule_class="small_molecule")
    dds_b  = resolve_dds_bundle(carrier_type="plga", ligand="transferrin",
                                  formulation_id="F1")
    top1 = {"Formulation_Name": "Tf-PLGA-100",
              "Carrier_Type":      "plga",
              "Size_nm": 120, "Zeta_Potential_mV": -22, "PDI": 0.18,
              "Surface_Ligand": "transferrin",
              "Drug_Loading_Pct": 15,
              "Release_Kinetics": "sustained", "pH_Trigger": 6.5,
              "Composite_Score": 76.7, "Principle_Composite_Score": 76.7}

    paths = generate_cinematic_suite(drug_b, dds_b, top1,
                                          Path("/tmp/cinematic_demo"))
    print(f"\nGenerated {len(paths)} scenes:")
    for p in paths:
        print(f"  {p.stat().st_size:>7,} bytes  {p.name}")
