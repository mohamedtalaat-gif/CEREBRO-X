"""
================================================================================
CEREBRO-X |  HTML5 CANVAS VIDEO ENGINE
================================================================================
Created by: Muhammad Talaat — CEREBRO-X

Replaces MP4 video generation with standalone HTML5 Canvas animations.
Each "video" is a self-contained HTML file with requestAnimationFrame loop.
No ffmpeg, no imageio, no server needed — runs in any browser.

5 animations:
  V01: BBB Crossing — nanocarrier traversing blood-brain barrier
  V02: PBPK Simulation — drug concentration time-course in 6 compartments
  V03: Drug Release — release kinetics from carrier (blood vs endosomal)
  V04: DDS Ranking — animated bar race of composite scores
  V05: Biodistribution — organ uptake animation over time
================================================================================
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path

log = logging.getLogger("CEREBRO-CANVAS")

_BASE_STYLE = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@200;300;400;500;600;700;800;900&display=swap">
<style>
:root {
  --void-base:#060610; --void-elevated:#0a0a1a; --void-panel:#0f2040;
  --gold:#C9A84C; --gold-light:#D4B563; --gold-dark:#B89A3F;
  --neuro-positive:#0D6E6E; --alert-red:#C62828; --molecule-orange:#F57C00;
  --text-primary:#E0E0E0; --text-secondary:#9CA3AF; --text-muted:#6B7280;
  --hairline:#1F2937;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: var(--void-base);
       font-family: 'Inter','Segoe UI',Helvetica,Arial,sans-serif;
       color: var(--text-primary); font-weight: 300;
       line-height: 1.65; letter-spacing: 0.01em; }
.container { max-width: 900px; margin: 0 auto; padding: 24px; }
h2 { color: var(--gold); font-size: 1.4em; font-weight: 700;
     margin-bottom: 6px; letter-spacing: -0.3px; }
.subtitle { color: var(--text-secondary); font-size: .82em;
            margin-bottom: 16px; font-weight: 400; }
canvas { display: block; border-radius: 10px;
         border: 1px solid var(--hairline); background: var(--void-elevated); }
.ctrl { margin-top: 12px; display: flex; gap: 10px; flex-wrap: wrap; }
button { background: var(--void-panel); color: var(--text-primary);
         border: 1px solid var(--hairline); padding: 8px 18px;
         border-radius: 8px; cursor: pointer; font-family: inherit;
         font-size: .85em; font-weight: 500; transition: all .2s ease; }
button:hover { background: var(--void-elevated); border-color: var(--gold);
               color: var(--gold); transform: translateY(-1px); }
.metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
           gap: 10px; margin-top: 16px; }
.metric { background: var(--void-panel); border: 1px solid var(--hairline);
          border-radius: 10px; padding: 14px; text-align: center; }
.metric-val { color: var(--gold); font-size: 1.5em; font-weight: 800;
              letter-spacing: -0.4px; line-height: 1.1; }
.metric-lbl { color: var(--text-muted); font-size: .68em; margin-top: 5px;
              text-transform: uppercase; letter-spacing: 1.5px; font-weight: 500; }
.progress { width: 100%; height: 6px; background: var(--hairline);
            border-radius: 3px; margin-top: 10px; overflow: hidden; }
.progress-bar { height: 6px; background: linear-gradient(90deg,var(--gold-dark),var(--gold),var(--gold-light));
                border-radius: 3px; transition: width .05s; }
</style>
"""

def _html_wrap(title: str, subtitle: str, canvas_id: str,
               canvas_w: int, canvas_h: int,
               metrics_html: str, js_code: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CEREBRO-X | {title}</title>
{_BASE_STYLE}
</head>
<body>
<div class="container">
  <h2>CEREBRO-X | {title}</h2>
  <p class="subtitle">{subtitle}</p>
  <canvas id="{canvas_id}" width="{canvas_w}" height="{canvas_h}"></canvas>
  <div class="progress"><div class="progress-bar" id="progressBar" style="width:0%"></div></div>
  <div class="ctrl">
    <button onclick="anim.toggle()" id="playBtn">▶ Play</button>
    <button onclick="anim.reset()">↺ Reset</button>
    <button onclick="anim.step()">⏭ Step +1%</button>
  </div>
  {metrics_html}
</div>
<script>
{js_code}
</script>
</body>
</html>"""


# ─────────────────────────────────────────────────────────────────────────────
def make_v01_bbb(drug_name: str, top_dds: dict, out_dir: Path) -> Path:
    """V01: BBB Crossing Animation — Canvas replacement for MP4."""
    carrier = str(top_dds.get("Carrier_Type","Vexosome"))
    ligand  = str(top_dds.get("Surface_Ligand","RVG29"))
    size_nm = float(top_dds.get("size_nm",80) or 80)
    bbb_enh = float(top_dds.get("BBB_Enhanced_Pct",45) or 45)
    bbb_nat = float(top_dds.get("BBB_Native_Pct",3) or 3)
    cns_ba  = float(top_dds.get("CNS_Bioavailability_Pct",12) or 12)
    ee      = float(top_dds.get("encapsulation_efficiency_pct",75) or 75)
    peg     = float(top_dds.get("pegylation_degree_mol_pct",5) or 5)

    metrics = f"""<div class="metrics">
  <div class="metric"><div class="metric-val">{bbb_enh:.1f}%</div><div class="metric-lbl">BBB Enhancement</div></div>
  <div class="metric"><div class="metric-val">{bbb_nat:.1f}%</div><div class="metric-lbl">Native BBB</div></div>
  <div class="metric"><div class="metric-val">{cns_ba:.1f}%</div><div class="metric-lbl">CNS Bioavailability</div></div>
  <div class="metric"><div class="metric-val">{size_nm:.0f}nm</div><div class="metric-lbl">Carrier Size</div></div>
</div>"""

    js = f"""
const C = document.getElementById('c01');
const X = C.getContext('2d');
const DATA = {{drug:'{drug_name}',carrier:'{carrier}',ligand:'{ligand}',
  size:{size_nm},bbbEnh:{bbb_enh},bbbNat:{bbb_nat},cnsBA:{cns_ba},ee:{ee},peg:{peg}}};

const anim = (function(){{
  let t=0, playing=false, raf=null;
  const W=C.width,H=C.height;

  function draw(t){{
    X.fillStyle='#0a0a1a';X.fillRect(0,0,W,H);
    // Background zones
    const bbbY=H*0.42;
    X.fillStyle='rgba(13,110,60,0.08)';X.fillRect(0,0,W,bbbY-15);    // blood
    X.fillStyle='rgba(13,23,64,0.25)';X.fillRect(0,bbbY+15,W,H-bbbY-15); // brain
    // Zone labels
    X.fillStyle='rgba(46,204,113,0.5)';X.font='11px monospace';
    X.fillText('BLOOD (pH 7.4)',12,24);
    X.fillStyle='rgba(52,152,219,0.5)';
    X.fillText('BRAIN PARENCHYMA',12,H-14);

    // BBB membrane
    const g=X.createLinearGradient(0,bbbY-15,0,bbbY+15);
    g.addColorStop(0,'#0D6E6E');g.addColorStop(0.5,'#0D6E6E');g.addColorStop(1,'#0D6E6E');
    X.fillStyle=g;X.fillRect(0,bbbY-15,W,30);
    X.fillStyle='#0D6E6E';X.font='9px monospace';
    X.fillText('BBB Endothelium — '+DATA.ligand+' receptors',10,bbbY+4);

    // Receptors
    const recX=[80,170,270,370,460,560,660,760];
    recX.forEach((rx,ri)=>{{
      const engaged=t>0.3&&Math.abs(rx-W/2)<160;
      X.beginPath();X.arc(rx,bbbY-15,7,0,Math.PI*2);
      X.fillStyle=engaged?'#F57C00':'#0f2040';X.fill();
      X.strokeStyle='#C9A84C';X.lineWidth=1.5;X.stroke();
      if(engaged&&t>0.45){{
        X.fillStyle='rgba(232,119,34,0.25)';
        X.beginPath();X.arc(rx,bbbY-15,14,0,Math.PI*2);X.fill();
      }}
    }});

    // Nanocarrier position (approaches BBB, crosses at t=0.5)
    const npY = t<0.5 ? H*0.1+(bbbY-50-H*0.1)*t*2
                       : bbbY-50+(H*0.75-(bbbY-50))*(t-0.5)*2;
    const npX=W/2;
    const crossed=npY>bbbY+30;
    const crossing=npY>=bbbY-60&&npY<=bbbY+60;

    // PEG corona
    for(let i=0;i<12;i++){{
      const ang=i*30*Math.PI/180+t*1.5;
      const r=DATA.size/5+10;
      X.beginPath();X.moveTo(npX+Math.cos(ang)*r,npY+Math.sin(ang)*r);
      X.lineTo(npX+Math.cos(ang)*(r+8),npY+Math.sin(ang)*(r+8));
      X.strokeStyle=crossed?'rgba(13,110,110,0.5)':'#0D6E6E';X.lineWidth=1.5;X.stroke();
      X.beginPath();X.arc(npX+Math.cos(ang)*(r+8),npY+Math.sin(ang)*(r+8),2.5,0,Math.PI*2);
      X.fillStyle='#0D6E6E';X.fill();
    }}
    // NP core
    X.beginPath();X.arc(npX,npY,DATA.size/5,0,Math.PI*2);
    X.fillStyle=crossed?'#0D6E6E':'#0f2040';X.fill();
    X.strokeStyle='#C9A84C';X.lineWidth=2;X.stroke();
    // Ligands
    for(let i=0;i<8;i++){{
      const ang=i*45*Math.PI/180+t;
      const lr=DATA.size/5+3,lr2=lr+6;
      X.beginPath();X.moveTo(npX+Math.cos(ang)*lr,npY+Math.sin(ang)*lr);
      X.lineTo(npX+Math.cos(ang)*lr2,npY+Math.sin(ang)*lr2);
      X.strokeStyle=crossing?'#F57C00':'#7C4DFF';X.lineWidth=2;X.stroke();
      X.beginPath();X.arc(npX+Math.cos(ang)*lr2,npY+Math.sin(ang)*lr2,3,0,Math.PI*2);
      X.fillStyle=crossing?'#F57C00':'#7C4DFF';X.fill();
    }}
    // Drug payload
    X.beginPath();X.arc(npX,npY,7,0,Math.PI*2);
    X.fillStyle=crossed?'rgba(232,119,34,0.9)':'#F57C00';X.fill();

    // Multiple NPs trailing (simulating dosing)
    if(t>0.3){{
      for(let i=1;i<=3;i++){{
        const tt=Math.max(0,t-i*0.08);
        const ny=tt<0.5?H*0.1+(bbbY-50-H*0.1)*tt*2:bbbY-50+(H*0.75-(bbbY-50))*(tt-0.5)*2;
        const nx=npX+(i%2===0?-60:60);
        const a=Math.max(0,(1-i*0.2)*0.6);
        X.globalAlpha=a;
        X.beginPath();X.arc(nx,ny,DATA.size/6,0,Math.PI*2);
        X.fillStyle='#0f2040';X.fill();X.strokeStyle='#C9A84C';X.lineWidth=1;X.stroke();
        X.globalAlpha=1;
      }}
    }}

    // Status overlay
    const status=['Loading carriers...','Circulating in blood','Approaching BBB','Receptor binding!','Crossing BBB!','Releasing in brain ✓'];
    const si=Math.min(5,Math.floor(t*6));
    X.fillStyle='rgba(201,168,76,0.9)';X.font='bold 12px monospace';X.textAlign='center';
    X.fillText(status[si],W/2,H-16);X.textAlign='left';
    // Progress bar
    document.getElementById('progressBar').style.width=(t*100)+'%';
  }}

  function loop(){{
    if(!playing)return;
    t=Math.min(1,t+0.004);
    draw(t);
    if(t>=1){{playing=false;document.getElementById('playBtn').textContent='↺ Replay';return;}}
    raf=requestAnimationFrame(loop);
  }}
  return {{
    toggle(){{
      if(t>=1)t=0;
      playing=!playing;
      document.getElementById('playBtn').textContent=playing?'⏸ Pause':'▶ Play';
      if(playing)loop();
    }},
    reset(){{t=0;playing=false;draw(0);document.getElementById('playBtn').textContent='▶ Play';
      document.getElementById('progressBar').style.width='0%';}},
    step(){{t=Math.min(1,t+0.01);draw(t);}},
  }};
}})();
anim.reset();
"""
    html = _html_wrap(
        f"V01 — BBB Crossing | {drug_name}",
        f"Carrier: {carrier} | Ligand: {ligand} | BBB Enhancement: {bbb_enh:.1f}% (vs native {bbb_nat:.1f}%)",
        "c01", 860, 340, metrics, js)

    out = out_dir / f"V01_BBB_Crossing_{drug_name}.html"
    out.write_text(html, encoding='utf-8')
    return out


# ─────────────────────────────────────────────────────────────────────────────
def make_v02_pbpk(drug_name: str, pbpk: dict, out_dir: Path) -> Path:
    """V02: PBPK 6-compartment animated time-course."""
    t_arr  = pbpk.get("t_h", list(range(73))) or list(range(73))
    C_p    = pbpk.get("C_plasma",  [0]*len(t_arr)) or [0]*len(t_arr)
    C_b    = pbpk.get("C_brain_ISF", [0]*len(t_arr)) or [0]*len(t_arr)
    C_csf  = pbpk.get("C_CSF",    [0]*len(t_arr)) or [0]*len(t_arr)
    C_bc   = pbpk.get("C_brain_cell",[0]*len(t_arr)) or [0]*len(t_arr)
    C_per  = pbpk.get("C_peripheral",[0]*len(t_arr)) or [0]*len(t_arr)
    Kp     = float(pbpk.get("Kp_brain",0.002) or 0.002)
    Cmax_b = float(pbpk.get("Cmax_brain_ug_mL",0.001) or 0.001)
    t_max  = float(pbpk.get("t_max_brain_h",8) or 8)

    # Sample 80 points
    n = min(80, len(t_arr))
    idx = [int(i*(len(t_arr)-1)/(n-1)) for i in range(n)]
    t_s   = [round(t_arr[i],2) for i in idx]
    Cp_s  = [round(C_p[i],5) for i in idx]
    Cb_s  = [round(C_b[i],5) for i in idx]
    Ccsf_s= [round(C_csf[i],5) for i in idx]
    Cbc_s = [round(C_bc[i],5) for i in idx]
    Cper_s= [round(C_per[i],5) for i in idx]

    metrics = f"""<div class="metrics">
  <div class="metric"><div class="metric-val">{Cmax_b:.5f}</div><div class="metric-lbl">Cmax brain (µg/mL)</div></div>
  <div class="metric"><div class="metric-val">{t_max:.1f}h</div><div class="metric-lbl">t_max brain</div></div>
  <div class="metric"><div class="metric-val">{Kp:.5f}</div><div class="metric-lbl">Kp,brain</div></div>
  <div class="metric"><div class="metric-val">{float(pbpk.get("AUC_brain_ugh_mL",0)):.4f}</div><div class="metric-lbl">AUC brain (µg·h/mL)</div></div>
</div>"""

    js = f"""
const C2 = document.getElementById('c02');
const X2 = C2.getContext('2d');
const tArr={json.dumps(t_s)};
const series={{
  Plasma:    {{data:{json.dumps(Cp_s)}, color:'#F57C00'}},
  'Brain ISF':{{data:{json.dumps(Cb_s)}, color:'#C9A84C'}},
  CSF:       {{data:{json.dumps(Ccsf_s)},color:'#7C4DFF'}},
  'Brain Cell':{{data:{json.dumps(Cbc_s)},color:'#0D6E6E'}},
  Peripheral:{{data:{json.dumps(Cper_s)},color:'#C62828'}},
}};
const maxC=Math.max(...Object.values(series).flatMap(s=>s.data))*1.15||0.01;
const W2=C2.width,H2=C2.height,PAD={{t:20,r:120,b:40,l:70}};
const plotW=W2-PAD.l-PAD.r,plotH=H2-PAD.t-PAD.b;
const scX=i=>PAD.l+i/tArr.length*plotW;
const scY=v=>PAD.t+plotH-(v/maxC)*plotH;

const anim2=(function(){{
  let t=0,playing=false,raf=null;
  function draw(progress){{
    X2.fillStyle='#0a0a1a';X2.fillRect(0,0,W2,H2);
    // Grid
    X2.strokeStyle='#1F2937';X2.lineWidth=0.5;
    for(let i=0;i<=5;i++){{
      const y=PAD.t+i*plotH/5;
      X2.beginPath();X2.moveTo(PAD.l,y);X2.lineTo(W2-PAD.r,y);X2.stroke();
      const v=(maxC*(1-i/5)).toFixed(5);
      X2.fillStyle='#888';X2.font='9px monospace';X2.textAlign='right';
      X2.fillText(v,PAD.l-4,y+3);
    }}
    for(let i=0;i<=8;i++){{
      const x=PAD.l+i*plotW/8;
      X2.beginPath();X2.moveTo(x,PAD.t);X2.lineTo(x,H2-PAD.b);X2.stroke();
      const tv=Math.round(tArr[Math.floor(i*(tArr.length-1)/8)]);
      X2.fillStyle='#888';X2.textAlign='center';
      X2.fillText(tv+'h',x,H2-PAD.b+14);
    }}
    // Axes labels
    X2.fillStyle='#C9A84C';X2.font='10px monospace';X2.textAlign='center';
    X2.fillText('Time (h)',W2/2,H2-4);
    X2.save();X2.translate(14,H2/2);X2.rotate(-Math.PI/2);
    X2.fillText('Concentration (µg/mL)',0,0);X2.restore();

    // Series
    const nPts=Math.floor(progress*tArr.length);
    let li=0;
    Object.entries(series).forEach(([name,{{data,color}}])=>{{
      if(nPts<2)return;
      X2.beginPath();
      X2.moveTo(scX(0),scY(data[0]));
      for(let i=1;i<nPts;i++) X2.lineTo(scX(i),scY(data[i]));
      X2.strokeStyle=color;X2.lineWidth=2;X2.stroke();
      // Legend
      X2.fillStyle=color;X2.fillRect(W2-PAD.r+8,PAD.t+li*18,12,3);
      X2.fillStyle='#E0E0E0';X2.font='9px monospace';X2.textAlign='left';
      X2.fillText(name,W2-PAD.r+24,PAD.t+li*18+4);
      li++;
    }});
    document.getElementById('progressBar').style.width=(progress*100)+'%';
  }}
  function loop(){{
    if(!playing)return;
    t=Math.min(1,t+0.006);draw(t);
    if(t>=1){{playing=false;document.getElementById('playBtn').textContent='↺ Replay';return;}}
    raf=requestAnimationFrame(loop);
  }}
  return{{
    toggle(){{if(t>=1)t=0;playing=!playing;
      document.getElementById('playBtn').textContent=playing?'⏸ Pause':'▶ Play';if(playing)loop();}},
    reset(){{t=0;playing=false;draw(0);document.getElementById('playBtn').textContent='▶ Play';}},
    step(){{t=Math.min(1,t+0.02);draw(t);}},
  }};
}})();
anim2.reset();
"""
    html = _html_wrap(
        f"V02 — PBPK Digital Twin | {drug_name}",
        f"6-compartment ODE simulation | Kp,brain={Kp:.5f} | Cmax_brain={Cmax_b:.5f} µg/mL",
        "c02", 860, 340, metrics, js)
    out = out_dir / f"V02_PBPK_{drug_name}.html"
    out.write_text(html, encoding='utf-8')
    return out


# ─────────────────────────────────────────────────────────────────────────────
def make_v03_release(drug_name: str, release: dict, top_dds: dict, out_dir: Path) -> Path:
    """V03: Drug Release Kinetics animation."""
    t_arr  = release.get("t_h", list(range(49))) or list(range(49))
    rb     = release.get("release_blood_pct", []) or []
    re_    = release.get("release_endo_pct", []) or []
    t50_b  = float(release.get("t50_blood_h", 17) or 17)
    t50_e  = float(release.get("t50_endosomal_h", 5) or 5)
    model  = str(release.get("release_order", "First-order"))
    max_ee = float(release.get("max_release_pct", 75) or 75)

    n = min(60, len(t_arr))
    idx = [int(i*(len(t_arr)-1)/(n-1)) for i in range(n)]
    t_s  = [round(t_arr[i],1) for i in idx]
    rb_s = [round(rb[i],2) if i<len(rb) else 0 for i in idx]
    re_s = [round(re_[i],2) if i<len(re_) else 0 for i in idx]
    # Also compute free drug curve
    fd_s = [round(max_ee*(1-math.exp(-0.25*t)),2) for t in t_s]

    metrics = f"""<div class="metrics">
  <div class="metric"><div class="metric-val">{t50_b:.1f}h</div><div class="metric-lbl">t50 (blood pH 7.4)</div></div>
  <div class="metric"><div class="metric-val">{t50_e:.1f}h</div><div class="metric-lbl">t50 (endosomal pH 5.5)</div></div>
  <div class="metric"><div class="metric-val">{model}</div><div class="metric-lbl">Release Model</div></div>
  <div class="metric"><div class="metric-val">{max_ee:.0f}%</div><div class="metric-lbl">Max EE Released</div></div>
</div>"""

    js = f"""
const C3=document.getElementById('c03');const X3=C3.getContext('2d');
const tArr3={json.dumps(t_s)};
const series3=[
  {{name:'In-DDS (blood)',data:{json.dumps(rb_s)},color:'#F57C00',dash:[]}},
  {{name:'Endosomal (pH 5.5)',data:{json.dumps(re_s)},color:'#7C4DFF',dash:[]}},
  {{name:'Free drug (no DDS)',data:{json.dumps(fd_s)},color:'#C62828',dash:[6,4]}},
];
const W3=C3.width,H3=C3.height,PAD3={{t:20,r:130,b:40,l:60}};
const pW=W3-PAD3.l-PAD3.r,pH3=H3-PAD3.t-PAD3.b;
const sX3=i=>PAD3.l+i/(tArr3.length-1)*pW;
const sY3=v=>PAD3.t+pH3-(v/100)*pH3;

const anim3=(function(){{
  let t=0,playing=false;
  function draw(p){{
    X3.fillStyle='#0a0a1a';X3.fillRect(0,0,W3,H3);
    X3.strokeStyle='#1F2937';X3.lineWidth=0.5;
    for(let i=0;i<=5;i++){{
      const y=PAD3.t+i*pH3/5;
      X3.beginPath();X3.moveTo(PAD3.l,y);X3.lineTo(W3-PAD3.r,y);X3.stroke();
      X3.fillStyle='#888';X3.font='9px monospace';X3.textAlign='right';
      X3.fillText((100-i*20)+'%',PAD3.l-4,y+3);
    }}
    for(let i=0;i<=6;i++){{
      const x=PAD3.l+i*pW/6;
      X3.beginPath();X3.moveTo(x,PAD3.t);X3.lineTo(x,H3-PAD3.b);X3.stroke();
      const tv=tArr3[Math.floor(i*(tArr3.length-1)/6)]||0;
      X3.fillStyle='#888';X3.textAlign='center';X3.fillText(tv.toFixed(0)+'h',x,H3-PAD3.b+14);
    }}
    X3.fillStyle='#C9A84C';X3.font='10px monospace';X3.textAlign='center';
    X3.fillText('Time (h)',W3/2,H3-4);
    X3.save();X3.translate(12,H3/2);X3.rotate(-Math.PI/2);
    X3.fillText('% Dose Released',0,0);X3.restore();
    const nPts=Math.max(2,Math.floor(p*tArr3.length));
    series3.forEach((s,li)=>{{
      if(nPts<2)return;
      X3.setLineDash(s.dash);
      X3.beginPath();X3.moveTo(sX3(0),sY3(s.data[0]));
      for(let i=1;i<nPts;i++) X3.lineTo(sX3(i),sY3(s.data[i]||0));
      X3.strokeStyle=s.color;X3.lineWidth=2;X3.stroke();X3.setLineDash([]);
      X3.fillStyle=s.color;X3.fillRect(W3-PAD3.r+8,PAD3.t+li*18,20,3);
      X3.fillStyle='#E0E0E0';X3.font='9px monospace';X3.textAlign='left';
      X3.fillText(s.name,W3-PAD3.r+32,PAD3.t+li*18+4);
    }});
    document.getElementById('progressBar').style.width=(p*100)+'%';
  }}
  function loop(){{
    if(!playing)return;t=Math.min(1,t+0.005);draw(t);
    if(t>=1){{playing=false;document.getElementById('playBtn').textContent='↺ Replay';return;}}
    requestAnimationFrame(loop);
  }}
  return{{
    toggle(){{if(t>=1)t=0;playing=!playing;
      document.getElementById('playBtn').textContent=playing?'⏸ Pause':'▶ Play';if(playing)loop();}},
    reset(){{t=0;playing=false;draw(0);document.getElementById('playBtn').textContent='▶ Play';}},
    step(){{t=Math.min(1,t+0.02);draw(t);}},
  }};
}})();
anim3.reset();
"""
    html = _html_wrap(
        f"V03 — Drug Release Kinetics | {drug_name}",
        f"Release model: {model} | t50 blood={t50_b:.1f}h | t50 endosomal={t50_e:.1f}h | In-DDS vs Endosomal vs Free Drug",
        "c03", 860, 320, metrics, js)
    out = out_dir / f"V03_Release_{drug_name}.html"
    out.write_text(html, encoding='utf-8')
    return out


# ─────────────────────────────────────────────────────────────────────────────
def make_v04_ranking(drug_name: str, df_dds_data: list[dict], top_dds: dict, out_dir: Path) -> Path:
    """V04: DDS Ranking animated bar chart."""
    if not df_dds_data:
        return None
    # df_dds_data's real field is Principle_Composite_Score --
    # "Composite_Score" never exists, so this always ranked and
    # displayed BBB_Engineering_Score instead (same bug already fixed
    # in final_report_unified.py, cerebro_science_modules.py,
    # cerebro_advanced_modules_2.py, and cerebro_html5_engine.py).
    top15 = sorted(df_dds_data, key=lambda x: float(x.get("Principle_Composite_Score") or x.get("BBB_Engineering_Score") or 0), reverse=True)[:15]
    names  = [d.get("Formulation_Name","?")[:18] for d in top15]
    scores = [round(float(d.get("Principle_Composite_Score") or d.get("BBB_Engineering_Score") or 0), 1) for d in top15]
    bbb    = [round(float(d.get("BBB_Enhanced_Pct") or 0), 1) for d in top15]
    carrs  = [d.get("Carrier_Type","DDS") for d in top15]
    carrier_colors = {"Vexosome":"#C9A84C","Lipid Nanoparticle":"#0D6E6E",
                       "Liposome":"#0D6E6E","Solid Lipid Nanoparticle":"#F57C00",
                       "Polymeric Nanoparticle":"#7C4DFF","Default":"#C9A84C"}
    colors = [carrier_colors.get(c, carrier_colors["Default"]) for c in carrs]

    top_name  = names[0] if names else "?"
    top_score = scores[0] if scores else 0

    metrics = f"""<div class="metrics">
  <div class="metric"><div class="metric-val" style="font-size:1em">{top_name}</div><div class="metric-lbl">Top DDS</div></div>
  <div class="metric"><div class="metric-val">{top_score}</div><div class="metric-lbl">Composite Score</div></div>
  <div class="metric"><div class="metric-val">{len(df_dds_data)}</div><div class="metric-lbl">DDS Evaluated</div></div>
  <div class="metric"><div class="metric-val">{bbb[0] if bbb else '?'}%</div><div class="metric-lbl">Top BBB Enh.</div></div>
</div>"""

    js = f"""
const C4=document.getElementById('c04');const X4=C4.getContext('2d');
const names4={json.dumps(names)};
const scores4={json.dumps(scores)};
const bbb4={json.dumps(bbb)};
const colors4={json.dumps(colors)};
const W4=C4.width,H4=C4.height;
const maxScore=Math.max(...scores4)*1.1||100;
const barH=Math.floor((H4-60)/names4.length)-2;

const anim4=(function(){{
  let t=0,playing=false;
  function draw(p){{
    X4.fillStyle='#0a0a1a';X4.fillRect(0,0,W4,H4);
    X4.fillStyle='#C9A84C';X4.font='bold 11px monospace';X4.textAlign='center';
    X4.fillText('DDS Composite Score Ranking',W4/2,16);
    const lPad=200,rPad=80;
    names4.forEach((n,i)=>{{
      const y=30+i*(barH+2);
      const bW=Math.max(0,(scores4[i]/maxScore)*(W4-lPad-rPad)*p);
      // Bar
      const grad=X4.createLinearGradient(lPad,0,lPad+bW,0);
      grad.addColorStop(0,colors4[i]);grad.addColorStop(1,colors4[i]+'44');
      X4.fillStyle=grad;X4.fillRect(lPad,y,bW,barH);
      // Name
      X4.fillStyle='#E0E0E0';X4.font=`${{Math.min(10,barH*0.65)}}px monospace`;X4.textAlign='right';
      X4.fillText(n,lPad-4,y+barH*0.65);
      // Score label
      if(bW>30){{
        X4.fillStyle='white';X4.textAlign='left';
        X4.fillText(scores4[i].toFixed(1),lPad+bW+4,y+barH*0.65);
      }}
      // Top 1 crown
      if(i===0&&p>0.5){{
        X4.fillStyle='#C9A84C';X4.font='12px monospace';X4.textAlign='right';
        X4.fillText('★ BEST',lPad+bW-2,y+barH*0.65);
      }}
    }});
    document.getElementById('progressBar').style.width=(p*100)+'%';
  }}
  function loop(){{
    if(!playing)return;t=Math.min(1,t+0.008);draw(t);
    if(t>=1){{playing=false;document.getElementById('playBtn').textContent='↺ Replay';return;}}
    requestAnimationFrame(loop);
  }}
  return{{
    toggle(){{if(t>=1)t=0;playing=!playing;
      document.getElementById('playBtn').textContent=playing?'⏸ Pause':'▶ Play';if(playing)loop();}},
    reset(){{t=0;playing=false;draw(0);document.getElementById('playBtn').textContent='▶ Play';}},
    step(){{t=Math.min(1,t+0.05);draw(t);}},
  }};
}})();
anim4.reset();
"""
    html = _html_wrap(
        f"V04 — DDS Ranking | {drug_name}",
        f"Top {len(top15)} DDS by Composite Score | Winner: {top_name} ({top_score})",
        "c04", 860, max(300, 30+len(names)*18), metrics, js)
    out = out_dir / f"V04_Ranking_{drug_name}.html"
    out.write_text(html, encoding='utf-8')
    return out


# ─────────────────────────────────────────────────────────────────────────────
def make_v05_biodist(drug_name: str, science: dict, top_dds: dict, out_dir: Path) -> Path:
    """V05: Biodistribution organ map animation."""
    bd = science.get("biodistribution_map", {}) or {}
    organs = bd.get("organs")
    if not organs:
        cns_ba  = float(top_dds.get("CNS_Bioavailability_Pct",12) or 12)
        liver   = float(top_dds.get("Off_Target_Liver_pct",25) or 25)
        spleen  = max(2.0, 25*(1-float(top_dds.get("Stealth_Index",0.5) or 0.5)))
        lung    = 3.0
        kidney  = 5.0
        blood   = max(1.0, 100.0 - cns_ba - liver - spleen - lung - kidney)
        total   = cns_ba + liver + spleen + lung + kidney + blood
        factor  = 100.0 / max(total, 1)
        organs = {
            "Brain (Target)": round(cns_ba * factor, 1),
            "Liver":          round(liver  * factor, 1),
            "Spleen":         round(spleen * factor, 1),
            "Lung":           round(lung   * factor, 1),
            "Kidney":         round(kidney * factor, 1),
            "Blood":          round(blood  * factor, 1),
        }
    organ_list = [(k, round(float(v), 1)) for k,v in organs.items()][:7]
    org_colors = ["#C9A84C","#F57C00","#7C4DFF","#C62828","#0D6E6E","#888","#0D6E6E"]
    ratio = bd.get("CNS_vs_offtarget_ratio","?")

    cns_val = next((v for k,v in organ_list if "Brain" in k or "CNS" in k), 10)

    metrics = f"""<div class="metrics">
  <div class="metric"><div class="metric-val">{cns_val:.1f}%</div><div class="metric-lbl">Brain (Target)</div></div>
  <div class="metric"><div class="metric-val">{ratio}</div><div class="metric-lbl">CNS/Off-target</div></div>
  <div class="metric"><div class="metric-val">{len(organ_list)}</div><div class="metric-lbl">Organs Modelled</div></div>
  <div class="metric"><div class="metric-val">in-silico</div><div class="metric-lbl">No animal studies</div></div>
</div>"""

    organ_js = json.dumps([[k,v] for k,v in organ_list])
    colors_js = json.dumps(org_colors[:len(organ_list)])

    js = f"""
const C5=document.getElementById('c05');const X5=C5.getContext('2d');
const W5=C5.width,H5=C5.height;
const organs5={organ_js};
const colors5={colors_js};
const cx5=W5*0.38,cy5=H5*0.5,R5=Math.min(W5,H5)*0.32;

const anim5=(function(){{
  let t=0,playing=false;
  function draw(p){{
    X5.fillStyle='#0a0a1a';X5.fillRect(0,0,W5,H5);
    // Donut chart
    let startAng=-Math.PI/2;
    const total=organs5.reduce((s,[,v])=>s+v,0)||100;
    organs5.forEach(([name,val],i)=>{{
      const sweep=(val/total)*Math.PI*2*p;
      X5.beginPath();X5.moveTo(cx5,cy5);
      X5.arc(cx5,cy5,R5,startAng,startAng+sweep);
      X5.fillStyle=colors5[i];X5.fill();
      // Label
      const midAng=startAng+sweep/2;
      if(sweep>0.2){{
        const lx=cx5+Math.cos(midAng)*(R5*0.65);
        const ly=cy5+Math.sin(midAng)*(R5*0.65);
        X5.fillStyle='white';X5.font='bold 9px monospace';X5.textAlign='center';
        X5.fillText(val.toFixed(1)+'%',lx,ly);
      }}
      startAng+=sweep;
    }});
    // Donut hole
    X5.beginPath();X5.arc(cx5,cy5,R5*0.45,0,Math.PI*2);
    X5.fillStyle='#0a0a1a';X5.fill();
    X5.fillStyle='#C9A84C';X5.font='bold 12px monospace';X5.textAlign='center';
    X5.fillText('ORGAN',cx5,cy5-6);X5.fillText('MAP',cx5,cy5+10);
    // Legend bars (right side)
    const lx5=W5*0.67;
    organs5.forEach(([name,val],i)=>{{
      const ly=40+i*34;
      const bw=(val/total)*200*p;
      X5.fillStyle=colors5[i];X5.fillRect(lx5,ly,bw,14);
      X5.fillStyle='#E0E0E0';X5.font='9px monospace';X5.textAlign='left';
      X5.fillText(name,lx5+Math.max(bw+4,4),ly+10);
      X5.fillStyle=colors5[i];X5.fillText(val.toFixed(1)+'%',lx5-36,ly+10);
    }});
    document.getElementById('progressBar').style.width=(p*100)+'%';
  }}
  function loop(){{
    if(!playing)return;t=Math.min(1,t+0.006);draw(t);
    if(t>=1){{playing=false;document.getElementById('playBtn').textContent='↺ Replay';return;}}
    requestAnimationFrame(loop);
  }}
  return{{
    toggle(){{if(t>=1)t=0;playing=!playing;
      document.getElementById('playBtn').textContent=playing?'⏸ Pause':'▶ Play';if(playing)loop();}},
    reset(){{t=0;playing=false;draw(0);document.getElementById('playBtn').textContent='▶ Play';}},
    step(){{t=Math.min(1,t+0.04);draw(t);}},
  }};
}})();
anim5.reset();
"""
    html = _html_wrap(
        f"V05 — Biodistribution | {drug_name}",
        f"In-silico organ distribution | CNS target: {cns_val:.1f}% | CNS/off-target ratio: {ratio} | No animal studies (3R principle)",
        "c05", 860, 300, metrics, js)
    out = out_dir / f"V05_Biodistrib_{drug_name}.html"
    out.write_text(html, encoding='utf-8')
    return out


# ─────────────────────────────────────────────────────────────────────────────
def run_all_canvas_videos(drug_name: str, top_dds: dict, df_dds_data: list[dict],
                            science: dict, out_dir: Path) -> dict[str, Path | None]:
    """Generate all 5 HTML5 Canvas animations."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results = {}
    pbpk = science.get("pbpk_cns", {}) or {}
    release = science.get("release", {}) or {}

    tasks = [
        ("V01_BBB",     lambda: make_v01_bbb(drug_name, top_dds, out_dir)),
        ("V02_PBPK",    lambda: make_v02_pbpk(drug_name, pbpk, out_dir)),
        ("V03_Release", lambda: make_v03_release(drug_name, release, top_dds, out_dir)),
        ("V04_Rank",    lambda: make_v04_ranking(drug_name, df_dds_data, top_dds, out_dir)),
        ("V05_Biodist", lambda: make_v05_biodist(drug_name, science, top_dds, out_dir)),
    ]
    for name, fn in tasks:
        try:
            p = fn()
            results[name] = p
            if p: log.info(f"[CANVAS] {name}: {p.stat().st_size//1024}KB ✅")
        except Exception as e:
            results[name] = None
            log.warning(f"[CANVAS] {name}: {e}")
    return results