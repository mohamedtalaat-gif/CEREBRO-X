"""
CEREBRO-X | VIDEO ENGINE v2  — Fixed MP4 generation using imageio v2 + ffmpeg
Created by: Muhammad Talaat -- CEREBRO-X
"""
import io
import logging
import math
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Rectangle

log = logging.getLogger("CEREBRO-VIDEO2")

C = {"bg":"#0a0a1a","panel":"#0a0a1a","navy":"#0f2040","teal":"#0D6E6E",
     "gold":"#C9A84C","orange":"#F57C00","purple":"#7C4DFF","green":"#0D6E6E",
     "red":"#C62828","blue":"#C9A84C","text":"#E0E0E0","sub":"#888888"}


def _frame(fig) -> bytes:
    buf = io.BytesIO()
    # Fixed size: do NOT use bbox_inches="tight" — causes variable frame size
    fig.savefig(buf, format="png", dpi=108, facecolor=C["bg"])
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _write_video(frames: list[bytes], out: Path, fps: int = 20) -> bool:
    """Write MP4 using imageio v2 + bundled ffmpeg.

    If `imageio_ffmpeg` is unavailable, the caller gets a clear actionable
    message instead of a cryptic ImportError — this happens when the image
    was built before `imageio-ffmpeg` was added to the Dockerfile and
    Docker Compose is reusing a cached layer.
    """
    try:
        import imageio.v2 as iio
        import imageio_ffmpeg  # noqa: F401 — required for FFMPEG writer
    except ImportError as e:
        log.error(
            "[Video] imageio_ffmpeg is missing — MP4 generation disabled. "
            "Recovery (in container):  pip install imageio-ffmpeg==0.5.1  "
            "Permanent fix: rebuild the image with --no-cache  "
            f"(import error: {e})"
        )
        return False

    try:
        imgs = [iio.imread(io.BytesIO(f)) for f in frames]
        writer = iio.get_writer(
            str(out), format="FFMPEG", mode="I", fps=fps,
            codec="libx264", pixelformat="yuv420p",
            output_params=["-crf", "20", "-preset", "fast"]
        )
        for img in imgs:
            writer.append_data(img)
        writer.close()
        size_kb = out.stat().st_size / 1024
        log.info(f"[Video] {out.name}: {size_kb:.0f} KB, {len(frames)} frames")
        return size_kb > 10  # true MP4 if > 10 KB
    except Exception as e:
        log.warning(f"[Video] Write failed: {e}")
        return False


def make_video_bbb(drug_name: str, top_dds: dict, out_dir: Path, fps=24, n=120) -> Path | None:
    """V01: BBB Crossing — 5 stage animated simulation."""
    out = out_dir / f"V01_BBB_Crossing_{drug_name}.mp4"
    bbb_enh = float(top_dds.get("BBB_Enhanced_Pct", 30))
    bbb_nat = float(top_dds.get("BBB_Native_Pct", 3))
    escape  = float(top_dds.get("Endosomal_Escape_Eff", 0.5))
    ligand  = str(top_dds.get("Surface_Ligand", "RVG29"))
    carrier = str(top_dds.get("Carrier_Type", "DDS"))
    size_nm = float(top_dds.get("size_nm", 80))

    stages = ["IV → Blood","Corona form.","BBB encounter","Transcytosis","Drug release"]
    frames = []
    for fi in range(n):
        t = fi / (n - 1)
        stage_idx = min(4, int(t * 5))
        stage_t   = (t * 5) % 1

        fig, axes = plt.subplots(1, 2, figsize=(13, 6), facecolor=C["bg"])
        fig.patch.set_facecolor(C["bg"])

        ax = axes[0]; ax.set_facecolor(C["bg"])
        ax.set_xlim(0, 10); ax.set_ylim(0, 8); ax.axis("off")

        # Blood vessel
        ax.add_patch(Rectangle((0,5.5),10,2.5, facecolor="#1A0808", alpha=0.9))
        ax.add_patch(Rectangle((0,5.5),10,1.2, facecolor="#C62828", alpha=0.3))

        # BBB
        ax.add_patch(Rectangle((0,4.8),10,0.6, facecolor="#0D6E6E", edgecolor="#0D6E6E", lw=1.5))
        ax.text(5, 5.08,"Blood-Brain Barrier", ha="center", color="#0D6E6E", fontsize=8.5, fontweight="bold")

        # Brain
        ax.add_patch(Rectangle((0,0),10,4.8, facecolor="#0a0a1a", alpha=0.9))
        # Neurons
        for nx,ny in [(2,2.5),(4,3.5),(6,2),(8,3)]:
            ax.add_patch(Circle((nx,ny), 0.35, facecolor="#0f2040", edgecolor="#C9A84C", lw=1.2))

        # NP trajectory
        if t < 0.2:  npx=1+stage_t*5; npy=6.5
        elif t < 0.4: npx=6;          npy=6.5-stage_t*1.8
        elif t < 0.6: npx=6;          npy=5.0-stage_t*0.4
        elif t < 0.8: npx=6;          npy=4.6-stage_t*2.5
        else:          npx=6;          npy=2.0

        # Protein corona
        if 0.1 < t < 0.5:
            cr = min(0.6, (t-0.1)*1.5)
            ax.add_patch(Circle((npx,npy), 0.5+cr, facecolor="none",
                                 edgecolor="#D4B563", lw=2.5, alpha=0.6, ls="--"))

        # NP body
        np_a = max(0, 1 - max(0, t-0.85)*8)
        if np_a > 0:
            ax.add_patch(Circle((npx,npy), 0.5*size_nm/100, facecolor=C["navy"],
                                 edgecolor=C["gold"], lw=2, alpha=np_a, zorder=5))
            ax.add_patch(Circle((npx,npy), 0.2*size_nm/100, facecolor=C["orange"],
                                 alpha=np_a*0.9, zorder=6))

        # Released drug particles in brain
        if t > 0.75:
            rng = np.random.default_rng(42)
            n_d = int((t-0.75)/0.25 * 20)
            for di in range(n_d):
                ang = rng.uniform(0, 2*math.pi)
                r   = rng.uniform(0.3, 1.5)
                dx  = 6 + r * math.cos(ang); dy = 2 + r * math.sin(ang)
                if 0 < dy < 4.5:
                    ax.add_patch(Circle((dx,dy), 0.08, facecolor=C["orange"], alpha=0.7, zorder=7))

        # Stage indicator
        ax.text(0.5, 7.6, f"Stage {stage_idx+1}/5: {stages[stage_idx]}",
                 color=C["gold"], fontsize=9, fontweight="bold")
        # Progress bar
        ax.add_patch(Rectangle((0.3,0.2), 9.4, 0.25, facecolor="#1F2937"))
        ax.add_patch(Rectangle((0.3,0.2), 9.4*t, 0.25, facecolor=C["teal"]))

        # Right panel: metrics
        ax2 = axes[1]; ax2.set_facecolor(C["panel"]); ax2.axis("off")
        ax2.set_title(f"{carrier} + {ligand}", color=C["gold"], fontweight="bold", fontsize=11)
        metrics = [
            ("Drug", drug_name[:20]),
            ("Carrier", carrier),
            ("Ligand", ligand),
            ("Size", f"{size_nm:.0f} nm"),
            ("BBB Native", f"{bbb_nat:.1f}%"),
            ("BBB Enhanced", f"{bbb_enh:.1f}%"),
            ("Enhancement", f"{bbb_enh/max(bbb_nat,0.1):.1f}×"),
            ("Endo.Escape", f"{escape*100:.0f}%"),
            ("Stage", f"{stage_idx+1}/5"),
        ]
        for i, (k, v) in enumerate(metrics):
            col = C["gold"] if k in ["BBB Enhanced","Enhancement"] else C["text"]
            ax2.text(0.05, 0.90-i*0.095, f"{k}:", transform=ax2.transAxes,
                      color=C["sub"], fontsize=9)
            ax2.text(0.5, 0.90-i*0.095, v, transform=ax2.transAxes,
                      color=col, fontsize=9, fontweight="bold")

        fig.suptitle(f"CEREBRO-X  |  BBB Crossing Simulation  |  {drug_name}",
                      color=C["gold"], fontsize=11, fontweight="bold")
        frames.append(_frame(fig))

    frames.extend([frames[-1]] * fps)
    success = _write_video(frames, out, fps)
    return out if success else None


def make_video_pbpk(pbpk: dict, drug_name: str, top_dds: dict,
                     out_dir: Path, fps=20, n=80) -> Path | None:
    """V02: PBPK 6-compartment animated time course."""
    out = out_dir / f"V02_PBPK_{drug_name}.mp4"
    if not pbpk or pbpk.get("error"): return None

    t    = np.array(pbpk.get("t_h", []))
    Cp   = np.array(pbpk.get("C_plasma", []))
    Cisf = np.array(pbpk.get("C_brain_ISF", []))
    Ccsf = np.array(pbpk.get("C_CSF", []))
    Cmax = pbpk.get("Cmax_brain_ug_mL", 0)
    Kp   = pbpk.get("Kp_brain", 0)
    carrier = str(top_dds.get("Carrier_Type", "DDS"))

    if len(t) < 2: return None

    frames = []
    idxs = np.linspace(0, len(t)-1, n).astype(int)

    for fi, idx in enumerate(idxs):
        fig, ax = plt.subplots(figsize=(12, 6), facecolor=C["bg"])
        ax.set_facecolor(C["panel"])

        ax.fill_between(t, Cp, alpha=0.08, color=C["orange"])
        ax.fill_between(t, Cisf, alpha=0.12, color=C["blue"])

        ax.plot(t, Cp, color=C["orange"], lw=2.5, label="Plasma")
        ax.plot(t, Cisf, color=C["blue"], lw=2.5, label="Brain ISF")
        ax.plot(t, Ccsf, color=C["purple"], lw=1.8, ls="--", label="CSF")

        # Cursor
        ax.axvline(t[idx], color="white", lw=1, ls="--", alpha=0.4)
        ax.scatter([t[idx]], [Cisf[idx]], color=C["blue"], s=80, zorder=10)
        ax.scatter([t[idx]], [Cp[idx]], color=C["orange"], s=60, zorder=10)

        ax.set_xlabel("Time (hours)", color=C["text"])
        ax.set_ylabel("Concentration (µg/mL)", color=C["text"])
        ax.set_title(f"PBPK-CNS Digital Twin  |  {drug_name} + {carrier}  |  "
                      f"t={t[idx]:.1f}h  Kp={Kp:.5f}", color=C["gold"], fontweight="bold")
        ax.tick_params(colors=C["text"])
        ax.legend(fontsize=9, facecolor=C["panel"], labelcolor=C["text"])
        ax.spines[:].set_color("#1F2937")

        ax.text(0.98, 0.95, f"Cmax_brain = {Cmax:.4f} µg/mL",
                 transform=ax.transAxes, ha="right", color=C["gold"], fontsize=9.5)
        frames.append(_frame(fig))

    frames.extend([frames[-1]] * fps)
    return out if _write_video(frames, out, fps) else None


def make_video_release(release: dict, drug_name: str, top_dds: dict,
                        out_dir: Path, fps=20, n=70) -> Path | None:
    """V03: Drug release kinetics animation."""
    out = out_dir / f"V03_Release_{drug_name}.mp4"
    if not release or release.get("error"): return None

    t   = np.array(release.get("t_h", []))
    rb  = np.array(release.get("release_blood_pct", []))
    re  = np.array(release.get("release_endo_pct", []))
    t50 = release.get("t50_blood_h", 0)
    model= release.get("release_model","")
    ee  = release.get("max_release_pct", 75)
    carrier = str(top_dds.get("Carrier_Type","DDS"))

    frames = []
    idxs = np.linspace(0, len(t)-1, n).astype(int)

    for fi, idx in enumerate(idxs):
        fig, ax = plt.subplots(figsize=(12, 6), facecolor=C["bg"])
        ax.set_facecolor(C["panel"])

        ax.plot(t[:idx+1], rb[:idx+1], color=C["orange"], lw=2.5, label="Blood (pH 7.4)")
        ax.plot(t[:idx+1], re[:idx+1], color=C["purple"], lw=2.5, label="Endosomal (pH 5.5)")
        ax.axhline(ee, color=C["gold"], ls="--", lw=1.2, alpha=0.6, label=f"Max EE ({ee:.0f}%)")
        ax.axvline(t50, color=C["red"], ls=":", lw=1.2, alpha=0.5, label=f"t50={t50:.1f}h")

        ax.set_xlim(0, t[-1]); ax.set_ylim(0, 105)
        ax.set_xlabel("Time (hours)", color=C["text"])
        ax.set_ylabel("Drug Released (%)", color=C["text"])
        ax.set_title(f"Drug Release Profile  |  {drug_name} from {carrier}  |  "
                      f"Model: {model}  t={t[idx]:.1f}h", color=C["gold"], fontweight="bold")
        ax.tick_params(colors=C["text"])
        ax.legend(fontsize=9, facecolor=C["panel"], labelcolor=C["text"])
        ax.spines[:].set_color("#1F2937")
        frames.append(_frame(fig))

    frames.extend([frames[-1]] * fps)
    return out if _write_video(frames, out, fps) else None


def make_video_ranking(df_data: list[dict], drug_name: str,
                        out_dir: Path, fps=20) -> Path | None:
    """V04: DDS ranking reveal animation."""
    out = out_dir / f"V04_DDS_Ranking_{drug_name}.mp4"
    if not df_data: return None

    # df_data's real field is Principle_Composite_Score --
    # "Composite_Score" never exists as a key, so this always fell
    # through to BBB_Engineering_Score (same bug already fixed in
    # final_report_unified.py, cerebro_science_modules.py,
    # cerebro_advanced_modules_2.py, cerebro_html5_engine.py, and
    # cerebro_canvas_engine.py).
    score_key = ("Principle_Composite_Score"
                 if any("Principle_Composite_Score" in d for d in df_data)
                 else "BBB_Engineering_Score")
    top = sorted(df_data, key=lambda d: float(d.get(score_key,0) or 0), reverse=True)[:15]
    names  = [d.get("Formulation_Name","?")[:22] for d in top]
    scores = [float(d.get(score_key,0) or 0) for d in top]
    carrier_colors = {"Vexosome":"#0f2040","Liposome":"#0D6E6E",
                      "Solid Lipid Nanoparticle":"#C9A84C","Polymeric Nanoparticle":"#7C4DFF"}
    colors = [carrier_colors.get(d.get("Carrier_Type",""),"#C9A84C") for d in top]

    frames = []
    n_reveal = 50; hold = 20
    for fi in range(n_reveal + hold):
        t = min(fi / n_reveal, 1.0)
        n_show = max(1, int(t * len(scores)))

        fig, ax = plt.subplots(figsize=(12, 7), facecolor=C["bg"])
        ax.set_facecolor(C["bg"])

        shown_s = scores[-n_show:][::-1]
        shown_n = names[-n_show:][::-1]
        shown_c = colors[-n_show:][::-1]

        bars = ax.barh(range(len(shown_s)), shown_s, color=shown_c,
                        edgecolor="white", height=0.7, linewidth=0.8)
        for bar, sc in zip(bars, shown_s):
            ax.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height()/2,
                     f"{sc:.1f}", va="center", color=C["gold"], fontsize=9, fontweight="bold")

        ax.set_yticks(range(len(shown_n)))
        ax.set_yticklabels(shown_n, color=C["text"], fontsize=9)
        ax.set_xlabel("Composite Score", color=C["text"])
        ax.set_xlim(0, max(scores) * 1.12)
        ax.tick_params(colors=C["text"]); ax.spines[:].set_color("#1F2937")

        if n_show == len(scores):
            ax.barh([len(scores)-1], [scores[0]], color=C["gold"], alpha=0.25, height=0.7)
            ax.text(scores[0]/2, len(scores)-1, "★ #1 RECOMMENDED",
                     ha="center", va="center", color="white", fontsize=10, fontweight="bold")

        ax.set_title(f"CEREBRO-X  |  DDS Ranking  |  {drug_name}  |  "
                      f"{n_show}/{len(scores)} formulations", color=C["gold"], fontweight="bold")
        frames.append(_frame(fig))

    return out if _write_video(frames, out, fps) else None


def make_video_biodistrib(top_dds: dict, drug_name: str,
                           out_dir: Path, fps=20, n=60) -> Path | None:
    """V05: Organ biodistribution animated pie."""
    out = out_dir / f"V05_Biodistrib_{drug_name}.mp4"
    cns   = float(top_dds.get("CNS_Bioavailability_Pct", 10))
    liver = float(top_dds.get("Off_Target_Liver_pct", 30))
    stealth = float(top_dds.get("Stealth_Index", 0.5))
    carrier = str(top_dds.get("Carrier_Type","DDS"))

    spleen = max(2.0, 30-stealth*20)
    lung, kidney, other = 3.0, 5.0, 5.0
    blood = max(1.0, 100.0 - cns - liver - spleen - lung - kidney - other)
    organs = {"Brain\n(Target)": cns, "Liver": liver,
              "Spleen": spleen, "Lung": lung, "Kidney": kidney,
              "Blood": blood, "Other": other}
    org_colors = {"Brain\n(Target)": C["blue"], "Liver": C["orange"],
                  "Spleen": C["purple"], "Lung": C["teal"],
                  "Kidney": C["green"], "Blood": C["red"], "Other": C["sub"]}

    frames = []
    for fi in range(n+20):
        t = min(fi/n, 1.0)
        vals = [max(0.01, v*t) for v in organs.values()]
        total = sum(vals)
        vals = [v/total*100 for v in vals]

        fig, axes = plt.subplots(1, 2, figsize=(13, 6.5), facecolor=C["bg"])
        fig.patch.set_facecolor(C["bg"])
        fig.subplots_adjust(left=0.05, right=0.95, top=0.88, bottom=0.08)

        axes[0].set_facecolor(C["bg"])
        # ax.pie()'s return type isn't stable across matplotlib versions:
        # older versions return a plain (wedges, texts[, autotexts]) tuple,
        # newer ones (matplotlib >= 3.11 here) return a PieContainer that
        # supports indexing/unpacking but not len() -- so len(_pie_r) used
        # to raise TypeError on every single call, meaning this video was
        # never actually produced on this environment's matplotlib version.
        # Star-unpacking works against both return shapes.
        _pie_wedges, _pie_txts, *_pie_rest = axes[0].pie(
            vals, labels=list(organs.keys()),
            colors=[org_colors[k] for k in organs],
            autopct="%1.1f%%" if t>0.5 else None,
            wedgeprops={"edgecolor":C["bg"],"linewidth":2},
            explode=[0.12 if k == "Brain\n(Target)" else 0 for k in organs],
        )
        _pie_apct = _pie_rest[0] if _pie_rest else []
        for _t in _pie_txts: _t.set_color(C["text"]); _t.set_fontsize(9)
        for _a in _pie_apct: _a.set_color("white"); _a.set_fontsize(8)
        axes[0].set_title("Organ Biodistribution (%dose)", color=C["gold"], fontweight="bold")

        axes[1].set_facecolor(C["panel"])
        axes[1].bar(["CNS (Target)","Off-target"],
                     [cns*t, (liver+15)*t],
                     color=[C["blue"], C["orange"]], edgecolor="white", width=0.5)
        axes[1].set_ylim(0, max(liver+20, 50))
        axes[1].set_ylabel("% Dose", color=C["text"])
        axes[1].set_title(f"CNS vs Off-target  |  t={t*24:.0f}h",
                            color=C["gold"], fontweight="bold")
        axes[1].tick_params(colors=C["text"]); axes[1].spines[:].set_color("#1F2937")

        fig.suptitle(f"CEREBRO-X  |  Biodistribution  |  {carrier}  |  {drug_name}",
                      color=C["gold"], fontsize=11, fontweight="bold")
        frames.append(_frame(fig))

    return out if _write_video(frames, out, fps) else None


def run_all_videos(drug_name: str, top_dds: dict, df_dds_data: list[dict],
                    science: dict, out_dir: Path, fps: int = 24) -> dict:
    """Generate all videos. Returns dict of {name: path}."""
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    results = {}

    tasks = [
        ("V01_BBB",   lambda: make_video_bbb(drug_name, top_dds, out_dir, fps)),
        ("V02_PBPK",  lambda: make_video_pbpk(science.get("pbpk_cns",{}), drug_name, top_dds, out_dir)),
        ("V03_Release",lambda: make_video_release(science.get("release",{}), drug_name, top_dds, out_dir)),
        ("V04_Rank",  lambda: make_video_ranking(df_dds_data, drug_name, out_dir)),
        ("V05_Biodist",lambda: make_video_biodistrib(top_dds, drug_name, out_dir)),
    ]
    for name, fn in tasks:
        try:
            p = fn()
            results[name] = p
            log.info(f"[Video] {name}: {'OK' if p else 'SKIP'}")
        except Exception as e:
            log.warning(f"[Video] {name}: {e}")
            results[name] = None

    n_ok = sum(1 for v in results.values() if v)
    log.info(f"[VIDEO] Done: {n_ok}/{len(results)} videos generated")
    return results