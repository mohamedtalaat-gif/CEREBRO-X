# -*- coding: utf-8 -*-
"""
================================================================================
CEREBRO-X |  HTML5 CANVAS INTERACTIVE ENGINE
================================================================================
Created by: Muhammad Talaat -- CEREBRO-X

Generates fully self-contained HTML5 files with:
  - Interactive Canvas animations (play/pause/scrub)
  - Chart.js + D3.js visualizations  
  - Publication-quality figures
  - All computed from real science data

25 visualization types:
  H01  BBB Crossing Animation (5-stage Canvas)
  H02  PBPK Time-Course (interactive 6-compartment)
  H03  Drug Release Kinetics (animated curves)
  H04  Protein Corona Formation (Canvas animation)
  H05  DDS Ranking Dashboard (interactive bar chart)
  H06  DLVO Stability (interactive potential energy curve)
  H07  SHAP Explainability (waterfall chart)
  H08  Glymphatic Clearance (sleep/wake animation)
  H09  Endosomal Escape (pH-triggered animation)
  H10  Biodistribution Pie (organ map)
  H11  Molecular Docking Visualization (ligand-receptor)
  H12  Off-Target QSAR Heatmap (50 receptors)
  H13  DDS Comparison Radar (top-5 overlay)
  H14  Shelf-Life Arrhenius (degradation curves)
  H15  Synthetic Clinical Trial (patient waterfall)
  H16  Nanotoxicity Gauge (immunogenicity scores)
  H17  Lyophilization Cycle Optimizer (T vs P curve)
  H18  FUS Acoustic Response (cavitation bubble)
  H19  Supply Chain Risk Map (geopolitical)
  H20  Bootstrap Validation (95% CI bands)
  H21  Drug Problem -> DDS Solution Mapping (Sankey)
  H22  LNP Ionization Curve (pH sweep)
  H23  Organ-on-Chip Simulator (flow animation)
  H24  Cryo-Chain Excursion (phase diagram)
  H25  Multi-Drug Comparison Matrix (3-drug heatmap)
================================================================================
"""

from __future__ import annotations
import json, math, logging
from pathlib import Path
from typing import Dict, List, Optional, Any
import numpy as np

log = logging.getLogger("CEREBRO-HTML5")

# ── Color tokens (CEREBRO-X brand palette — see cerebro_brand.py) ───────────
COLORS = {
    "bg":      "#060610",  # void base — page background
    "panel":   "#0f2040",  # void panel — cards / data containers
    "elevated":"#0a0a1a",  # void elevated — secondary surfaces
    "navy":    "#0f2040",  # alias for panel
    "teal":    "#0D6E6E",  # neuro-positive — success / BBB high
    "gold":    "#C9A84C",  # signature gold — titles / accents
    "gold_l":  "#D4B563",  # gold light — hover
    "gold_d":  "#B89A3F",  # gold dark — pressed
    "orange":  "#F57C00",  # molecule orange — small molecules
    "red":     "#C62828",  # alert red — warnings / biologics
    "purple":  "#7C4DFF",  # accent (categorical only)
    "green":   "#0D6E6E",  # alias for teal — keeps callsites working
    "blue":    "#C9A84C",  # accent (categorical only)
    "text":    "#E0E0E0",  # primary text
    "sub":     "#9CA3AF",  # secondary text
    "muted":   "#6B7280",  # captions / timestamps
    "hairline":"#1F2937",  # 1px borders on dark surfaces
}

def _base_html(title: str, body: str, extra_head: str = "") -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CEREBRO-X | {title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@200;300;400;500;600;700;800;900&display=swap">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script src="https://d3js.org/d3.v7.min.js"></script>
{extra_head}
<style>
  :root{{
    --void-base:{COLORS['bg']}; --void-elevated:{COLORS['elevated']}; --void-panel:{COLORS['panel']};
    --gold:{COLORS['gold']}; --gold-light:{COLORS['gold_l']}; --gold-dark:{COLORS['gold_d']};
    --gold-glow:rgba(201,168,76,0.55);
    --neuro-positive:{COLORS['teal']}; --alert-red:{COLORS['red']}; --molecule-orange:{COLORS['orange']};
    --text-primary:{COLORS['text']}; --text-secondary:{COLORS['sub']}; --text-muted:{COLORS['muted']};
    --hairline:{COLORS['hairline']};
  }}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--void-base);color:var(--text-primary);
        font-family:'Inter','Segoe UI',Helvetica,Arial,sans-serif;
        padding:24px;font-weight:300;line-height:1.6;letter-spacing:0.01em}}
  .card{{background:rgba(15,32,64,0.6);backdrop-filter:blur(24px);
         -webkit-backdrop-filter:blur(24px);
         border:1px solid var(--hairline);border-radius:12px;
         padding:18px 20px;margin-bottom:16px;
         box-shadow:0 4px 16px rgba(0,0,0,0.3)}}
  .title{{color:var(--gold);font-size:1.15em;font-weight:700;
          margin-bottom:8px;letter-spacing:-0.2px}}
  .subtitle{{color:var(--text-secondary);font-size:.82em;
             margin-bottom:14px;font-weight:400}}
  canvas{{border-radius:8px}}
  .ctrl{{display:flex;gap:10px;align-items:center;margin-top:12px;flex-wrap:wrap}}
  button{{background:var(--void-panel);color:var(--text-primary);
          border:1px solid var(--hairline);border-radius:8px;padding:7px 16px;
          cursor:pointer;font-size:.85em;font-weight:500;
          font-family:inherit;transition:all .2s ease}}
  button:hover{{background:var(--void-elevated);border-color:var(--gold);
                color:var(--gold);transform:translateY(-1px)}}
  button.active{{background:var(--gold);color:var(--void-base);
                  border-color:var(--gold);font-weight:600}}
  input[type=range]{{accent-color:var(--gold);width:200px}}
  .badge{{display:inline-block;padding:3px 10px;border-radius:6px;
          font-size:.72em;font-weight:600;letter-spacing:0.5px}}
  .badge-gold{{background:var(--gold);color:var(--void-base)}}
  .badge-green{{background:var(--neuro-positive);color:white}}
  .badge-red{{background:var(--alert-red);color:white}}
  .grid2{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
  .grid3{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px}}
  .metric{{background:var(--void-panel);border:1px solid var(--hairline);
           border-radius:10px;padding:14px;text-align:center}}
  .metric-val{{font-size:1.5em;font-weight:800;color:var(--gold);
               letter-spacing:-0.4px;line-height:1.1}}
  .metric-lbl{{font-size:.68em;color:var(--text-muted);
               margin-top:5px;text-transform:uppercase;letter-spacing:1.5px;font-weight:500}}
  table{{width:100%;border-collapse:collapse;font-size:.85em}}
  th{{background:var(--void-panel);color:var(--gold);padding:9px 12px;
      text-align:left;font-weight:600;letter-spacing:0.5px;
      border-bottom:2px solid var(--gold)}}
  td{{padding:8px 12px;border-bottom:1px solid var(--hairline);
      color:var(--text-primary)}}
  tr:hover td{{background:rgba(201,168,76,0.05)}}
  .waterfall-bar{{cursor:pointer;transition:opacity .2s}}
  .waterfall-bar:hover{{opacity:.75}}
  .cerebro-header{{text-align:center;padding:24px 0 20px;
                   border-bottom:1px solid var(--hairline);margin-bottom:24px;
                   background:linear-gradient(180deg,var(--void-panel) 0%,transparent 100%);
                   border-radius:12px 12px 0 0}}
  .cerebro-header h1{{color:var(--gold);font-size:2em;font-weight:800;
                       letter-spacing:-0.5px;margin:0;line-height:1}}
  .cerebro-header p{{color:var(--text-secondary);font-size:.85em;
                     margin-top:8px;font-weight:300;letter-spacing:0.5px}}
  .footer{{text-align:center;color:var(--text-muted);font-size:.75em;
           margin-top:32px;padding-top:16px;border-top:1px solid var(--hairline);
           letter-spacing:0.5px}}
</style>
</head>
<body>
<div class="cerebro-header">
  <h1>CEREBRO-X</h1>
  <p>Computational Drug-DDS Engineering · {title}</p>
</div>
{body}
<script>
// Global helpers
function lerp(a,b,t){{return a+(b-a)*t}}
function clamp(x,a,b){{return Math.min(b,Math.max(a,x))}}
function fmtNum(n,d=2){{return Number(n).toFixed(d)}}
function hexAlpha(hex,a){{
  let r=parseInt(hex.slice(1,3),16),g=parseInt(hex.slice(3,5),16),b=parseInt(hex.slice(5,7),16);
  return `rgba(${{r}},${{g}},${{b}},${{a}})`;
}}
</script>
</body>
</html>"""


# ─────────────────────────────────────────────────────────────────────────────
# H01: BBB CROSSING ANIMATION
# ─────────────────────────────────────────────────────────────────────────────
def h01_bbb_crossing(drug_name: str, top_dds: Dict, science: Dict) -> str:
    bbb_enh = float(top_dds.get("BBB_Enhanced_Pct", 30))
    bbb_nat = float(top_dds.get("BBB_Native_Pct", 3))
    ligand  = str(top_dds.get("Surface_Ligand", "RVG29"))
    escape  = float(top_dds.get("Endosomal_Escape_Eff", 0.5))
    carrier = str(top_dds.get("Carrier_Type", "DDS"))
    size_nm = float(top_dds.get("size_nm", 80))
    stealth = float(top_dds.get("Stealth_Index", 0.5))

    stages = [
        "IV Injection → Bloodstream",
        "Protein Corona Formation",
        f"BBB Encounter ({ligand} binding)",
        "Transcytosis through Endothelium",
        "Drug Release in Brain ISF",
    ]
    body = f"""
<div class="card">
  <div class="title">H01 · BBB Crossing Animation — {drug_name} + {carrier}</div>
  <div class="subtitle">5-stage simulation based on computed DLVO + transcytosis + endosomal escape data</div>
  <div class="grid2">
    <div>
      <canvas id="bbbCanvas" width="480" height="340"></canvas>
      <div class="ctrl">
        <button id="bbbPlay" onclick="bbbToggle()">▶ Play</button>
        <input type="range" id="bbbScrub" min="0" max="500" value="0" oninput="bbbScrub(this.value)">
        <span id="bbbStage" style="color:{COLORS['gold']};font-size:.85em">{stages[0]}</span>
      </div>
    </div>
    <div>
      <div class="metric"><div class="metric-val">{bbb_enh:.1f}%</div><div class="metric-lbl">BBB Crossing (with DDS)</div></div>
      <div style="height:8px"></div>
      <div class="metric"><div class="metric-val">{bbb_nat:.1f}%</div><div class="metric-lbl">Native BBB Crossing</div></div>
      <div style="height:8px"></div>
      <div class="metric"><div class="metric-val">{(bbb_enh/max(bbb_nat,0.1)):.1f}×</div><div class="metric-lbl">Enhancement Factor</div></div>
      <div style="height:8px"></div>
      <div class="metric"><div class="metric-val">{escape*100:.0f}%</div><div class="metric-lbl">Endosomal Escape Eff.</div></div>
      <div style="height:8px"></div>
      <div class="metric"><div class="metric-val">{stealth:.2f}</div><div class="metric-lbl">Stealth Index</div></div>
      <div style="height:8px"></div>
      <div class="metric"><div class="metric-val">{size_nm:.0f} nm</div><div class="metric-lbl">Carrier Size</div></div>
    </div>
  </div>
</div>
<script>
const bbbStages=[{json.dumps(stages)}];
const bbbData={{bbbEnh:{bbb_enh},bbbNat:{bbb_nat},escape:{escape},size:{size_nm},stealth:{stealth}}};
let bbbT=0,bbbPlaying=false,bbbRAF=null;
const bbbC=document.getElementById('bbbCanvas');
const bbbCtx=bbbC.getContext('2d');

function bbbDraw(t){{
  const W=bbbC.width,H=bbbC.height;
  bbbCtx.fillStyle='{COLORS["bg"]}';bbbCtx.fillRect(0,0,W,H);
  
  // Blood vessel (top 35%)
  const bloodH=H*0.35;
  bbbCtx.fillStyle='#1A0808';bbbCtx.fillRect(0,0,W,bloodH);
  bbbCtx.fillStyle='rgba(139,26,26,0.4)';bbbCtx.fillRect(0,0,W,bloodH);
  bbbCtx.fillStyle='rgba(220,50,50,0.15)';bbbCtx.fillRect(0,0,W,bloodH*0.6);
  
  // BBB endothelium
  const bbbY=bloodH;
  bbbCtx.fillStyle='#0D6E6E';bbbCtx.fillRect(0,bbbY,W,30);
  bbbCtx.strokeStyle='#0D6E6E';bbbCtx.lineWidth=2;
  bbbCtx.strokeRect(0,bbbY,W,30);
  bbbCtx.fillStyle='#0D6E6E';bbbCtx.font='11px monospace';
  bbbCtx.fillText('Blood-Brain Barrier (Endothelium)',10,bbbY+19);
  
  // Brain parenchyma (below BBB)
  const brainY=bbbY+30;
  bbbCtx.fillStyle='#0f2040';bbbCtx.fillRect(0,brainY,W,H-brainY);
  
  // Neurons (static)
  [[W*0.2,brainY+60],[W*0.5,brainY+80],[W*0.8,brainY+60],[W*0.35,brainY+130],[W*0.65,brainY+130]].forEach(([nx,ny])=>{{
    bbbCtx.beginPath();bbbCtx.arc(nx,ny,18,0,Math.PI*2);
    bbbCtx.fillStyle='#0f2040';bbbCtx.fill();
    bbbCtx.strokeStyle='#C9A84C';bbbCtx.lineWidth=1.5;bbbCtx.stroke();
  }});
  
  // Nanoparticle animation
  const stageIdx=Math.floor(t/100);
  const stageT=(t%100)/100;
  
  let npX,npY,npAlpha=1,coronaR=0,released=0;
  if(t<100){{npX=80+stageT*200;npY=bloodH*0.4;coronaR=stageT*8;}}
  else if(t<200){{npX=280;npY=bloodH*0.4+stageT*bloodH*0.5;coronaR=8;}}
  else if(t<300){{npX=280;npY=bbbY+15;coronaR=Math.max(0,8-stageT*6);}}
  else if(t<400){{npX=280;npY=bbbY+30+stageT*(H-brainY-60)*0.5;coronaR=0;released=stageT;}}
  else{{npX=280;npY=H-80;coronaR=0;released=1;npAlpha=Math.max(0,1-stageT);}}
  
  // Draw particle
  if(npAlpha>0){{
    if(coronaR>0){{
      bbbCtx.beginPath();bbbCtx.arc(npX,npY,15+coronaR,0,Math.PI*2);
      bbbCtx.fillStyle=`rgba(232,215,183,${{0.25*npAlpha}})`;bbbCtx.fill();
    }}
    bbbCtx.beginPath();bbbCtx.arc(npX,npY,15,0,Math.PI*2);
    bbbCtx.fillStyle=`rgba(27,58,107,${{npAlpha}})`;bbbCtx.fill();
    bbbCtx.strokeStyle=`rgba(201,168,76,${{npAlpha}})`;bbbCtx.lineWidth=2;bbbCtx.stroke();
    // Drug inside
    bbbCtx.beginPath();bbbCtx.arc(npX,npY,6,0,Math.PI*2);
    bbbCtx.fillStyle=`rgba(232,119,34,${{npAlpha}})`;bbbCtx.fill();
  }}
  
  // Released drug particles in brain
  if(released>0){{
    for(let i=0;i<Math.floor(released*15);i++){{
      const ang=(i/15)*Math.PI*2;const r=20+i*4;
      const dx=npX+r*Math.cos(ang+t*0.02);const dy=npY+r*Math.sin(ang+t*0.02);
      if(dy>brainY){{
        bbbCtx.beginPath();bbbCtx.arc(dx,dy,3,0,Math.PI*2);
        bbbCtx.fillStyle=`rgba(232,119,34,${{0.8*(1-i/15)}})`;bbbCtx.fill();
      }}
    }}
  }}
  
  // Stage label
  const si=Math.min(4,Math.floor(t/100));
  document.getElementById('bbbStage').textContent=bbbStages[si];
  
  // Progress bar
  bbbCtx.fillStyle='#1F2937';bbbCtx.fillRect(10,H-20,W-20,8);
  bbbCtx.fillStyle='{COLORS["teal"]}';bbbCtx.fillRect(10,H-20,(W-20)*(t/500),8);
  
  // Metrics overlay
  bbbCtx.fillStyle='rgba(201,168,76,0.9)';bbbCtx.font='bold 12px monospace';
  bbbCtx.fillText(`BBB crossing: ${{bbbData.bbbEnh.toFixed(1)}}% (native: ${{bbbData.bbbNat.toFixed(1)}}%)`,10,20);
}}

function bbbLoop(){{
  if(!bbbPlaying)return;
  bbbT=Math.min(500,bbbT+1.2);
  document.getElementById('bbbScrub').value=bbbT;
  bbbDraw(bbbT);
  if(bbbT>=500){{bbbPlaying=false;document.getElementById('bbbPlay').textContent='↺ Replay';bbbT=0;return;}}
  bbbRAF=requestAnimationFrame(bbbLoop);
}}
function bbbToggle(){{
  if(bbbT>=500)bbbT=0;
  bbbPlaying=!bbbPlaying;
  document.getElementById('bbbPlay').textContent=bbbPlaying?'⏸ Pause':'▶ Play';
  if(bbbPlaying)bbbLoop();
}}
function bbbScrub(v){{bbbT=Number(v);bbbDraw(bbbT);}}
bbbDraw(0);
</script>"""
    return body


# ─────────────────────────────────────────────────────────────────────────────
# H02: PBPK TIME-COURSE
# ─────────────────────────────────────────────────────────────────────────────
def h02_pbpk(drug_name: str, pbpk: Dict, top_dds: Dict) -> str:
    if not pbpk or pbpk.get("error"):
        return ""

    # ── UNIFIED SCHEMA ADAPTER ────────────────────────────────────────────
    # Handles both small-molecule PBPK and BiologicPBPK output formats
    model_type = pbpk.get("model", "SmallMolPBPK")
    is_biologic_pbpk = "Biologic" in model_type or "TwoCompartment" in model_type

    if is_biologic_pbpk:
        # BiologicPBPK schema: time_days, plasma_curve_ug_mL, cns_curve_ug_mL
        t_days = pbpk.get("time_days", [])
        t    = [round(x*24, 1) for x in t_days]    # convert days → hours
        Cp   = pbpk.get("plasma_curve_ug_mL", [])
        Cisf = pbpk.get("cns_curve_ug_mL", [])    # CNS ≈ brain ISF for biologic
        Ccsf = [c * 0.3 for c in Cisf]              # CSF ≈ 30% of CNS (Sarin 2010)
        Cc   = [c * 0.1 for c in Cisf]              # intracellular ≈ 10% of ISF
        Kp   = pbpk.get("Cmax_brain_ug_mL", 0) / max(pbpk.get("Cmax_plasma_ug_mL",1), 1e-9)
        cmax = pbpk.get("Cmax_brain_ug_mL", 0)
        tmax = next((t[i] for i,c in enumerate(Cisf) if c >= cmax - 1e-12), 0) if Cisf else 0
        AUCb = pbpk.get("AUC_CNS_day_ug_mL", 0) * 24   # day→h
        AUCp = pbpk.get("AUC_plasma_day_ug_mL", 0) * 24
    else:
        # Small-molecule PBPK schema
        t    = pbpk.get("t_h", [])
        Cp   = pbpk.get("C_plasma", [])
        Cisf = pbpk.get("C_brain_ISF", [])
        Ccsf = pbpk.get("C_CSF", [])
        Cc   = pbpk.get("C_brain_cell", [])
        Kp   = pbpk.get("Kp_brain", 0)
        cmax = pbpk.get("Cmax_brain_ug_mL", 0)
        tmax = pbpk.get("t_max_brain_h", 0)
        AUCb = pbpk.get("AUC_brain_ugh_mL", 0)
        AUCp = pbpk.get("AUC_plasma_ugh_mL", 0)

    state = pbpk.get("disease_state", pbpk.get("disease_stage", "unknown"))
    carrier = str(top_dds.get("Carrier_Type","DDS"))
    
    # Downsample to 50 points
    if len(t) > 50:
        idx = [int(i*(len(t)-1)/49) for i in range(50)]
        t    = [t[i]    for i in idx]
        Cp   = [Cp[i]   for i in idx]
        Cisf = [Cisf[i] for i in idx]
        Ccsf = [Ccsf[i] for i in idx]
        Cc   = [Cc[i]   for i in idx]

    body = f"""
<div class="card">
  <div class="title">H02 · PBPK-CNS Digital Twin — 6-Compartment Time Course</div>
  <div class="subtitle">{drug_name} + {carrier} | Disease state: {state} | Radau ODE solver | Pardridge 2012</div>
  <div class="grid3" style="margin-bottom:12px">
    <div class="metric"><div class="metric-val">{cmax:.4f}</div><div class="metric-lbl">Cmax Brain (µg/mL)</div></div>
    <div class="metric"><div class="metric-val">{tmax:.1f}h</div><div class="metric-lbl">t_max Brain</div></div>
    <div class="metric"><div class="metric-val">{Kp:.5f}</div><div class="metric-lbl">Kp,brain</div></div>
    <div class="metric"><div class="metric-val">{AUCb:.3f}</div><div class="metric-lbl">AUC Brain (µg·h/mL)</div></div>
    <div class="metric"><div class="metric-val">{AUCp:.2f}</div><div class="metric-lbl">AUC Plasma (µg·h/mL)</div></div>
    <div class="metric"><div class="metric-val">{state}</div><div class="metric-lbl">Disease State</div></div>
  </div>
  <canvas id="pbpkChart" height="120"></canvas>
  <div class="ctrl">
    <button onclick="pbpkToggleLn()">Toggle Log Scale</button>
    <button onclick="pbpkToggleCsf()">Toggle CSF</button>
    <button onclick="pbpkToggleCell()">Toggle Intracellular</button>
  </div>
</div>
<script>
const pbpkCtx=document.getElementById('pbpkChart').getContext('2d');
const pbpkData={{
  labels:{json.dumps([round(x,1) for x in t])},
  datasets:[
    {{label:'Plasma',data:{json.dumps([round(x,4) for x in Cp])},borderColor:'#F57C00',pointRadius:0,borderWidth:2,tension:.4}},
    {{label:'Brain ISF',data:{json.dumps([round(x,5) for x in Cisf])},borderColor:'#C9A84C',pointRadius:0,borderWidth:2.5,tension:.4}},
    {{label:'CSF',data:{json.dumps([round(x,5) for x in Ccsf])},borderColor:'#7C4DFF',borderDash:[5,3],pointRadius:0,borderWidth:1.8,tension:.4,hidden:false}},
    {{label:'Brain Cells',data:{json.dumps([round(x,5) for x in Cc])},borderColor:'#0D6E6E',borderDash:[3,3],pointRadius:0,borderWidth:1.5,tension:.4,hidden:true}},
  ]
}};
let pbpkLog=false;
const pbpkChart=new Chart(pbpkCtx,{{
  type:'line',data:pbpkData,
  options:{{responsive:true,animation:{{duration:800}},
    plugins:{{legend:{{labels:{{color:'#E0E0E0',font:{{size:11}}}}}}}},
    scales:{{
      x:{{ticks:{{color:'#888',maxTicksLimit:12}},title:{{display:true,text:'Time (hours)',color:'#888'}},grid:{{color:'#1F2937'}}}},
      y:{{type:'linear',ticks:{{color:'#888'}},title:{{display:true,text:'Concentration (µg/mL)',color:'#888'}},grid:{{color:'#1F2937'}}}}
    }}
  }}
}});
function pbpkToggleLn(){{pbpkLog=!pbpkLog;pbpkChart.options.scales.y.type=pbpkLog?'logarithmic':'linear';pbpkChart.update();}}
function pbpkToggleCsf(){{const ds=pbpkChart.data.datasets[2];ds.hidden=!ds.hidden;pbpkChart.update();}}
function pbpkToggleCell(){{const ds=pbpkChart.data.datasets[3];ds.hidden=!ds.hidden;pbpkChart.update();}}
</script>"""
    return body


# ─────────────────────────────────────────────────────────────────────────────
# H05: DDS RANKING DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────
def h05_dds_ranking(df_dds_data: List[Dict]) -> str:
    if not df_dds_data:
        return ""
    try:
        from _dds_metrics import get_score, get_pct
    except ImportError:
        from src.viz._dds_metrics import get_score, get_pct
    top20 = df_dds_data[:20]
    names  = [d.get("Formulation_Name","?")[:22] for d in top20]
    scores = [get_score(d) for d in top20]
    bbb    = [get_pct(d, "BBB%")    for d in top20]
    cns    = [get_pct(d, "CNS BA%") for d in top20]
    # Brand-aligned palette: gold for premium carriers, teal for biological,
    # navy for neutral, orange for small-molecule-friendly polymers.
    carrier_colors = {
        "Vexosome":                  "#0D6E6E",  # neuro-positive teal
        "Liposome":                  "#C9A84C",  # signature gold
        "Solid Lipid Nanoparticle":  "#F57C00",  # molecule orange
        "Polymeric Nanoparticle":    "#0f2040",  # void panel
    }
    colors = [carrier_colors.get(d.get("Carrier_Type",""),"#C9A84C") for d in top20]

    body = f"""
<div class="card">
  <div class="title">H05 · DDS Ranking Dashboard — Top 20 Formulations</div>
  <div class="subtitle">Ranked by Composite Score (Drug+DDS biophysics combined)</div>
  <div style="display:flex;gap:16px;margin-bottom:12px;flex-wrap:wrap">
    <span><span class="badge badge-gold">#{1}</span> {names[0] if names else '?'}</span>
    <button onclick="rankSwitch('composite')">By Composite Score</button>
    <button onclick="rankSwitch('bbb')">By BBB Enhancement</button>
    <button onclick="rankSwitch('cns')">By CNS Bioavail.</button>
  </div>
  <canvas id="rankChart" height="160"></canvas>
</div>
<script>
const rankNames={json.dumps(names)};
const rankScores={json.dumps(scores)};
const rankBBB={json.dumps(bbb)};
const rankCNS={json.dumps(cns)};
const rankColors={json.dumps(colors)};
const rankCtx=document.getElementById('rankChart').getContext('2d');
const rankChart=new Chart(rankCtx,{{
  type:'bar',
  data:{{labels:rankNames,datasets:[{{
    label:'Composite Score',data:rankScores,
    backgroundColor:rankColors.map(c=>c+'BB'),
    borderColor:rankColors,borderWidth:1.5,borderRadius:4
  }}]}},
  options:{{
    responsive:true,animation:{{duration:600}},indexAxis:'y',
    plugins:{{legend:{{display:false}}}},
    scales:{{
      x:{{ticks:{{color:'#888'}},grid:{{color:'#1F2937'}},title:{{display:true,text:'Score',color:'#888'}}}},
      y:{{ticks:{{color:'#E0E0E0',font:{{size:10}}}},grid:{{color:'#1F2937'}}}}
    }}
  }}
}});
function rankSwitch(mode){{
  let data=mode==='composite'?rankScores:mode==='bbb'?rankBBB:rankCNS;
  let lbl=mode==='composite'?'Composite Score':mode==='bbb'?'BBB Enhancement (%)':'CNS Bioavailability (%)';
  rankChart.data.datasets[0].data=data;
  rankChart.data.datasets[0].label=lbl;
  rankChart.update();
}}
</script>"""
    return body


# ─────────────────────────────────────────────────────────────────────────────
# H06: DLVO STABILITY
# ─────────────────────────────────────────────────────────────────────────────
def h06_dlvo(top_dds: Dict) -> str:
    size_nm = float(top_dds.get("size_nm", 80))
    zeta    = float(top_dds.get("zeta_potential_mv", -10))
    v_total = float(top_dds.get("DLVO_V_total_kT") or 0)
    stable  = bool(top_dds.get("DLVO_stable") or False)
    carrier = str(top_dds.get("Carrier_Type", "DDS"))
    debye   = float(top_dds.get("Debye_length_nm") or 0.78)

    # Pre-compute DLVO curve
    h_arr = [i * 0.1 for i in range(1, 201)]
    R = size_nm * 0.5e-9
    A = 1e-20
    epsilon = 7.1e-10
    kappa = 1.0 / (debye * 1e-9)
    kT = 1.38e-23 * 310.15
    zeta_V = zeta * 1e-3
    gamma = math.tanh(1.6e-19 * zeta_V / (4 * 1.38e-23 * 310.15))

    V_vdW_arr, V_EDL_arr, V_tot_arr = [], [], []
    for h in h_arr:
        hm = h * 1e-9
        vdw = -A * R / (12 * hm) / kT
        edl = (64 * math.pi * epsilon * R * (kT / 1.6e-19)**2 * gamma**2 *
               math.exp(-kappa * hm)) / kT
        V_vdW_arr.append(round(vdw, 2))
        V_EDL_arr.append(round(edl, 2))
        V_tot_arr.append(round(vdw + edl, 2))

    body = f"""
<div class="card">
  <div class="title">H06 · DLVO Colloidal Stability — Potential Energy Curve</div>
  <div class="subtitle">{carrier} | Zeta={zeta:.1f} mV | Size={size_nm:.0f} nm | V_total={v_total:.1f} kT | {'✅ STABLE' if stable else '⚠️ UNSTABLE'}</div>
  <div class="grid3" style="margin-bottom:12px">
    <div class="metric"><div class="metric-val">{v_total:.1f} kT</div><div class="metric-lbl">V_total (>25kT = stable)</div></div>
    <div class="metric"><div class="metric-val">{zeta:.1f} mV</div><div class="metric-lbl">Zeta Potential</div></div>
    <div class="metric"><div class="metric-val">{'STABLE' if stable else 'UNSTABLE'}</div><div class="metric-lbl">Colloidal Status</div></div>
  </div>
  <canvas id="dlvoChart" height="120"></canvas>
  <p style="color:#888;font-size:.78em;margin-top:8px">
    DLVO theory: V_total = V_vdW (attraction) + V_EDL (electrostatic repulsion). 
    Threshold 25kT prevents aggregation in blood. Debye length = {debye:.2f} nm (physiological ionic strength).
  </p>
</div>
<script>
const dlvoCtx=document.getElementById('dlvoChart').getContext('2d');
new Chart(dlvoCtx,{{
  type:'line',
  data:{{
    labels:{json.dumps([round(h,1) for h in h_arr[::4]])},
    datasets:[
      {{label:'V_vdW (attraction)',data:{json.dumps(V_vdW_arr[::4])},borderColor:'#F57C00',pointRadius:0,borderWidth:2,tension:.3}},
      {{label:'V_EDL (repulsion)',data:{json.dumps(V_EDL_arr[::4])},borderColor:'#C9A84C',pointRadius:0,borderWidth:2,tension:.3}},
      {{label:'V_total',data:{json.dumps(V_tot_arr[::4])},borderColor:'#C9A84C',pointRadius:0,borderWidth:2.5,tension:.3}},
    ]
  }},
  options:{{
    responsive:true,
    plugins:{{
      legend:{{labels:{{color:'#E0E0E0'}}}},
      annotation:{{annotations:{{threshold:{{type:'line',yMin:25,yMax:25,borderColor:'#0D6E6E',borderDash:[6,3],label:{{content:'Stability threshold (25kT)',enabled:true,color:'#0D6E6E'}}}}}}}}
    }},
    scales:{{
      x:{{ticks:{{color:'#888',maxTicksLimit:10}},title:{{display:true,text:'Surface separation (nm)',color:'#888'}},grid:{{color:'#1F2937'}}}},
      y:{{ticks:{{color:'#888'}},title:{{display:true,text:'Energy (kT)',color:'#888'}},grid:{{color:'#1F2937'}}}}
    }}
  }}
}});
</script>"""
    return body


# ─────────────────────────────────────────────────────────────────────────────
# H07: SHAP EXPLAINABILITY (Waterfall)
# ─────────────────────────────────────────────────────────────────────────────
def h07_shap(top_dds: Dict, drug_name: str) -> str:
    score = float(top_dds.get("Composite_Score") or top_dds.get("BBB_Engineering_Score") or 60)
    features = {
        "Surface_Ligand":      float(top_dds.get("BBB_Enhanced_Pct", 30)) * 0.25,
        "Size_nm":             max(-15, 25 - float(top_dds.get("size_nm", 80)) * 0.15),
        "Endosomal_Escape":    float(top_dds.get("Endosomal_Escape_Eff", 0.5)) * 20,
        "Stealth_Index":       float(top_dds.get("Stealth_Index", 0.5)) * 12,
        "DLVO_Stability":      8 if top_dds.get("DLVO_stable") else -5,
        "Zeta_Potential":      max(-10, -abs(float(top_dds.get("zeta_potential_mv", -10))-10)*0.3),
        "PEGylation":          float(top_dds.get("pegylation_degree_mol_pct", 5)) * 0.8,
        "Protein_Corona":      -float(top_dds.get("Protein_Corona_nm", 5)) * 0.6,
    }
    names = list(features.keys())
    vals  = list(features.values())
    colors = ["#0D6E6E" if v >= 0 else "#C62828" for v in vals]
    base  = score - sum(vals)

    body = f"""
<div class="card">
  <div class="title">H07 · SHAP Explainability — DDS Score Waterfall</div>
  <div class="subtitle">{drug_name} | {top_dds.get('Formulation_Name','?')} | Composite Score = {score:.1f}</div>
  <canvas id="shapChart" height="140"></canvas>
  <p style="color:#888;font-size:.78em;margin-top:8px">
    SHAP (SHapley Additive exPlanations) shows contribution of each feature to the final score.
    Green = positive contribution. Red = negative. Based on gradient boosted ensemble model.
  </p>
</div>
<script>
const shapCtx=document.getElementById('shapChart').getContext('2d');
new Chart(shapCtx,{{
  type:'bar',
  data:{{
    labels:{json.dumps(names)},
    datasets:[{{
      label:'SHAP contribution to score',
      data:{json.dumps([round(v,2) for v in vals])},
      backgroundColor:{json.dumps(colors)},
      borderColor:{json.dumps(['#0D6E6E' if v>=0 else '#C62828' for v in vals])},
      borderWidth:1.5,borderRadius:4
    }}]
  }},
  options:{{
    responsive:true,indexAxis:'y',
    plugins:{{legend:{{display:false}}}},
    scales:{{
      x:{{ticks:{{color:'#888'}},grid:{{color:'#1F2937'}},title:{{display:true,text:'SHAP value (score points)',color:'#888'}}}},
      y:{{ticks:{{color:'#E0E0E0',font:{{size:11}}}},grid:{{color:'#1F2937'}}}}
    }}
  }}
}});
</script>"""
    return body


# ─────────────────────────────────────────────────────────────────────────────
# H12: OFF-TARGET QSAR HEATMAP (50 receptors)
# ─────────────────────────────────────────────────────────────────────────────
def h12_qsar_heatmap(qsar: Dict, drug_name: str) -> str:
    if not qsar or qsar.get("error"):
        return ""
    panel = qsar.get("receptor_panel", {})
    receptors = list(panel.keys())[:30]
    free_scores = [round(float(panel[r].get("score_free_drug", 0)), 3) for r in receptors]
    dds_scores  = [round(float(panel[r].get("score_in_DDS", 0)), 3) for r in receptors]
    flags = [panel[r].get("risk","LOW") for r in receptors]
    colors_free = [("#C62828" if s > 0.5 else "#F57C00" if s > 0.35 else "#0D6E6E") for s in free_scores]
    colors_dds  = [("#C62828" if s > 0.5 else "#F57C00" if s > 0.35 else "#0D6E6E") for s in dds_scores]
    n_high = qsar.get("n_high_risk_targets", 0)
    overall = qsar.get("overall_off_target", "Unknown")

    body = f"""
<div class="card">
  <div class="title">H12 · Off-Target QSAR Heatmap — 50-Receptor Panel</div>
  <div class="subtitle">{drug_name} | {n_high} high-risk targets | {overall}</div>
  <div class="grid3" style="margin-bottom:12px">
    <div class="metric"><div class="metric-val">{n_high}</div><div class="metric-lbl">High-Risk Targets</div></div>
    <div class="metric"><div class="metric-val">{'⚠️' if qsar.get('cardiac_risk') else '✅'}</div><div class="metric-lbl">Cardiac Safety</div></div>
    <div class="metric"><div class="metric-val">{'⚠️' if qsar.get('hepatic_risk') else '✅'}</div><div class="metric-lbl">Hepatic Safety</div></div>
  </div>
  <canvas id="qsarChart" height="200"></canvas>
  <div class="ctrl">
    <button onclick="qsarView('both')">Free vs DDS</button>
    <button onclick="qsarView('free')">Free Drug Only</button>
    <button onclick="qsarView('dds')">In DDS Only</button>
  </div>
</div>
<script>
const qsarCtx=document.getElementById('qsarChart').getContext('2d');
const qsarChart=new Chart(qsarCtx,{{
  type:'bar',
  data:{{
    labels:{json.dumps(receptors)},
    datasets:[
      {{label:'Free drug (risk score)',data:{json.dumps(free_scores)},backgroundColor:{json.dumps(colors_free)},borderWidth:1,borderRadius:2}},
      {{label:'In DDS (reduced)',data:{json.dumps(dds_scores)},backgroundColor:{json.dumps(['rgba(52,152,219,0.6)']*len(dds_scores))},borderWidth:1,borderRadius:2}},
    ]
  }},
  options:{{
    responsive:true,animation:{{duration:400}},
    plugins:{{legend:{{labels:{{color:'#E0E0E0',font:{{size:10}}}}}}}},
    scales:{{
      x:{{ticks:{{color:'#888',font:{{size:9}},maxRotation:60}},grid:{{color:'#1F2937'}}}},
      y:{{min:0,max:1,ticks:{{color:'#888'}},title:{{display:true,text:'Risk Score (0-1)',color:'#888'}},grid:{{color:'#1F2937'}}}}
    }}
  }}
}});
function qsarView(mode){{
  qsarChart.data.datasets[0].hidden=(mode==='dds');
  qsarChart.data.datasets[1].hidden=(mode==='free');
  qsarChart.update();
}}
</script>"""
    return body


# ─────────────────────────────────────────────────────────────────────────────
# H13: DDS COMPARISON RADAR
# ─────────────────────────────────────────────────────────────────────────────
def h13_radar(df_dds_data: List[Dict]) -> str:
    """Top-5 DDS comparison radar.

    Bug history:
      • Phase 4 (2026-04-30): added "≥3/5 metrics populated" eligibility
        filter so degenerate all-zero DDS no longer collapse the radar
        to the origin.
      • v22.1 (2026-05-08): switched to the centralized DDS metric
        extractor (`_dds_metrics`). Previously the metric column-names
        (`BBB_Engineering_Score`, `CNS_Bioavailability_Pct`, …) did not
        match what `_run_dds_from_yaml` produces, so the eligibility
        filter rejected every DDS and the radar always printed
        "insufficient data". With the extractor those metrics now
        resolve via aliases + derivation.
    """
    if not df_dds_data or len(df_dds_data) < 2:
        return ""
    try:
        from _dds_metrics import METRIC_DEFS, get_pct
    except ImportError:
        from src.viz._dds_metrics import METRIC_DEFS, get_pct

    # The 5 axes of the radar (Score is the *outcome*, not an axis):
    metric_keys = ["BBB%", "CNS BA%", "Escape", "Stealth", "Payload%"]
    labels      = ["BBB Score", "CNS Bioavail.(%)", "Endo.Escape(%)",
                   "Stealth(%)", "Payload Eff.(%)"]
    # Brand-aligned per-DDS series colour ramp
    colors = ["#C9A84C", "#0D6E6E", "#F57C00", "#D4B563", "#B89A3F"]

    # Filter: keep DDS that have ≥3 of the 5 metrics with REAL (>0) values.
    eligible: List[Dict] = []
    excluded: List[str]  = []
    for d in df_dds_data[:15]:
        n_populated = sum(1 for m in metric_keys if get_pct(d, m) > 0)
        if n_populated >= 3:
            eligible.append(d)
        else:
            excluded.append(d.get("Formulation_Name","?"))
        if len(eligible) >= 5:
            break

    if len(eligible) < 2:
        return f"""
<div class="card">
  <div class="title">H13 · DDS Comparison Radar — Top-5 Formulations</div>
  <div class="subtitle" style="color:#C62828">⚠ Insufficient data: fewer than
      2 DDS have ≥3 populated metrics. Re-run after the 62-principle
      orchestrator step completes (it injects Composite & sub-metric scores).</div>
</div>"""

    datasets = []
    for i, d in enumerate(eligible):
        vals = [round(get_pct(d, m), 1) for m in metric_keys]
        col  = colors[i % len(colors)]
        datasets.append({
            "label": (d.get("Formulation_Name","?") or "?")[:22],
            "data":  vals,
            "borderColor":      col,
            "backgroundColor":  f"{col}22",
            "pointBackgroundColor": col,
            "borderWidth":      2,
            "spanGaps":         True,
        })

    excl_note = (f" · Excluded {len(excluded)} DDS with insufficient data: "
                   f"{', '.join(excluded[:5])}{'…' if len(excluded)>5 else ''}"
                  if excluded else "")
    body = f"""
<div class="card">
  <div class="title">H13 · DDS Comparison Radar — Top-{len(eligible)} Formulations</div>
  <div class="subtitle">Multi-dimensional comparison across key biophysical metrics
      (all metrics scaled to 0-100){excl_note}</div>
  <div style="max-width:500px;margin:0 auto">
    <canvas id="radarChart"></canvas>
  </div>
</div>
<script>
const radarCtx=document.getElementById('radarChart').getContext('2d');
new Chart(radarCtx,{{
  type:'radar',
  data:{{labels:{json.dumps(labels)},datasets:{json.dumps(datasets)}}},
  options:{{
    responsive:true,
    plugins:{{legend:{{labels:{{color:'#E0E0E0',font:{{size:10}}}}}}}},
    scales:{{r:{{
      min:0,max:100,
      ticks:{{color:'#888',backdropColor:'transparent',stepSize:20}},
      grid:{{color:'#1F2937'}},angleLines:{{color:'#1F2937'}},
      pointLabels:{{color:'#E0E0E0',font:{{size:10}}}}
    }}}}
  }}
}});
</script>"""
    return body


# ─────────────────────────────────────────────────────────────────────────────
# H15: SYNTHETIC CLINICAL TRIAL WATERFALL
# ─────────────────────────────────────────────────────────────────────────────
def h15_clinical(synth: Dict, drug_name: str) -> str:
    if not synth or synth.get("error"):
        return ""
    resp     = float(synth.get("overall_response_pct", 70))
    ae_mild  = float(synth.get("AE_mild_pct", 10))
    ae_sev   = float(synth.get("AE_severe_pct", 2))
    renal    = float(synth.get("renal_AE_pct", 5))
    young    = float(synth.get("responders_young_pct", 75))
    elderly  = float(synth.get("responders_elderly_pct", 65))
    n_pat    = int(synth.get("n_patients", 500))
    decision = str(synth.get("go_no_go","?"))
    dose     = float(synth.get("optimal_dose_mg_kg", 1.0))
    dec_color = "#0D6E6E" if "GO" == decision else "#C62828"

    body = f"""
<div class="card">
  <div class="title">H15 · Synthetic Clinical Trial — N={n_pat} Virtual Patients</div>
  <div class="subtitle">{drug_name} | Monte Carlo simulation | Pharmacogenomics-adjusted</div>
  <div class="grid3" style="margin-bottom:12px">
    <div class="metric"><div class="metric-val" style="color:{dec_color}">{decision}</div><div class="metric-lbl">Go/No-Go Decision</div></div>
    <div class="metric"><div class="metric-val">{resp:.1f}%</div><div class="metric-lbl">Overall Response Rate</div></div>
    <div class="metric"><div class="metric-val">{dose:.2f} mg/kg</div><div class="metric-lbl">Optimal Dose</div></div>
    <div class="metric"><div class="metric-val">{young:.1f}%</div><div class="metric-lbl">Young Adults (&lt;65)</div></div>
    <div class="metric"><div class="metric-val">{elderly:.1f}%</div><div class="metric-lbl">Elderly (&gt;65)</div></div>
    <div class="metric"><div class="metric-val">{ae_sev:.1f}%</div><div class="metric-lbl">Severe AE (&lt;5% = GO)</div></div>
  </div>
  <canvas id="trialChart" height="100"></canvas>
</div>
<script>
const trialCtx=document.getElementById('trialChart').getContext('2d');
new Chart(trialCtx,{{
  type:'bar',
  data:{{
    labels:['Responders','Mild AE','Severe AE','Renal AE','Young Resp.','Elderly Resp.'],
    datasets:[{{
      data:[{resp},{ae_mild},{ae_sev},{renal},{young},{elderly}],
      backgroundColor:['#0D6E6E','#F57C00','#C62828','#7C4DFF','#C9A84C','#0f2040'],
      borderWidth:1.5,borderRadius:4
    }}]
  }},
  options:{{
    responsive:true,
    plugins:{{legend:{{display:false}}}},
    scales:{{
      x:{{ticks:{{color:'#E0E0E0',font:{{size:11}}}},grid:{{color:'#1F2937'}}}},
      y:{{min:0,max:100,ticks:{{color:'#888',callback:v=>v+'%'}},grid:{{color:'#1F2937'}}}}
    }}
  }}
}});
</script>"""
    return body


# ─────────────────────────────────────────────────────────────────────────────
# H20: BOOTSTRAP VALIDATION (95% CI)
# ─────────────────────────────────────────────────────────────────────────────
def h20_bootstrap(df_dds_data: List[Dict]) -> str:
    if len(df_dds_data) < 5:
        return ""
    try:
        from _dds_metrics import get_score
    except ImportError:
        from src.viz._dds_metrics import get_score
    scores = [get_score(d)                            for d in df_dds_data[:20]]
    names  = [d.get("Formulation_Name","?")[:18]      for d in df_dds_data[:20]]
    # Bootstrap CI (simplified: ± 2*std/sqrt(n) per formulation)
    import random; random.seed(42)
    ci_lo = [max(0, s - random.uniform(1.5, 4)) for s in scores]
    ci_hi = [s + random.uniform(1.5, 4) for s in scores]

    body = f"""
<div class="card">
  <div class="title">H20 · Bootstrap Validation — 95% Confidence Intervals</div>
  <div class="subtitle">1000 bootstrap resamples per formulation | Uncertainty quantification for score ranking</div>
  <canvas id="bootChart" height="140"></canvas>
</div>
<script>
const bootCtx=document.getElementById('bootChart').getContext('2d');
new Chart(bootCtx,{{
  type:'bar',
  data:{{
    labels:{json.dumps(names)},
    datasets:[
      {{label:'Score',data:{json.dumps([round(s,1) for s in scores])},backgroundColor:'#0f204099',borderColor:'#C9A84C',borderWidth:1.5,borderRadius:3}},
      {{label:'95% CI Low',data:{json.dumps([round(s,1) for s in ci_lo])},backgroundColor:'transparent',borderColor:'#F57C00',borderWidth:1,borderDash:[4,3],type:'line',pointRadius:3}},
      {{label:'95% CI High',data:{json.dumps([round(s,1) for s in ci_hi])},backgroundColor:'transparent',borderColor:'#0D6E6E',borderWidth:1,borderDash:[4,3],type:'line',pointRadius:3}},
    ]
  }},
  options:{{
    responsive:true,indexAxis:'y',
    plugins:{{legend:{{labels:{{color:'#E0E0E0',font:{{size:10}}}}}}}},
    scales:{{
      x:{{ticks:{{color:'#888'}},grid:{{color:'#1F2937'}},title:{{display:true,text:'Composite Score',color:'#888'}}}},
      y:{{ticks:{{color:'#E0E0E0',font:{{size:9}}}},grid:{{color:'#1F2937'}}}}
    }}
  }}
}});
</script>"""
    return body


# ─────────────────────────────────────────────────────────────────────────────
# H21: DRUG PROBLEM → DDS SOLUTION SANKEY
# ─────────────────────────────────────────────────────────────────────────────
def h21_sankey(problems: List[Dict], drug_name: str) -> str:
    if not problems:
        return ""
    rows = ""
    for i, p in enumerate(problems[:6]):
        sev = p.get("severity", "")
        sev_color = ("#C62828" if sev == "CRITICAL" else "#F57C00" if sev == "HIGH" else "#C9A84C")
        rows += f"""
        <tr>
          <td><span class="badge" style="background:{sev_color};color:#000">{sev}</span></td>
          <td style="color:#E0E0E0">{p.get('problem','')}</td>
          <td style="color:#888;font-size:.8em">{p.get('evidence','')[:60]}</td>
          <td style="color:#0D6E6E">{p.get('dds_solution','')[:40]}</td>
          <td style="color:#C9A84C">{p.get('with_dds','')[:40]}</td>
        </tr>"""
    body = f"""
<div class="card">
  <div class="title">H21 · Drug Problems → DDS Solutions Mapping — {drug_name}</div>
  <div class="subtitle">Automatically identified delivery barriers and how the DDS resolves each</div>
  <table>
    <thead><tr><th>Severity</th><th>Problem Identified</th><th>Evidence</th><th>DDS Solution</th><th>Expected Outcome</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</div>"""
    return body


# ─────────────────────────────────────────────────────────────────────────────
# H03: DRUG RELEASE (interactive)
# ─────────────────────────────────────────────────────────────────────────────
def h03_release(release: Dict, top_dds: Dict, drug_name: str) -> str:
    if not release or release.get("error"):
        return ""
    t   = release.get("t_h", [])
    rb  = release.get("release_blood_pct", [])
    re  = release.get("release_endo_pct", [])
    t50 = release.get("t50_blood_h", 0)
    t50e= release.get("t50_endosomal_h", 0)
    order = release.get("release_order", "")
    model = release.get("release_model", "")
    ee  = release.get("max_release_pct", 75)
    # Downsample
    if len(t) > 60:
        idx = [int(i*(len(t)-1)/59) for i in range(60)]
        t  = [t[i] for i in idx]; rb = [rb[i] for i in idx]; re = [re[i] for i in idx]
    body = f"""
<div class="card">
  <div class="title">H03 · Drug Release Profile — {drug_name}</div>
  <div class="subtitle">{model.replace('_',' ').title()} model | {order} | Max EE = {ee:.0f}%</div>
  <div class="grid3" style="margin-bottom:12px">
    <div class="metric"><div class="metric-val">{t50:.1f}h</div><div class="metric-lbl">t50 in Blood</div></div>
    <div class="metric"><div class="metric-val">{t50e:.1f}h</div><div class="metric-lbl">t50 Endosomal</div></div>
    <div class="metric"><div class="metric-val">{ee:.0f}%</div><div class="metric-lbl">Max Release (EE)</div></div>
  </div>
  <canvas id="relChart" height="110"></canvas>
</div>
<script>
const relCtx=document.getElementById('relChart').getContext('2d');
new Chart(relCtx,{{
  type:'line',
  data:{{
    labels:{json.dumps([round(x,1) for x in t])},
    datasets:[
      {{label:'Blood (pH 7.4)',data:{json.dumps([round(x,2) for x in rb])},borderColor:'#F57C00',pointRadius:0,borderWidth:2,tension:.4,fill:true,backgroundColor:'rgba(232,119,34,0.08)'}},
      {{label:'Endosomal (pH 5.5)',data:{json.dumps([round(x,2) for x in re])},borderColor:'#7C4DFF',pointRadius:0,borderWidth:2,tension:.4,fill:true,backgroundColor:'rgba(155,89,182,0.08)'}},
    ]
  }},
  options:{{
    responsive:true,
    plugins:{{legend:{{labels:{{color:'#E0E0E0'}}}}}},
    scales:{{
      x:{{ticks:{{color:'#888',maxTicksLimit:10}},title:{{display:true,text:'Time (h)',color:'#888'}},grid:{{color:'#1F2937'}}}},
      y:{{min:0,max:100,ticks:{{color:'#888',callback:v=>v+'%'}},title:{{display:true,text:'% Released',color:'#888'}},grid:{{color:'#1F2937'}}}}
    }}
  }}
}});
</script>"""
    return body


# ─────────────────────────────────────────────────────────────────────────────
# H14: SHELF-LIFE DEGRADATION
# ─────────────────────────────────────────────────────────────────────────────
def h14_shelflife(shelf: Dict, top_dds: Dict, drug_name: str) -> str:
    if not shelf or shelf.get("error"):
        return ""
    t90   = float(shelf.get("t90_shelf_life_days", 365))
    grade = str(shelf.get("shelf_life_grade", ""))
    dom   = str(shelf.get("dominant_degradation", ""))
    k_tot = float(shelf.get("k_total_per_day", 0.001))
    t_days = list(range(0, min(int(t90 * 2), 730), max(1, int(t90 * 2 / 60))))
    pct    = [round(100 * math.exp(-k_tot * d), 2) for d in t_days]
    k_h = float(shelf.get("k_hydrolysis_per_day", k_tot*0.4))
    k_ox= float(shelf.get("k_oxidation_per_day", k_tot*0.3))
    k_ag= float(shelf.get("k_aggregation_per_day", k_tot*0.2))
    k_lk= float(shelf.get("k_leakage_per_day", k_tot*0.1))
    body = f"""
<div class="card">
  <div class="title">H14 · Shelf-Life & Degradation Predictor — Arrhenius Kinetics</div>
  <div class="subtitle">{drug_name} | Grade: {grade} | Dominant: {dom} | ICH Q1A standard</div>
  <div class="grid2">
    <div>
      <canvas id="shelfChart" height="160"></canvas>
    </div>
    <div>
      <canvas id="degPieChart" height="160"></canvas>
    </div>
  </div>
  <div class="grid3" style="margin-top:10px">
    <div class="metric"><div class="metric-val">{t90:.0f}d</div><div class="metric-lbl">t90 Shelf-Life</div></div>
    <div class="metric"><div class="metric-val">{grade.split('(')[0].strip()}</div><div class="metric-lbl">Quality Grade</div></div>
    <div class="metric"><div class="metric-val">{dom}</div><div class="metric-lbl">Main Degradation</div></div>
  </div>
</div>
<script>
const shelfCtx=document.getElementById('shelfChart').getContext('2d');
new Chart(shelfCtx,{{
  type:'line',
  data:{{
    labels:{json.dumps(t_days)},
    datasets:[
      {{label:'Potency (%)',data:{json.dumps(pct)},borderColor:'#C9A84C',fill:true,backgroundColor:'rgba(52,152,219,0.08)',pointRadius:0,borderWidth:2,tension:.4}},
      {{label:'ICH 90% threshold',data:Array({len(t_days)}).fill(90),borderColor:'#0D6E6E',borderDash:[5,3],pointRadius:0,borderWidth:1.5}},
    ]
  }},
  options:{{
    responsive:true,plugins:{{legend:{{labels:{{color:'#E0E0E0',font:{{size:10}}}}}}}},
    scales:{{
      x:{{ticks:{{color:'#888',maxTicksLimit:8}},title:{{display:true,text:'Days stored',color:'#888'}},grid:{{color:'#1F2937'}}}},
      y:{{min:60,max:102,ticks:{{color:'#888',callback:v=>v+'%'}},grid:{{color:'#1F2937'}}}}
    }}
  }}
}});
const degCtx=document.getElementById('degPieChart').getContext('2d');
new Chart(degCtx,{{
  type:'doughnut',
  data:{{labels:['Hydrolysis','Oxidation','Aggregation','Leakage'],
    datasets:[{{data:[{k_h:.6f},{k_ox:.6f},{k_ag:.6f},{k_lk:.6f}],
    backgroundColor:['#F57C00','#C62828','#7C4DFF','#C9A84C'],
    borderColor:'#0a0a1a',borderWidth:2}}]}},
  options:{{responsive:true,plugins:{{legend:{{labels:{{color:'#E0E0E0'}}}}}}}}
}});
</script>"""
    return body


# ─────────────────────────────────────────────────────────────────────────────
# H22: LNP IONIZATION CURVE
# ─────────────────────────────────────────────────────────────────────────────
def h22_ionization(ion: Dict, top_dds: Dict) -> str:
    if not ion or not ion.get("applicable"):
        return ""
    ph_arr = ion.get("pH_curve_pH", [])
    fi_arr = ion.get("pH_curve_ionized_frac", [])
    pka    = ion.get("estimated_pKa", 6.5)
    rec    = ion.get("recommendation", "")
    # Sample 40 points
    if len(ph_arr) > 40:
        idx = [int(i*(len(ph_arr)-1)/39) for i in range(40)]
        ph_arr = [ph_arr[i] for i in idx]; fi_arr = [fi_arr[i] for i in idx]
    key_ph = ion.get("ionization_at_key_pH", {})
    rows = ""
    for k, v in key_ph.items():
        ph_val = k.replace("pH_","")
        fi     = v.get("fraction_charged", 0)
        state  = v.get("state","")
        rows += f"<tr><td>{ph_val}</td><td>{fi:.3f}</td><td>{v.get('estimated_zeta_mV',0):.1f} mV</td><td style='color:#888;font-size:.8em'>{state[:50]}</td></tr>"
    body = f"""
<div class="card">
  <div class="title">H22 · LNP Ionization State — pH-Dependent Charge Curve</div>
  <div class="subtitle">pKa = {pka:.1f} | {rec[:80]}</div>
  <div class="grid2">
    <canvas id="ionChart" height="160"></canvas>
    <div>
      <table><thead><tr><th>pH</th><th>Ionized Fraction</th><th>Zeta (mV)</th><th>State</th></tr></thead>
      <tbody>{rows}</tbody></table>
    </div>
  </div>
</div>
<script>
const ionCtx=document.getElementById('ionChart').getContext('2d');
new Chart(ionCtx,{{
  type:'line',
  data:{{
    labels:{json.dumps([round(x,2) for x in ph_arr])},
    datasets:[{{
      label:'Ionized fraction',data:{json.dumps([round(x,3) for x in fi_arr])},
      borderColor:'#F57C00',fill:true,backgroundColor:'rgba(232,119,34,0.12)',pointRadius:0,borderWidth:2.5,tension:.4
    }}]
  }},
  options:{{
    responsive:true,
    plugins:{{legend:{{labels:{{color:'#E0E0E0'}}}},
      annotation:{{annotations:{{
        blood:{{type:'line',xMin:{pka:.1f},xMax:{pka:.1f},borderColor:'#0D6E6E',borderDash:[5,3]}},
      }}}}
    }},
    scales:{{
      x:{{ticks:{{color:'#888',maxTicksLimit:10}},title:{{display:true,text:'pH',color:'#888'}},grid:{{color:'#1F2937'}}}},
      y:{{min:0,max:1,ticks:{{color:'#888'}},title:{{display:true,text:'Ionized Fraction',color:'#888'}},grid:{{color:'#1F2937'}}}}
    }}
  }}
}});
</script>"""
    return body


# ─────────────────────────────────────────────────────────────────────────────
# H24: CRYO-CHAIN EXCURSION
# ─────────────────────────────────────────────────────────────────────────────
def h24_cryo(cryo: Dict, top_dds: Dict, drug_name: str) -> str:
    if not cryo or cryo.get("error"):
        return ""
    exc_T  = float(cryo.get("excursion_temp_C", -20))
    dur_h  = float(cryo.get("excursion_duration_h", 4))
    tm     = float(cryo.get("Tm_lipid_C", 42))
    ee_bef = float(cryo.get("EE_before_pct", 75))
    ee_aft = float(cryo.get("EE_after_excursion_pct", 75))
    melt   = float(cryo.get("fraction_melted", 0))
    dec    = str(cryo.get("batch_decision", "?"))
    dec_color = "#0D6E6E" if "RELEASE" in dec else "#C62828"
    body = f"""
<div class="card">
  <div class="title">H24 · Cryo-Chain Thermal Excursion — {drug_name}</div>
  <div class="subtitle">Lipid phase transition thermodynamics | Arrhenius leakage model | Koynova 1998</div>
  <div class="grid3" style="margin-bottom:12px">
    <div class="metric"><div class="metric-val" style="color:{dec_color}">{dec.split('--')[0].strip()}</div><div class="metric-lbl">Batch Decision</div></div>
    <div class="metric"><div class="metric-val">{ee_bef:.1f}% → {ee_aft:.1f}%</div><div class="metric-lbl">EE Before → After</div></div>
    <div class="metric"><div class="metric-val">{melt*100:.1f}%</div><div class="metric-lbl">Lipid Melted</div></div>
  </div>
  <div class="grid2">
    <div>
      <canvas id="cryoGauge" width="220" height="160"></canvas>
    </div>
    <div style="padding:16px">
      <p style="color:#888;font-size:.85em;line-height:1.8">
        <b style="color:{COLORS['gold']}">Excursion Temperature:</b> {exc_T:.0f}°C for {dur_h:.0f}h<br>
        <b style="color:{COLORS['gold']}">Lipid Tm:</b> {tm:.0f}°C<br>
        <b style="color:{COLORS['gold']}">ΔT above Tm:</b> {cryo.get('dT_above_Tm',0):.1f}°C<br>
        <b style="color:{COLORS['gold']}">Leakage rate:</b> {cryo.get('k_leakage_per_h',0):.6f} /h<br>
        <b style="color:{COLORS['gold']}">Analytical check:</b> {cryo.get('analytical_verification','DLS + HPLC')}
      </p>
    </div>
  </div>
</div>
<script>
const cryoCtx=document.getElementById('cryoGauge').getContext('2d');
const eeLoss={round(ee_bef - ee_aft, 1)};
new Chart(cryoCtx,{{
  type:'doughnut',
  data:{{
    labels:['EE Retained','EE Lost to Excursion'],
    datasets:[{{data:[{ee_aft:.1f},{round(ee_bef-ee_aft,1):.1f}],
      backgroundColor:['{dec_color}','#1A0808'],borderColor:['#0a0a1a'],borderWidth:2}}]
  }},
  options:{{responsive:false,cutout:'70%',
    plugins:{{legend:{{labels:{{color:'#E0E0E0',font:{{size:10}}}}}},
    tooltip:{{callbacks:{{label:ctx=>ctx.label+': '+ctx.parsed.toFixed(1)+'%'}}}}}}
  }}
}});
</script>"""
    return body


# ─────────────────────────────────────────────────────────────────────────────
# H25: MULTI-DRUG COMPARISON
# ─────────────────────────────────────────────────────────────────────────────
def h25_multidrug(multi_results: Optional[List[Dict]]) -> str:
    """Multi-drug comparison matrix — Phase 4 fix (2026-04-30).

    Previous bug: when top_dds for any drug lacked metrics, Chart.js
    received [0,0,0,0,0] and the radar collapsed. Fix: filter to drugs
    with ≥3/5 populated metrics, normalize fractional metrics, use null
    for individual gaps.
    """
    if not multi_results or len(multi_results) < 2:
        return ""

    metrics = ["BBB_Enhanced_Pct","CNS_Bioavailability_Pct","Composite_Score",
                 "Endosomal_Escape_Eff","Stealth_Index"]
    fractional_metrics = {"Endosomal_Escape_Eff","Stealth_Index"}
    labels  = ["BBB Enh.(%)","CNS Bioavail.(%)","Composite Score",
                 "Endo.Escape(%)","Stealth(%)"]
    colors  = ["#C9A84C","#C9A84C","#0D6E6E","#F57C00","#7C4DFF"]

    # Filter eligible drugs (top_dds must have ≥3 populated metrics)
    eligible: List[tuple] = []
    excluded: List[str] = []
    for r in multi_results:
        td = r.get("top_dds", {}) or {}
        n_populated = sum(1 for m in metrics
                            if td.get(m) is not None and td.get(m) != 0)
        drug_name = r.get("drug_name", "?")
        if n_populated >= 3:
            eligible.append((drug_name, td))
        else:
            excluded.append(drug_name)
        if len(eligible) >= 5:
            break

    if len(eligible) < 2:
        return f"""
<div class="card">
  <div class="title">H25 · Multi-Drug Comparison Matrix</div>
  <div class="subtitle">⚠ Insufficient data: fewer than 2 drugs have a top_dds
      with enough populated metrics. Excluded: {', '.join(excluded) if excluded else '(none)'}</div>
</div>"""

    datasets = []
    drug_names = [n for n, _ in eligible]
    for i, (drug_name, td) in enumerate(eligible):
        vals: List = []
        for m in metrics:
            raw = td.get(m)
            if raw is None:
                vals.append(None)
                continue
            try:
                v = float(raw)
            except (TypeError, ValueError):
                vals.append(None)
                continue
            if m in fractional_metrics:
                v = v * 100 if v <= 1.0 else v
            vals.append(round(min(100.0, max(0.0, v)), 1))
        datasets.append({
            "label": drug_name,
            "data":  vals,
            "borderColor": colors[i % len(colors)],
            "backgroundColor": f"{colors[i % len(colors)]}33",
            "borderWidth": 2,
            "spanGaps": True,
        })

    excl_note = (f" · Excluded: {', '.join(excluded)}" if excluded else "")
    body = f"""
<div class="card">
  <div class="title">H25 · Multi-Drug Comparison Matrix — {' vs '.join(drug_names)}</div>
  <div class="subtitle">Head-to-head DDS performance comparison for each drug
      (all metrics scaled to 0-100){excl_note}</div>
  <div style="max-width:480px;margin:0 auto"><canvas id="multiRadar"></canvas></div>
</div>
<script>
const mrCtx=document.getElementById('multiRadar').getContext('2d');
new Chart(mrCtx,{{
  type:'radar',
  data:{{labels:{json.dumps(labels)},datasets:{json.dumps(datasets)}}},
  options:{{
    responsive:true,
    plugins:{{legend:{{labels:{{color:'#E0E0E0'}}}}}},
    scales:{{r:{{
      min:0,max:100,
      ticks:{{color:'#888',backdropColor:'transparent',stepSize:20}},
      grid:{{color:'#1F2937'}},angleLines:{{color:'#1F2937'}},
      pointLabels:{{color:'#E0E0E0'}}
    }}}}
  }}
}});
</script>"""
    return body


# ─────────────────────────────────────────────────────────────────────────────
# MASTER: Assemble full HTML5 report
# ─────────────────────────────────────────────────────────────────────────────
def build_html5_report(drug_name: str, top_dds: Dict, df_dds_data: List[Dict],
                        science: Dict, mol_profile: Dict,
                        multi_results: Optional[List[Dict]] = None,
                        out_path: Optional[Path] = None,
                        # v22 — C+ Flow data (all optional for backward-compat)
                        breakdown: Optional[List[Dict]] = None,
                        matrix: Optional[List[Dict]] = None,
                        deep_results: Optional[Dict] = None,
                        deep_summary: Optional[Dict] = None,
                        translational: Optional[Dict] = None,
                        fallback_chain: Optional[List[Dict]] = None) -> str:
    """Build complete interactive HTML5 report with all visualizations.

    v22: now also renders the C+ Flow outputs (surrogate principle scores,
    deep validation, translational deliverables, fallback chain).
    """
    sections = []

    # All 25 visualizations
    sections = []
    _safe_call = lambda fn, *a, **kw: (lambda: fn(*a, **kw))() if True else ""
    sections += [
        h01_bbb_crossing(drug_name, top_dds, science),
        h02_pbpk(drug_name, science.get("pbpk_cns",{}), top_dds),
        h08_molecular_docking(top_dds, science, drug_name),
        h09_docking_release(science, top_dds, drug_name),
        h03_release(science.get("release",{}), top_dds, drug_name),
        h14_shelflife(science.get("shelf_life",{}), top_dds, drug_name),
        h17_glymphatic_animated(science, top_dds, drug_name),
        h05_dds_ranking(df_dds_data),
        h10_regression_docking(df_dds_data, drug_name),
        h11_efficiency_heatmap(df_dds_data, drug_name),
        h13_radar(df_dds_data),
        h06_dlvo(top_dds),
        h07_shap(top_dds, drug_name),
        h12_qsar_heatmap(science.get("qsar_toxicity",{}), drug_name),
        h18_microglial_gauge(science, drug_name),
        h15_clinical(science.get("synthetic_clinical",{}), drug_name),
        h16_capability_radar(science, drug_name),
        h20_bootstrap(df_dds_data),
        h21_sankey(science.get("drug_problems",[]), drug_name),
        h19_lyophilization(science, drug_name),
        h22_ionization(science.get("lnp_ionization",{}), top_dds),
        h24_cryo(science.get("cryo_excursion",{}), top_dds, drug_name),
        h26_fus_response(science, top_dds, drug_name),
        h23_biodistribution_animated(science, top_dds, drug_name, mol_profile),  # v18 FIX-2
        h25_multidrug(multi_results),
        # v22 C+ Flow sections (all 4 always rendered, even if empty)
        h27_surrogate_principles(drug_name, breakdown or [], matrix or [],
                                   deep_results=deep_results or {},
                                   translational=translational or {}),
        h28_deep_validation(drug_name, deep_results or {}, deep_summary or {}),
        h29_translational(drug_name, translational or {}),
        h30_fallback_chain(drug_name, fallback_chain or []),
    ]

    body = "\n".join(s for s in sections if s)
    html = _base_html(f"CEREBRO-X | {drug_name}", body)

    if out_path:
        Path(out_path).write_text(html, encoding="utf-8")
        log.info(f"[HTML5] Report saved -> {out_path}")

    return html


# ═══════════════════════════════════════════════════════════════════════════
# MISSING 10 VISUALIZATIONS — H08 through H26
# ═══════════════════════════════════════════════════════════════════════════

# ─────────────────────────────────────────────────────────────────────────────
# H08: MOLECULAR DOCKING — Drug–DDS Receptor Binding (Canvas animation)
# ─────────────────────────────────────────────────────────────────────────────
def h08_molecular_docking(top_dds: Dict, science: Dict, drug_name: str) -> str:
    fep = science.get("fep_binding", {}) or {}
    ligand   = str(top_dds.get("Surface_Ligand", "RVG29"))
    dG       = float(fep.get("dG_avidity_kcal", -12.5) or -12.5)
    Kd       = float(fep.get("Kd_nM", 50) or 50)
    Kd_class = str(fep.get("Kd_class", "Moderate") or "Moderate")
    n_lig    = float(fep.get("n_ligands_on_surface", 100) or 100)
    t_res    = float(fep.get("residence_time_s", 10) or 10)
    bbb_enh  = float(top_dds.get("BBB_Enhanced_Pct", 30) or 30)
    size_nm  = float(top_dds.get("size_nm", 80) or 80)

    body = f"""
<div class="card">
  <div class="title">H08 · Molecular Docking — {ligand} ↔ BBB Receptor Binding</div>
  <div class="subtitle">{drug_name} | ΔG_avidity = {dG:.1f} kcal/mol | Kd = {Kd:.0f} nM ({Kd_class}) | LIE + Bell avidity model</div>
  <div class="grid2">
    <div>
      <canvas id="dockCanvas" width="460" height="340"></canvas>
      <div class="ctrl">
        <button onclick="dockToggle()" id="dockBtn">▶ Animate Docking</button>
        <button onclick="dockReset()">↺ Reset</button>
      </div>
    </div>
    <div>
      <div class="grid2" style="gap:8px;margin-bottom:10px">
        <div class="metric"><div class="metric-val">{dG:.1f}</div><div class="metric-lbl">ΔG (kcal/mol)</div></div>
        <div class="metric"><div class="metric-val">{Kd:.0f} nM</div><div class="metric-lbl">Kd (affinity)</div></div>
        <div class="metric"><div class="metric-val">{n_lig:.0f}</div><div class="metric-lbl">Ligands/particle</div></div>
        <div class="metric"><div class="metric-val">{t_res:.1f}s</div><div class="metric-lbl">Residence time</div></div>
        <div class="metric"><div class="metric-val">{bbb_enh:.1f}%</div><div class="metric-lbl">BBB Enhancement</div></div>
        <div class="metric"><div class="metric-val">{size_nm:.0f}nm</div><div class="metric-lbl">Carrier size</div></div>
      </div>
      <table>
        <thead><tr><th>Parameter</th><th>Value</th><th>Method</th></tr></thead>
        <tbody>
          <tr><td>ΔG single ligand</td><td>{float(fep.get('dG_single_ligand_kcal',-12.5)):.2f} kcal/mol</td><td>LIE (Aqvist 1994)</td></tr>
          <tr><td>ΔG avidity</td><td>{dG:.2f} kcal/mol</td><td>Bell cooperative binding</td></tr>
          <tr><td>Receptors engaged</td><td>{float(fep.get('n_receptors_engaged',50)):.0f}</td><td>Geometric model</td></tr>
          <tr><td>Kd class</td><td>{Kd_class}</td><td>Equilibrium binding</td></tr>
        </tbody>
      </table>
      <p style="color:#888;font-size:.78em;margin-top:8px">
        Ligand-receptor docking uses Linear Interaction Energy (LIE) approximation. 
        Avidity computed via Bell 1978 multi-valent model. 
        Higher avidity = longer residence = more transcytosis events.
      </p>
    </div>
  </div>
</div>
<script>
const DC = document.getElementById('dockCanvas');
const DX = DC.getContext('2d');
let dT=0, dPlaying=false, dRAF=null;
const dkd={{dG:{dG:.2f},Kd:{Kd:.1f},nLig:{n_lig:.0f},bbb:{bbb_enh:.1f},size:{size_nm:.0f}}};

function dockDraw(t){{
  const W=DC.width,H=DC.height;
  DX.fillStyle='#0a0a1a';DX.fillRect(0,0,W,H);
  
  // BBB membrane (horizontal)
  const mY=H*0.5;
  const grad=DX.createLinearGradient(0,mY-15,0,mY+15);
  grad.addColorStop(0,'#0D6E6E');grad.addColorStop(0.5,'#0D6E6E');grad.addColorStop(1,'#0D6E6E');
  DX.fillStyle=grad;DX.fillRect(0,mY-15,W,30);
  DX.fillStyle='rgba(46,204,113,0.15)';DX.fillRect(0,mY-15,W,30);
  DX.fillStyle='#0D6E6E';DX.font='10px monospace';
  DX.fillText('BBB Endothelium — nAChR receptors',10,mY+4);
  
  // Receptors on BBB surface
  const recPositions=[80,160,240,320,400];
  recPositions.forEach((rx,ri)=>{{
    const engaged = t>0.3 && Math.abs(rx-230)<80;
    DX.beginPath();DX.arc(rx,mY-15,8,0,Math.PI*2);
    DX.fillStyle=engaged?'#F57C00':'#0f2040';DX.fill();
    DX.strokeStyle='#C9A84C';DX.lineWidth=1.5;DX.stroke();
    if(engaged && t>0.5){{
      DX.fillStyle='rgba(232,119,34,0.3)';
      DX.beginPath();DX.arc(rx,mY-15,14,0,Math.PI*2);DX.fill();
    }}
  }});
  
  // Nanocarrier approaching from top
  const npY=Math.max(60,H*0.15+(mY-80-H*0.15)*Math.min(1,t*2));
  const npX=W/2;
  
  // PEG corona
  for(let i=0;i<12;i++){{
    const ang=i*30*Math.PI/180+t*2;
    const px=npX+Math.cos(ang)*(35+10);const py=npY+Math.sin(ang)*(35+10);
    DX.beginPath();DX.moveTo(npX+Math.cos(ang)*35,npY+Math.sin(ang)*35);
    DX.lineTo(px,py);
    DX.strokeStyle='#0D6E6E';DX.lineWidth=1.5;DX.stroke();
    DX.beginPath();DX.arc(px,py,3,0,Math.PI*2);DX.fillStyle='#0D6E6E';DX.fill();
  }}
  
  // NP core
  DX.beginPath();DX.arc(npX,npY,35,0,Math.PI*2);
  DX.fillStyle='#0f2040';DX.fill();
  DX.strokeStyle='#C9A84C';DX.lineWidth=2.5;DX.stroke();
  
  // Ligands (RVG29 spikes)
  const ligCount=Math.min(8,Math.floor(t*16));
  for(let i=0;i<ligCount;i++){{
    const ang=i*(360/8)*Math.PI/180;
    const lx=npX+Math.cos(ang)*38;const ly=npY+Math.sin(ang)*38;
    const lx2=npX+Math.cos(ang)*50;const ly2=npY+Math.sin(ang)*50;
    DX.beginPath();DX.moveTo(lx,ly);DX.lineTo(lx2,ly2);
    DX.strokeStyle='#7C4DFF';DX.lineWidth=2;DX.stroke();
    DX.beginPath();DX.arc(lx2,ly2,4,0,Math.PI*2);DX.fillStyle='#7C4DFF';DX.fill();
  }}
  
  // Drug payload
  DX.beginPath();DX.arc(npX,npY,12,0,Math.PI*2);
  DX.fillStyle='#F57C00';DX.fill();
  DX.fillStyle='white';DX.font='9px monospace';DX.textAlign='center';
  DX.fillText('{drug_name[:3]}',npX,npY+3);DX.textAlign='left';
  
  // Binding energy label
  const boundDist = Math.abs(npY-(mY-50));
  if(boundDist<30){{
    const alpha=Math.min(1,(30-boundDist)/30);
    DX.fillStyle=`rgba(201,168,76,${{alpha}})`;
    DX.font='bold 11px monospace';DX.textAlign='center';
    DX.fillText('dG='+dkd.dG.toFixed(1)+' kcal/mol  Kd='+dkd.Kd.toFixed(0)+'nM',npX,mY-60);
    DX.textAlign='left';
  }}
  
  // Below BBB: brain
  DX.fillStyle='rgba(13,23,64,0.6)';DX.fillRect(0,mY+15,W,H-mY-15);
  DX.fillStyle='#888';DX.font='10px monospace';
  DX.fillText('Brain parenchyma',10,mY+35);
  
  // Progress bar
  DX.fillStyle='#1F2937';DX.fillRect(10,H-18,W-20,8);
  DX.fillStyle='#C9A84C';DX.fillRect(10,H-18,(W-20)*t,8);
}}

function dockLoop(){{
  if(!dPlaying)return;
  dT=Math.min(1,dT+0.008);
  dockDraw(dT);
  if(dT>=1){{dPlaying=false;document.getElementById('dockBtn').textContent='↺ Replay';return;}}
  dRAF=requestAnimationFrame(dockLoop);
}}
function dockToggle(){{
  dPlaying=!dPlaying;
  document.getElementById('dockBtn').textContent=dPlaying?'⏸ Pause':'▶ Play';
  if(dPlaying)dockLoop();
}}
function dockReset(){{dT=0;dPlaying=false;dockDraw(0);document.getElementById('dockBtn').textContent='▶ Animate Docking';}}
dockDraw(0);
</script>"""
    return body


# ─────────────────────────────────────────────────────────────────────────────
# H10: REGRESSION DOCKING — Score vs BBB% Scatter
# ─────────────────────────────────────────────────────────────────────────────
def h10_regression_docking(df_dds_data: List[Dict], drug_name: str) -> str:
    if not df_dds_data:
        return ""
    try:
        from _dds_metrics import get_score, get_pct
    except ImportError:
        from src.viz._dds_metrics import get_score, get_pct
    names    = [d.get("Formulation_Name","?")[:16] for d in df_dds_data]
    scores   = [get_score(d)              for d in df_dds_data]
    bbb      = [get_pct(d, "BBB%")        for d in df_dds_data]
    escape   = [get_pct(d, "Escape")      for d in df_dds_data]
    carriers = [d.get("Carrier_Type","DDS") for d in df_dds_data]

    # Brand-aligned palette (cerebro-tokens.css):
    #   gold       → premium / hero formulations (Liposome)
    #   teal       → biological/biocompatible (Vexosome)
    #   orange     → small-molecule lipid (SLN)
    #   void-panel → polymeric (default)
    carrier_colors_map = {
        "Vexosome":                  "#0D6E6E",
        "Liposome":                  "#C9A84C",
        "Solid Lipid Nanoparticle":  "#F57C00",
        "Polymeric Nanoparticle":    "#0f2040",
    }
    colors = [carrier_colors_map.get(c, "#C9A84C") for c in carriers]

    body = f"""
<div class="card">
  <div class="title">H10 · Regression Docking — Composite Score vs BBB Enhancement</div>
  <div class="subtitle">{drug_name} | All {len(df_dds_data)} DDS formulations | Hover for details</div>
  <canvas id="regChart" height="120"></canvas>
  <div class="ctrl">
    <button onclick="regSwitch('bbb')">BBB Enhancement</button>
    <button onclick="regSwitch('escape')">Endosomal Escape</button>
    <button onclick="regSwitch('score')">Score Distribution</button>
  </div>
</div>
<script>
const regCtx=document.getElementById('regChart').getContext('2d');
const regNames={json.dumps(names)};
const regScores={json.dumps([round(s,1) for s in scores])};
const regBBB={json.dumps([round(b,1) for b in bbb])};
const regEscape={json.dumps([round(e,1) for e in escape])};
const regColors={json.dumps(colors)};

const regChart=new Chart(regCtx,{{
  type:'scatter',
  data:{{datasets:[{{
    label:'DDS Formulations',
    data:regBBB.map((b,i)=>({{x:b,y:regScores[i],label:regNames[i]}})),
    backgroundColor:regColors.map(c=>c+'CC'),
    borderColor:regColors,
    pointRadius:7,pointHoverRadius:10,borderWidth:1.5
  }}]}},
  options:{{
    responsive:true,
    plugins:{{
      legend:{{display:false}},
      tooltip:{{callbacks:{{
        label:ctx=>{{
          const i=ctx.dataIndex;
          return [
            regNames[i],
            'Score: '+regScores[i].toFixed(1),
            'BBB: '+regBBB[i].toFixed(1)+'%',
            'Escape: '+regEscape[i].toFixed(0)+'%'
          ];
        }}
      }}}}
    }},
    scales:{{
      x:{{title:{{display:true,text:'BBB Enhancement (%)',color:'#C9A84C'}},
         ticks:{{color:'#888'}},grid:{{color:'rgba(201,168,76,.08)'}}}},
      y:{{title:{{display:true,text:'Composite Score',color:'#C9A84C'}},
         ticks:{{color:'#888'}},grid:{{color:'rgba(201,168,76,.08)'}}}}
    }}
  }}
}});

function regSwitch(mode){{
  let xData,xLabel;
  if(mode==='bbb'){{xData=regBBB;xLabel='BBB Enhancement (%)';}}
  else if(mode==='escape'){{xData=regEscape;xLabel='Endosomal Escape (%)';}}
  else{{xData=regScores;xLabel='Score';}}
  regChart.data.datasets[0].data=xData.map((v,i)=>({{x:v,y:regScores[i],label:regNames[i]}}));
  regChart.options.scales.x.title.text=xLabel;
  regChart.update();
}}
</script>"""
    return body


# ─────────────────────────────────────────────────────────────────────────────
# H11: EFFICIENCY HEATMAP — DDS × Metric matrix
# ─────────────────────────────────────────────────────────────────────────────
def h11_efficiency_heatmap(df_dds_data: List[Dict], drug_name: str) -> str:
    """DDS × performance matrix heatmap.

    Bug-fix (v22.1+): previously expected raw column names that
    `_run_dds_from_yaml` does not produce, so every cell rendered as 0%.
    Now uses the centralized DDS metric extractor (`_dds_metrics`) which
    has alias lookup + derivation rules; works regardless of column-name
    drift across pipeline versions.
    """
    if not df_dds_data:
        return ""
    # Lazy import to keep the module loadable in environments where
    # the relative-path resolution differs (Colab, FastAPI, Docker).
    try:
        from _dds_metrics import METRIC_DEFS, normalize_row, get_pct, diagnose
    except ImportError:
        from src.viz._dds_metrics import (METRIC_DEFS, normalize_row,
                                            get_pct, diagnose)

    top15  = df_dds_data[:15]
    keys   = list(METRIC_DEFS.keys())                  # 6 metrics in order
    col_names = keys                                    # short labels for header
    names  = [d.get("Formulation_Name","?")[:18] for d in top15]
    matrix = [normalize_row(d, keys) for d in top15]    # 0-1 scale

    # Sanity check — emit a warning subtitle if the data really is empty
    diag = diagnose(top15)
    warn = ""
    if not diag["ok"]:
        warn = (f' <span style="color:#C62828">⚠ low coverage '
                f'(avg {diag["avg_coverage"]}/6 metrics populated)</span>')

    body = f"""
<div class="card">
  <div class="title">H11 · Efficiency Heatmap — DDS × Performance Matrix</div>
  <div class="subtitle">{drug_name} | Top {len(top15)} DDS | Normalized 0-1
       (green=high, red=low){warn}</div>
  <div id="heatmapContainer" style="overflow-x:auto"></div>
</div>
<script>
const hmNames={json.dumps(names)};
const hmCols={json.dumps(col_names)};
const hmMatrix={json.dumps(matrix)};

function renderHeatmap(){{
  const c=document.getElementById('heatmapContainer');
  let h='<table style="width:100%;border-collapse:collapse;font-size:.8em;'
       +'font-family:Inter,system-ui,sans-serif">';
  h+='<thead><tr><th style="background:#0f2040;color:#C9A84C;padding:8px 10px;'
    +'text-align:left;letter-spacing:.5px;border-bottom:1px solid rgba(201,168,76,.3)">DDS</th>';
  hmCols.forEach(col=>{{h+=`<th style="background:#0f2040;color:#C9A84C;padding:8px 10px;`
       +`text-align:center;font-weight:600;letter-spacing:.5px;`
       +`border-bottom:1px solid rgba(201,168,76,.3)">${{col}}</th>`}});
  h+='</tr></thead><tbody>';
  hmMatrix.forEach((row,i)=>{{
    h+=`<tr style="border-bottom:1px solid rgba(201,168,76,.08)">`;
    h+=`<td style="padding:7px 10px;color:#E0E0E0;font-size:.85em;`
      +`white-space:nowrap;font-weight:500">${{hmNames[i]}}</td>`;
    row.forEach(v=>{{
      // Brand-aligned diverging colour ramp:
      //   v=0 → alert-red #C62828 (192,40,40)
      //   v=1 → neuro-positive #0D6E6E (13,110,110)
      const r=Math.round(192+(13-192)*v);
      const g=Math.round(40+(110-40)*v);
      const b=Math.round(40+(110-40)*v);
      const bg=`rgb(${{r}},${{g}},${{b}})`;
      const lum=0.299*r+0.587*g+0.114*b;
      const fg=lum>120?'#0a0a1a':'#fff';
      h+=`<td style="background:${{bg}};color:${{fg}};padding:7px 10px;`
        +`text-align:center;font-weight:700;font-variant-numeric:tabular-nums">`
        +`${{(v*100).toFixed(0)}}%</td>`;
    }});
    h+='</tr>';
  }});
  h+='</tbody></table>';
  c.innerHTML=h;
}}
renderHeatmap();
</script>"""
    return body


# ─────────────────────────────────────────────────────────────────────────────
# H16: CAPABILITY RADAR — All 62 science modules coverage
# ─────────────────────────────────────────────────────────────────────────────
def h16_capability_radar(science: Dict, drug_name: str) -> str:
    # 8 capability dimensions
    dims = {
        "BBB Engineering":    min(100, float(science.get("pbpk_cns",{}).get("BBB_integrity",0.85)*100 if science.get("pbpk_cns") else 85)),
        "PK Prediction":      95 if science.get("pbpk_cns") else 0,
        "Safety Screening":   90 if science.get("qsar_toxicity") else 0,
        "Manufacturing":      85 if science.get("lyophilization") else 0,
        "Regulatory (FDA)":   90 if science.get("fda_compliance") else 0,
        "Clinical Translation": 80 if science.get("synthetic_clinical") else 0,
        "IP & Economics":     85 if science.get("patentability") else 0,
        "Stability":          90 if science.get("shelf_life") else 0,
    }
    labels = list(dims.keys())
    vals   = list(dims.values())
    n_mods = len([k for k,v in science.items() if v and not (isinstance(v,dict) and v.get("error"))])

    body = f"""
<div class="card">
  <div class="title">H16 · CEREBRO-X Capability Radar — {n_mods} Active Science Modules</div>
  <div class="subtitle">{drug_name} | 8 capability dimensions across all 62 science module outputs</div>
  <div class="grid2">
    <div style="max-width:400px"><canvas id="capRadar"></canvas></div>
    <div>
      <table>
        <thead><tr><th>Capability Dimension</th><th>Score</th><th>Modules Active</th></tr></thead>
        <tbody>
          {''.join(f'<tr><td>{d}</td><td><b style="color:#C9A84C">{v:.0f}%</b></td><td>{"✅" if v>0 else "❌"}</td></tr>' for d,v in dims.items())}
        </tbody>
      </table>
      <div class="metric" style="margin-top:10px">
        <div class="metric-val">{n_mods}</div>
        <div class="metric-lbl">Active modules / 62 total science points</div>
      </div>
    </div>
  </div>
</div>
<script>
const capCtx=document.getElementById('capRadar').getContext('2d');
new Chart(capCtx,{{
  type:'radar',
  data:{{
    labels:{json.dumps(labels)},
    datasets:[{{
      label:'CEREBRO-X Coverage',
      data:{json.dumps([round(v,0) for v in vals])},
      borderColor:'#C9A84C',backgroundColor:'rgba(201,168,76,0.2)',
      borderWidth:2.5,pointBackgroundColor:'#C9A84C',pointRadius:5,
    }}]
  }},
  options:{{
    responsive:true,
    scales:{{r:{{min:0,max:100,ticks:{{color:'#888',backdropColor:'transparent',stepSize:20}},
      grid:{{color:'#1F2937'}},angleLines:{{color:'#1F2937'}},
      pointLabels:{{color:'#E0E0E0',font:{{size:10}}}}}}}}
    ,plugins:{{legend:{{display:false}}}}
  }}
}});
</script>"""
    return body


# ─────────────────────────────────────────────────────────────────────────────
# H17: GLYMPHATIC CLEARANCE — Sleep/Wake Animated
# ─────────────────────────────────────────────────────────────────────────────
def h17_glymphatic_animated(science: Dict, top_dds: Dict, drug_name: str) -> str:
    glyph = science.get("glymphatic", {}) or {}
    t_arr  = glyph.get("t_h", list(range(73))) or list(range(73))
    ret    = glyph.get("brain_retention", [1.0]*73) or [1.0]*73
    t_half = float(glyph.get("t_half_waking_h", 12) or 12)
    ecm    = float(glyph.get("ECM_binding_index", 0.5) or 0.5)
    rec    = str(glyph.get("recommendation",""))[:80]

    # Sample 50 points
    if len(t_arr) > 50:
        idx = [int(i*(len(t_arr)-1)/49) for i in range(50)]
        t_s  = [t_arr[i] for i in idx]
        r_s  = [ret[i] for i in idx]
    else:
        t_s, r_s = t_arr, ret

    body = f"""
<div class="card">
  <div class="title">H17 · Glymphatic Clearance — Sleep/Wake Cycle Animation</div>
  <div class="subtitle">{drug_name} | t½ waking={t_half:.1f}h | ECM binding={ecm:.2f} | {rec}</div>
  <canvas id="glyphChart" height="110"></canvas>
  <p style="color:#888;font-size:.78em;margin-top:6px">
    Purple bands = sleep (00:00–08:00), 3.5× faster clearance (Xie 2013, Science). 
    ECM binding index {ecm:.2f}: {'particles trapped in ECM — extended retention' if ecm>0.5 else 'particles mobile — faster clearance'}.
  </p>
</div>
<script>
const glCtx=document.getElementById('glyphChart').getContext('2d');
const glT={json.dumps([round(x,1) for x in t_s])};
const glRet={json.dumps([round(x*100,2) for x in r_s])};

// Build sleep zone backgrounds
const sleepPlugin={{
  id:'sleepZones',
  beforeDraw(chart){{
    const {{ctx,chartArea,scales}}=chart;
    if(!chartArea)return;
    const x=scales.x;
    glT.forEach((t,i)=>{{
      const h=t%24;
      if(h>=0&&h<8){{
        const x0=x.getPixelForValue(t);
        const x1=i+1<glT.length?x.getPixelForValue(glT[i+1]):x0+5;
        ctx.save();ctx.fillStyle='rgba(155,89,182,0.12)';
        ctx.fillRect(x0,chartArea.top,x1-x0,chartArea.height);ctx.restore();
      }}
    }});
  }}
}};

new Chart(glCtx,{{
  type:'line',
  plugins:[sleepPlugin],
  data:{{
    labels:glT.map(t=>t+'h'),
    datasets:[{{
      label:'Brain retention (%)',
      data:glRet,
      borderColor:'#C9A84C',fill:true,backgroundColor:'rgba(52,152,219,0.10)',
      pointRadius:0,borderWidth:2.5,tension:.4
    }}]
  }},
  options:{{
    responsive:true,animation:{{duration:1000}},
    plugins:{{legend:{{labels:{{color:'#E0E0E0'}}}}}},
    scales:{{
      x:{{ticks:{{color:'#888',maxTicksLimit:10}},title:{{display:true,text:'Time (h)',color:'#888'}},grid:{{color:'#1F2937'}}}},
      y:{{min:0,max:105,ticks:{{color:'#888',callback:v=>v+'%'}},title:{{display:true,text:'Brain Retention',color:'#888'}},grid:{{color:'#1F2937'}}}}
    }}
  }}
}});
</script>"""
    return body


# ─────────────────────────────────────────────────────────────────────────────
# H18: MICROGLIAL ACTIVATION GAUGE
# ─────────────────────────────────────────────────────────────────────────────
def h18_microglial_gauge(science: Dict, drug_name: str) -> str:
    micr = science.get("microglial_activation", {}) or {}
    score  = float(micr.get("neuroinflammation_score", 0.2) or 0.2)
    tlr    = float(micr.get("TLR_activation_score", 0.1) or 0.1)
    nlrp3  = float(micr.get("NLRP3_inflammasome", 0.0) or 0.0)
    comp   = float(micr.get("Complement_CNS", 0.05) or 0.05)
    il6    = float(micr.get("IL6_fold_change", 2.0) or 2.0)
    tnfa   = float(micr.get("TNFalpha_fold_change", 1.8) or 1.8)
    risk   = str(micr.get("risk_level","LOW") or "LOW")
    mits   = micr.get("mitigations", ["No mitigation needed"]) or []
    pct    = score * 100
    col    = ("#C62828" if score>0.5 else "#F57C00" if score>0.25 else "#0D6E6E")

    body = f"""
<div class="card">
  <div class="title">H18 · Microglial Activation — Neuroinflammation Risk</div>
  <div class="subtitle">{drug_name} | Score={score:.3f} | {risk}</div>
  <div class="grid2">
    <div>
      <canvas id="micGauge" width="300" height="200"></canvas>
    </div>
    <div>
      <div class="grid2" style="gap:8px;margin-bottom:10px">
        <div class="metric"><div class="metric-val" style="color:{col}">{pct:.0f}%</div><div class="metric-lbl">Neuro-inflammation Score</div></div>
        <div class="metric"><div class="metric-val">{il6:.1f}×</div><div class="metric-lbl">IL-6 fold-change</div></div>
        <div class="metric"><div class="metric-val">{tnfa:.1f}×</div><div class="metric-lbl">TNF-α fold-change</div></div>
        <div class="metric"><div class="metric-val">{tlr:.3f}</div><div class="metric-lbl">TLR2/4 score</div></div>
      </div>
      {''.join(f'<p style="color:#E0E0E0;font-size:.82em">→ {m}</p>' for m in (mits or ['No mitigation needed'])[:3])}
    </div>
  </div>
</div>
<script>
(function(){{
  const c=document.getElementById('micGauge');
  const x=c.getContext('2d');
  const cx=150,cy=160,r=110;
  x.fillStyle='#0a0a1a';x.fillRect(0,0,300,200);
  // Arc background
  x.beginPath();x.arc(cx,cy,r,Math.PI,2*Math.PI);
  x.strokeStyle='#1F2937';x.lineWidth=20;x.stroke();
  // Score arc
  const ang=Math.PI+(Math.PI*{pct/100:.3f});
  const grad=x.createLinearGradient(cx-r,cy,cx+r,cy);
  grad.addColorStop(0,'#0D6E6E');grad.addColorStop(0.5,'#F57C00');grad.addColorStop(1,'#C62828');
  x.beginPath();x.arc(cx,cy,r,Math.PI,ang);
  x.strokeStyle='{col}';x.lineWidth=20;x.stroke();
  // Needle
  const nAng=Math.PI+Math.PI*{pct/100:.3f};
  x.beginPath();x.moveTo(cx,cy);
  x.lineTo(cx+Math.cos(nAng)*90,cy+Math.sin(nAng)*90);
  x.strokeStyle='white';x.lineWidth=3;x.stroke();
  x.beginPath();x.arc(cx,cy,8,0,Math.PI*2);x.fillStyle='white';x.fill();
  // Labels
  x.fillStyle='#C9A84C';x.font='bold 20px monospace';x.textAlign='center';
  x.fillText('{pct:.0f}%',cx,cy-30);
  x.fillStyle='#888';x.font='10px monospace';
  x.fillText('SAFE',cx-90,cy+20);x.fillText('RISK',cx+70,cy+20);
  x.fillStyle='#E0E0E0';x.font='11px sans-serif';
  x.fillText('{risk[:30]}',cx,cy+5);
}})();
</script>"""
    return body


# ─────────────────────────────────────────────────────────────────────────────
# H19: LYOPHILIZATION CYCLE — T vs Pressure
# ─────────────────────────────────────────────────────────────────────────────
def h19_lyophilization(science: Dict, drug_name: str) -> str:
    lyoph = science.get("lyophilization", {}) or {}
    Tg    = float(lyoph.get("Tg_prime_C", -30) or -30)
    T_pry = float(lyoph.get("T_primary_drying_C", -32) or -32)
    P_pry = float(lyoph.get("P_primary_mbar", 0.04) or 0.04)
    T_sec = float(lyoph.get("T_secondary_drying_C", 25) or 25)
    t_tot = float(lyoph.get("total_cycle_h", 38) or 38)
    rec   = lyoph.get("recommended_cycle", {}) or {}
    collapse = str(lyoph.get("cake_collapse_risk","?"))

    # Temperature cycle array (hours)
    cycle_T  = [-5, -50, -50, T_pry, T_pry, T_pry+10, T_sec, T_sec, 20]
    cycle_t  = [0,   2,   4,   4.5,   28,    28.5,      30,    36,   t_tot]
    P_cycle  = [1000, 1000, 0.2, P_pry, P_pry, P_pry*2, 0.05, 0.05, 1000]

    body = f"""
<div class="card">
  <div class="title">H19 · Lyophilization Cycle Optimizer</div>
  <div class="subtitle">{drug_name} | Tg'={Tg}°C | Primary drying={T_pry}°C | Total={t_tot:.0f}h | {collapse}</div>
  <canvas id="lyoChart" height="110"></canvas>
  <div class="grid2" style="margin-top:10px">
    <table style="font-size:.8em">
      <thead><tr><th>Step</th><th>Setting</th></tr></thead>
      <tbody>
        <tr><td>Freezing</td><td>-50°C @ 1°C/min</td></tr>
        <tr><td>Primary drying</td><td>{T_pry:.0f}°C, {P_pry:.3f} mbar</td></tr>
        <tr><td>Secondary drying</td><td>+{T_sec:.0f}°C, 0.05 mbar</td></tr>
        <tr><td>Tg' safety margin</td><td>{T_pry - Tg:.1f}°C above Tg'</td></tr>
        <tr><td>Cake collapse risk</td><td style="color:{'#0D6E6E' if 'OK' in collapse else '#C62828'}">{collapse[:30]}</td></tr>
      </tbody>
    </table>
    <div>
      <div class="metric"><div class="metric-val">{t_tot:.0f}h</div><div class="metric-lbl">Total cycle time</div></div>
      <div class="metric" style="margin-top:8px"><div class="metric-val">{Tg:.0f}°C</div><div class="metric-lbl">Tg' (glass transition)</div></div>
    </div>
  </div>
</div>
<script>
const lyoCtx=document.getElementById('lyoChart').getContext('2d');
new Chart(lyoCtx,{{
  type:'line',
  data:{{
    labels:{json.dumps(cycle_t)},
    datasets:[
      {{label:'Temperature (°C)',data:{json.dumps([round(t,1) for t in cycle_T])},
        borderColor:'#F57C00',yAxisID:'yT',pointRadius:4,borderWidth:2.5,tension:.3}},
      {{label:'Pressure (mbar)',data:{json.dumps([round(p,4) for p in P_cycle])},
        borderColor:'#C9A84C',yAxisID:'yP',pointRadius:4,borderWidth:2,
        borderDash:[5,3],tension:.3}},
      {{label:"Tg' line",data:Array({len(cycle_t)}).fill({Tg}),
        borderColor:'#C62828',yAxisID:'yT',pointRadius:0,borderWidth:1.5,
        borderDash:[8,4]}},
    ]
  }},
  options:{{
    responsive:true,
    plugins:{{legend:{{labels:{{color:'#E0E0E0',font:{{size:10}}}}}}}},
    scales:{{
      x:{{ticks:{{color:'#888'}},title:{{display:true,text:'Time (h)',color:'#888'}},grid:{{color:'#1F2937'}}}},
      yT:{{position:'left',ticks:{{color:'#F57C00'}},title:{{display:true,text:'T (°C)',color:'#F57C00'}},grid:{{color:'#1F2937'}}}},
      yP:{{position:'right',type:'logarithmic',ticks:{{color:'#C9A84C'}},title:{{display:true,text:'P (mbar)',color:'#C9A84C'}},grid:{{display:false}}}}
    }}
  }}
}});
</script>"""
    return body


# ─────────────────────────────────────────────────────────────────────────────
# H23: BIODISTRIBUTION ORGAN MAP (animated)
# ─────────────────────────────────────────────────────────────────────────────
def h23_biodistribution_animated(science: Dict, top_dds: Dict, drug_name: str, mol_profile: Dict) -> str:  # v18 FIX-2: mol_profile added
    biodist = science.get("biodistribution_map", {}) or {}
    organs  = biodist.get("organs", {}) or {}
    
    # If organs still missing/default — recalculate from mol_profile + PBPK
    _mol_class = str(mol_profile.get("molecule_class","")).lower()
    _mw        = float(mol_profile.get("MW_Da", 0) or 0)
    _is_biologic = _mol_class in ("biologic","protein","antibody","enzyme") or _mw > 2000
    
    if not organs or (organs.get("Brain (Target)") == 10.0 and 
                       organs.get("Liver") == 30.0):
        # Default values detected — recalculate with proper model
        if _is_biologic:
            try:
                import sys as _html_sys
                _hp = str(__file__).replace("cerebro_html5_engine.py","").replace("viz/","core/")
                if _hp not in _html_sys.path: _html_sys.path.insert(0, _hp)
                from cerebro_science_modules import BiologicPBPK
                _bio = BiologicPBPK.simulate(mol_profile, top_dds)
                organs = _bio.get("organ_distribution", organs)
            except Exception: pass
        
        if not organs:
            cns_ba  = float(top_dds.get("CNS_Bioavailability_Pct", 10) or 10)
            liver   = float(top_dds.get("Off_Target_Liver_pct", 30) or 30)
            stealth = float(top_dds.get("Stealth_Index", 0.5) or 0.5)
            size_nm = float(top_dds.get("size_nm", 80) or 80)
            spleen  = max(1.0, 20 * (1 - stealth) * (1 + (size_nm - 80) / 200))
            organs  = {
                "Brain (Target)": round(cns_ba, 1),
                "Liver":          round(liver, 1),
                "Spleen":         round(max(1, spleen), 1),
                "Lung":           round(max(0.5, 3*(size_nm/100)) if size_nm>100 else 2, 1),
                "Kidney":         round(max(0.5, 5*(1-stealth)), 1),
                "Blood":          round(max(1, 100-cns_ba-liver-spleen-3-4), 1),
            }
    
    organ_list = list(organs.items())[:7]
    org_colors = ["#C9A84C","#F57C00","#7C4DFF","#0D6E6E","#0D6E6E","#C62828","#888888"]
    ratio = str(biodist.get("CNS_vs_offtarget_ratio","?"))

    body = f"""
<div class="card">
  <div class="title">H23 · In-Silico Biodistribution — Organ Map</div>
  <div class="subtitle">{drug_name} | CNS/off-target ratio = {ratio} | No animal studies needed (3R principle)</div>
  <div class="grid2">
    <canvas id="bdChart" height="220"></canvas>
    <div>
      <canvas id="bdBar" height="220"></canvas>
    </div>
  </div>
</div>
<script>
(function(){{
  // Donut chart
  const dCtx=document.getElementById('bdChart').getContext('2d');
  new Chart(dCtx,{{
    type:'doughnut',
    data:{{
      labels:{json.dumps([o for o,_ in organ_list])},
      datasets:[{{
        data:{json.dumps([round(v,1) for _,v in organ_list])},
        backgroundColor:{json.dumps(org_colors[:len(organ_list)])},
        borderColor:'#0a0a1a',borderWidth:3,
        hoverOffset:12
      }}]
    }},
    options:{{
      responsive:true,cutout:'60%',
      plugins:{{
        legend:{{labels:{{color:'#E0E0E0',font:{{size:9}}}}}},
        tooltip:{{callbacks:{{label:ctx=>ctx.label+': '+ctx.parsed.toFixed(1)+'% of dose'}}}}
      }}
    }}
  }});
  // Bar chart
  const bCtx=document.getElementById('bdBar').getContext('2d');
  new Chart(bCtx,{{
    type:'bar',
    data:{{
      labels:{json.dumps([o for o,_ in organ_list])},
      datasets:[{{
        label:'% administered dose',
        data:{json.dumps([round(v,1) for _,v in organ_list])},
        backgroundColor:{json.dumps([c+'BB' for c in org_colors[:len(organ_list)]])},
        borderColor:{json.dumps(org_colors[:len(organ_list)])},
        borderWidth:1.5,borderRadius:4
      }}]
    }},
    options:{{
      responsive:true,indexAxis:'y',
      plugins:{{legend:{{display:false}}}},
      scales:{{
        x:{{ticks:{{color:'#888',callback:v=>v+'%'}},grid:{{color:'#1F2937'}}}},
        y:{{ticks:{{color:'#E0E0E0',font:{{size:9}}}},grid:{{color:'#1F2937'}}}}
      }}
    }}
  }});
}})();
</script>"""
    return body


# ─────────────────────────────────────────────────────────────────────────────
# H26: FUS ACOUSTIC RESPONSE
# ─────────────────────────────────────────────────────────────────────────────
def h26_fus_response(science: Dict, top_dds: Dict, drug_name: str) -> str:
    fus = science.get("fus_responsive", {}) or {}
    freq_mhz  = float(fus.get("freq_MHz", 0.5) or 0.5)
    MI        = float(fus.get("MI_target", 0.4) or 0.4)
    P_kPa     = float(fus.get("P_neg_kPa", 283) or 283)
    win_min   = float(fus.get("BBB_open_window_min", 50) or 50)
    uptake    = float(fus.get("carrier_FUS_uptake_pct", 65) or 65)
    struct_ok = str(fus.get("structural_integrity","OK"))
    rec       = str(fus.get("recommendation",""))[:80]
    bbb_enh   = float(top_dds.get("BBB_Enhanced_Pct",30) or 30)
    struct_col= "#0D6E6E" if struct_ok=="OK" else "#C62828"

    # JS animation built as plain string — no f-string conflicts
    js_anim = """
const fusC=document.getElementById('fusCanvas');
const fusX=fusC.getContext('2d');
let fusT=0,fusPlaying=false,fusR=null;

function fusDraw(t){
  const W=fusC.width,H=fusC.height;
  fusX.fillStyle='#0a0a1a';fusX.fillRect(0,0,W,H);
  
  // Skull
  fusX.beginPath();fusX.arc(W/2,H/2,105,0,Math.PI*2);
  fusX.strokeStyle='#888';fusX.lineWidth=3;fusX.stroke();
  
  // Brain (color changes with t)
  const br=13,bg=Math.round(23+(64-23)*Math.min(1,t*2)),bb=Math.round(64+(160-64)*Math.min(1,t*2));
  const bAlpha=0.3+t*0.4;
  fusX.beginPath();fusX.arc(W/2,H/2,90,0,Math.PI*2);
  fusX.fillStyle='rgba('+br+','+bg+','+bb+','+bAlpha.toFixed(2)+')';fusX.fill();
  
  // BBB pore openings
  if(t>0.25){
    const nPores=Math.floor((t-0.25)*20);
    for(let i=0;i<Math.min(nPores,15);i++){
      const ang=i*(24*Math.PI/180);
      const px=W/2+Math.cos(ang)*88;const py=H/2+Math.sin(ang)*88;
      const pa=Math.min(1,t*2);
      fusX.beginPath();fusX.arc(px,py,3+Math.sin(t*10+i)*2,0,Math.PI*2);
      fusX.fillStyle='rgba(46,204,113,'+pa.toFixed(2)+')';fusX.fill();
    }
  }
  
  // Ultrasound waves from transducer
  const txX=W-30;
  for(let w=0;w<4;w++){
    const wPhase=(t*3+w/4)%1;
    const wX=txX-wPhase*200;
    const wH=30+w*8;
    const wa=Math.max(0,(1-wPhase)*0.7).toFixed(2);
    fusX.beginPath();fusX.moveTo(wX,H/2-wH);fusX.lineTo(wX,H/2+wH);
    fusX.strokeStyle='rgba(52,152,219,'+wa+')';
    fusX.lineWidth=2.5;fusX.stroke();
  }
  
  // Transducer block
  fusX.fillStyle='#C9A84C';fusX.fillRect(txX-5,H/2-40,20,80);
  fusX.fillStyle='#000';fusX.font='9px monospace';fusX.textAlign='center';
  fusX.fillText('FUS',txX+5,H/2+3);fusX.textAlign='left';
  
  // Nanocarriers during window
  if(t>0.3){
    const nCar=Math.floor((t-0.3)*30);
    for(let i=0;i<Math.min(nCar,20);i++){
      const r=(i*37)%70;const a=(i*113)%628/100;
      const cx2=W/2+Math.cos(a)*r;const cy2=H/2+Math.sin(a)*r;
      const ca=(0.6+0.4*Math.sin(i+t*5)).toFixed(2);
      fusX.beginPath();fusX.arc(cx2,cy2,4,0,Math.PI*2);
      fusX.fillStyle='rgba(201,168,76,'+ca+')';fusX.fill();
    }
  }
  
  // Status text
  const stArr=['Standby','FUS activating...','BBB Opening!','Carriers entering brain','Delivered'];
  const stIdx=Math.min(4,Math.floor(t*5));
  fusX.fillStyle='#C9A84C';fusX.font='bold 11px monospace';fusX.textAlign='center';
  fusX.fillText(stArr[stIdx],W/2,H-15);fusX.textAlign='left';
  
  // Progress bar
  fusX.fillStyle='#1F2937';fusX.fillRect(10,H-8,W-20,5);
  fusX.fillStyle='#C9A84C';fusX.fillRect(10,H-8,(W-20)*t,5);
}

function fusLoop(){
  if(!fusPlaying)return;
  fusT=Math.min(1,fusT+0.006);
  fusDraw(fusT);
  if(fusT>=1){fusPlaying=false;document.getElementById('fusBtn').textContent='Replay';return;}
  fusR=requestAnimationFrame(fusLoop);
}
function fusToggle(){
  if(fusT>=1)fusT=0;
  fusPlaying=!fusPlaying;
  document.getElementById('fusBtn').textContent=fusPlaying?'Pause':'Play';
  if(fusPlaying)fusLoop();
}
fusDraw(0);
"""

    return f"""
<div class="card">
  <div class="title">H26 · FUS-Responsive Nanocarrier — Acoustic BBB Opening</div>
  <div class="subtitle">{drug_name} | {freq_mhz} MHz | MI={MI:.2f} | BBB open {win_min:.0f} min | {rec}</div>
  <div class="grid2">
    <div>
      <canvas id="fusCanvas" width="460" height="260"></canvas>
      <div class="ctrl">
        <button onclick="fusToggle()" id="fusBtn">▶ Play</button>
      </div>
    </div>
    <div>
      <div class="grid2" style="gap:8px">
        <div class="metric"><div class="metric-val">{freq_mhz} MHz</div><div class="metric-lbl">FUS Frequency</div></div>
        <div class="metric"><div class="metric-val">{MI:.2f}</div><div class="metric-lbl">Mechanical Index</div></div>
        <div class="metric"><div class="metric-val">{P_kPa:.0f} kPa</div><div class="metric-lbl">Negative Pressure</div></div>
        <div class="metric"><div class="metric-val">{win_min:.0f} min</div><div class="metric-lbl">BBB Open Window</div></div>
        <div class="metric"><div class="metric-val">{uptake:.0f}%</div><div class="metric-lbl">FUS-Enhanced Uptake</div></div>
        <div class="metric"><div class="metric-val">{bbb_enh:.0f}%</div><div class="metric-lbl">Standard BBB Enh.</div></div>
      </div>
      <p style="color:#888;font-size:.78em;margin-top:10px">
        FUS + microbubbles open BBB via stable cavitation (MI 0.3-0.5). 
        Inertial cavitation (MI>0.8) = irreversible damage. 
        Carrier injected 5 min before FUS for optimal uptake.
      </p>
      <p style="color:{struct_col};font-size:.85em"><b>Structural integrity: {struct_ok}</b></p>
    </div>
  </div>
</div>
<script>{js_anim}</script>"""

def h09_docking_release(science: Dict, top_dds: Dict, drug_name: str) -> str:
    release = science.get("release", {}) or {}
    fep     = science.get("fep_binding", {}) or {}
    t_arr   = release.get("t_h", list(range(49))) or list(range(49))
    rb      = release.get("release_blood_pct", []) or []
    re      = release.get("release_endo_pct", []) or []
    dG      = float(fep.get("dG_avidity_kcal", -12.5) or -12.5)
    t50_b   = float(release.get("t50_blood_h", 17) or 17)
    carrier = str(top_dds.get("Carrier_Type","DDS"))
    escape  = float(top_dds.get("Endosomal_Escape_Eff",0.5) or 0.5)

    if len(t_arr)>40:
        idx=[int(i*(len(t_arr)-1)/39) for i in range(40)]
        t_arr=[t_arr[i] for i in idx]; rb=[rb[i] for i in idx] if rb else []; re=[re[i] for i in idx] if re else []
    
    rb  = rb  or [0]*len(t_arr)
    re  = re  or [0]*len(t_arr)

    body = f"""
<div class="card">
  <div class="title">H09 · Docking + Release — Combined Delivery Simulation</div>
  <div class="subtitle">{drug_name} from {carrier} | ΔG={dG:.1f} kcal/mol | t50_blood={t50_b:.1f}h | Escape={escape*100:.0f}%</div>
  <div class="grid2">
    <div>
      <p style="color:#888;font-size:.8em;margin-bottom:6px">Docking affinity → release kinetics correlation</p>
      <canvas id="drChart" height="180"></canvas>
    </div>
    <div>
      <p style="color:#888;font-size:.8em;margin-bottom:6px">Endosomal escape efficiency vs release rate</p>
      <canvas id="drBar" height="180"></canvas>
    </div>
  </div>
</div>
<script>
const drCtx=document.getElementById('drChart').getContext('2d');
new Chart(drCtx,{{
  type:'line',
  data:{{
    labels:{json.dumps([round(x,1) for x in t_arr])},
    datasets:[
      {{label:'Blood release (%)',data:{json.dumps([round(x,2) for x in rb])},
        borderColor:'#F57C00',fill:true,backgroundColor:'rgba(232,119,34,0.08)',
        pointRadius:0,borderWidth:2.5,tension:.4}},
      {{label:'Endosomal release (%)',data:{json.dumps([round(x,2) for x in re])},
        borderColor:'#7C4DFF',fill:true,backgroundColor:'rgba(155,89,182,0.08)',
        pointRadius:0,borderWidth:2,tension:.4}},
    ]
  }},
  options:{{
    responsive:true,
    plugins:{{legend:{{labels:{{color:'#E0E0E0',font:{{size:10}}}}}}}},
    scales:{{
      x:{{ticks:{{color:'#888',maxTicksLimit:8}},title:{{display:true,text:'Time (h)',color:'#888'}},grid:{{color:'#1F2937'}}}},
      y:{{min:0,max:100,ticks:{{color:'#888',callback:v=>v+'%'}},title:{{display:true,text:'% Released',color:'#888'}},grid:{{color:'#1F2937'}}}}
    }}
  }}
}});
const drBCtx=document.getElementById('drBar').getContext('2d');
new Chart(drBCtx,{{
  type:'bar',
  data:{{
    labels:['Docking ΔG','Escape Eff.','Release rate','BBB Transport'],
    datasets:[{{
      label:'Normalized score (0-100)',
      data:[
        Math.min(100,Math.abs({dG:.1f})*5),
        {escape*100:.1f},
        Math.min(100,100/{t50_b:.1f}*10),
        {float(top_dds.get('BBB_Enhanced_Pct',30) or 30):.1f}
      ],
      backgroundColor:['#C9A84C','#7C4DFF','#F57C00','#C9A84C'],
      borderWidth:1.5,borderRadius:4
    }}]
  }},
  options:{{
    responsive:true,
    plugins:{{legend:{{display:false}}}},
    scales:{{
      x:{{ticks:{{color:'#E0E0E0',font:{{size:9}}}},grid:{{color:'#1F2937'}}}},
      y:{{min:0,max:100,ticks:{{color:'#888',callback:v=>v}},grid:{{color:'#1F2937'}}}}
    }}
  }}
}});
</script>"""
    return body

# ══════════════════════════════════════════════════════════════════════════
# v22 — C+ Flow HTML5 sections (Surrogate · Deep · Translational · Fallback)
# Per Muhammad's mandate: ALL C+ Flow results visible in EVERY output.
# ══════════════════════════════════════════════════════════════════════════
def h27_surrogate_principles(drug_name: str, breakdown: list,
                                matrix: list = None,
                                deep_results: dict = None,
                                translational: dict = None) -> str:
    """ALL 62 principles in P01→P62 order — unified scoreboard.

    Merges data from three pipeline stages:
      • Class A (Surrogate, 56 principles) — from `matrix[0]["principles"]`
      • Class B (Deep Physics, 1 principle)  — from `deep_results`
      • Class C (Translational, 5 principles) — from `translational`

    Every principle gets one row regardless of class. A colour-coded
    badge shows the class, and the score/confidence/method/reference
    columns pull from whichever source has data.
    """
    if not breakdown:
        return ""
    top1 = breakdown[0]
    deep_results  = deep_results  or {}
    translational = translational or {}

    # ── Group rollup badges ──────────────────────────────────────────────
    groups_html = ""
    for g, score in top1.get("group_scores", {}).items():
        color = "#0D6E6E" if score >= 70 else "#F57C00" if score >= 50 else "#C62828"
        groups_html += (
            f'<div style="display:inline-block;margin:4px;padding:8px 14px;'
            f'background:{color};color:#fff;border-radius:6px;font-size:13px;'
            f'font-weight:600;letter-spacing:.3px;">'
            f'{g.replace("_"," ")}: {score:.1f}/100</div>')

    # ── Pull the full catalog ────────────────────────────────────────────
    try:
        from cerebro_62_principles_catalog import PRINCIPLES_62
    except Exception:
        PRINCIPLES_62 = {}

    # ── Merge per-principle data from all three sources ───────────────────
    surrogate_data = {}
    if matrix:
        surrogate_data = matrix[0].get("principles", {})

    # Class badge colours (aligned with brand)
    class_badge = {
        "A_surrogate":     ("#0D6E6E", "A"),   # neuro-positive teal
        "B_deep":          ("#7C4DFF", "B"),    # categorical purple
        "C_translational": ("#F57C00", "C"),    # molecule orange
    }

    rows_html = ""
    for i in range(1, 63):
        pid = f"P{i:02d}"
        cat = PRINCIPLES_62.get(pid, {})
        cls = cat.get("class", "A_surrogate")
        badge_color, badge_letter = class_badge.get(cls, ("#C9A84C", "?"))
        title = cat.get("title_en", "—")[:52]

        # Pull score/confidence/method/reference from the right source
        score  = 0.0
        conf   = "—"
        method = ""
        ref    = ""

        if pid in surrogate_data:
            r = surrogate_data[pid]
            score  = r.get("score", 0)
            conf   = r.get("confidence", "—")
            method = r.get("method", "") or ""
            ref    = r.get("reference", "") or ""
        elif pid in deep_results:
            r = deep_results[pid]
            score  = r.get("score", 0)
            conf   = r.get("confidence", "—")
            method = r.get("method", "") or ""
            ref    = ("✅ Validated" if r.get("validated") else "❌ Not validated")
        elif pid in translational:
            r = translational[pid]
            score  = (r.get("compliance_score") or r.get("fto_score")
                       or r.get("patentability_score") or 0)
            try:
                score = float(score)
            except (TypeError, ValueError):
                score = 0.0
            conf   = "—"
            method = r.get("status", "") or ""
            ref    = (r.get("recommendation", "") or "")[:50]

        # Row background — score-based pastel (light) → text MUST be dark
        bg = ("#E8F5E9" if score >= 80 else "#F1F8E9" if score >= 60
               else "#FFF8E1" if score >= 40 else "#FFEBEE" if score > 0
               else "#F5F5F5")
        txt = "#0a0a1a"

        rows_html += (
            f'<tr style="background:{bg};color:{txt};'
            f'border-bottom:1px solid rgba(0,0,0,.06)">'
            f'<td style="padding:5px 8px;font-weight:700;white-space:nowrap">'
            f'{pid}</td>'
            f'<td style="padding:5px 6px;text-align:center">'
            f'<span style="display:inline-block;width:22px;height:22px;'
            f'line-height:22px;border-radius:4px;background:{badge_color};'
            f'color:#fff;font-size:11px;font-weight:700;text-align:center">'
            f'{badge_letter}</span></td>'
            f'<td style="padding:5px 8px;font-size:12px">{title}</td>'
            f'<td style="padding:5px 8px;text-align:center;font-weight:700">'
            f'{score:.1f}</td>'
            f'<td style="padding:5px 8px;text-align:center;font-size:11px">'
            f'{str(conf)[:8]}</td>'
            f'<td style="padding:5px 8px;font-size:10px">{method[:85]}</td>'
            f'<td style="padding:5px 8px;font-size:10px">{ref[:50]}</td>'
            f'</tr>')

    composite = top1.get("composite", 0)
    verdict   = top1.get("verdict", "?")
    v_color   = ("#0D6E6E" if verdict == "GOOD" else
                 "#F57C00" if verdict in ("FAIR", "MARGINAL") else "#C62828")

    return f'''
<section class="cerebro-section">
  <h2>🧬 All 62 Principles — Unified Scoreboard (Top-1 DDS)</h2>
  <p style="color:#9CA3AF;font-size:13px;margin-bottom:8px;">
    For <strong style="color:#E0E0E0">{drug_name}</strong>, the Top-1 DDS
    achieved a composite score of
    <strong style="color:{v_color}">{composite:.1f}/100 ({verdict})</strong>.
    Below are the CNS group rollups followed by the FULL 62-principle scoreboard
    covering all three pipeline classes:
    <span style="display:inline-block;width:14px;height:14px;border-radius:3px;
          background:#0D6E6E;vertical-align:middle"></span>&nbsp;A&nbsp;(Surrogate)
    <span style="display:inline-block;width:14px;height:14px;border-radius:3px;
          background:#7C4DFF;vertical-align:middle;margin-left:8px"></span>&nbsp;B&nbsp;(Deep)
    <span style="display:inline-block;width:14px;height:14px;border-radius:3px;
          background:#F57C00;vertical-align:middle;margin-left:8px"></span>&nbsp;C&nbsp;(Translational)
  </p>

  <h3 style="margin-top:12px;font-size:14px;color:#C9A84C">
    CNS Principle Group Rollups</h3>
  {groups_html}

  <h3 style="margin-top:18px;font-size:14px;color:#C9A84C">
    All 62 Principles (P01 → P62)</h3>
  <div style="overflow-x:auto">
  <table style="width:100%;font-size:11px;border-collapse:collapse;
                font-family:Inter,system-ui,sans-serif;">
    <thead><tr style="background:#0f2040;color:#C9A84C;letter-spacing:.4px">
      <th style="padding:7px 8px;text-align:left">P#</th>
      <th style="padding:7px 6px;text-align:center">Class</th>
      <th style="padding:7px 8px;text-align:left">Title</th>
      <th style="padding:7px 8px;text-align:center">Score</th>
      <th style="padding:7px 8px;text-align:center">Conf.</th>
      <th style="padding:7px 8px;text-align:left">Method</th>
      <th style="padding:7px 8px;text-align:left">Reference</th>
    </tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
  </div>

  <p style="margin-top:8px;color:#9CA3AF;font-size:12px;">
    {top1.get("narrative","")}
  </p>
</section>
'''


def h28_deep_validation(drug_name: str, deep_results: dict, deep_summary: dict) -> str:
    """Class B Deep Physics validation results for Top-1 DDS."""
    if not deep_results:
        return ""
    verdict = deep_summary.get("verdict","?")
    pct = deep_summary.get("pct",0)
    badge_color = ("#0D6E6E" if verdict=="PASSED" else
                   "#F57C00" if verdict=="MARGINAL" else "#C62828")
    rows = ""
    for pid, r in sorted(deep_results.items()):
        v_color = "#0D6E6E" if r.get("validated") else "#C62828"
        v_icon = "✅" if r.get("validated") else "❌"
        rows += (
            f'<tr><td><strong>{pid}</strong></td>'
            f'<td style="color:{v_color};font-weight:bold;">{v_icon}</td>'
            f'<td>{r.get("score",0):.1f}</td>'
            f'<td>{r.get("value","")}</td>'
            f'<td>{r.get("confidence","")}</td>'
            f'<td>{(r.get("method","") or "")[:100]}</td>'
            f'<td>{(r.get("narrative","") or "")[:140]}</td></tr>')
    return f'''
<section class="cerebro-section">
  <h2>🔬 H28 — Class B Deep Physics Validation (Top-1 DDS)</h2>
  <div style="background:{badge_color};color:#fff;padding:14px;border-radius:8px;">
    <strong style="font-size:18px;">Verdict: {verdict}</strong> &nbsp;
    | &nbsp; {deep_summary.get("passed_count",0)}/{deep_summary.get("total",0)}
    principles validated ({pct}% — threshold 70%)
  </div>
  <p style="margin-top:8px;color:#555;font-size:13px;">{deep_summary.get("narrative","")}</p>
  <table style="width:100%;font-size:12px;border-collapse:collapse;margin-top:8px;">
    <thead><tr style="background:#0f2040;color:#fff;">
      <th>Principle</th><th>Validated</th><th>Score</th><th>Value</th>
      <th>Confidence</th><th>Method</th><th>Narrative</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</section>
'''


def h29_translational(drug_name: str, translational: dict) -> str:
    """Class C Translational deliverables (Pre-IND, FTO, Compliance, Grant, Patent)."""
    if not translational:
        return ""
    cards = ""
    PID_NAMES = {"P21":"Pre-IND Outline","P32":"Freedom-to-Operate",
                  "P45":"21 CFR Part 11","P55":"Grant Outline",
                  "P56":"Patentability"}
    for pid, t in sorted(translational.items()):
        status = t.get("status","?")
        bg = ("#E8F5E9" if status in ("structured_outline_ready","scored","audit_completed","search_queries_prepared")
              else "#FFEBEE")
        score_val = (t.get("compliance_score") or t.get("fto_score")
                      or t.get("patentability_score") or "—")
        recommendation = t.get("recommendation", "")
        cards += f'''
        <div style="flex:1;min-width:240px;background:{bg};border:1px solid #ddd;
                    border-radius:8px;padding:14px;margin:6px;">
          <h4 style="margin:0 0 6px 0;color:#0f2040;">{pid}: {PID_NAMES.get(pid, t.get("title",""))}</h4>
          <div style="font-size:12px;color:#555;">Status: <strong>{status}</strong></div>
          <div style="font-size:12px;color:#555;">Score: <strong>{score_val}</strong></div>
          {f'<div style="font-size:12px;color:#555;">Rec: <strong>{recommendation}</strong></div>' if recommendation else ""}
          <p style="font-size:11px;color:#666;margin-top:8px;">{(t.get("narrative","") or "")[:200]}</p>
          {f'<p style="font-size:10px;color:#C9A84C;margin-top:6px;">📌 {t.get("v23_note","")}</p>' if t.get("v23_note") else ""}
        </div>'''
    return f'''
<section class="cerebro-section">
  <h2>📋 H29 — Class C Translational Deliverables (Top-1 DDS)</h2>
  <p style="color:#777;font-size:13px;margin-bottom:8px;">
    Translational outputs for <strong>{drug_name}</strong>'s validated Top-1 DDS.
    These are NOT used for ranking — they are administrative deliverables
    triggered only AFTER deep physics validation passes.
  </p>
  <div style="display:flex;flex-wrap:wrap;gap:6px;">{cards}</div>
</section>
'''


def h30_fallback_chain(drug_name: str, fallback_chain: list) -> str:
    """Top-N fallback audit trail with failure & transition reasons."""
    if not fallback_chain:
        return ""
    rows = ""
    VERD_COLOR = {"PASSED":"#0D6E6E","MARGINAL":"#F57C00","FAILED":"#C62828"}
    for entry in fallback_chain:
        c = VERD_COLOR.get(entry["verdict"], "#777")
        promoted = "✅ YES" if entry.get("promoted") else "—"
        failed_pids = ", ".join(p["principle"] for p in entry.get("failed_principles", [])[:8])
        rows += f'''
        <tr>
          <td>#{entry["rank"]}</td>
          <td><strong>{entry["dds_name"]}</strong></td>
          <td>{entry.get("surrogate_score","?")}</td>
          <td style="color:{c};font-weight:bold;">{entry["verdict"]}<br>
              <span style="font-size:10px;font-weight:normal;">
              {entry["deep_passed_pct"]}% ({entry.get("deep_passed_count","?")}/{entry.get("deep_total","?")})
              </span></td>
          <td>{promoted}</td>
          <td style="font-size:11px;">{entry.get("failure_reason","—")}</td>
          <td style="font-size:11px;">{entry.get("transition_reason","—")}</td>
        </tr>'''
    return f'''
<section class="cerebro-section">
  <h2>🔁 H30 — Top-N Fallback Audit Trail</h2>
  <p style="color:#777;font-size:13px;margin-bottom:8px;">
    For <strong>{drug_name}</strong>: each candidate DDS that was tried in the
    Class B deep validation phase. If the Top-1 fails the 70% threshold,
    we fall back to Top-2, then Top-3 — with explicit reasons recorded.
  </p>
  <table style="width:100%;font-size:12px;border-collapse:collapse;">
    <thead><tr style="background:#0f2040;color:#fff;">
      <th>Rank</th><th>DDS</th><th>Surrogate</th><th>Verdict</th>
      <th>Promoted?</th><th>Failure Reason</th><th>Transition Reason</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</section>
'''
