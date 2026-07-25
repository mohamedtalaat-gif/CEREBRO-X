#!/usr/bin/env python3
"""
================================================================================
CEREBRO-X |  cerebro_inspector.py  —  Bundle Inspector CLI
================================================================================
Created by: Muhammad Talaat (BPharm) — CEREBRO-X
Date: 2026-04-30

A standalone tool that prints all 65 resolved values for any drug + DDS
combination, with their tier, source, and `_computational_method` strings.

Useful for:
  • Debugging: see exactly which tier produced each number
  • Academic publications: supplementary material with full provenance
  • Sanity checks: verify a researcher's input is being interpreted correctly
  • Reproducibility: every value in the pipeline is auditable

Usage:
  python cerebro_inspector.py --drug "Donepezil" \\
      --smiles "COc1cc2c(cc1OC)C(=O)C(CC1CCN(Cc3ccccc3)CC1)C2" \\
      --carrier "plga" --ligand "transferrin"

  python cerebro_inspector.py --fasta "MGSDKIHHHH..." --carrier "aav9"
  python cerebro_inspector.py --sequence "GCAGAGUACAU..." --carrier "lnp"

  python cerebro_inspector.py --drug "donepezil" --carrier "plga" --json
  python cerebro_inspector.py --drug "donepezil" --carrier "plga" --markdown

Output formats:
  default  — readable terminal table
  --json   — machine-readable JSON for downstream tools
  --markdown — markdown table for paper supplementaries
================================================================================
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Allow running from anywhere
sys.path.insert(0, str(Path(__file__).parent.resolve()))

try:
    from cerebro_resolved_bundles import (
        b_method,
        b_tier,
        b_value,
        cache_stats,
        resolve_combo_bundle,
        resolve_dds_bundle,
        resolve_drug_bundle,
    )
    from cerebro_value_resolver import list_categories
except ImportError as e:
    print(f"❌ Import error: {e}", file=sys.stderr)
    print("  Make sure cerebro_value_resolver and cerebro_resolved_bundles "
          "are on PYTHONPATH or in the same folder as this script.",
          file=sys.stderr)
    sys.exit(1)


# Color codes for terminal output (degrade to plain when not a TTY)
class C:
    """ANSI color codes."""
    if sys.stdout.isatty():
        RESET   = "\033[0m"
        BOLD    = "\033[1m"
        DIM     = "\033[2m"
        BLUE    = "\033[94m"
        CYAN    = "\033[96m"
        GREEN   = "\033[92m"
        YELLOW  = "\033[93m"
        RED     = "\033[91m"
        MAGENTA = "\033[95m"
    else:
        RESET = BOLD = DIM = BLUE = CYAN = GREEN = YELLOW = RED = MAGENTA = ""


TIER_COLORS = {
    0: C.MAGENTA,    # researcher override
    1: C.GREEN,      # primary live DB
    2: C.GREEN,
    3: C.CYAN,       # cheminformatics
    4: C.CYAN,
    5: C.YELLOW,     # library correlation
    6: C.YELLOW,
    7: C.DIM,        # pure-math fallback
}


def _fmt_value(v: Any) -> str:
    """Format a value for display."""
    if v is None: return "—"
    if isinstance(v, bool): return "true" if v else "false"
    if isinstance(v, float):
        if abs(v) < 0.01 or abs(v) > 9999:
            return f"{v:.3e}"
        return f"{v:.4g}"
    if isinstance(v, dict):
        return "{...}"
    if isinstance(v, str):
        return v[:40] + "…" if len(v) > 40 else v
    return str(v)


def _print_terminal_table(bundle: dict[str, dict], title: str) -> None:
    """Print a bundle as a colorized terminal table."""
    print(f"\n{C.BOLD}{C.BLUE}{'═'*100}{C.RESET}")
    print(f"{C.BOLD}{C.BLUE}  {title}{C.RESET}")
    print(f"{C.BOLD}{C.BLUE}{'═'*100}{C.RESET}\n")

    # Sort categories with _meta first
    if "_meta" in bundle:
        m = bundle["_meta"]
        print(f"  {C.BOLD}_meta{C.RESET}: {json.dumps(m, indent=2, default=str)}\n")

    # Group by category prefix
    rows = []
    for cat, rec in bundle.items():
        if cat == "_meta": continue
        if not isinstance(rec, dict): continue
        rows.append((cat, rec))
    rows.sort(key=lambda x: x[0])

    print(f"  {C.BOLD}{'Category':<32s} {'Value':>14s}  {'Tier':>4s}  "
          f"{'Source':<35s}{C.RESET}")
    print(f"  {'-'*32}  {'-'*14}  {'-'*4}  {'-'*35}")
    for cat, rec in rows:
        v   = rec.get("value")
        t   = rec.get("tier", "?")
        src = rec.get("source", "")
        c   = TIER_COLORS.get(t, "")
        print(f"  {cat:<32s} {_fmt_value(v):>14s}  {c}T{t}{C.RESET}    "
              f"{src[:35]:<35s}")
    print()


def _print_computational_methods(bundle: dict[str, dict], title: str) -> None:
    """Print the _computational_method for every category (verbose)."""
    print(f"\n{C.BOLD}{C.YELLOW}─── {title} — computational methods ───{C.RESET}\n")
    for cat, rec in sorted(bundle.items()):
        if cat == "_meta" or not isinstance(rec, dict): continue
        cm = rec.get("_computational_method", "")
        if not cm: continue
        print(f"  {C.BOLD}{cat}{C.RESET} (T{rec.get('tier','?')}, "
              f"value={_fmt_value(rec.get('value'))}):")
        # Wrap long methods
        words = cm.split()
        line = "    "
        for w in words:
            if len(line) + len(w) > 95:
                print(line); line = "    "
            line += w + " "
        if line.strip(): print(line)
        print()


def _to_json(drug_b: dict, dds_b: dict, combo_b: dict | None = None) -> str:
    """Serialize bundles to JSON."""
    out = {"drug": drug_b, "dds": dds_b}
    if combo_b is not None:
        out["combo"] = combo_b
    return json.dumps(out, indent=2, default=str)


def _to_markdown(drug_b: dict, dds_b: dict,
                   combo_b: dict | None = None) -> str:
    """Serialize bundles to a markdown supplementary table."""
    lines: list[str] = []
    for label, bundle in [("Drug", drug_b), ("DDS", dds_b)]:
        lines.append(f"\n## {label} bundle\n")
        meta = bundle.get("_meta", {})
        lines.append(f"**Meta**: `{json.dumps(meta, default=str)}`\n")
        lines.append("| Category | Value | Tier | Source | Method |")
        lines.append("|----------|-------|------|--------|--------|")
        for cat in sorted(bundle.keys()):
            if cat == "_meta": continue
            rec = bundle[cat]
            if not isinstance(rec, dict): continue
            v   = _fmt_value(rec.get("value"))
            t   = rec.get("tier", "?")
            src = rec.get("source", "")
            m   = (rec.get("_computational_method", "") or "")
            m_esc = m.replace("|", "\\|").replace("\n", " ")[:200]
            lines.append(f"| {cat} | {v} | T{t} | {src} | {m_esc} |")
    if combo_b:
        lines.append("\n## Combo (drug × DDS) bundle\n")
        for cat in sorted(combo_b.keys()):
            if cat == "_meta": continue
            rec = combo_b[cat]
            if not isinstance(rec, dict): continue
            v   = _fmt_value(rec.get("value"))
            t   = rec.get("tier", "?")
            src = rec.get("source", "")
            lines.append(f"- **{cat}**: {v} (T{t}, {src})")
    return "\n".join(lines)


def _summary_table(drug_b: dict, dds_b: dict, combo_b: dict | None) -> None:
    """Print a 1-line summary."""
    drug_type = drug_b.get("_meta", {}).get("drug_type", "?")
    dds_type  = dds_b.get("_meta", {}).get("dds_type", "?")

    # Count by tier
    tier_counts: dict[int, int] = {}
    for b in (drug_b, dds_b, *([combo_b] if combo_b else [])):
        for cat, rec in b.items():
            if cat == "_meta" or not isinstance(rec, dict): continue
            t = rec.get("tier")
            if t is not None:
                tier_counts[t] = tier_counts.get(t, 0) + 1

    print(f"\n{C.BOLD}{C.GREEN}═══ SUMMARY ═══{C.RESET}")
    print(f"  Drug type:  {C.BOLD}{drug_type}{C.RESET}")
    print(f"  DDS type:   {C.BOLD}{dds_type}{C.RESET}")
    total = sum(tier_counts.values())
    print(f"  Total resolved values: {total}")
    print("  Tier distribution:")
    for t in sorted(tier_counts.keys()):
        n = tier_counts[t]
        pct = 100 * n / total
        bar = "█" * int(pct / 2)
        c = TIER_COLORS.get(t, "")
        print(f"    {c}T{t}{C.RESET}: {n:>3} ({pct:>5.1f}%)  {bar}")
    print()


def _to_pdf_supplementary(drug_b: dict, dds_b: dict,
                            combo_b: dict | None,
                            output_path: Path,
                            include_methods: bool = True) -> Path:
    """Generate a paper-supplementary PDF with full provenance for every value.

    Output format:
        Page 1: Title + meta + tier distribution chart
        Page 2+: drug bundle table (5-column: category / value / tier / source / method)
        Page N+: dds bundle table
        Last page: combo bundle table + summary
    """
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            KeepTogether,
            PageBreak,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError:
        print("❌ reportlab not installed. Install: pip install reportlab",
              file=sys.stderr)
        return output_path

    # Tier color codes (matches the constitution colour map)
    TIER_BG = {
        0: colors.HexColor("#9333EA"),    # researcher override → purple
        1: colors.HexColor("#10B981"),    # primary live DB    → green
        2: colors.HexColor("#10B981"),
        3: colors.HexColor("#06B6D4"),    # cheminformatics     → cyan
        4: colors.HexColor("#06B6D4"),
        5: colors.HexColor("#F59E0B"),    # library correlation → amber
        6: colors.HexColor("#F59E0B"),
        7: colors.HexColor("#94A3B8"),    # pure-math fallback → gray
    }

    doc = SimpleDocTemplate(
        str(output_path), pagesize=landscape(A4),
        leftMargin=1.2*cm, rightMargin=1.2*cm,
        topMargin=1.5*cm, bottomMargin=1.5*cm,
        title="CEREBRO-X Bundle Provenance — Supplementary Material",
        author="Muhammad Talaat / CEREBRO Therapeutics",
    )
    story: list[Any] = []
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("H1", parent=styles["Heading1"],
                          fontSize=18, textColor=colors.HexColor("#1F2937"),
                          spaceAfter=12)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"],
                          fontSize=13, textColor=colors.HexColor("#111827"),
                          spaceAfter=8)
    body = ParagraphStyle("Body", parent=styles["BodyText"],
                            fontSize=9, leading=11)
    small = ParagraphStyle("Small", parent=styles["BodyText"],
                              fontSize=8, leading=10,
                              textColor=colors.HexColor("#475569"))

    drug_meta = drug_b.get("_meta", {})
    dds_meta  = dds_b.get("_meta", {})
    drug_name = drug_meta.get("name", "Drug")
    drug_type = drug_meta.get("drug_type", "—")
    dds_type  = dds_meta.get("dds_type", "—")
    carrier   = dds_meta.get("carrier_type", "—")

    # ── Page 1: Title + summary ─────────────────────────────────────
    story.append(Paragraph(
        "CEREBRO-X — Bundle Provenance Report", h1))
    story.append(Paragraph(
        f"Drug: <b>{drug_name}</b> · Type: <b>{drug_type}</b> ·  "
        f"Carrier: <b>{carrier}</b> · DDS Type: <b>{dds_type}</b>", h2))
    story.append(Spacer(1, 0.5*cm))
    story.append(Paragraph(
        "This supplementary material documents the resolved value, tier, "
        "source, and computational method for every resolver category "
        "consumed by the CEREBRO-X 62-principle pipeline. Every cell is "
        "auditable — researchers can trace any score in the main report "
        "back to its underlying computation through this table.", body))
    story.append(Spacer(1, 0.5*cm))

    # Tier-distribution summary
    tier_counts: dict[int, int] = {}
    for b in (drug_b, dds_b, *([combo_b] if combo_b else [])):
        for cat, rec in b.items():
            if cat == "_meta" or not isinstance(rec, dict): continue
            t = rec.get("tier")
            if t is not None:
                tier_counts[t] = tier_counts.get(t, 0) + 1
    total = sum(tier_counts.values()) or 1
    rows = [["Tier", "Description", "Count", "Percentage"]]
    tier_desc = {
        0: "Researcher override (in-vitro)",
        1: "Primary live database (DrugBank/ChEMBL)",
        2: "Secondary live database",
        3: "RDKit / cheminformatics computation",
        4: "Bioinformatics (Biopython sequence)",
        5: "First-principles correlation (mendeleev/thermo)",
        6: "Library correlation (Wager-MPO, Clark logBB)",
        7: "Class-typical mean / pure-math fallback",
    }
    for t in sorted(tier_counts.keys()):
        n = tier_counts[t]
        pct = 100 * n / total
        rows.append([f"T{t}", tier_desc.get(t, "—"), str(n), f"{pct:.1f}%"])
    tbl = Table(rows, colWidths=[1.5*cm, 11*cm, 2*cm, 2.5*cm])
    style = [
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#1F2937")),
        ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
        ("FONTNAME",   (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",   (0,0), (-1,0), 10),
        ("FONTSIZE",   (0,1), (-1,-1), 9),
        ("GRID",       (0,0), (-1,-1), 0.5, colors.HexColor("#CBD5E1")),
        ("VALIGN",     (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING",(0,0), (-1,-1), 6),
        ("RIGHTPADDING",(0,0), (-1,-1), 6),
    ]
    for i in range(1, len(rows)):
        try: t = int(rows[i][0][1:])
        except (ValueError, IndexError): continue
        bg = TIER_BG.get(t, colors.HexColor("#94A3B8"))
        style.append(("BACKGROUND", (0, i), (0, i), bg))
        style.append(("TEXTCOLOR",  (0, i), (0, i), colors.white))
    tbl.setStyle(TableStyle(style))
    story.append(Paragraph(f"Tier distribution ({total} resolved values total)", h2))
    story.append(tbl)
    story.append(PageBreak())

    # ── Helper to render a bundle as a table ────────────────────────
    def _bundle_to_table(b: dict, title: str) -> None:
        story.append(Paragraph(title, h1))
        meta = b.get("_meta", {})
        story.append(Paragraph(
            f"<b>Cache key:</b> <font face='Courier' size='8'>"
            f"{meta.get('cache_key','—')}</font>", small))
        story.append(Spacer(1, 0.3*cm))

        if include_methods:
            rows = [["Category", "Value", "Tier", "Source", "Method (abbreviated)"]]
            col_widths = [4.5*cm, 2.8*cm, 1.0*cm, 5.5*cm, 13*cm]
        else:
            rows = [["Category", "Value", "Tier", "Source"]]
            col_widths = [5*cm, 4*cm, 1.5*cm, 16*cm]
        for cat in sorted(b.keys()):
            if cat == "_meta": continue
            rec = b[cat]
            if not isinstance(rec, dict): continue
            v   = rec.get("value")
            t   = rec.get("tier", "?")
            src = (rec.get("source", "") or "")[:42]
            v_str = _fmt_value(v)
            row = [cat, v_str, f"T{t}", src]
            if include_methods:
                m = (rec.get("_computational_method", "") or "")
                # Truncate to 200 chars wrapped
                m = m.replace("\n", " ").strip()[:280]
                row.append(Paragraph(m, small))
            rows.append(row)

        tbl = Table(rows, colWidths=col_widths, repeatRows=1)
        style = [
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#1F2937")),
            ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
            ("FONTNAME",   (0,0), (-1,0), "Helvetica-Bold"),
            ("FONTSIZE",   (0,0), (-1,0), 9),
            ("FONTSIZE",   (0,1), (-1,-1), 7),
            ("GRID",       (0,0), (-1,-1), 0.3, colors.HexColor("#E2E8F0")),
            ("VALIGN",     (0,0), (-1,-1), "TOP"),
            ("LEFTPADDING",(0,0), (-1,-1), 4),
            ("RIGHTPADDING",(0,0), (-1,-1), 4),
            ("TOPPADDING", (0,0), (-1,-1), 3),
            ("BOTTOMPADDING",(0,0), (-1,-1), 3),
        ]
        # Color the tier column per row
        for i in range(1, len(rows)):
            tier_str = rows[i][2]
            try: t = int(tier_str[1:])
            except (ValueError, IndexError): continue
            bg = TIER_BG.get(t, colors.HexColor("#94A3B8"))
            style.append(("BACKGROUND", (2, i), (2, i), bg))
            style.append(("TEXTCOLOR",  (2, i), (2, i), colors.white))
            style.append(("FONTNAME",   (2, i), (2, i), "Helvetica-Bold"))
            # Alternate row coloring
            if i % 2 == 0:
                style.append(("BACKGROUND", (0, i), (1, i), colors.HexColor("#F8FAFC")))
                style.append(("BACKGROUND", (3, i), (-1, i), colors.HexColor("#F8FAFC")))
        tbl.setStyle(TableStyle(style))
        story.append(tbl)
        story.append(PageBreak())

    _bundle_to_table(drug_b, f"Drug bundle — {drug_name}")
    _bundle_to_table(dds_b,  f"DDS bundle — {carrier}")
    if combo_b is not None:
        _bundle_to_table(combo_b,
            f"Combo bundle — {drug_name} × {carrier} (drug-DDS interactions)")

    # ── Final page: legend + footer ─────────────────────────────────
    story.append(Paragraph("Legend", h1))
    legend_rows = [
        ["Tier", "Color", "Meaning"],
        ["T0", "Purple",   "Researcher override — in-vitro value (highest confidence)"],
        ["T1", "Green",    "Primary live database (DrugBank, ChEMBL, FDA label)"],
        ["T2", "Green",    "Secondary live database (UniProt, PubChem)"],
        ["T3", "Cyan",     "RDKit cheminformatics computation from SMILES"],
        ["T4", "Cyan",     "Biopython bioinformatics from FASTA/sequence"],
        ["T5", "Amber",    "First-principles correlation (mendeleev / thermo / chemicals)"],
        ["T6", "Amber",    "Library correlation (Wager-MPO, Clark logBB, Lipinski Ro5)"],
        ["T7", "Gray",     "Class-typical mean / pure-math fallback (researcher override candidate)"],
    ]
    legend = Table(legend_rows, colWidths=[1.5*cm, 2*cm, 17.5*cm])
    legend_style = [
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#1F2937")),
        ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
        ("FONTNAME",   (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",   (0,0), (-1,0), 10),
        ("FONTSIZE",   (0,1), (-1,-1), 9),
        ("GRID",       (0,0), (-1,-1), 0.5, colors.HexColor("#CBD5E1")),
        ("VALIGN",     (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING",(0,0), (-1,-1), 6),
        ("RIGHTPADDING",(0,0), (-1,-1), 6),
    ]
    for i in range(1, len(legend_rows)):
        t = int(legend_rows[i][0][1:])
        bg = TIER_BG.get(t, colors.HexColor("#94A3B8"))
        legend_style.append(("BACKGROUND", (1, i), (1, i), bg))
        legend_style.append(("TEXTCOLOR",  (1, i), (1, i), colors.white))
    legend.setStyle(TableStyle(legend_style))
    story.append(legend)
    story.append(Spacer(1, 1*cm))
    story.append(Paragraph(
        "<i>Generated by CEREBRO-X Bundle Inspector. For citation: "
        "Talaat M (2026) CEREBRO-X. CEREBRO Therapeutics.</i>", small))

    doc.build(story)
    return output_path


def main() -> int:
    p = argparse.ArgumentParser(
        prog="cerebro_inspector",
        description="Print all resolved values for a drug + DDS with full provenance",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Output formats:")[1] if __doc__ else "",
    )
    # Drug input (one of these)
    p.add_argument("--drug", help="Drug name (resolver will fetch SMILES via cascade)")
    p.add_argument("--smiles", help="SMILES string (small molecule)")
    p.add_argument("--fasta", help="FASTA string (biologic)")
    p.add_argument("--sequence", help="DNA/RNA sequence (gene therapy)")
    p.add_argument("--molecule-class", default="",
                     help="Optional explicit drug type: small_molecule, "
                          "monoclonal_antibody, oligonucleotide, etc.")
    # DDS input
    p.add_argument("--carrier", default="plga",
                     help="Carrier type (plga, liposome, aav9, lnp, ...)")
    p.add_argument("--ligand", default="",
                     help="Surface ligand (transferrin, rvg29, apoe, ...)")
    p.add_argument("--formulation-id", default="F1",
                     help="Formulation ID for bundle caching")
    # Output options
    p.add_argument("--json", action="store_true",
                     help="Output as JSON instead of formatted tables")
    p.add_argument("--markdown", action="store_true",
                     help="Output as markdown table (for paper supplementaries)")
    p.add_argument("--methods", action="store_true",
                     help="Include _computational_method for every value")
    p.add_argument("--pdf", default=None,
                     help="Generate paper-supplementary PDF at this path")
    p.add_argument("--no-combo", action="store_true",
                     help="Skip combo bundle (drug × DDS interaction props)")

    args = p.parse_args()

    # Validation
    if not any([args.drug, args.smiles, args.fasta, args.sequence]):
        print("❌ At least one of --drug, --smiles, --fasta, --sequence required",
              file=sys.stderr)
        return 1

    drug_name = args.drug or "drug"

    # Resolve bundles
    if not (args.json or args.markdown):
        print(f"\n{C.BOLD}🔬 CEREBRO-X Bundle Inspector{C.RESET}")
        print(f"{C.DIM}Resolving {len(list_categories())} categories...{C.RESET}")

    drug_b = resolve_drug_bundle(
        name=drug_name, smiles=args.smiles or "",
        fasta=args.fasta or "", sequence=args.sequence or "",
        molecule_class=args.molecule_class or "",
    )
    dds_b = resolve_dds_bundle(
        carrier_type=args.carrier, ligand=args.ligand or "",
        formulation_id=args.formulation_id,
    )
    combo_b = None if args.no_combo else resolve_combo_bundle(drug_b, dds_b)

    # Output
    if args.pdf:
        pdf_path = Path(args.pdf)
        result = _to_pdf_supplementary(drug_b, dds_b, combo_b, pdf_path,
                                            include_methods=True)
        size = result.stat().st_size if result.exists() else 0
        if not (args.json or args.markdown):
            print(f"\n{C.GREEN}✓ PDF supplementary generated{C.RESET}: "
                  f"{pdf_path}  ({size:,} bytes)")
    elif args.json:
        print(_to_json(drug_b, dds_b, combo_b))
    elif args.markdown:
        print(_to_markdown(drug_b, dds_b, combo_b))
    else:
        _print_terminal_table(drug_b,
            f"DRUG BUNDLE: {drug_name} ({len([k for k in drug_b if k != '_meta'])} categories)")
        _print_terminal_table(dds_b,
            f"DDS BUNDLE: {args.carrier} ({len([k for k in dds_b if k != '_meta'])} categories)")
        if combo_b:
            _print_terminal_table(combo_b,
                f"COMBO BUNDLE: {drug_name} × {args.carrier} "
                f"({len([k for k in combo_b if k != '_meta'])} categories)")
        _summary_table(drug_b, dds_b, combo_b)
        if args.methods:
            _print_computational_methods(drug_b, "DRUG")
            _print_computational_methods(dds_b, "DDS")
            if combo_b:
                _print_computational_methods(combo_b, "COMBO")

    return 0


if __name__ == "__main__":
    sys.exit(main())
