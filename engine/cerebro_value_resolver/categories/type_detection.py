"""
================================================================================
CEREBRO-X | categories/type_detection.py
================================================================================
FDA-COMPREHENSIVE drug + DDS type classifier.

DRUG TYPES (every category the FDA recognizes):
  1.  small_molecule         — chemical entity (NCE)
  2.  peptide                — amino-acid sequence < ~50 aa
  3.  protein                — therapeutic protein (50-1300 aa)
  4.  monoclonal_antibody    — mAb (-mab USAN suffix or full IgG ~1320 aa)
  5.  fusion_protein         — Fc fusion (-cept USAN)
  6.  vaccine                — antigen-based prophylactic/therapeutic
  7.  blood_product          — clotting factors, immunoglobulins
  8.  cell_therapy           — CAR-T, TCR-T, NK, MSC, iPSC
  9.  gene_therapy           — DNA/mRNA/CRISPR (>50 nt or AAV-encoded)
  10. oligonucleotide        — ASO, siRNA (<50 nt synthetic NA)
  11. radiopharmaceutical    — radiotracer / targeted radionuclide therapy
  12. allergenic_extract     — allergy desensitization
  13. natural_product        — botanical/mineral/animal-derived
  14. enzyme_replacement     — recombinant enzyme (-ase suffix)

DDS TYPES (carrier classes):
  1.  material   2.  liposomal   3.  viral_envelope   4.  gene_dds
  5.  exosome    6.  cell_carrier   7.  biological_membrane
  8.  magnetic   9.  implantable   10. dendrimer   11. micelle
  12. metallic
================================================================================
"""
from __future__ import annotations

import logging

from .._core import _HAS_RDKIT, _resolved, register

log = logging.getLogger("CEREBRO-RESOLVER.type_detection")


def _is_valid_smiles(smiles: str) -> bool:
    if not smiles or not _HAS_RDKIT: return False
    from rdkit import Chem
    try:
        return Chem.MolFromSmiles(smiles) is not None
    except Exception:
        return False


def _smiles_mw(smiles: str) -> float | None:
    if not (_HAS_RDKIT and smiles): return None
    from rdkit import Chem
    from rdkit.Chem import Descriptors
    mol = Chem.MolFromSmiles(smiles)
    return float(Descriptors.MolWt(mol)) if mol else None


def _is_valid_amino_acid_sequence(seq: str) -> bool:
    if not seq: return False
    s = seq.strip().upper()
    if s.startswith(">"):
        s = "\n".join(l for l in s.split("\n") if not l.startswith(">"))
    s = s.replace("\n", "").replace(" ", "")
    if len(s) < 5: return False
    return all(c in set("ACDEFGHIKLMNPQRSTVWYUO") for c in s)


def _amino_acid_count(seq: str) -> int:
    if not seq: return 0
    s = seq.strip()
    if s.startswith(">"):
        s = "\n".join(l for l in s.split("\n") if not l.startswith(">"))
    return len(s.replace("\n","").replace(" ",""))


def _is_valid_nucleic_acid(seq: str) -> bool:
    if not seq: return False
    s = seq.strip().upper()
    if s.startswith(">"):
        s = "\n".join(l for l in s.split("\n") if not l.startswith(">"))
    s = s.replace("\n","").replace(" ","")
    if len(s) < 5: return False
    return all(c in set("ACGTURYSWKMBDHVN") for c in s)


def _normalize_drug_class(v: str) -> str:
    aliases = {
        "small molecule":"small_molecule","sm":"small_molecule",
        "small_molecule":"small_molecule","nce":"small_molecule",
        "chemical":"small_molecule",
        "peptide":"peptide","polypeptide":"peptide",
        "protein":"protein","therapeutic protein":"protein",
        "recombinant protein":"protein","rprotein":"protein",
        "antibody":"monoclonal_antibody","mab":"monoclonal_antibody",
        "monoclonal":"monoclonal_antibody",
        "monoclonal_antibody":"monoclonal_antibody",
        "monoclonal antibody":"monoclonal_antibody",
        "fusion protein":"fusion_protein","fusion_protein":"fusion_protein",
        "fc fusion":"fusion_protein",
        "vaccine":"vaccine",
        "blood product":"blood_product","blood_product":"blood_product",
        "plasma":"blood_product","ivig":"blood_product",
        "cell therapy":"cell_therapy","cell_therapy":"cell_therapy",
        "car-t":"cell_therapy","cart":"cell_therapy",
        "gene therapy":"gene_therapy","gene_therapy":"gene_therapy",
        "mrna":"gene_therapy","dna":"gene_therapy","crispr":"gene_therapy",
        "oligonucleotide":"oligonucleotide","oligo":"oligonucleotide",
        "sirna":"oligonucleotide","aso":"oligonucleotide",
        "antisense":"oligonucleotide","aptamer":"oligonucleotide",
        "biologic":"protein",
        "radiopharmaceutical":"radiopharmaceutical",
        "radiotracer":"radiopharmaceutical",
        "radionuclide":"radiopharmaceutical",
        "allergen":"allergenic_extract",
        "allergenic_extract":"allergenic_extract",
        "natural product":"natural_product",
        "natural_product":"natural_product","botanical":"natural_product",
        "enzyme":"enzyme_replacement",
        "enzyme replacement":"enzyme_replacement",
        "enzyme_replacement":"enzyme_replacement",
    }
    return aliases.get(v, "small_molecule")


# ──────────────────────────────────────────────────────────────────────────
# DRUG TYPE
# ──────────────────────────────────────────────────────────────────────────
@register("drug_type")
def resolve_drug_type(name: str = "", smiles: str = "", fasta: str = "",
                        sequence: str = "", molecule_class: str = "",
                        researcher_override: str | None = None) -> dict:
    db_misses: list[str] = []

    if researcher_override:
        v = str(researcher_override).strip().lower()
        normalized = _normalize_drug_class(v)
        return _resolved(
            value=normalized, tier=0, source="researcher_override",
            method=f"User-provided drug class: {researcher_override!r}",
            computational_method=(
                f"Step 1: Read 'Molecule Class' from Excel Sheet 1. "
                f"Step 2: Normalize {researcher_override!r} → {normalized!r}."),
            reference="FDA CDER/CBER drug classification framework",
            live_db_misses=[], extra={"is_categorical": True})

    if molecule_class:
        v = str(molecule_class).strip().lower()
        normalized = _normalize_drug_class(v)
        return _resolved(
            value=normalized, tier=1, source="caller_molecule_class",
            method=f"Caller passed molecule_class={molecule_class!r}",
            computational_method=(
                f"Step 1: Receive molecule_class kwarg. "
                f"Step 2: Normalize {molecule_class!r} → {normalized!r}."),
            reference="Pipeline upstream metadata",
            live_db_misses=[], extra={"is_categorical": True})

    # Tier 3a: SMILES
    if smiles and _is_valid_smiles(smiles):
        mw = _smiles_mw(smiles) or 0
        if mw < 900:
            cls = "small_molecule"
            why = f"Valid SMILES, MW={mw:.1f} Da < 900"
        elif mw < 5000:
            cls = "peptide"
            why = f"Valid SMILES, MW={mw:.1f} Da in [900, 5000]"
        else:
            cls = "protein"
            why = f"Valid SMILES, MW={mw:.1f} Da > 5000"
        return _resolved(
            value=cls, tier=3, source="rdkit:SMILES_validation+MW",
            method=why,
            computational_method=(
                f"Step 1: RDKit Chem.MolFromSmiles(SMILES) → valid Mol object. "
                f"Step 2: RDKit Descriptors.MolWt(mol) → {mw:.2f} Da. "
                f"Step 3: Apply MW thresholds (Lipinski Ro5 + FDA peptide guidance): "
                f"<900=small_molecule, 900-5000=peptide, >5000=protein. "
                f"Result: {cls!r}."),
            reference="",
            live_db_misses=db_misses,
            extra={"is_categorical": True, "computed_MW_Da": round(mw, 2)})

    # Tier 3b: FASTA
    if fasta and _is_valid_amino_acid_sequence(fasta):
        n_aa = _amino_acid_count(fasta)
        if n_aa < 50:
            cls = "peptide"
            why = f"FASTA len={n_aa} aa < 50 (peptide)"
        elif n_aa < 150:
            cls = "protein"
            why = f"FASTA len={n_aa} aa in [50, 150] (small protein)"
        else:
            n_low = name.lower()
            if any(s in n_low for s in ("mab","ximab","zumab")) or n_aa > 1300:
                cls = "monoclonal_antibody"
                why = (f"FASTA len={n_aa} aa + USAN '-mab' OR len>1300 "
                        f"(full IgG ~1320 aa)")
            else:
                cls = "protein"
                why = f"FASTA len={n_aa} aa, no -mab suffix"
        return _resolved(
            value=cls, tier=3,
            source="cerebro_value_resolver:AA_alphabet+length",
            method=why,
            computational_method=(
                f"Step 1: Strip FASTA header (>...). "
                f"Step 2: Validate alphabet against IUPAC AA set "
                f"{{A,C,D,E,F,G,H,I,K,L,M,N,P,Q,R,S,T,V,W,Y,U,O}} → all valid. "
                f"Step 3: Count residues → {n_aa}. "
                f"Step 4: <50 aa = peptide, 50-150 = protein, "
                f"≥150 = protein-or-mAb. "
                f"Step 5: If USAN '-mab' suffix or len>1300 → monoclonal_antibody. "
                f"Result: {cls!r}."),
            reference="",
            live_db_misses=db_misses,
            extra={"is_categorical": True, "sequence_length_aa": n_aa})

    # Tier 3c: nucleic acid
    if sequence and _is_valid_nucleic_acid(sequence):
        s = sequence.strip().upper()
        if s.startswith(">"):
            s = "\n".join(l for l in s.split("\n") if not l.startswith(">"))
        s = s.replace("\n","").replace(" ","")
        n_nt = len(s)
        if n_nt < 50:
            cls = "oligonucleotide"
            why = f"NA len={n_nt} nt < 50 (siRNA/ASO)"
        else:
            cls = "gene_therapy"
            why = f"NA len={n_nt} nt ≥ 50 (mRNA/DNA construct)"
        return _resolved(
            value=cls, tier=3,
            source="cerebro_value_resolver:NA_alphabet+length",
            method=why,
            computational_method=(
                f"Step 1: Strip header. "
                f"Step 2: Validate alphabet against IUPAC NA set "
                f"{{A,C,G,T,U + RYSWKMBDHVN ambiguity}} → all valid. "
                f"Step 3: Count nt → {n_nt}. "
                f"Step 4: <50 nt = oligonucleotide (siRNA/ASO), "
                f"≥50 nt = gene_therapy (mRNA/DNA). "
                f"Result: {cls!r}."),
            reference="",
            live_db_misses=db_misses,
            extra={"is_categorical": True, "sequence_length_nt": n_nt})

    # Tier 4: USAN suffix + keyword
    if name:
        n = name.lower().strip()
        suffix_map = [
            ("ximab",  "monoclonal_antibody", "chimeric mAb"),
            ("zumab",  "monoclonal_antibody", "humanized mAb"),
            ("umab",   "monoclonal_antibody", "human mAb"),
            ("omab",   "monoclonal_antibody", "mouse mAb"),
            ("mab",    "monoclonal_antibody", "monoclonal antibody"),
            ("cept",   "fusion_protein",      "Fc fusion"),
            ("ase",    "enzyme_replacement",  "enzyme"),
            ("tide",   "peptide",             "peptide"),
            ("kin",    "protein",             "cytokine"),
            ("vax",    "vaccine",             "vaccine"),
        ]
        for suffix, cls, label in suffix_map:
            if n.endswith(suffix):
                return _resolved(
                    value=cls, tier=4,
                    source="cerebro_value_resolver:USAN_suffix",
                    method=f"Name {name!r} ends with USAN '-{suffix}' → {cls}",
                    computational_method=(
                        f"Step 1: Lowercase {name!r} → {n!r}. "
                        f"Step 2: Match against USAN suffix table "
                        f"(specificity-ordered: ximab→zumab→umab→omab→mab). "
                        f"Step 3: Found '-{suffix}' → {cls!r} ({label})."),
                    reference="WHO INN program / USAN Council suffix table",
                    live_db_misses=db_misses,
                    extra={"is_categorical": True, "matched_suffix": suffix})

        keyword_map = [
            (("sirna","si rna"), "oligonucleotide"),
            (("mrna","m rna","messenger rna"), "gene_therapy"),
            (("aso","antisense"), "oligonucleotide"),
            (("crispr","cas9"), "gene_therapy"),
            (("aav-","gene editing","gene therapy"), "gene_therapy"),
            (("car-t","car t","tcr-t","ipsc","leucel","cabtagene",
                "ctl019","cilta-cel","-cel ","tisagenlecleucel"), "cell_therapy"),
            (("vaccine","vaccin"), "vaccine"),
            (("immunoglobulin","ivig"), "blood_product"),
            (("factor viii","factor ix"), "blood_product"),
            (("99mtc","68ga","177lu","225ac","tc-99m","[18f]","[11c]",
                "[68ga]","[177lu]","[225ac]","-radium","fluorodeoxyglucose",
                "dotatate","psma-617","lutathera","pluvicto"),
              "radiopharmaceutical"),
            (("allergen extract","grass pollen","ragweed extract"),
              "allergenic_extract"),
            (("ginseng","echinacea","botanical","cannabidiol","cbd "),
              "natural_product"),
        ]
        for keywords, cls in keyword_map:
            for kw in keywords:
                if kw in n:
                    return _resolved(
                        value=cls, tier=4,
                        source="cerebro_value_resolver:keyword_match",
                        method=f"Name {name!r} contains {kw!r} → {cls}",
                        computational_method=(
                            f"Step 1: Lowercase → {n!r}. "
                            f"Step 2: Substring search across FDA drug-class "
                            f"keyword table. Step 3: Match {kw!r} → {cls!r}."),
                        reference="FDA classification keyword tables",
                        live_db_misses=db_misses,
                        extra={"is_categorical": True, "matched_keyword": kw})

    # Tier 7: name provided but unrecognized
    if name:
        return _resolved(
            value="small_molecule", tier=7,
            source="cerebro_value_resolver:default_by_name",
            method=f"Name {name!r} unrecognized; default small_molecule",
            computational_method=(
                "Step 1: No SMILES/FASTA/sequence to validate. "
                "Step 2: No USAN suffix matched. "
                "Step 3: No FDA-class keyword matched. "
                "Step 4: Default to small_molecule per FDA approval frequency "
                "(~70% of NDAs are NCEs)."),
            reference="FDA CDER Novel Drug Approvals statistics",
            live_db_misses=db_misses,
            extra={"is_categorical": True,
                    "warning": "Default applied — verify via Excel"})

    return _resolved(
        value="small_molecule", tier=7,
        source="cerebro_value_resolver:default_no_input",
        method="No identifiers; defaulted to small_molecule",
        computational_method=(
            "Step 1: All inputs (name, smiles, fasta, sequence) empty. "
            "Step 2: Default small_molecule per FDA approval frequency."),
        reference="FDA CDER Novel Drug Approvals statistics",
        live_db_misses=db_misses,
        extra={"is_categorical": True,
                "warning": "No input — Excel may be incomplete"})


# ──────────────────────────────────────────────────────────────────────────
# DDS TYPE
# ──────────────────────────────────────────────────────────────────────────
DDS_KEYWORD_MAP = [
    ("aav",          "viral_envelope", "AAV vector"),
    ("lentivirus",    "viral_envelope", "lentiviral vector"),
    ("lenti",         "viral_envelope", "lentiviral vector"),
    ("adenovirus",    "viral_envelope", "adenoviral vector"),
    ("adv-",          "viral_envelope", "adenoviral vector"),
    ("retrovirus",    "viral_envelope", "retroviral vector"),
    ("hsv",           "viral_envelope", "HSV vector"),
    ("phage",         "viral_envelope", "bacteriophage carrier"),
    ("envelope",      "viral_envelope", "viral envelope"),
    ("capsid",        "viral_envelope", "viral capsid"),
    ("vector",        "viral_envelope", "viral vector"),

    ("lnp",           "gene_dds",       "lipid nanoparticle"),
    ("lipoplex",      "gene_dds",       "cationic-lipid/DNA complex"),
    ("polyplex",      "gene_dds",       "cationic polymer/DNA complex"),
    ("dendriplex",    "gene_dds",       "dendrimer/NA complex"),
    ("siplex",        "gene_dds",       "siRNA-loaded complex"),
    ("transfection",  "gene_dds",       "transfection reagent"),

    ("exosome",       "exosome",        "extracellular vesicle"),
    ("microvesicle",  "exosome",        "microvesicle"),

    ("car-t",         "cell_carrier",   "CAR-T cell"),
    ("erythrocyte",   "cell_carrier",   "RBC carrier"),
    ("rbc-",          "cell_carrier",   "RBC carrier"),
    ("msc-",          "cell_carrier",   "MSC carrier"),

    ("membrane-coated","biological_membrane", "cell-membrane-coated NP"),
    ("cell membrane", "biological_membrane", "cell membrane coating"),
    ("cmc-np",        "biological_membrane", "cell-membrane-coated NP"),

    ("spion",         "magnetic",       "SPION"),
    ("magnetite",     "magnetic",       "magnetite NP"),
    ("magnetic",      "magnetic",       "magnetic carrier"),

    ("stent",         "implantable",    "drug-eluting stent"),
    ("scaffold",      "implantable",    "drug-eluting scaffold"),
    ("implant",       "implantable",    "implant depot"),

    ("dendrimer",     "dendrimer",      "branched polymer"),
    ("pamam",         "dendrimer",      "PAMAM dendrimer"),

    ("micelle",       "micelle",        "micellar carrier"),

    ("liposome",      "liposomal",      "phospholipid vesicle"),
    ("dopc",          "liposomal",      "DOPC liposome"),
    ("dppc",          "liposomal",      "DPPC liposome"),
    ("dspc",          "liposomal",      "DSPC liposome"),
    ("dmpc",          "liposomal",      "DMPC liposome"),
    ("popc",          "liposomal",      "POPC liposome"),

    ("gold-np",       "metallic",       "gold nanoparticle"),
    ("au-np",         "metallic",       "gold nanoparticle"),
    ("silver-np",     "metallic",       "silver nanoparticle"),
    ("silica",        "metallic",       "silica nanoparticle"),
    ("metallic",      "metallic",       "metallic carrier"),

    ("plga",          "material",       "PLGA polymer"),
    ("pcl-",          "material",       "PCL polymer"),
    ("pla-",          "material",       "PLA polymer"),
    ("polymer",       "material",       "synthetic polymer"),
    ("solid_lipid",   "material",       "solid lipid NP"),
    ("solid lipid",   "material",       "solid lipid NP"),
    ("nanogel",       "material",       "nanogel"),
    ("chitosan",      "material",       "chitosan"),
    ("alginate",      "material",       "alginate"),
    ("albumin",       "material",       "albumin carrier"),
    ("peg-",          "material",       "PEG-based"),
]


@register("dds_type")
def resolve_dds_type(carrier: str = "", carrier_type: str = "",
                       formulation_name: str = "",
                       researcher_override: str | None = None) -> dict:
    db_misses: list[str] = []

    if researcher_override:
        v = str(researcher_override).strip().lower().replace(" ","_")
        return _resolved(
            value=v, tier=0, source="researcher_override",
            method=f"User-provided DDS type: {researcher_override!r}",
            computational_method=(
                f"Step 1: Read DDS_Type override from Excel. "
                f"Step 2: Normalize {researcher_override!r} → {v!r}."),
            reference="Researcher input via Excel",
            live_db_misses=[],
            extra={"is_categorical": True})

    text = " ".join([carrier or "", carrier_type or "",
                       formulation_name or ""]).lower()
    if not text.strip():
        return _resolved(
            value="material", tier=7,
            source="cerebro_value_resolver:default_no_input",
            method="No carrier identifier; default material",
            computational_method=(
                "Step 1: All carrier inputs empty. "
                "Step 2: Default material per most-common DDS class."),
            reference="—", live_db_misses=db_misses,
            extra={"is_categorical": True, "warning":"No carrier info"})

    for keyword, cls, label in DDS_KEYWORD_MAP:
        if keyword in text:
            return _resolved(
                value=cls, tier=3,
                source="cerebro_value_resolver:keyword_match",
                method=f"Carrier matches {keyword!r} → {cls} ({label})",
                computational_method=(
                    f"Step 1: Concat (carrier, carrier_type, formulation_name) "
                    f"→ {text!r}. "
                    f"Step 2: Lowercase + substring search across DDS keyword "
                    f"table (most-specific first: viral → gene_dds → exosome → "
                    f"cell → membrane → magnetic → implantable → "
                    f"dendrimer/micelle/liposomal/metallic → material). "
                    f"Step 3: Match {keyword!r} → classify as {cls!r} ({label})."),
                reference="",
                live_db_misses=db_misses,
                extra={"is_categorical": True, "matched_keyword": keyword,
                        "label": label})

    return _resolved(
        value="material", tier=7,
        source="cerebro_value_resolver:material_class_inferred",
        method=f"No specific keyword match in {text!r}; classified as 'material' "
                f"(non-viral, non-gene-DDS) by exclusion",
        computational_method=(
            f"Step 1: Concatenated text → {text!r}. "
            f"Step 2: Searched 50+ keywords — none matched. "
            f"Step 3: Default to material as most-common FDA-approved DDS class."),
        reference="—", live_db_misses=db_misses,
        extra={"is_categorical": True,
                "warning": "DDS type defaulted; researcher should clarify"})
