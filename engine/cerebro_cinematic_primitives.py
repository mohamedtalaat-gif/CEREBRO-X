# -*- coding: utf-8 -*-
"""
================================================================================
CEREBRO-X | cerebro_cinematic_primitives.py
================================================================================
Created by: Muhammad Talaat (BPharm) — CEREBRO-X

Shared visual primitives for the cinematic media engine. Every scene
imports from here so visual consistency is enforced across all 5 scenes.

Contents:
    DRUG_VISUAL_PROFILES   — 14 drug type signatures (color, shape, motion)
    DDS_VISUAL_PROFILES    — 11 carrier type signatures (morphology, color)
    LIGAND_RECEPTOR_MAP    — surface ligand → receptor target → mechanism
    BASE_CSS               — glassmorphism panels, broadcast typography
    JS_DRAW_PRIMITIVES     — JavaScript drawing functions reused across scenes
    JS_PARTICLE_SYSTEM     — JavaScript particle physics engine

Design language:
    • Deep navy background with subtle radial gradient (#020817 → #0a1628)
    • Glassmorphic panels (backdrop-blur + 1px border + soft shadow)
    • Inter Display typography family (with system-font fallbacks)
    • Drug-color-coded accents on every panel
    • Cinematic loading ramps (3s build-in for visual clarity)
================================================================================
"""

# ──────────────────────────────────────────────────────────────────────────
# Drug-type-specific visual signatures
# ──────────────────────────────────────────────────────────────────────────
# Each drug type has a distinct visual rendering: shape, color, particle
# count, animation speed, narration vocabulary. This is what makes
# Lecanemab + AAV9 visually different from Temozolomide + PLGA on screen.
DRUG_VISUAL_PROFILES = {
    "small_molecule": {
        "shape":          "diamond",
        "size_px":        9,
        "primary":        "#FFD166",      # warm gold
        "secondary":      "#F59E0B",
        "tertiary":       "#FCD34D",
        "glow":           "rgba(255,209,102,0.7)",
        "narrative":      "small molecule",
        "perm_archetype": "passive_diffusion",
        "motion":         "swift",
        "speed":          1.0,
        "n_particles":    80,
        "rotation_speed": 0.001,
        "subtitle":       "Lipophilic small-molecule diffusion",
    },
    "monoclonal_antibody": {
        "shape":          "y_shape",
        "size_px":        24,
        "primary":        "#60A5FA",      # cool sky blue
        "secondary":      "#3B82F6",
        "tertiary":       "#93C5FD",
        "glow":           "rgba(96,165,250,0.6)",
        "narrative":      "monoclonal antibody (IgG)",
        "perm_archetype": "receptor_mediated_transcytosis",
        "motion":         "deliberate",
        "speed":          0.55,
        "n_particles":    35,
        "rotation_speed": 0.0006,
        "subtitle":       "Bivalent IgG · Fc-mediated FcRn recycling",
    },
    "biologic_protein": {
        "shape":          "blob",
        "size_px":        20,
        "primary":        "#A78BFA",
        "secondary":      "#8B5CF6",
        "tertiary":       "#C4B5FD",
        "glow":           "rgba(167,139,250,0.6)",
        "narrative":      "protein therapeutic",
        "perm_archetype": "receptor_mediated_transcytosis",
        "motion":         "deliberate",
        "speed":          0.7,
        "n_particles":    40,
        "rotation_speed": 0.0008,
        "subtitle":       "Folded protein · receptor-mediated uptake",
    },
    "biologic_peptide": {
        "shape":          "chain",
        "size_px":        14,
        "primary":        "#34D399",
        "secondary":      "#10B981",
        "tertiary":       "#6EE7B7",
        "glow":           "rgba(52,211,153,0.65)",
        "narrative":      "therapeutic peptide",
        "perm_archetype": "carrier_assisted",
        "motion":         "fluid",
        "speed":          0.85,
        "n_particles":    55,
        "rotation_speed": 0.0012,
        "subtitle":       "Linear peptide · enzymatic susceptibility",
    },
    "oligonucleotide": {
        "shape":          "double_helix",
        "size_px":        16,
        "primary":        "#F87171",
        "secondary":      "#EF4444",
        "tertiary":       "#FCA5A5",
        "glow":           "rgba(248,113,113,0.65)",
        "narrative":      "antisense oligonucleotide (ASO)",
        "perm_archetype": "intrathecal_or_carrier",
        "motion":         "deliberate",
        "speed":          0.7,
        "n_particles":    50,
        "rotation_speed": 0.0014,
        "subtitle":       "ssDNA backbone · electrostatic capture",
    },
    "gene_therapy": {
        "shape":          "double_helix",
        "size_px":        18,
        "primary":        "#F472B6",
        "secondary":      "#EC4899",
        "tertiary":       "#FBCFE8",
        "glow":           "rgba(244,114,182,0.6)",
        "narrative":      "gene therapy payload",
        "perm_archetype": "viral_or_carrier",
        "motion":         "deliberate",
        "speed":          0.65,
        "n_particles":    35,
        "rotation_speed": 0.0010,
        "subtitle":       "DNA / mRNA cargo · viral encapsidation",
    },
    "vaccine": {
        "shape":          "blob",
        "size_px":        18,
        "primary":        "#86EFAC",
        "secondary":      "#22C55E",
        "tertiary":       "#BBF7D0",
        "glow":           "rgba(134,239,172,0.6)",
        "narrative":      "vaccine antigen",
        "perm_archetype": "lymphatic_uptake",
        "motion":         "fluid",
        "speed":          0.85,
        "n_particles":    45,
        "rotation_speed": 0.0010,
        "subtitle":       "Antigen · APC presentation",
    },
    "cell_therapy": {
        "shape":          "circle_with_nucleus",
        "size_px":        34,
        "primary":        "#FB923C",
        "secondary":      "#F97316",
        "tertiary":       "#FDBA74",
        "glow":           "rgba(251,146,60,0.6)",
        "narrative":      "engineered cellular therapy",
        "perm_archetype": "homing_engraftment",
        "motion":         "slow",
        "speed":          0.45,
        "n_particles":    18,
        "rotation_speed": 0.0004,
        "subtitle":       "CAR-T / hPSC · tissue engraftment",
    },
    "radiopharmaceutical": {
        "shape":          "diamond",
        "size_px":        10,
        "primary":        "#FCD34D",
        "secondary":      "#F59E0B",
        "tertiary":       "#FFE4A0",
        "glow":           "rgba(252,211,77,0.85)",
        "narrative":      "radiopharmaceutical",
        "perm_archetype": "passive_diffusion",
        "motion":         "swift",
        "speed":          1.2,
        "n_particles":    65,
        "rotation_speed": 0.0014,
        "subtitle":       "Radioligand · target-specific accumulation",
    },
    "natural_product": {
        "shape":          "diamond",
        "size_px":        10,
        "primary":        "#5EEAD4",
        "secondary":      "#14B8A6",
        "tertiary":       "#99F6E4",
        "glow":           "rgba(94,234,212,0.6)",
        "narrative":      "natural-product derivative",
        "perm_archetype": "passive_diffusion",
        "motion":         "swift",
        "speed":          1.0,
        "n_particles":    65,
        "rotation_speed": 0.0010,
        "subtitle":       "Plant / microbial natural product",
    },
    "blood_product": {
        "shape":          "blob",
        "size_px":        20,
        "primary":        "#FB7185",
        "secondary":      "#E11D48",
        "tertiary":       "#FECDD3",
        "glow":           "rgba(251,113,133,0.6)",
        "narrative":      "blood-derived therapeutic",
        "perm_archetype": "intravenous_systemic",
        "motion":         "fluid",
        "speed":          0.75,
        "n_particles":    40,
        "rotation_speed": 0.0008,
        "subtitle":       "Plasma fraction · systemic distribution",
    },
    "fusion_protein": {
        "shape":          "y_shape",
        "size_px":        22,
        "primary":        "#94A3B8",
        "secondary":      "#64748B",
        "tertiary":       "#CBD5E1",
        "glow":           "rgba(148,163,184,0.6)",
        "narrative":      "Fc-fusion protein",
        "perm_archetype": "receptor_mediated_transcytosis",
        "motion":         "deliberate",
        "speed":          0.6,
        "n_particles":    32,
        "rotation_speed": 0.0006,
        "subtitle":       "Domain fusion · extended half-life",
    },
    "enzyme_replacement": {
        "shape":          "blob",
        "size_px":        18,
        "primary":        "#C084FC",
        "secondary":      "#A855F7",
        "tertiary":       "#E9D5FF",
        "glow":           "rgba(192,132,252,0.6)",
        "narrative":      "enzyme replacement therapy",
        "perm_archetype": "mannose_6_phosphate_uptake",
        "motion":         "deliberate",
        "speed":          0.65,
        "n_particles":    34,
        "rotation_speed": 0.0007,
        "subtitle":       "Lysosomal enzyme · M6P-mediated uptake",
    },
    "allergenic_extract": {
        "shape":          "blob",
        "size_px":        15,
        "primary":        "#FDE047",
        "secondary":      "#EAB308",
        "tertiary":       "#FEF08A",
        "glow":           "rgba(253,224,71,0.6)",
        "narrative":      "allergenic immunotherapy extract",
        "perm_archetype": "subcutaneous",
        "motion":         "fluid",
        "speed":          0.85,
        "n_particles":    45,
        "rotation_speed": 0.0010,
        "subtitle":       "Allergen mix · desensitization",
    },
}


# ──────────────────────────────────────────────────────────────────────────
# DDS-type-specific visual signatures
# ──────────────────────────────────────────────────────────────────────────
DDS_VISUAL_PROFILES = {
    "plga": {
        "shape":          "sphere_with_pores",
        "outer":          "#3B82F6",
        "inner":          "#1E40AF",
        "highlight":      "#60A5FA",
        "wall_px":        4,
        "label":          "PLGA Nanoparticle",
        "subtitle":       "Poly(lactic-co-glycolic acid) · biodegradable",
        "release":        "polymer_degradation",
        "release_text":   "Bulk erosion of PLGA matrix releases drug as ester bonds hydrolyze (1–4 wk t½)",
        "mech_subtitle":  "Polymeric matrix · hydrolytic degradation",
    },
    "liposome": {
        "shape":          "bilayer_vesicle",
        "outer":          "#14B8A6",
        "inner":          "#0F766E",
        "highlight":      "#5EEAD4",
        "wall_px":        6,
        "label":          "Liposome",
        "subtitle":       "Phospholipid bilayer vesicle · biocompatible",
        "release":        "membrane_fusion",
        "release_text":   "Fusion with target-cell membrane delivers aqueous core contents",
        "mech_subtitle":  "Bilayer · pH/temp-responsive options",
    },
    "lnp": {
        "shape":          "core_shell_lipid",
        "outer":          "#EF4444",
        "inner":          "#991B1B",
        "highlight":      "#FCA5A5",
        "wall_px":        5,
        "label":          "Lipid Nanoparticle (LNP)",
        "subtitle":       "Ionizable lipid · pH-triggered endosomal escape",
        "release":        "endosomal_escape",
        "release_text":   "Endosome acidification protonates ionizable lipid → membrane disruption → cytosol release",
        "mech_subtitle":  "Ionizable cationic lipid · ApoE-mediated uptake",
    },
    "aav9": {
        "shape":          "icosahedral_capsid",
        "outer":          "#8B5CF6",
        "inner":          "#5B21B6",
        "highlight":      "#C4B5FD",
        "wall_px":        3,
        "label":          "AAV9 Viral Capsid",
        "subtitle":       "T=1 icosahedral · 25 nm · CNS-tropic",
        "release":        "receptor_uncoating",
        "release_text":   "AAVR-mediated endocytosis → endosomal escape → nuclear transport → uncoating",
        "mech_subtitle":  "Adeno-associated virus 9 · galactose-binding",
    },
    "aav": {
        "shape":          "icosahedral_capsid",
        "outer":          "#8B5CF6",
        "inner":          "#5B21B6",
        "highlight":      "#C4B5FD",
        "wall_px":        3,
        "label":          "AAV Vector",
        "subtitle":       "Adeno-associated virus · serotype-tunable tropism",
        "release":        "receptor_uncoating",
        "release_text":   "Receptor-mediated endocytosis → endosomal escape → genome delivery",
        "mech_subtitle":  "Engineered viral capsid",
    },
    "polymer": {
        "shape":          "sphere_with_pores",
        "outer":          "#0EA5E9",
        "inner":          "#0369A1",
        "highlight":      "#7DD3FC",
        "wall_px":        4,
        "label":          "Polymer Nanoparticle",
        "subtitle":       "Synthetic polymer matrix",
        "release":        "polymer_degradation",
        "release_text":   "Polymer chain scission releases entrapped drug",
        "mech_subtitle":  "Functionalized polymer · diffusion-limited",
    },
    "solid_lipid": {
        "shape":          "sphere_solid",
        "outer":          "#22C55E",
        "inner":          "#15803D",
        "highlight":      "#86EFAC",
        "wall_px":        0,
        "label":          "Solid Lipid Nanoparticle (SLN)",
        "subtitle":       "Solid lipid matrix · stable at room temp",
        "release":        "lipid_dissolution",
        "release_text":   "Lipid matrix dissolves at body temperature releasing drug payload",
        "mech_subtitle":  "Solid lipid · Brownian-limited diffusion",
    },
    "micelle": {
        "shape":          "core_shell_micelle",
        "outer":          "#F59E0B",
        "inner":          "#B45309",
        "highlight":      "#FCD34D",
        "wall_px":        3,
        "label":          "Polymeric Micelle",
        "subtitle":       "Self-assembly above CMC · hydrophobic core",
        "release":        "cmc_disassembly",
        "release_text":   "Below CMC concentration micelles disassemble releasing core cargo",
        "mech_subtitle":  "Amphiphilic block-copolymer assembly",
    },
    "dendrimer": {
        "shape":          "dendritic_branched",
        "outer":          "#EC4899",
        "inner":          "#9D174D",
        "highlight":      "#FBCFE8",
        "wall_px":        2,
        "label":          "Dendrimer",
        "subtitle":       "Hyperbranched · monodisperse · multivalent",
        "release":        "surface_release",
        "release_text":   "Surface-conjugated drug released by linker hydrolysis",
        "mech_subtitle":  "Generation-G dendritic architecture",
    },
    "metallic": {
        "shape":          "sphere_metallic",
        "outer":          "#94A3B8",
        "inner":          "#334155",
        "highlight":      "#CBD5E1",
        "wall_px":        0,
        "label":          "Metallic Nanoparticle",
        "subtitle":       "Plasmonic core · gold/iron oxide options",
        "release":        "ligand_displacement",
        "release_text":   "Surface ligand exchange or photo-thermal trigger releases drug",
        "mech_subtitle":  "Inorganic core · plasmonic / magnetic",
    },
    "nanogel": {
        "shape":          "porous_gel",
        "outer":          "#06B6D4",
        "inner":          "#0E7490",
        "highlight":      "#67E8F9",
        "wall_px":        5,
        "label":          "Nanogel",
        "subtitle":       "Cross-linked hydrogel network · swellable",
        "release":        "swelling_release",
        "release_text":   "Stimulus-driven gel swelling opens pores releasing drug",
        "mech_subtitle":  "Hydrogel · stimuli-responsive",
    },
    "_default": {
        "shape":          "sphere_solid",
        "outer":          "#64748B",
        "inner":          "#334155",
        "highlight":      "#94A3B8",
        "wall_px":        2,
        "label":          "Drug Delivery System",
        "subtitle":       "Generic delivery vehicle",
        "release":        "diffusion",
        "release_text":   "Drug diffuses through carrier surface",
        "mech_subtitle":  "Generic delivery system",
    },
}


# ──────────────────────────────────────────────────────────────────────────
# Ligand → receptor → mechanism map (for BBB scene narration)
# ──────────────────────────────────────────────────────────────────────────
LIGAND_RECEPTOR_MAP = {
    "transferrin": {
        "receptor": "Transferrin Receptor (TfR1, CD71)",
        "mechanism": "Receptor-mediated transcytosis (RMT)",
        "uptake_efficiency": 0.42,
        "literature": "Pardridge WM (2020) Pharmaceutics 12:1283",
    },
    "tf-peg": {
        "receptor": "Transferrin Receptor (TfR1)",
        "mechanism": "PEGylated TfR-targeted RMT",
        "uptake_efficiency": 0.48,
        "literature": "Johnsen KB et al (2018) J Control Release 270:31",
    },
    "rvg29":      {
        "receptor": "Nicotinic Acetylcholine Receptor (nAChR α7)",
        "mechanism": "Rabies-virus-glycoprotein-29 mediated endocytosis",
        "uptake_efficiency": 0.55,
        "literature": "Kumar P et al (2007) Nature 448:39",
    },
    "rvg":        {
        "receptor": "Nicotinic Acetylcholine Receptor",
        "mechanism": "RVG peptide nAChR-targeted uptake",
        "uptake_efficiency": 0.55,
        "literature": "Kumar P et al (2007) Nature 448:39",
    },
    "apoe":       {
        "receptor": "Low-Density-Lipoprotein Receptor family (LDLR/LRP1)",
        "mechanism": "ApoE-mediated lipoprotein uptake",
        "uptake_efficiency": 0.38,
        "literature": "Re F et al (2012) Bioconjug Chem 23:2228",
    },
    "g23":        {
        "receptor": "Sulfatide / Glucocerebroside (myelin sphingolipids)",
        "mechanism": "G23 peptide-mediated CMT",
        "uptake_efficiency": 0.30,
        "literature": "Georgieva JV et al (2014) ACS Nano 8:10159",
    },
    "angiopep":   {
        "receptor": "LRP1 (Angiopep-2 binding)",
        "mechanism": "Angiopep-2-mediated transcytosis",
        "uptake_efficiency": 0.45,
        "literature": "Demeule M et al (2008) J Pharmacol Exp Ther 324:1064",
    },
    "lf":         {
        "receptor": "Lactoferrin Receptor (LfR)",
        "mechanism": "Lactoferrin-mediated transcytosis",
        "uptake_efficiency": 0.40,
        "literature": "Hu K et al (2009) Int J Pharm 379:125",
    },
    "lactoferrin":{
        "receptor": "Lactoferrin Receptor (LfR)",
        "mechanism": "Lactoferrin-mediated transcytosis",
        "uptake_efficiency": 0.40,
        "literature": "Hu K et al (2009) Int J Pharm 379:125",
    },
    "mannose":    {
        "receptor": "Mannose Receptor (CD206) / GLUT1",
        "mechanism": "Mannose / glucose transporter-mediated uptake",
        "uptake_efficiency": 0.32,
        "literature": "Anraku Y et al (2017) Nat Commun 8:1001",
    },
    "":           {
        "receptor": "(none — passive diffusion or non-targeted uptake)",
        "mechanism": "Unligated carrier — relies on intrinsic permeability",
        "uptake_efficiency": 0.15,
        "literature": "—",
    },
    "none":       {
        "receptor": "(none — passive diffusion)",
        "mechanism": "Unligated carrier",
        "uptake_efficiency": 0.15,
        "literature": "—",
    },
}


def get_drug_profile(drug_type: str) -> dict:
    """Get drug visual profile, with fallback to small_molecule."""
    return DRUG_VISUAL_PROFILES.get(
        (drug_type or "small_molecule").lower(),
        DRUG_VISUAL_PROFILES["small_molecule"])


def get_dds_profile(carrier: str) -> dict:
    """Match carrier name to DDS profile, with partial-match support."""
    c = (carrier or "").lower().strip()
    if c in DDS_VISUAL_PROFILES:
        return DDS_VISUAL_PROFILES[c]
    # Partial-match (e.g. "PLGA-Tf" → "plga")
    for key, prof in DDS_VISUAL_PROFILES.items():
        if key != "_default" and key in c:
            return prof
    return DDS_VISUAL_PROFILES["_default"]


def get_ligand_info(ligand: str) -> dict:
    """Get ligand→receptor mapping with case-insensitive and partial match."""
    l = (ligand or "").lower().strip()
    if l in LIGAND_RECEPTOR_MAP:
        return LIGAND_RECEPTOR_MAP[l]
    # Partial match
    for key, info in LIGAND_RECEPTOR_MAP.items():
        if key and key in l:
            return info
    return LIGAND_RECEPTOR_MAP[""]


# ──────────────────────────────────────────────────────────────────────────
# Shared CSS — glassmorphism + broadcast typography
# ──────────────────────────────────────────────────────────────────────────
BASE_CSS = """
*{margin:0;padding:0;box-sizing:border-box}
html,body{height:100%;overflow:hidden;background:#020817;color:#F1F5F9;
  font-family:'Inter',-apple-system,BlinkMacSystemFont,sans-serif;
  font-feature-settings:'cv11','ss03';-webkit-font-smoothing:antialiased;
  letter-spacing:-0.011em}
body{background:radial-gradient(ellipse 120% 80% at 50% 40%,#0a1628 0%,#020817 70%)}
canvas{display:block}

/* Header bar */
.cere-header{position:fixed;top:0;left:0;right:0;height:56px;display:flex;
  align-items:center;justify-content:space-between;padding:0 32px;
  background:linear-gradient(180deg,rgba(2,8,23,0.95) 0%,rgba(2,8,23,0) 100%);
  z-index:100;backdrop-filter:blur(8px)}
.cere-header .logo{font-size:13px;font-weight:600;letter-spacing:3px;
  color:#94A3B8;display:flex;align-items:center;gap:14px}
.cere-header .logo .badge{padding:4px 10px;border-radius:4px;background:rgba(255,255,255,0.06);
  font-weight:500;letter-spacing:2px;color:#E2E8F0;font-size:10px}
.cere-header .scene-label{font-size:11px;letter-spacing:4px;color:#64748B;
  font-weight:500;text-transform:uppercase}

/* Glassmorphism panels */
.glass{background:rgba(15,23,42,0.55);border:1px solid rgba(148,163,184,0.10);
  border-radius:10px;backdrop-filter:blur(20px) saturate(140%);
  -webkit-backdrop-filter:blur(20px) saturate(140%);
  box-shadow:0 8px 32px rgba(0,0,0,0.4),
             0 1px 0 rgba(255,255,255,0.04) inset}
.glass-strong{background:rgba(15,23,42,0.78)}

/* Info card variants */
.info-card{padding:14px 18px}
.info-card .eyebrow{font-size:10px;letter-spacing:3px;text-transform:uppercase;
  color:#94A3B8;font-weight:500;margin-bottom:6px}
.info-card .title{font-size:18px;font-weight:300;letter-spacing:-0.4px;
  color:#F8FAFC;margin-bottom:4px;line-height:1.2}
.info-card .body{font-size:11px;color:#94A3B8;line-height:1.5}
.info-card .body b{color:#F1F5F9;font-weight:500}
.info-card.accent-left{border-left:2px solid var(--accent)}
.info-card.accent-right{border-right:2px solid var(--accent)}

/* Stat pill row */
.stat-row{position:fixed;left:0;right:0;display:flex;gap:10px;justify-content:center;
  flex-wrap:wrap;padding:0 32px;z-index:50}
.stat-pill{padding:7px 14px;border-radius:18px;background:rgba(15,23,42,0.65);
  border:1px solid rgba(148,163,184,0.10);font-size:11px;color:#CBD5E1;
  backdrop-filter:blur(12px);font-feature-settings:'tnum'}
.stat-pill b{color:#F8FAFC;margin-left:5px;font-weight:600}

/* Verdict block */
.verdict{padding:32px 40px;text-align:center;background:rgba(0,0,0,0.45);
  backdrop-filter:blur(12px);border-top:1px solid rgba(148,163,184,0.08)}
.verdict .score{font-size:54px;font-weight:200;line-height:1;
  letter-spacing:-2px;font-feature-settings:'tnum'}
.verdict .score sup{font-size:22px;color:#64748B;font-weight:300;margin-left:4px}
.verdict .verdict-text{font-size:13px;letter-spacing:5px;text-transform:uppercase;
  margin-top:10px;font-weight:600}
.verdict .meta{font-size:11px;color:#64748B;margin-top:8px;letter-spacing:0.5px}

/* Loading ramp on first paint */
@keyframes fadeIn{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}
.fade-in{animation:fadeIn 1.2s ease-out forwards}
.fade-in-2{animation:fadeIn 1.2s ease-out 0.4s forwards;opacity:0}
.fade-in-3{animation:fadeIn 1.2s ease-out 0.8s forwards;opacity:0}
"""


# ──────────────────────────────────────────────────────────────────────────
# Shared JavaScript drawing primitives
# ──────────────────────────────────────────────────────────────────────────
# These are concatenated into each scene's <script> block for consistent
# rendering. They handle:
#   • DPI-aware canvas resizing
#   • Drug-shape primitives (diamond, Y, helix, blob, chain, cell)
#   • DDS-shape primitives (bilayer, capsid, dendrimer, etc.)
#   • Atmospheric haze / depth-of-field
#   • Easing functions for cinematic timing
JS_DRAW_PRIMITIVES = r"""
// ── DPI-aware canvas setup ──────────────────────────────────────────
function setupCanvas(canvasId){
  const cnv = document.getElementById(canvasId);
  const ctx = cnv.getContext('2d', {alpha: false});
  const dpr = window.devicePixelRatio || 1;
  function resize(){
    const w = cnv.offsetWidth || window.innerWidth;
    const h = cnv.offsetHeight || window.innerHeight;
    cnv.width = w * dpr;
    cnv.height = h * dpr;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.scale(dpr, dpr);
  }
  window.addEventListener('resize', resize);
  resize();
  return {cnv, ctx, getW: () => cnv.offsetWidth || window.innerWidth,
                     getH: () => cnv.offsetHeight || window.innerHeight};
}

// ── Easing ──────────────────────────────────────────────────────────
const easeOutCubic = t => 1 - Math.pow(1-t, 3);
const easeInOutCubic = t => t<0.5 ? 4*t*t*t : 1 - Math.pow(-2*t+2, 3)/2;
const easeOutExpo = t => t===1 ? 1 : 1 - Math.pow(2, -10*t);

// ── Atmospheric haze (depth-of-field illusion) ──────────────────────
function drawAtmosphere(ctx, W, H, t, density){
  density = density || 40;
  for(let i=0;i<density;i++){
    const seed = i*73.31;
    const x = ((seed + t*0.015) % W);
    const y = H*0.5 + Math.sin(seed*0.1 + t*0.0008)*H*0.4;
    const z = 0.3 + 0.7*Math.sin(seed*0.07);    // depth
    const r = 1.2 + z*1.8;
    ctx.fillStyle = "rgba(148,163,184," + (0.012 + z*0.025) + ")";
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI*2);
    ctx.fill();
  }
}

// ── Drug shape primitives ───────────────────────────────────────────
function drawDrugDiamond(ctx, x, y, size, primary, secondary, glow, t, rot){
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(rot || t*0.001);
  ctx.shadowColor = glow;
  ctx.shadowBlur = 14;
  // Multi-stop gradient for jewel look
  const g = ctx.createLinearGradient(-size, -size, size, size);
  g.addColorStop(0, primary);
  g.addColorStop(0.5, secondary);
  g.addColorStop(1, primary);
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.moveTo(0, -size);
  ctx.lineTo(size, 0);
  ctx.lineTo(0, size);
  ctx.lineTo(-size, 0);
  ctx.closePath();
  ctx.fill();
  // Inner highlight (shine)
  ctx.fillStyle = "rgba(255,255,255,0.35)";
  ctx.beginPath();
  ctx.moveTo(0, -size*0.6);
  ctx.lineTo(size*0.3, -size*0.2);
  ctx.lineTo(0, 0);
  ctx.lineTo(-size*0.3, -size*0.2);
  ctx.closePath();
  ctx.fill();
  ctx.restore();
}

function drawDrugY(ctx, x, y, size, primary, secondary, glow, t, rot){
  // Y-shape for IgG antibody
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(rot || 0);
  ctx.shadowColor = glow;
  ctx.shadowBlur = 16;
  ctx.strokeStyle = primary;
  ctx.lineWidth = 3;
  ctx.lineCap = 'round';
  ctx.beginPath();
  ctx.moveTo(0, size);                          // Fc stem
  ctx.lineTo(0, 0);
  ctx.moveTo(0, 0);
  ctx.lineTo(-size*0.7, -size*0.7);             // Fab arm 1
  ctx.moveTo(0, 0);
  ctx.lineTo(size*0.7, -size*0.7);              // Fab arm 2
  ctx.stroke();
  // Knobs at tips (CDR loops)
  ctx.fillStyle = secondary;
  [[0, size], [-size*0.7, -size*0.7], [size*0.7, -size*0.7]].forEach(p => {
    ctx.beginPath();
    ctx.arc(p[0], p[1], 4, 0, Math.PI*2);
    ctx.fill();
  });
  // Hinge region dot
  ctx.fillStyle = primary;
  ctx.beginPath();
  ctx.arc(0, 0, 3, 0, Math.PI*2);
  ctx.fill();
  ctx.restore();
}

function drawDrugHelix(ctx, x, y, size, primary, secondary, glow, t, rot){
  // Double helix for oligonucleotides
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(rot || 0);
  ctx.shadowColor = glow;
  ctx.shadowBlur = 12;
  for(let i=0;i<8;i++){
    const u = i/7;
    const yp = (u-0.5)*size*2.2;
    const phaseShift = t*0.002;
    const x1 = Math.sin(u*Math.PI*4 + phaseShift)*size*0.45;
    const x2 = -x1;
    // Backbone strands
    ctx.fillStyle = primary;
    ctx.beginPath();
    ctx.arc(x1, yp, 2.5, 0, Math.PI*2);
    ctx.fill();
    ctx.fillStyle = secondary;
    ctx.beginPath();
    ctx.arc(x2, yp, 2.5, 0, Math.PI*2);
    ctx.fill();
    // Base pairs (rungs)
    if(i%2===0){
      ctx.strokeStyle = "rgba(255,255,255,0.35)";
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      ctx.moveTo(x1, yp);
      ctx.lineTo(x2, yp);
      ctx.stroke();
    }
  }
  ctx.restore();
}

function drawDrugBlob(ctx, x, y, size, primary, secondary, glow, t){
  ctx.save();
  ctx.translate(x, y);
  ctx.shadowColor = glow;
  ctx.shadowBlur = 18;
  const grad = ctx.createRadialGradient(-size*0.3, -size*0.3, 0, 0, 0, size);
  grad.addColorStop(0, primary);
  grad.addColorStop(1, secondary);
  ctx.fillStyle = grad;
  ctx.beginPath();
  for(let a=0; a<Math.PI*2; a+=0.08){
    const r = size*(1 + 0.18*Math.sin(a*3 + t*0.0012) + 0.10*Math.sin(a*5 + t*0.0017));
    const px = Math.cos(a)*r;
    const py = Math.sin(a)*r;
    if(a===0) ctx.moveTo(px, py);
    else ctx.lineTo(px, py);
  }
  ctx.closePath();
  ctx.fill();
  ctx.restore();
}

function drawDrugChain(ctx, x, y, size, primary, secondary, glow, t){
  // Linear peptide chain
  ctx.save();
  ctx.translate(x, y);
  ctx.shadowColor = glow;
  ctx.shadowBlur = 10;
  for(let i=0;i<7;i++){
    const u = i/6;
    const xp = (u-0.5)*size*2;
    const yp = Math.sin(u*Math.PI*2 + t*0.002)*size*0.3;
    ctx.fillStyle = (i%2===0) ? primary : secondary;
    ctx.beginPath();
    ctx.arc(xp, yp, 3.5, 0, Math.PI*2);
    ctx.fill();
    if(i>0){
      const u0 = (i-1)/6;
      const xp0 = (u0-0.5)*size*2;
      const yp0 = Math.sin(u0*Math.PI*2 + t*0.002)*size*0.3;
      ctx.strokeStyle = "rgba(255,255,255,0.3)";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(xp0, yp0);
      ctx.lineTo(xp, yp);
      ctx.stroke();
    }
  }
  ctx.restore();
}

function drawDrugCell(ctx, x, y, size, primary, secondary, glow, t){
  // Cell with nucleus
  ctx.save();
  ctx.translate(x, y);
  ctx.shadowColor = glow;
  ctx.shadowBlur = 16;
  // Cytoplasm
  const grad = ctx.createRadialGradient(-size*0.3, -size*0.3, 0, 0, 0, size);
  grad.addColorStop(0, primary + "AA");
  grad.addColorStop(1, secondary + "60");
  ctx.fillStyle = grad;
  ctx.beginPath();
  ctx.arc(0, 0, size, 0, Math.PI*2);
  ctx.fill();
  // Nucleus
  ctx.fillStyle = secondary;
  ctx.beginPath();
  ctx.arc(0, 0, size*0.4, 0, Math.PI*2);
  ctx.fill();
  ctx.restore();
}

// Universal drug-shape dispatcher
function drawDrug(ctx, shape, x, y, size, primary, secondary, glow, t, rot){
  switch(shape){
    case "y_shape":            drawDrugY(ctx, x, y, size, primary, secondary, glow, t, rot); break;
    case "double_helix":       drawDrugHelix(ctx, x, y, size, primary, secondary, glow, t, rot); break;
    case "blob":               drawDrugBlob(ctx, x, y, size, primary, secondary, glow, t); break;
    case "chain":              drawDrugChain(ctx, x, y, size, primary, secondary, glow, t); break;
    case "circle_with_nucleus":drawDrugCell(ctx, x, y, size, primary, secondary, glow, t); break;
    default:                   drawDrugDiamond(ctx, x, y, size, primary, secondary, glow, t, rot);
  }
}

// ── DDS shape primitives ────────────────────────────────────────────
function drawDDSBilayer(ctx, cx, cy, R, outer, inner, highlight, t){
  // Outer glow halo
  const halo = ctx.createRadialGradient(cx, cy, R*0.95, cx, cy, R*1.4);
  halo.addColorStop(0, outer + "30");
  halo.addColorStop(1, "transparent");
  ctx.fillStyle = halo;
  ctx.beginPath(); ctx.arc(cx, cy, R*1.4, 0, Math.PI*2); ctx.fill();
  // Outer leaflet
  const og = ctx.createRadialGradient(cx-R*0.3, cy-R*0.3, R*0.4, cx, cy, R);
  og.addColorStop(0, highlight + "AA");
  og.addColorStop(0.7, outer + "60");
  og.addColorStop(1, outer + "30");
  ctx.fillStyle = og;
  ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI*2); ctx.fill();
  // Bilayer rings (lipid headgroups)
  ctx.strokeStyle = outer;
  ctx.lineWidth = 1.8;
  ctx.beginPath(); ctx.arc(cx, cy, R-3, 0, Math.PI*2); ctx.stroke();
  ctx.beginPath(); ctx.arc(cx, cy, R-9, 0, Math.PI*2); ctx.stroke();
  // Aqueous core
  ctx.fillStyle = inner + "30";
  ctx.beginPath(); ctx.arc(cx, cy, R-12, 0, Math.PI*2); ctx.fill();
  // Phospholipid head dots (simulated)
  ctx.fillStyle = highlight;
  for(let i=0;i<24;i++){
    const a = i*Math.PI*2/24 + t*0.0003;
    const px = cx + Math.cos(a)*(R-3);
    const py = cy + Math.sin(a)*(R-3);
    ctx.beginPath(); ctx.arc(px, py, 1.2, 0, Math.PI*2); ctx.fill();
  }
}

function drawDDSCapsid(ctx, cx, cy, R, outer, inner, highlight, t){
  const sides = 12;
  ctx.save();
  ctx.translate(cx, cy);
  ctx.rotate(t*0.0003);
  // Outer halo
  const halo = ctx.createRadialGradient(0, 0, R*0.9, 0, 0, R*1.3);
  halo.addColorStop(0, outer + "40");
  halo.addColorStop(1, "transparent");
  ctx.fillStyle = halo;
  ctx.beginPath(); ctx.arc(0, 0, R*1.3, 0, Math.PI*2); ctx.fill();
  // Capsid faces
  const grad = ctx.createRadialGradient(-R*0.3, -R*0.3, 0, 0, 0, R);
  grad.addColorStop(0, highlight);
  grad.addColorStop(0.6, outer);
  grad.addColorStop(1, inner);
  ctx.fillStyle = grad;
  ctx.strokeStyle = outer;
  ctx.lineWidth = 2;
  ctx.beginPath();
  for(let i=0;i<sides;i++){
    const a = i*Math.PI*2/sides;
    const x = Math.cos(a)*R; const y = Math.sin(a)*R;
    if(i===0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.closePath();
  ctx.fill();
  ctx.stroke();
  // Inner triangulation (faceted look)
  ctx.strokeStyle = "rgba(255,255,255,0.15)";
  ctx.lineWidth = 1;
  for(let i=0;i<sides;i++){
    const a = i*Math.PI*2/sides;
    ctx.beginPath();
    ctx.moveTo(0, 0);
    ctx.lineTo(Math.cos(a)*R, Math.sin(a)*R);
    ctx.stroke();
  }
  // Spike proteins (capsid surface)
  for(let i=0;i<sides;i++){
    const a = i*Math.PI*2/sides + Math.PI/sides;
    const x = Math.cos(a)*R; const y = Math.sin(a)*R;
    ctx.beginPath();
    ctx.arc(x, y, 3, 0, Math.PI*2);
    ctx.fillStyle = highlight;
    ctx.fill();
  }
  ctx.restore();
}

function drawDDSPLGA(ctx, cx, cy, R, outer, inner, highlight, t){
  // Outer halo
  const halo = ctx.createRadialGradient(cx, cy, R*0.95, cx, cy, R*1.35);
  halo.addColorStop(0, outer + "30");
  halo.addColorStop(1, "transparent");
  ctx.fillStyle = halo;
  ctx.beginPath(); ctx.arc(cx, cy, R*1.35, 0, Math.PI*2); ctx.fill();
  // Sphere with depth gradient
  const grad = ctx.createRadialGradient(cx-R*0.3, cy-R*0.3, R*0.1, cx, cy, R);
  grad.addColorStop(0, highlight);
  grad.addColorStop(0.5, outer);
  grad.addColorStop(1, inner);
  ctx.fillStyle = grad;
  ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI*2); ctx.fill();
  // Pore texture
  ctx.fillStyle = "rgba(0,0,0,0.35)";
  for(let i=0;i<28;i++){
    const seed = i*73.31;
    const a = seed % (Math.PI*2);
    const r = R*(0.3 + 0.5*((seed*0.13) % 1));
    const px = cx + Math.cos(a + t*0.0003)*r;
    const py = cy + Math.sin(a + t*0.0003)*r;
    const dotR = 1 + 1.5*((seed*0.07) % 1);
    ctx.beginPath(); ctx.arc(px, py, dotR, 0, Math.PI*2); ctx.fill();
  }
  // Edge highlight ring
  ctx.strokeStyle = highlight + "80";
  ctx.lineWidth = 1.2;
  ctx.beginPath(); ctx.arc(cx, cy, R-1, 0, Math.PI*2); ctx.stroke();
}

function drawDDSLNP(ctx, cx, cy, R, outer, inner, highlight, t){
  // Outer halo
  const halo = ctx.createRadialGradient(cx, cy, R, cx, cy, R*1.4);
  halo.addColorStop(0, outer + "40"); halo.addColorStop(1, "transparent");
  ctx.fillStyle = halo;
  ctx.beginPath(); ctx.arc(cx, cy, R*1.4, 0, Math.PI*2); ctx.fill();
  // Outer lipid shell (PEG corona)
  const og = ctx.createRadialGradient(cx, cy, R*0.6, cx, cy, R);
  og.addColorStop(0, outer + "AA"); og.addColorStop(1, outer);
  ctx.fillStyle = og;
  ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI*2); ctx.fill();
  // Inner ionizable lipid core
  const ig = ctx.createRadialGradient(cx-R*0.2, cy-R*0.2, 0, cx, cy, R*0.7);
  ig.addColorStop(0, highlight); ig.addColorStop(1, inner);
  ctx.fillStyle = ig;
  ctx.beginPath(); ctx.arc(cx, cy, R*0.7, 0, Math.PI*2); ctx.fill();
  // PEG corona "hairs" — wisps
  ctx.strokeStyle = highlight + "50";
  ctx.lineWidth = 1.2;
  for(let i=0;i<28;i++){
    const a = i*Math.PI*2/28 + t*0.0002;
    const x1 = cx + Math.cos(a)*R;
    const y1 = cy + Math.sin(a)*R;
    const x2 = cx + Math.cos(a)*(R + 8 + Math.sin(t*0.002 + i)*3);
    const y2 = cy + Math.sin(a)*(R + 8 + Math.sin(t*0.002 + i)*3);
    ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
  }
}

function drawDDSGeneric(ctx, cx, cy, R, outer, inner, highlight, t){
  const halo = ctx.createRadialGradient(cx, cy, R*0.95, cx, cy, R*1.35);
  halo.addColorStop(0, outer + "20"); halo.addColorStop(1, "transparent");
  ctx.fillStyle = halo;
  ctx.beginPath(); ctx.arc(cx, cy, R*1.35, 0, Math.PI*2); ctx.fill();
  const grad = ctx.createRadialGradient(cx-R*0.3, cy-R*0.3, 0, cx, cy, R);
  grad.addColorStop(0, highlight);
  grad.addColorStop(0.5, outer);
  grad.addColorStop(1, inner);
  ctx.fillStyle = grad;
  ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI*2); ctx.fill();
}

function drawDDS(ctx, shape, cx, cy, R, outer, inner, highlight, t){
  switch(shape){
    case "bilayer_vesicle":     drawDDSBilayer(ctx, cx, cy, R, outer, inner, highlight, t); break;
    case "icosahedral_capsid":  drawDDSCapsid(ctx, cx, cy, R, outer, inner, highlight, t); break;
    case "sphere_with_pores":   drawDDSPLGA(ctx, cx, cy, R, outer, inner, highlight, t); break;
    case "core_shell_lipid":    drawDDSLNP(ctx, cx, cy, R, outer, inner, highlight, t); break;
    default:                    drawDDSGeneric(ctx, cx, cy, R, outer, inner, highlight, t);
  }
}
"""
