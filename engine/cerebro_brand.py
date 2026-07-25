"""
CEREBRO-X  —  Brand & Visual Identity (Single Source of Truth)
================================================================
Centralized colour palette, typography spec, asset paths, and helper
adapters for matplotlib / reportlab / openpyxl / Plotly.

DESIGN PHILOSOPHY
─────────────────
The CEREBRO-X aesthetic is "Deep-Space + Signature Gold":

  • Three layers of darkness create visual hierarchy:
        Layer 1 — Deepest Void   #060610   (page background)
        Layer 2 — Elevated Base  #0a0a1a   (section containers)
        Layer 3 — Panel Color    #0f2040   (data cards, tables)

  • Signature Gold (#C9A84C) — the ONLY accent colour for titles,
    interactive states, and brand mark. Its variants form a complete
    interaction vocabulary (light = hover, dark = pressed, glow = focus).

  • Functional palette — narrow, intentional, scientifically meaningful:
        Neuro-Positive  #0D6E6E  — success / high BBB scores
        Alert Red       #C62828  — warnings / biologics
        Molecule Orange #F57C00  — small-molecule tagging

  • Typography — Inter (200–900). Tight tracking on hero headings,
    wide tracking on section headers, generous line-height on body.

Every output generator (PDFs, HTML, Matplotlib, Plotly, Excel, video)
MUST import from this module rather than hard-coding hex values.

Created by: Muhammad Talaat (BPharm, R&D Computational Lead)
"""
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════════
# 1.  COLOR PALETTE  (hex strings — for matplotlib, reportlab, CSS, etc.)
# ═══════════════════════════════════════════════════════════════════════════

# ── The Void: three layers of darkness ─────────────────────────────────────
VOID_BASE       = "#060610"   # deepest canvas (page background)
VOID_ELEVATED   = "#0a0a1a"   # secondary containers
VOID_PANEL      = "#0f2040"   # data containers, tables, cards

# ── Signature Gold: the ONE accent colour ──────────────────────────────────
GOLD            = "#C9A84C"   # primary — titles, brand mark, primary buttons
GOLD_LIGHT      = "#D4B563"   # hover state
GOLD_DARK       = "#B89A3F"   # pressed/active state
GOLD_GLOW_RGBA  = "rgba(201, 168, 76, 0.55)"  # focus halos / shadows
GOLD_GLOW_HEX8  = "#C9A84C8C"                  # ≈55% alpha as 8-digit hex

# ── Functional colours (narrow set, scientifically meaningful) ─────────────
NEURO_POSITIVE  = "#0D6E6E"   # success, BBB-positive
ALERT_RED       = "#C62828"   # warnings, biologics, danger
MOLECULE_ORANGE = "#F57C00"   # small-molecule drug tagging

# ── Neutral text on dark backgrounds ───────────────────────────────────────
TEXT_PRIMARY    = "#E0E0E0"   # body text on void
TEXT_SECONDARY  = "#9CA3AF"   # captions, metadata
TEXT_MUTED      = "#6B7280"   # timestamps, disclaimers
HAIRLINE        = "#1F2937"   # 1px borders on dark surfaces

# ── Convenience: matplotlib-friendly dicts ─────────────────────────────────
PALETTE = {
    "void":             VOID_BASE,
    "void_elevated":    VOID_ELEVATED,
    "void_panel":       VOID_PANEL,
    "gold":             GOLD,
    "gold_light":       GOLD_LIGHT,
    "gold_dark":        GOLD_DARK,
    "neuro_positive":   NEURO_POSITIVE,
    "teal":             NEURO_POSITIVE,    # alias
    "alert":            ALERT_RED,
    "molecule":         MOLECULE_ORANGE,
    "orange":           MOLECULE_ORANGE,   # alias
    "text":             TEXT_PRIMARY,
    "text_secondary":   TEXT_SECONDARY,
    "text_muted":       TEXT_MUTED,
    "hairline":         HAIRLINE,
}

# ── Sequential ramp for heatmaps / gradient charts (low → high) ────────────
# Goes from alert-red (poor) → muted neutral → gold (good) → teal (excellent)
SEQUENTIAL_RAMP = [
    "#C62828",   # 0.00  red — failure
    "#E97A2C",   # 0.25  orange — below target
    "#C9A84C",   # 0.50  gold — neutral / at target
    "#5BA89B",   # 0.75  teal-light — good
    "#0D6E6E",   # 1.00  teal — excellent
]

# ── Categorical palette for bar/scatter charts ─────────────────────────────
CATEGORICAL = [GOLD, NEURO_POSITIVE, MOLECULE_ORANGE, "#7C4DFF",
               "#5BA89B", ALERT_RED, GOLD_LIGHT, "#4A6FE3"]


# ═══════════════════════════════════════════════════════════════════════════
# 2.  TYPOGRAPHY  (Inter family — fall-backs for non-web outputs)
# ═══════════════════════════════════════════════════════════════════════════

FONT_FAMILY     = "Inter, 'Segoe UI', Helvetica, Arial, sans-serif"
FONT_HERO       = ("Inter", 900, -1.0)        # (family, weight, letter-spacing px)
FONT_H1         = ("Inter", 800, -0.5)
FONT_H2         = ("Inter", 700, -0.3)
FONT_SECTION    = ("Inter", 600, 2.0)         # wide tracking for section headers
FONT_BODY       = ("Inter", 400, 0.0)
FONT_CAPTION    = ("Inter", 300, 0.5)

# Reportlab fallbacks (Inter not available in stock reportlab → Helvetica)
RL_FONT_TITLE   = "Helvetica-Bold"
RL_FONT_BODY    = "Helvetica"
RL_FONT_MONO    = "Courier"


# ═══════════════════════════════════════════════════════════════════════════
# 3.  ASSET PATHS  (resolved relative to the project root)
# ═══════════════════════════════════════════════════════════════════════════

_PROJECT_ROOT   = Path(__file__).resolve().parent
ASSETS_DIR      = _PROJECT_ROOT / "assets" / "brand"
LOGO_PATH       = ASSETS_DIR / "cerebro_logo.png"
PATTERN_PATH    = ASSETS_DIR / "cerebro_pattern.png"
ENGINE_BG_PATH  = ASSETS_DIR / "cerebro_engine_bg.png"


# ═══════════════════════════════════════════════════════════════════════════
# 4.  ADAPTERS  (helpers that emit framework-specific objects)
# ═══════════════════════════════════════════════════════════════════════════

def reportlab_color(hex_str: str):
    """Return a reportlab.lib.colors.Color from a hex string."""
    from reportlab.lib import colors as _rlcol
    return _rlcol.HexColor(hex_str)


def register_brand_fonts(verbose: bool = False) -> dict:
    """
    Register Inter / Liberation Sans with matplotlib's font_manager so the
    canonical brand typography is *actually* available — not just listed
    in `font.family`.

    On Linux containers, the system can have `fonts-inter` installed
    (visible to fontconfig via `fc-list`) yet matplotlib still emits
    "Font family 'Inter' not found" warnings. The reason: matplotlib has
    its OWN font cache (`~/.cache/matplotlib/fontlist-*.json`). Files
    added to the system AFTER that cache was built are invisible to
    matplotlib until the cache is rebuilt.

    This helper:
      1. Walks well-known font directories looking for Inter / Liberation.
      2. Calls `font_manager.fontManager.addfont()` for every Inter*.ttf
         / Liberation*.ttf file it finds — bypassing the cache entirely.
      3. Returns a dict telling the caller which fonts are now registered.

    Usage:
        from cerebro_brand import register_brand_fonts, matplotlib_style
        register_brand_fonts()             # do this BEFORE matplotlib_style
        plt.rcParams.update(matplotlib_style())
    """
    import os
    try:
        from matplotlib import font_manager as _fm
    except ImportError:
        return {"inter": False, "liberation": False, "reason": "matplotlib missing"}

    # Standard font directories on Debian/Ubuntu/macOS/Windows
    candidate_dirs = [
        "/usr/share/fonts/truetype/inter",
        "/usr/share/fonts/opentype/inter",
        "/usr/share/fonts/truetype/liberation",
        "/usr/share/fonts/truetype/liberation2",
        "/usr/share/fonts/TTF",
        "/usr/local/share/fonts",
        "/Library/Fonts",
        "/System/Library/Fonts",
        os.path.expanduser("~/.fonts"),
        os.path.expanduser("~/Library/Fonts"),
        os.environ.get("WINDIR", "") + "/Fonts" if os.name == "nt" else "",
    ]
    inter_added = 0
    liberation_added = 0
    for d in candidate_dirs:
        if not d or not os.path.isdir(d):
            continue
        for root, _, files in os.walk(d):
            for fn in files:
                low = fn.lower()
                if not (low.endswith(".ttf") or low.endswith(".otf")):
                    continue
                p = os.path.join(root, fn)
                try:
                    if "inter" in low:
                        _fm.fontManager.addfont(p)
                        inter_added += 1
                    elif "liberation" in low and "sans" in low:
                        _fm.fontManager.addfont(p)
                        liberation_added += 1
                except Exception:
                    continue

    # Re-check what's actually registered now
    available = {f.name for f in _fm.fontManager.ttflist}
    inter_ok      = any(n.lower().startswith("inter") for n in available)
    liberation_ok = any(n.lower().startswith("liberation") for n in available)

    if verbose:
        print(f"[BRAND-FONTS] Inter files added: {inter_added}, "
              f"Liberation files added: {liberation_added}")
        print(f"[BRAND-FONTS] Inter detected: {inter_ok}, "
              f"Liberation detected: {liberation_ok}")

    return {"inter": inter_ok, "liberation": liberation_ok,
            "inter_files": inter_added, "liberation_files": liberation_added}


def matplotlib_style() -> dict:
    """
    Returns a dict suitable for `plt.rcParams.update(matplotlib_style())`.
    Applies the deep-space dark theme + Inter-family fallback typography.

    Note: call `register_brand_fonts()` BEFORE applying this style if you
    want Inter actually used. Without that, matplotlib falls back to
    Liberation Sans (a Helvetica metric-equivalent) or DejaVu Sans —
    both produce correct output, just with slightly different glyph
    metrics than Inter.
    """
    return {
        "figure.facecolor":   VOID_BASE,
        "axes.facecolor":     VOID_PANEL,
        "axes.edgecolor":     HAIRLINE,
        "axes.labelcolor":    TEXT_PRIMARY,
        "axes.titlecolor":    GOLD,
        "axes.titleweight":   "bold",
        "axes.titlesize":     13,
        "axes.labelsize":     10,
        "xtick.color":        TEXT_SECONDARY,
        "ytick.color":        TEXT_SECONDARY,
        "grid.color":         HAIRLINE,
        "grid.alpha":         0.6,
        "text.color":         TEXT_PRIMARY,
        "font.family":        ["Inter", "Liberation Sans", "DejaVu Sans", "sans-serif"],
        "font.size":          10,
        "legend.facecolor":   VOID_ELEVATED,
        "legend.edgecolor":   HAIRLINE,
        "legend.labelcolor":  TEXT_PRIMARY,
        "savefig.facecolor":  VOID_BASE,
        "savefig.edgecolor":  "none",
        "savefig.dpi":        150,
    }


def html_css_block() -> str:
    """
    Returns the canonical CSS block to embed in any standalone HTML
    output (dashboards, reports, comparison pages). Provides:
      - CSS variables matching the design tokens
      - body / h1 / h2 / table baseline styling
      - glass-panel utility class
      - report-card utility class
      - Inter font import
    """
    return f"""<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@200;300;400;500;600;700;800;900&display=swap');

:root {{
  --void-base:       {VOID_BASE};
  --void-elevated:   {VOID_ELEVATED};
  --void-panel:      {VOID_PANEL};
  --gold:            {GOLD};
  --gold-light:      {GOLD_LIGHT};
  --gold-dark:       {GOLD_DARK};
  --gold-glow:       {GOLD_GLOW_RGBA};
  --neuro-positive:  {NEURO_POSITIVE};
  --alert-red:       {ALERT_RED};
  --molecule-orange: {MOLECULE_ORANGE};
  --text-primary:    {TEXT_PRIMARY};
  --text-secondary:  {TEXT_SECONDARY};
  --text-muted:      {TEXT_MUTED};
  --hairline:        {HAIRLINE};
}}

* {{ box-sizing: border-box; }}

body {{
  font-family: {FONT_FAMILY};
  background: var(--void-base);
  color: var(--text-primary);
  margin: 0;
  padding: 32px 40px;
  font-weight: 300;
  line-height: 1.65;
  letter-spacing: 0.01em;
}}

h1, h2, h3, h4 {{
  color: var(--gold);
  font-weight: 700;
  letter-spacing: -0.3px;
  margin: 16px 0 8px;
}}
h1 {{ font-size: 2.0em; font-weight: 800; letter-spacing: -0.6px; }}
h2 {{ font-size: 1.35em; border-bottom: 1px solid var(--hairline); padding-bottom: 6px; }}
h3 {{ font-size: 1.1em; color: var(--gold-light); }}

a {{ color: var(--gold); text-decoration: none; border-bottom: 1px solid var(--gold-glow); }}
a:hover {{ color: var(--gold-light); border-bottom-color: var(--gold-light); }}

.brand-header {{
  background: linear-gradient(135deg, var(--void-panel) 0%, var(--void-elevated) 100%);
  border: 1px solid var(--hairline);
  border-radius: 12px;
  padding: 28px 32px;
  margin-bottom: 24px;
  text-align: center;
}}
.brand-header .title {{
  font-size: 2.2em;
  font-weight: 800;
  color: var(--gold);
  letter-spacing: -0.6px;
  margin: 0;
}}
.brand-header .subtitle {{
  color: var(--text-secondary);
  font-size: 0.95em;
  margin-top: 6px;
}}
.brand-header .meta {{
  color: var(--text-muted);
  font-size: 0.8em;
  margin-top: 10px;
}}

.glass-panel, .card {{
  background: rgba(15, 32, 64, 0.6);
  backdrop-filter: blur(24px);
  -webkit-backdrop-filter: blur(24px);
  border: 1px solid var(--hairline);
  border-radius: 12px;
  padding: 20px 24px;
  margin: 16px 0;
  box-shadow: 0 8px 32px rgba(0,0,0,0.4);
}}

.metric-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px;
  margin: 16px 0;
}}
.metric {{
  background: var(--void-panel);
  border: 1px solid var(--hairline);
  border-radius: 10px;
  padding: 14px;
  text-align: center;
}}
.metric .val {{
  font-size: 1.8em;
  font-weight: 800;
  color: var(--gold);
  letter-spacing: -0.5px;
}}
.metric .lbl {{
  font-size: 0.75em;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 1.5px;
  margin-top: 4px;
}}

table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9em;
  margin: 12px 0;
}}
thead th {{
  background: var(--void-panel);
  color: var(--gold);
  text-align: left;
  padding: 10px 14px;
  font-weight: 600;
  letter-spacing: 0.5px;
  border-bottom: 2px solid var(--gold);
}}
tbody td {{
  padding: 9px 14px;
  border-bottom: 1px solid var(--hairline);
  color: var(--text-primary);
}}
tbody tr:hover {{ background: rgba(201, 168, 76, 0.05); }}

.badge-success {{ background: var(--neuro-positive); color: white; padding: 3px 10px; border-radius: 4px; font-size: 0.78em; }}
.badge-warning {{ background: var(--molecule-orange); color: white; padding: 3px 10px; border-radius: 4px; font-size: 0.78em; }}
.badge-danger  {{ background: var(--alert-red);      color: white; padding: 3px 10px; border-radius: 4px; font-size: 0.78em; }}

.footer {{
  text-align: center;
  color: var(--text-muted);
  font-size: 0.78em;
  margin-top: 32px;
  padding-top: 16px;
  border-top: 1px solid var(--hairline);
  letter-spacing: 0.5px;
}}
</style>"""


def html_brand_header(title: str, subtitle: str = "", meta: str = "") -> str:
    """
    Standardized HTML page header. The visible TITLE is just the project
    name ("CEREBRO-X") — version goes in the meta line if at all.

    Args:
        title:    main heading shown in gold (e.g. "Drug Delivery Report")
        subtitle: secondary line in muted grey (e.g. drug name)
        meta:    timestamp / version / file info line in dim grey

    Returns: an HTML block ready to drop after <body>.
    """
    parts = [
        '<div class="brand-header">',
        f'  <div class="title">{PROJECT_NAME}</div>',
    ]
    if title and title.strip().lower() not in ("cerebro-x", PROJECT_NAME.lower()):
        parts.append(f'  <div class="subtitle">{title}</div>')
    if subtitle:
        parts.append(f'  <div class="subtitle">{subtitle}</div>')
    if meta:
        parts.append(f'  <div class="meta">{meta}</div>')
    parts.append('</div>')
    return "\n".join(parts)


# Project name re-exported here so callers can do
#   `from cerebro_brand import PROJECT_NAME, GOLD, ...`
# in one import.
try:
    from _version import (
        AUTHOR,
        CITATION,
        COPYRIGHT,
        PROJECT_NAME,
        PROJECT_TITLE_FULL,
        PROJECT_VERSION,
        footer_line,
    )
except ImportError:
    # Defensive fallback so this module imports cleanly even if _version
    # is somehow unreachable.
    PROJECT_NAME       = "CEREBRO-X"
    PROJECT_VERSION    = "22.1"
    PROJECT_TITLE_FULL = "CEREBRO-X"
    AUTHOR             = "Muhammad Talaat"
    CITATION           = "Talaat M (2026) CEREBRO-X."
    COPYRIGHT          = "© 2024–2026  Muhammad Talaat  |  CEREBRO-X"
    def footer_line() -> str:
        return "CEREBRO-X |  Muhammad Talaat"


__all__ = [
    # Colors
    "VOID_BASE", "VOID_ELEVATED", "VOID_PANEL",
    "GOLD", "GOLD_LIGHT", "GOLD_DARK", "GOLD_GLOW_RGBA", "GOLD_GLOW_HEX8",
    "NEURO_POSITIVE", "ALERT_RED", "MOLECULE_ORANGE",
    "TEXT_PRIMARY", "TEXT_SECONDARY", "TEXT_MUTED", "HAIRLINE",
    "PALETTE", "SEQUENTIAL_RAMP", "CATEGORICAL",
    # Typography
    "FONT_FAMILY", "FONT_HERO", "FONT_H1", "FONT_H2",
    "FONT_SECTION", "FONT_BODY", "FONT_CAPTION",
    "RL_FONT_TITLE", "RL_FONT_BODY", "RL_FONT_MONO",
    # Assets
    "ASSETS_DIR", "LOGO_PATH", "PATTERN_PATH", "ENGINE_BG_PATH",
    # Adapters
    "reportlab_color", "matplotlib_style", "html_css_block", "html_brand_header",
    # Re-exports
    "PROJECT_NAME", "PROJECT_VERSION", "PROJECT_TITLE_FULL",
    "AUTHOR", "CITATION", "COPYRIGHT", "footer_line",
]
