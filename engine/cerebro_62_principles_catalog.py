"""
================================================================================
CEREBRO-X |  cerebro_62_principles_catalog.py
================================================================================
Created by: Muhammad Talaat (BPharm, R&D Computational Lead) — CEREBRO-X

This is CEREBRO-X's internal 62-criterion scoring rubric — an in-house
design decision by this project, NOT an externally validated, peer-reviewed,
or regulator-endorsed "framework." Each entry cites literature for the
underlying pharmaceutical/physical concept it draws on, but the specific
scoring formulas, weights, and lookup tables below are this project's own
construction and have not been independently benchmarked. P04 (quantum
tunneling of whole drug molecules across the BBB) describes a mechanism not
currently accepted in the pharmacology literature — see its "maturity_note"
field below. Do not cite this catalog as evidence of external validation in
papers, reports, or outreach.

Classified per this project's internal C+ Flow triage (2026-04-28):

  CLASS A — Fast Surrogates    (run on ALL 100 DDS, drives ranking)
  CLASS B — Deep Physics        (run on TOP-1 only, validates winner — see
                                  cerebro_62_deep_engine.py: only 7 of 28
                                  Class-B principles run independent
                                  computation as of v22; the rest re-use
                                  their Class-A surrogate score pending a
                                  future full-physics HPC run)
  CLASS C — Translational Admin (run on TOP-1 only AFTER Deep Physics passes)

Source: internal project notes (not published; not a citable external source)

Principle IDs:  P01..P62  (canonical numbering used throughout the codebase)

Each entry carries:
  • title_en, title_ar
  • class             ('A_surrogate', 'B_deep', 'C_translational')
  • cns_relevant      (True if directly tied to CNS/BBB/glymphatic)
  • dds_dependent     (True if score depends on DDS specs; False = drug-only)
  • method_surrogate  (the fast formula used in CLASS A)
  • method_deep       (the heavy method used in CLASS B; None for CLASS C)
  • libraries         (Python packages required)
  • reference         (literature citation)
  • weight_cns        (0..1, CNS-focused weight in composite scoring)

Weight policy (CNS-focused per project mandate):
  - Class A weights sum to 1.000
  - CNS-direct principles carry the highest weights (P12, P33, P38, P39,
    P42, P43, P44 — collectively ≥ 40%)
  - Translational principles (Class C) carry weight 0 in DDS ranking
================================================================================
"""
from __future__ import annotations

# ──────────────────────────────────────────────────────────────────────────
# Master 62-principle registry
# ──────────────────────────────────────────────────────────────────────────
PRINCIPLES_62: dict[str, dict] = {

    # ════════════════════════════════════════════════════════════════════
    # PRINCIPLES 1-12 — Block 1 (Adversarial, PK Scaling, Patient Strat,
    #   Lysosomal, Lit Mining, Oxidative, Pharmacovigilance,
    #   LNP Ionization, Instability Fingerprint, CNS Stage Dosing)
    # ════════════════════════════════════════════════════════════════════
    "P01": {
        "title_en": "Adversarial Stress-Testing Engine",
        "title_ar": "اختبار الإجهاد العدائي",
        "class": "A_surrogate",
        "cns_relevant": False,
        "dds_dependent": True,
        "method_surrogate":
            "Score = mean of stability under 6 worst-case scenarios "
            "(pH 4.5/2.0/8.5, 42°C, presence of antibodies, oxidative "
            "stress). Each scenario tested via Arrhenius + ionization + "
            "carrier-class robustness table.",
        "method_deep": "Full MD simulation of carrier under stress conditions",
        "libraries": ["thermo", "scipy"],
        "reference": "Anchordoquy TJ et al (2017) ACS Nano 11:12-18",
        "weight_cns": 0.015,
    },
    "P02": {
        "title_en": "Cross-Species PK Scaling (Allometric)",
        "title_ar": "قياس الفارما العابر للأنواع",
        "class": "A_surrogate",
        "cns_relevant": True,
        "dds_dependent": False,
        "method_surrogate":
            "Body-weight^0.75 allometric scaling. Mouse → human: "
            "dose_h = dose_m × (BW_h/BW_m)^0.75; CNS-specific BBB "
            "permeability scaling factor.",
        "method_deep": "Full multi-species PBPK with organ-specific scaling",
        "libraries": ["scipy"],
        "reference": "Mahmood I (2007) Eur J Drug Metab Pharmacokinet 32:25",
        "weight_cns": 0.010,
    },
    "P03": {
        "title_en": "Competitive DDS Landscape Radar",
        "title_ar": "رادار المنافسين",
        "class": "A_surrogate",
        "cns_relevant": True,
        "dds_dependent": True,
        "method_surrogate":
            "Tanimoto similarity to benchmark CNS DDS in ClinicalTrials.gov. "
            "Score = 100 × (1 - max_similarity_to_active_competitor) — "
            "encourages novelty over crowded landscape.",
        "method_deep": "Live API fetch from ClinicalTrials.gov + literature",
        "libraries": ["rdkit", "requests"],
        "reference": "ClinicalTrials.gov API; Bento AP et al ChEMBL Nucleic Acids Res 42:D1083",
        "weight_cns": 0.010,
    },
    "P04": {
        "title_en": "Quantum Coherence Transport Model",
        "title_ar": "نموذج نقل الكم",
        "class": "A_surrogate",
        "cns_relevant": True,
        "dds_dependent": False,
        "method_surrogate":
            "WKB tunneling probability for small drugs (<500 Da) crossing "
            "lipid bilayer. P_tunnel ≈ exp(-2·a·sqrt(2m(V-E))/ℏ). "
            "Surrogate uses pre-computed barrier height from LogP.",
        "method_deep": "Full QM tunneling with QCElemental + ASE",
        "libraries": ["scipy", "qcelemental"],
        "reference": "Cao J et al (2020) Sci Adv 6:eaaz4888 (quantum biology)",
        "weight_cns": 0.012,
        "maturity_note":
            "NOT an accepted BBB-crossing mechanism in the pharmacology "
            "literature. Whole-molecule quantum tunneling (treating a "
            "several-hundred-Da drug as a single tunneling particle) is not "
            "physically supported at this mass/temperature scale — real BBB "
            "transport is governed by passive diffusion, carrier-mediated "
            "transport, and receptor-mediated transcytosis (see P33), not "
            "tunneling. The cited reference (Cao et al. 2020) concerns "
            "quantum effects in photosynthesis/enzyme catalysis, not drug "
            "transport, and does not support this application. This "
            "principle's score should not be presented as validated physics "
            "in any external report; kept for R&D exploration only, and its "
            "weight_cns (0.012, ~1% of total) is intentionally minimal.",
    },
    "P05": {
        "title_en": "In-Silico Patient Subgroup Stratifier",
        "title_ar": "تقسيم الفئات المرضية",
        "class": "A_surrogate",
        "cns_relevant": True,
        "dds_dependent": False,
        "method_surrogate":
            "Stratifies virtual patients by age (3 bins), CYP genotype "
            "(EM/IM/PM), CNS disease stage (early/mid/late). Score = "
            "% subgroups expected to respond.",
        "method_deep": "Full pharmacogenomic database lookup (PharmGKB)",
        "libraries": ["pandas"],
        "reference": "Whirl-Carrillo M et al (2012) Clin Pharmacol Ther 92:414",
        "weight_cns": 0.012,
    },
    "P06": {
        "title_en": "Lysosomal Trafficking Predictor",
        "title_ar": "مصير الـ lysosome",
        "class": "A_surrogate",
        "cns_relevant": True,
        "dds_dependent": True,
        "method_surrogate":
            "P(escape lysosome) = f(endosomal_escape_eff, surface_charge, "
            "pH-trigger). Score = endosomal_escape × (1 - lysosome_trap_prob).",
        "method_deep": "Full intracellular trafficking ODE model",
        "libraries": ["scipy"],
        "reference": "Smith SA et al (2019) Trends Biotechnol 37:1077",
        "weight_cns": 0.012,
    },
    "P07": {
        "title_en": "Real-Time Literature Mining (PubMed)",
        "title_ar": "استخراج الأدبيات الحية",
        "class": "A_surrogate",
        "cns_relevant": False,
        "dds_dependent": True,
        "method_surrogate":
            "PubMed E-utilities: count of papers matching (carrier + "
            "CNS + indication). Score = log10(hit_count + 1) × 20, "
            "capped at 100.",
        "method_deep": "Full NLP-based citation extraction",
        "libraries": ["requests", "Bio"],
        "reference": "NCBI E-utilities API",
        "weight_cns": 0.005,
    },
    "P08": {
        "title_en": "Degradation Kinetics Under Oxidative Stress",
        "title_ar": "حركية التحلل تحت ROS",
        "class": "A_surrogate",
        "cns_relevant": True,
        "dds_dependent": True,
        "method_surrogate":
            "k_ox = A·exp(-Ea/RT) at [ROS]=10µM. Score = "
            "100 × exp(-k_ox × t_target). Carrier-specific Ea table "
            "(liposome 80 kJ/mol, PLGA 110, etc.)",
        "method_deep": "Full radical-chain reaction MD",
        "libraries": ["thermo", "scipy"],
        "reference": "Halliwell B & Gutteridge JMC (2015) Free Radicals in Biology and Medicine",
        "weight_cns": 0.015,
    },
    "P09": {
        "title_en": "Digital Pharmacovigilance Engine",
        "title_ar": "محرك الفارماكوفيجلانس الرقمي",
        "class": "A_surrogate",
        "cns_relevant": False,
        "dds_dependent": False,
        "method_surrogate":
            "Predicts metabolite organ accumulation: liver, kidney, lung. "
            "Score = 100 × (1 - max_accumulation_risk). Uses SMILES SoM "
            "(Site of Metabolism) heuristics.",
        "method_deep": "Full SMARTS-based metabolite prediction (BioTransformer)",
        "libraries": ["rdkit"],
        "reference": "Djoumbou-Feunang Y et al (2019) J Cheminform 11:2",
        "weight_cns": 0.010,
    },
    "P10": {
        "title_en": "LNP Ionization State Predictor",
        "title_ar": "حالة تأين الـ LNP",
        "class": "A_surrogate",
        "cns_relevant": True,
        "dds_dependent": True,
        "method_surrogate":
            "Henderson-Hasselbalch: charge_at_pH = f(pKa, pH). "
            "Compartments: plasma (7.4), endosome (5.5), lysosome (4.5). "
            "Score = ionization_optimal_for_endosomal_escape.",
        "method_deep": "Constant-pH MD simulation",
        "libraries": ["numpy"],
        "reference": "Hafez IM et al (2001) Adv Drug Deliv Rev 47:139",
        "weight_cns": 0.012,
    },
    "P11": {
        "title_en": "Formulation Instability Fingerprint",
        "title_ar": "بصمة عدم الاستقرار",
        "class": "A_surrogate",
        "cns_relevant": False,
        "dds_dependent": True,
        "method_surrogate":
            "Identifies weakest bond from SMILES. Score = activation "
            "energy of weakest bond (kcal/mol) normalized 0-100. "
            "RDKit BondGetBondType + bond dissociation energy table.",
        "method_deep": "DFT bond dissociation energies",
        "libraries": ["rdkit"],
        "reference": "Luo YR (2007) Comprehensive Handbook of Chemical Bond Energies",
        "weight_cns": 0.010,
    },
    "P12": {
        "title_en": "CNS Disease-Stage-Aware Dosing",
        "title_ar": "جرعات حسب مرحلة المرض",
        "class": "A_surrogate",
        "cns_relevant": True,
        "dds_dependent": True,
        "method_surrogate":
            "Adjusts effective BBB permeability by stage: Stage1 (intact), "
            "Stage2 (-15%), Stage3 (-40%), Stage4 (-60%). Score = "
            "100 × (cns_concentration_target / cns_concentration_predicted).",
        "method_deep": "Stage-specific PBPK model with full BBB physiology",
        "libraries": ["scipy"],
        "reference": "Sweeney MD et al (2018) Nat Rev Neurol 14:133",
        "weight_cns": 0.030,   # CNS direct
    },

    # ════════════════════════════════════════════════════════════════════
    # PRINCIPLES 13-21 — Block 2 (PBPK Twin, Release Profile, Shelf-life,
    #   Scale-up, Nanotox, Active Targeting, QbD, Cost, Pre-IND)
    # ════════════════════════════════════════════════════════════════════
    "P13": {
        "title_en": "PBPK Digital Twin",
        "title_ar": "التوأم الرقمي للمريض",
        "class": "A_surrogate",
        "cns_relevant": True,
        "dds_dependent": True,
        "method_surrogate":
            "3-compartment PBPK: blood, brain, peripheral. Estimates "
            "AUC_brain/AUC_plasma from BBB permeability + clearance. "
            "Score = 100 × min(1.0, AUC_ratio / 0.05).",
        "method_deep": "Full multi-organ PBPK ODE solver (scipy.integrate)",
        "libraries": ["scipy"],
        "reference": "Hammarlund-Udenaes M et al (2008) Pharm Res 25:1737",
        "weight_cns": 0.030,   # CNS direct
    },
    "P14": {
        "title_en": "In-silico Dissolution & Release Profile",
        "title_ar": "منحنى التحرر",
        "class": "A_surrogate",
        "cns_relevant": False,
        "dds_dependent": True,
        "method_surrogate":
            "Carrier-kinetics lookup: t50 from (carrier × release_kinetics). "
            "Score = 100 if 12h ≤ t50 ≤ 72h, decay outside.",
        "method_deep": "Full Higuchi/Korsmeyer-Peppas/Weibull model fit",
        "libraries": ["scipy"],
        "reference": "Costa P & Lobo JM (2001) Eur J Pharm Sci 13:123",
        "weight_cns": 0.018,
    },
    "P15": {
        "title_en": "Shelf-life & Degradation Predictor",
        "title_ar": "العمر التخزيني",
        "class": "A_surrogate",
        "cns_relevant": False,
        "dds_dependent": True,
        "method_surrogate":
            "Arrhenius extrapolation: shelf25C = baseline × (0.7 + 0.3·EE). "
            "Carrier baselines (months): liposome 18, PLGA 36, polymer 36.",
        "method_deep": "ICH Q1A real-time + accelerated stability",
        "libraries": ["thermo"],
        "reference": "Kennon L (1964) J Pharm Sci 53:815; ICH Q1A(R2)",
        "weight_cns": 0.012,
    },
    "P16": {
        "title_en": "Scale-up & Manufacturability",
        "title_ar": "قابلية التصنيع",
        "class": "A_surrogate",
        "cns_relevant": False,
        "dds_dependent": True,
        "method_surrogate":
            "Scale-up readiness lookup (lab/pilot/clinical/commercial) × "
            "shear-stress tolerance from carrier elasticity. Score 0-100.",
        "method_deep": "CFD simulation of 1000L bioreactor mixing",
        "libraries": ["scipy"],
        "reference": "am Ende DJ (2011) Chemical Engineering in the Pharmaceutical Industry",
        "weight_cns": 0.010,
    },
    "P17": {
        "title_en": "Nanotoxicity & Immunogenicity Screening",
        "title_ar": "سمية النانو والمناعة",
        "class": "A_surrogate",
        "cns_relevant": True,
        "dds_dependent": True,
        "method_surrogate":
            "Composite: hemolysis_risk (zeta), complement_activation (PEG), "
            "RES_uptake (size), oxidative_stress (surface). Score = "
            "100 - composite_risk.",
        "method_deep": "Full immunogenicity QSAR (NanoSafer, in vitro models)",
        "libraries": ["sklearn", "rdkit"],
        "reference": "Nel A et al (2006) Science 311:622",
        "weight_cns": 0.018,
    },
    "P18": {
        "title_en": "Active Targeting & Receptor Binding",
        "title_ar": "الاستهداف النشط",
        "class": "A_surrogate",
        "cns_relevant": True,
        "dds_dependent": True,
        "method_surrogate":
            "Ligand-affinity table for BBB receptors (Tf, RVG29, ApoE, "
            "LRP1, insulin, leptin) × ligand density per nm². Score 0-100.",
        "method_deep": "Full MM/GBSA + atomistic MD docking",
        "libraries": ["rdkit"],
        "reference": "Pardridge WM (2020) Fluids Barriers CNS 17:62",
        "weight_cns": 0.025,   # CNS direct
    },
    "P19": {
        "title_en": "QbD - Quality by Design Engine",
        "title_ar": "محرك جودة التصميم",
        "class": "A_surrogate",
        "cns_relevant": False,
        "dds_dependent": True,
        "method_surrogate":
            "Design-space coverage: how many CQAs (size, zeta, EE, PDI) "
            "fall within ICH Q8 acceptance ranges. Score = % within spec.",
        "method_deep": "Full multivariate DoE + 3D design-space generation",
        "libraries": ["sklearn", "scipy"],
        "reference": "ICH Q8(R2) Pharmaceutical Development",
        "weight_cns": 0.010,
    },
    "P20": {
        "title_en": "Cost-Efficiency Engine",
        "title_ar": "حاسبة التكلفة",
        "class": "A_surrogate",
        "cns_relevant": False,
        "dds_dependent": True,
        "method_surrogate":
            "Estimates manufacturing $/dose from carrier_class + ligand "
            "(Tf=$$, RVG29=$$$, none=$). Score = 100 × (1 - cost/upper_bound).",
        "method_deep": "Live API fetch from Sigma-Aldrich + ChemSpider pricing",
        "libraries": ["requests"],
        "reference": "Cost-of-goods analysis frameworks (Pharm Eng J 2019)",
        "weight_cns": 0.008,
    },
    "P21": {
        "title_en": "Pre-IND Regulatory Reports",
        "title_ar": "تقارير ما قبل التجارب",
        "class": "C_translational",
        "cns_relevant": False,
        "dds_dependent": False,
        "method_surrogate": None,
        "method_deep": "Auto-generates FDA Pre-IND Word document for Top-1",
        "libraries": ["python-docx"],
        "reference": "FDA 21 CFR 312.23 (IND content)",
        "weight_cns": 0.0,    # Translational only
    },

    # ════════════════════════════════════════════════════════════════════
    # PRINCIPLES 22-32 — Block 3 (Protein Corona, Crystal Polymorph,
    #   Shear Stress, Leachables, Microbiome, Lyophilization, 3D Print,
    #   Exosome, QM/MM Cleavage, Biodistribution, FTO Patents)
    # ════════════════════════════════════════════════════════════════════
    "P22": {
        "title_en": "Protein Corona Predictor",
        "title_ar": "كورونا البروتين",
        "class": "A_surrogate",
        "cns_relevant": True,
        "dds_dependent": True,
        "method_surrogate":
            "Corona thickness ∝ |zeta| + size + hydrophobicity. Score = "
            "100 × exp(-thickness_nm/5). PEG > 5% protects (×1.3 boost).",
        "method_deep": "Full proteomic corona MS prediction (Mass-Spec lib)",
        "libraries": ["sklearn"],
        "reference": "Tenzer S et al (2013) Nat Nanotechnol 8:772",
        "weight_cns": 0.020,
    },
    "P23": {
        "title_en": "Dynamic Crystal Polymorphism",
        "title_ar": "التغير البلوري",
        "class": "A_surrogate",
        "cns_relevant": False,
        "dds_dependent": False,
        "method_surrogate":
            "Number of rotatable bonds + H-bond pattern → polymorph "
            "risk score. RDKit RotatableBondCount + HBD/HBA. Score = "
            "100 - risk_pct.",
        "method_deep": "CSP (Crystal Structure Prediction) via DFT",
        "libraries": ["rdkit"],
        "reference": "Bernstein J (2020) Polymorphism in Molecular Crystals",
        "weight_cns": 0.008,
    },
    "P24": {
        "title_en": "Shear-Stress & Scale-Up Collapse",
        "title_ar": "إجهاد القص",
        "class": "A_surrogate",
        "cns_relevant": False,
        "dds_dependent": True,
        "method_surrogate":
            "Critical shear rate (s⁻¹): liposome=10⁴, PLGA=10⁶, polymer=10⁵. "
            "Score = log10(critical_shear/operating_shear) × 30, capped 100.",
        "method_deep": "Full CFD + MD coupling for 1000L reactor",
        "libraries": ["scipy"],
        "reference": "Maa YF & Hsu CC (1996) Biotechnol Bioeng 51:458",
        "weight_cns": 0.010,
    },
    "P25": {
        "title_en": "Extractables & Leachables",
        "title_ar": "تسرب التغليف",
        "class": "A_surrogate",
        "cns_relevant": False,
        "dds_dependent": True,
        "method_surrogate":
            "Container compatibility lookup (glass=safest, PE=med, "
            "PVC=risk for lipophilic). Score from carrier-LogP × packaging.",
        "method_deep": "Full LC-MS/MS leachables database + 2-yr extraction sim",
        "libraries": ["pandas"],
        "reference": "USP <1663>/<1664> Extractables/Leachables",
        "weight_cns": 0.008,
    },
    "P26": {
        "title_en": "Microbiome-Excipient Interactions",
        "title_ar": "تفاعل الميكروبيوم",
        "class": "A_surrogate",
        "cns_relevant": False,
        "dds_dependent": True,
        "method_surrogate":
            "Excipient-degradability index: PEG (low), chitosan (high), "
            "PLGA (low), lactose (high). Score = 100 - mean_degradability.",
        "method_deep": "Full microbiome enzyme database (GMrepo + KEGG)",
        "libraries": ["pandas"],
        "reference": "Zimmermann M et al (2019) Nature 570:462",
        "weight_cns": 0.005,
    },
    "P27": {
        "title_en": "Lyophilization Cycle Optimizer",
        "title_ar": "محسّن دورة التجفيف",
        "class": "A_surrogate",
        "cns_relevant": False,
        "dds_dependent": True,
        "method_surrogate":
            "Tg' lookup by carrier + excipient (sucrose +cryo, trehalose "
            "+cryo). Score = 100 - cake_collapse_risk based on carrier_Tg'.",
        "method_deep": "Full SMART freeze-drying cycle optimization",
        "libraries": ["scipy", "thermo"],
        "reference": "Pikal MJ (2002) Pharmaceutical Lyophilization",
        "weight_cns": 0.005,
    },
    "P28": {
        "title_en": "3D-Printed Polypill Rheology",
        "title_ar": "ريولوجيا الطباعة ثلاثية الأبعاد",
        "class": "A_surrogate",
        "cns_relevant": False,
        "dds_dependent": True,
        "method_surrogate":
            "Printability index = f(viscosity, shear-thinning, recovery). "
            "Carrier-class lookup. Score 0-100.",
        "method_deep": "Full rheology curve simulation",
        "libraries": ["scipy"],
        "reference": "Trenfield SJ et al (2019) Adv Drug Deliv Rev 138:139",
        "weight_cns": 0.005,
    },
    "P29": {
        "title_en": "Biomimetic & Exosome Engineering",
        "title_ar": "هندسة الإكسوزومات",
        "class": "A_surrogate",
        "cns_relevant": True,
        "dds_dependent": True,
        "method_surrogate":
            "Stealth-from-macrophages score. RBC-coated +30, exosome +40, "
            "tumor-cell-coated +25, bare -20.",
        "method_deep": "Full membrane-fusion MD + macrophage uptake model",
        "libraries": ["MDAnalysis"],
        "reference": "Hu CMJ et al (2011) Proc Natl Acad Sci 108:10980",
        "weight_cns": 0.012,
    },
    "P30": {
        "title_en": "QM/MM Stimuli-Responsive Cleavage",
        "title_ar": "تنشيط كمي للأدوية",
        "class": "A_surrogate",
        "cns_relevant": False,
        "dds_dependent": True,
        "method_surrogate":
            "Bond cleavage E_a estimation by RDKit bond order + pH-trigger. "
            "Score = 100 × selectivity (target_pH vs blood_pH).",
        "method_deep": "Full QM/MM with PySCF or ORCA",
        "libraries": ["rdkit", "qcelemental"],
        "reference": "Senn HM & Thiel W (2009) Angew Chem Int Ed 48:1198",
        "weight_cns": 0.010,
    },
    "P31": {
        "title_en": "In-Silico Biodistribution",
        "title_ar": "التوزيع الحيوي",
        "class": "A_surrogate",
        "cns_relevant": True,
        "dds_dependent": True,
        "method_surrogate":
            "Organ-uptake fractions from size + zeta + ligand. "
            "Brain%, liver%, spleen%, kidney%. Score = 100 × brain_fraction "
            "(target ≥ 5% for CNS).",
        "method_deep": "Full whole-body PBPK with organ-specific kinetics",
        "libraries": ["scipy"],
        "reference": "Wilhelm S et al (2016) Nat Rev Mater 1:16014",
        "weight_cns": 0.022,   # CNS direct
    },
    "P32": {
        "title_en": "Automated FTO & IP Evader",
        "title_ar": "تجنب براءات الاختراع",
        "class": "C_translational",
        "cns_relevant": False,
        "dds_dependent": False,
        "method_surrogate": None,
        "method_deep": "Patent landscape search via Lens.org / Google Patents API",
        "libraries": ["requests"],
        "reference": "Lens.org open patent database",
        "weight_cns": 0.0,
    },

    # ════════════════════════════════════════════════════════════════════
    # PRINCIPLES 33-44 — Block 4 (BBB Quantum Breaker, DNA Logic Gates,
    #   Microgravity, Geopolitical, Eco-Destructible, Glymphatic Trap,
    #   Microglial Activation, Intranasal, Exosome Loading,
    #   Spatial Targeting, FUS Responsive, CNS-PBPK Time Machine)
    # ════════════════════════════════════════════════════════════════════
    "P33": {
        "title_en": "BBB Quantum Breaker (Trojan-Horse Design)",
        "title_ar": "قاهر BBB",
        "class": "A_surrogate",
        "cns_relevant": True,
        "dds_dependent": True,
        "method_surrogate":
            "Tf-receptor docking score from ligand identity × density × "
            "size compatibility (50-150 nm window). Score 0-100.",
        "method_deep": "Atomistic docking to TfR1/LRP1 + SMD pulling simulation",
        "libraries": ["rdkit", "MDAnalysis"],
        "reference": "Pardridge WM (2020) Fluids Barriers CNS 17:62",
        "weight_cns": 0.040,   # CNS direct, top weight
    },
    "P34": {
        "title_en": "DNA Logic Gates & Bio-computing",
        "title_ar": "بوابات منطق DNA",
        "class": "A_surrogate",
        "cns_relevant": False,
        "dds_dependent": True,
        "method_surrogate":
            "Logic-gate compatibility score: DNA-based carriers get +50, "
            "polymer-based +20, lipid -10. Score reflects programmability.",
        "method_deep": "Full strand-displacement simulation (NUPACK)",
        "libraries": ["networkx"],
        "reference": "Douglas SM et al (2012) Science 335:831",
        "weight_cns": 0.005,
    },
    "P35": {
        "title_en": "Microgravity Formulation Engine",
        "title_ar": "صياغات الفضاء",
        "class": "A_surrogate",
        "cns_relevant": False,
        "dds_dependent": True,
        "method_surrogate":
            "Sedimentation Péclet number proxy: Pe = (ρ-ρ₀)·g·r²/(kT). "
            "Score reflects gravity-independence (smaller = better).",
        "method_deep": "Full diffusion + sedimentation ODE in microgravity",
        "libraries": ["scipy"],
        "reference": "Reichert B et al (2019) NPJ Microgravity 5:18",
        "weight_cns": 0.003,
    },
    "P36": {
        "title_en": "Geopolitical Supply-Chain Resilience",
        "title_ar": "مرونة سلسلة الإمداد",
        "class": "A_surrogate",
        "cns_relevant": False,
        "dds_dependent": True,
        "method_surrogate":
            "Carrier-supplier diversity index. Common materials (lipids, "
            "PEG, PLGA) score high; rare/single-source materials score low.",
        "method_deep": "Live API fetch from supplier databases + risk model",
        "libraries": ["requests"],
        "reference": "FDA Drug Shortage Database analysis",
        "weight_cns": 0.005,
    },
    "P37": {
        "title_en": "Eco-Destructible Pharma",
        "title_ar": "الصيدلة الخضراء",
        "class": "A_surrogate",
        "cns_relevant": False,
        "dds_dependent": True,
        "method_surrogate":
            "Biodegradability index from carrier identity + UV-sensitive "
            "bonds. PLGA 90, polymer 70, lipid 95, metallic 5.",
        "method_deep": "Full ECOSAR + biodegradation kinetics database",
        "libraries": ["rdkit"],
        "reference": "Boxall ABA (2004) EMBO Rep 5:1110",
        "weight_cns": 0.005,
    },
    "P38": {
        "title_en": "Glymphatic Clearance Trap",
        "title_ar": "النظام الجليمفاوي",
        "class": "A_surrogate",
        "cns_relevant": True,
        "dds_dependent": True,
        "method_surrogate":
            "Stokes-Einstein in CSF: D = kT/(6πηr). Score for retention "
            "balance: too-small = washed out, too-large = stuck in vessel. "
            "Optimum 80-150 nm.",
        "method_deep": "Full glymphatic CSF flow model with sleep cycles",
        "libraries": ["scipy"],
        "reference": "Iliff JJ et al (2012) Sci Transl Med 4:147ra111",
        "weight_cns": 0.035,   # CNS direct
    },
    "P39": {
        "title_en": "Microglial Activation & Neuroinflammation",
        "title_ar": "نشاط الخلايا الدبقية",
        "class": "A_surrogate",
        "cns_relevant": True,
        "dds_dependent": True,
        "method_surrogate":
            "Inflammation risk: PEG ≥5% → +30 stealth. Cationic surface → "
            "-40 (TLR4 activation). Score = 100 - inflammation_risk.",
        "method_deep": "Full TLR4/NLRP3 activation pathway model",
        "libraries": ["sklearn"],
        "reference": "Hickman SE et al (2018) Nat Neurosci 21:1359",
        "weight_cns": 0.025,   # CNS direct
    },
    "P40": {
        "title_en": "Intranasal-to-Brain Delivery",
        "title_ar": "التوصيل عبر الأنف",
        "class": "A_surrogate",
        "cns_relevant": True,
        "dds_dependent": True,
        "method_surrogate":
            "Mucoadhesion + thermo-responsive index. Score boosted for "
            "chitosan, poloxamer 407, hydroxyethyl cellulose. Cap 100.",
        "method_deep": "Full nasal cavity CFD + olfactory neuron model",
        "libraries": ["scipy"],
        "reference": "Illum L (2003) J Pharm Pharmacol 56:3",
        "weight_cns": 0.015,
    },
    "P41": {
        "title_en": "Exosome Cargo Loading Thermodynamics",
        "title_ar": "تحميل الإكسوزومات",
        "class": "A_surrogate",
        "cns_relevant": True,
        "dds_dependent": True,
        "method_surrogate":
            "Sonication/electroporation efficiency lookup by exosome size "
            "+ drug MW. Score reflects loading yield 0-100%.",
        "method_deep": "Full membrane mechanics MD simulation",
        "libraries": ["MDAnalysis", "scipy"],
        "reference": "Alvarez-Erviti L et al (2011) Nat Biotechnol 29:341",
        "weight_cns": 0.010,
    },
    "P42": {
        "title_en": "Region-Specific Spatiotemporal Navigation",
        "title_ar": "الملاحة المكانية في المخ",
        "class": "A_surrogate",
        "cns_relevant": True,
        "dds_dependent": True,
        "method_surrogate":
            "Region-specific receptor targeting: Hippocampus (NMDA, "
            "α7-nAChR), Substantia Nigra (DA D2), Cortex (mAChR). "
            "Score = ligand-region match × density.",
        "method_deep": "Full brain-region perfusion + receptor density atlas",
        "libraries": ["pandas"],
        "reference": "Nutt DJ & Need AC (2014) Lancet Psychiatry 1:78",
        "weight_cns": 0.025,   # CNS direct
    },
    "P43": {
        "title_en": "FUS-Responsive Nanocarriers",
        "title_ar": "نواقل تستجيب للموجات الصوتية",
        "class": "A_surrogate",
        "cns_relevant": True,
        "dds_dependent": True,
        "method_surrogate":
            "FUS-responsiveness: microbubble-conjugated +50, gas-filled "
            "liposome +30, solid carriers 0. Threshold-frequency match.",
        "method_deep": "Full acoustic radiation force + cavitation MD",
        "libraries": ["scipy"],
        "reference": "Hynynen K & Jolesz FA (1998) Ultrasound Med Biol 24:275",
        "weight_cns": 0.018,
    },
    "P44": {
        "title_en": "CNS-Specific PBPK Time-Machine",
        "title_ar": "آلة الزمن للمخ",
        "class": "A_surrogate",
        "cns_relevant": True,
        "dds_dependent": True,
        "method_surrogate":
            "Time-course estimate: t10 (10% to brain), t50, t90 from "
            "BBB perm + clearance. Score = AUC over therapeutic window.",
        "method_deep": "Full PBPK ODE: blood + brain + CSF + glymphatic "
                        "compartments with sleep-cycle modulation",
        "libraries": ["scipy"],
        "reference": "Bies RR et al (2019) Annu Rev Pharmacol Toxicol 59:131",
        "weight_cns": 0.040,   # CNS direct, top weight
    },

    # ════════════════════════════════════════════════════════════════════
    # PRINCIPLES 45-50 — Block 5 (FDA Compliance, DDI, FEP+, Off-Target,
    #   Organ-on-Chip, Cryo-Chain)
    # ════════════════════════════════════════════════════════════════════
    "P45": {
        "title_en": "FDA 21 CFR Part 11 Compliance",
        "title_ar": "الامتثال للـ FDA",
        "class": "C_translational",
        "cns_relevant": False,
        "dds_dependent": False,
        "method_surrogate": None,
        "method_deep": "Audit trail + e-signature + tamper-proof logging",
        "libraries": ["sqlalchemy"],
        "reference": "21 CFR Part 11 (FDA)",
        "weight_cns": 0.0,
    },
    "P46": {
        "title_en": "Polypharmacy & DDI Simulator",
        "title_ar": "محاكي تفاعل الأدوية",
        "class": "A_surrogate",
        "cns_relevant": True,
        "dds_dependent": False,
        "method_surrogate":
            "CYP-inhibition risk from SMILES (CYP3A4, CYP2D6, CYP2C9). "
            "Score = 100 × (1 - max_inhibition_risk).",
        "method_deep": "Full Simcyp-style population PBPK with co-meds",
        "libraries": ["rdkit"],
        "reference": "Jamei M et al (2009) Br J Clin Pharmacol 67:472",
        "weight_cns": 0.012,
    },
    "P47": {
        "title_en": "Free Energy Perturbation (FEP+)",
        "title_ar": "اضطراب الطاقة الحرة",
        "class": "B_deep",
        "cns_relevant": True,
        "dds_dependent": True,
        "method_surrogate":
            "Surrogate: docking score (AutoDock Vina) for top-1 ligand-"
            "receptor pair. Class B promotes to FEP+ for confirmation.",
        "method_deep": "Full FEP+ via OpenMM/Schrödinger integration",
        "libraries": ["MDAnalysis", "scipy"],
        "reference": "Wang L et al (2015) J Am Chem Soc 137:2695",
        "weight_cns": 0.025,
    },
    "P48": {
        "title_en": "Off-Target Toxicity & QSAR (50-receptor)",
        "title_ar": "السمية خارج الهدف",
        "class": "A_surrogate",
        "cns_relevant": True,
        "dds_dependent": False,
        "method_surrogate":
            "QSAR vs hERG (cardiac), 5HT2B (cardiac), AhR (hepato), "
            "MAO. Score = 100 - max_off_target_risk.",
        "method_deep": "Full 50-receptor docking panel (BindingDB)",
        "libraries": ["rdkit", "sklearn"],
        "reference": "Bowes J et al (2012) Nat Rev Drug Discov 11:909",
        "weight_cns": 0.015,
    },
    "P49": {
        "title_en": "Organ-on-a-Chip Simulator",
        "title_ar": "الأعضاء على شريحة",
        "class": "A_surrogate",
        "cns_relevant": True,
        "dds_dependent": True,
        "method_surrogate":
            "Microphysiological compatibility: shear stress (DDS robust?), "
            "cell-uptake (size match?), oxygen consumption proxy. Score 0-100.",
        "method_deep": "Full multiphysics microfluidic simulation",
        "libraries": ["scipy"],
        "reference": "Bhatia SN & Ingber DE (2014) Nat Biotechnol 32:760",
        "weight_cns": 0.012,
    },
    "P50": {
        "title_en": "Cryo-Chain Thermal Excursion Predictor",
        "title_ar": "صدمات السلسلة الباردة",
        "class": "A_surrogate",
        "cns_relevant": False,
        "dds_dependent": True,
        "method_surrogate":
            "Lipid phase-transition margin: |37 − Tm|. LNP threshold "
            "tolerance lookup. Score reflects survival under -20°C × 4h.",
        "method_deep": "Full coarse-grained MD of lipid phase transition",
        "libraries": ["MDAnalysis"],
        "reference": "Crommelin DJA et al (2021) Int J Pharm 593:120163",
        "weight_cns": 0.010,
    },

    # ════════════════════════════════════════════════════════════════════
    # PRINCIPLES 51-62 — From the second numbering block (21-32 → P51-P62)
    # which the source file re-numbered. These are 12 NEW principles after
    # the original 50.
    # ════════════════════════════════════════════════════════════════════
    "P51": {
        "title_en": "Terminal Sterilization Survivability",
        "title_ar": "النجاة من التعقيم",
        "class": "A_surrogate",
        "cns_relevant": False,
        "dds_dependent": True,
        "method_surrogate":
            "Carrier-radiation tolerance: liposome 10kGy (low), PLGA 25kGy "
            "(med), polymer 25kGy. Score reflects gamma/autoclave survival.",
        "method_deep": "Full radical-chain damage MD + dose-response curve",
        "libraries": ["thermo"],
        "reference": "Reid BD (1995) J Pharm Sci Technol 49:83",
        "weight_cns": 0.005,
    },
    "P52": {
        "title_en": "Continuous Manufacturing Digital Twin",
        "title_ar": "التصنيع المستمر",
        "class": "A_surrogate",
        "cns_relevant": False,
        "dds_dependent": True,
        "method_surrogate":
            "Continuous-process readiness lookup: lipid NPs (ready), PLGA "
            "(ready), exosomes (challenging), dendrimers (lab-only). 0-100.",
        "method_deep": "Full process digital twin with feedback control",
        "libraries": ["scipy"],
        "reference": "Lee SL et al (2015) J Pharm Innov 10:191",
        "weight_cns": 0.005,
    },
    "P53": {
        "title_en": "Dark Data & Negative Results Vault",
        "title_ar": "البيانات المظلمة",
        "class": "A_surrogate",
        "cns_relevant": False,
        "dds_dependent": True,
        "method_surrogate":
            "Failure-pattern matching against known failed CNS DDS in "
            "database (size/zeta/ligand combos with documented failure). "
            "Score = 100 - similarity_to_failed.",
        "method_deep": "Full ML similarity model on large failure corpus",
        "libraries": ["sklearn"],
        "reference": "Begley CG & Ellis LM (2012) Nature 483:531",
        "weight_cns": 0.008,
    },
    "P54": {
        "title_en": "Pharmacogenomic-Guided Targeting",
        "title_ar": "ديناميكا الجينات",
        "class": "A_surrogate",
        "cns_relevant": True,
        "dds_dependent": False,
        "method_surrogate":
            "CYP2D6/CYP3A4 metabolism + indication-specific gene panel. "
            "Score = % patient variants well-served.",
        "method_deep": "Full PharmGKB integration",
        "libraries": ["pandas"],
        "reference": "Whirl-Carrillo M et al (2012) Clin Pharmacol Ther 92:414",
        "weight_cns": 0.010,
    },
    "P55": {
        "title_en": "Automated Grant & NIH Proposal Generator",
        "title_ar": "مولد المنح",
        "class": "C_translational",
        "cns_relevant": False,
        "dds_dependent": False,
        "method_surrogate": None,
        "method_deep": "Auto-generates NIH R01 Word document for Top-1",
        "libraries": ["python-docx"],
        "reference": "NIH SF424 Application Guide",
        "weight_cns": 0.0,
    },
    "P56": {
        "title_en": "Patentability Score Engine",
        "title_ar": "مُقيّم براءة الاختراع",
        "class": "C_translational",
        "cns_relevant": False,
        "dds_dependent": False,
        "method_surrogate": None,
        "method_deep": "USPTO + Lens.org search + novelty score 0-100",
        "libraries": ["requests"],
        "reference": "USPTO patent novelty criteria",
        "weight_cns": 0.0,
    },
    "P57": {
        "title_en": "Microfluidics & LNP Synthesis Digital Twin",
        "title_ar": "التوأم الرقمي للموائع الدقيقة",
        "class": "A_surrogate",
        "cns_relevant": False,
        "dds_dependent": True,
        "method_surrogate":
            "Microfluidics-readiness for target size 50-150 nm. Carrier-"
            "specific flow-rate-window estimation.",
        "method_deep": "Full CFD of T-junction or staggered herringbone mixer",
        "libraries": ["scipy"],
        "reference": "Belliveau NM et al (2012) Mol Ther Nucleic Acids 1:e37",
        "weight_cns": 0.005,
    },
    "P58": {
        "title_en": "Impurity Cascade Predictor",
        "title_ar": "تأثير الفراشة للشوائب",
        "class": "A_surrogate",
        "cns_relevant": False,
        "dds_dependent": True,
        "method_surrogate":
            "Common impurity-drug reactivity matrix. Carrier-residual "
            "metals (PLGA Sn-traces, polymer initiators). Score 0-100.",
        "method_deep": "Full QM/MM cascade simulation over 2-yr aging",
        "libraries": ["rdkit", "qcelemental"],
        "reference": "ICH Q3D Elemental Impurities",
        "weight_cns": 0.008,
    },
    "P59": {
        "title_en": "4D Shape-Shifting Carriers",
        "title_ar": "نواقل متغيرة الشكل",
        "class": "A_surrogate",
        "cns_relevant": False,
        "dds_dependent": True,
        "method_surrogate":
            "Stimuli-responsive polymer index. pH-responsive +50, "
            "temp-responsive +40, redox-responsive +30, none = 0.",
        "method_deep": "Full coarse-grained MD of morphological transition",
        "libraries": ["MDAnalysis"],
        "reference": "Stuart MAC et al (2010) Nat Mater 9:101",
        "weight_cns": 0.008,
    },
    "P60": {
        "title_en": "Swarm Nanorobotics Intelligence",
        "title_ar": "ذكاء السرب النانوي",
        "class": "A_surrogate",
        "cns_relevant": False,
        "dds_dependent": True,
        "method_surrogate":
            "Cooperativity score from chemoattractant carrier. Most "
            "carriers score 0; specialized swarm carriers +60-100.",
        "method_deep": "Full agent-based simulation (Mesa)",
        "libraries": ["networkx"],
        "reference": "Servant A et al (2015) Sci Robot 1:eaaq1155",
        "weight_cns": 0.003,
    },
    "P61": {
        "title_en": "Synthetic Clinical Trials & Virtual Humans",
        "title_ar": "التجارب السريرية الاصطناعية",
        "class": "A_surrogate",
        "cns_relevant": True,
        "dds_dependent": True,
        "method_surrogate":
            "Virtual phase-1 efficacy estimate from PBPK + variability. "
            "Cohort: 100 virtual patients (age, weight, CYP, BBB integrity). "
            "Score = % responders ≥ therapeutic threshold.",
        "method_deep": "Full Monte-Carlo population PBPK + outcome model",
        "libraries": ["scipy"],
        "reference": "Polasek TM & Rostami-Hodjegan A (2020) AAPS J 22:97",
        "weight_cns": 0.015,
    },
    "P62": {
        "title_en": "Biobetter / Supergeneric Generator",
        "title_ar": "مولد الـ Biobetter",
        "class": "A_surrogate",
        "cns_relevant": False,
        "dds_dependent": True,
        "method_surrogate":
            "Novelty distance from on-market reference DDS. Tanimoto-based "
            "if SMILES + carrier-class fingerprint different from references.",
        "method_deep": "Full patent-aware molecule generator",
        "libraries": ["rdkit"],
        "reference": "Ekins S et al (2019) Drug Discov Today 24:2104",
        "weight_cns": 0.008,
    },
}


# ═════════════════════════════════════════════════════════════════════════
# PARTITIONS BY CLASS
# ═════════════════════════════════════════════════════════════════════════
CLASS_A_SURROGATE       = [pid for pid, p in PRINCIPLES_62.items()
                            if p["class"] == "A_surrogate"]
CLASS_B_DEEP            = [pid for pid, p in PRINCIPLES_62.items()
                            if p["class"] == "B_deep"]
CLASS_C_TRANSLATIONAL   = [pid for pid, p in PRINCIPLES_62.items()
                            if p["class"] == "C_translational"]

assert len(PRINCIPLES_62) == 62, f"Expected 62, got {len(PRINCIPLES_62)}"

# Verify weights sum across Class A + B (Class C has weight_cns = 0
# in DDS ranking — translational only).
_weight_total_raw = sum(p["weight_cns"] for p in PRINCIPLES_62.values()
                         if p["class"] in ("A_surrogate", "B_deep"))

# Auto-normalize so Class A+B weights sum to exactly 1.0.
# Preserves the relative CNS-focused ordering set above.
if _weight_total_raw > 0 and abs(_weight_total_raw - 1.0) > 0.001:
    _scale = 1.0 / _weight_total_raw
    for _pid, _p in PRINCIPLES_62.items():
        if _p["class"] in ("A_surrogate", "B_deep"):
            _p["weight_cns"] = round(_p["weight_cns"] * _scale, 5)

# Re-verify
_weight_total = sum(p["weight_cns"] for p in PRINCIPLES_62.values()
                     if p["class"] in ("A_surrogate", "B_deep"))
assert 0.99 < _weight_total < 1.01, \
    f"Weight sum after normalization {_weight_total} not ≈ 1.0"


def get_class_a_principles() -> list[str]:
    """Principles run on every DDS (the surrogate fast-screen)."""
    return CLASS_A_SURROGATE


def get_class_b_principles() -> list[str]:
    """Principles run on Top-1 only (deep physics validation)."""
    return CLASS_B_DEEP


def get_class_c_principles() -> list[str]:
    """Principles run on Top-1 AFTER deep validation (translational)."""
    return CLASS_C_TRANSLATIONAL


def get_principle(pid: str) -> dict:
    return PRINCIPLES_62[pid]


def summarize() -> dict:
    """Quick summary used by tests and the rationale sheet."""
    return {
        "total":             len(PRINCIPLES_62),
        "class_A_surrogate": len(CLASS_A_SURROGATE),
        "class_B_deep":      len(CLASS_B_DEEP),
        "class_C_admin":     len(CLASS_C_TRANSLATIONAL),
        "cns_direct_count":  sum(1 for p in PRINCIPLES_62.values() if p["cns_relevant"]),
        "dds_dependent":     sum(1 for p in PRINCIPLES_62.values() if p["dds_dependent"]),
        "weight_total_A_plus_B": round(_weight_total, 4),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(summarize(), indent=2))
    print(f"\nClass A ({len(CLASS_A_SURROGATE)}):", CLASS_A_SURROGATE)
    print(f"\nClass B ({len(CLASS_B_DEEP)}):",      CLASS_B_DEEP)
    print(f"\nClass C ({len(CLASS_C_TRANSLATIONAL)}):", CLASS_C_TRANSLATIONAL)
