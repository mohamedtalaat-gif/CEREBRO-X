#!/usr/bin/env python3
"""
================================================================================
CEREBRO-X — MASTER RUNNER
================================================================================
File: run.py

SINGLE ENTRY POINT. Drop this next to your other .py files and run it.

What changed from v1:
  ✦ No more hardcoded drug lists — 100% Excel-driven
  ✦ Trial versioning (Trial_0, Trial_1, …) — each new Excel → new folder
  ✦ Hash-based change detection — only re-runs when Excel actually changed
  ✦ Cache invalidation — forces fresh API fetch for every new trial
  ✦ SQLite upsert — always writes latest data, never reads stale cache
  ✦ No GIFs, no videos, no 3D simulation figures
  ✦ One merged PDF per trial — decision-ready

Usage:
  python run.py                   # Full mode (pipeline + DDS + API + scheduler)
  python run.py --headless        # Background only (no API, scheduler only)
  python run.py --pipeline-only   # Run once and exit
  python run.py --dds-only        # DDS analysis only
  python run.py --force           # Force re-run even if Excel unchanged

Cross-platform:
  Windows  → python run.py
  macOS    → python3 run.py
  Linux    → python3 run.py

AUTO-START: Registers itself on first run. After that runs every hour headlessly.
================================================================================
"""

# ─────────────────────────────────────────────────────────────────────────────
# 0.  ANCHOR  (must be first — sets working directory before any imports)
# ─────────────────────────────────────────────────────────────────────────────
import hashlib
import logging
import os
import platform
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    SCRIPT_DIR = Path(os.path.abspath(__file__)).parent
except NameError:
    SCRIPT_DIR = Path(os.path.abspath(sys.argv[0])).parent

# # os.chdir(  # REMOVED: SCRIPT_DIR)  # REMOVED: use absolute pathlib paths for cloud/Docker
sys.path.insert(0, str(SCRIPT_DIR))

# ── Wire all module aliases BEFORE any pipeline imports ───────────────────────
# src/path_resolver.py maps every old flat name (CEREBRO_Pipeline,
# cerebro_molecule_engine, etc.) to its real location in src/.
# It also freezes os.chdir so sub-modules cannot change the working directory.
try:
    import src.path_resolver as _path_resolver  # noqa: F401
except ImportError:
    pass  # Shim files in project root act as fallback

# ─────────────────────────────────────────────────────────────────────────────
# 1.  LOGGING
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(SCRIPT_DIR / "cerebro_run.log", encoding="utf-8"),
    ]
)
log = logging.getLogger("CEREBRO-RUN")

# ─────────────────────────────────────────────────────────────────────────────
# 1b.  BRAND IDENTITY  (apply once, inherited by every matplotlib chart)
# ─────────────────────────────────────────────────────────────────────────────
# cerebro_brand.py is the single source of truth for the visual identity.
# Calling matplotlib_style() here means every figure produced anywhere in
# the pipeline picks up the deep-space + signature-gold theme automatically
# — no per-chart configuration needed.
#
# We also proactively register Inter / Liberation Sans with matplotlib's
# font_manager so the typography is actually used (not just *listed* in
# font.family). Without this step, matplotlib emits the noisy
# "Font family 'Inter' not found" warning even when fonts-inter is
# installed at the OS level — its internal cache simply hasn't been
# rebuilt since the package was added.
try:
    import matplotlib
    matplotlib.use("Agg")           # headless backend (works in Docker / Colab)
    import matplotlib.pyplot as _plt
    from cerebro_brand import matplotlib_style as _brand_style
    from cerebro_brand import register_brand_fonts as _register_fonts
    _font_status = _register_fonts(verbose=False)
    _plt.rcParams.update(_brand_style())
    log.info(f"[BRAND] matplotlib brand style applied  "
              f"(Inter={_font_status['inter']}, "
              f"Liberation={_font_status['liberation']})")
except Exception as _be:
    log.warning(f"[BRAND] matplotlib brand style not applied: {_be}")

# ─────────────────────────────────────────────────────────────────────────────
# 2.  PATHS  (all relative to script dir — works on any OS)
# ─────────────────────────────────────────────────────────────────────────────
EXCEL_GLOB_PATTERNS = [
    "CEREBRO_Input*.xlsx",
    "CEREBRO_Input*.xls",
    "cerebro_input*.xlsx",
]
INPUTS_DIR     = SCRIPT_DIR / "inputs"
RESULTS_ROOT   = SCRIPT_DIR / "outputs"
TRIAL_INDEX_DB = RESULTS_ROOT / "trial_index.db"
CONFIG_DIR     = SCRIPT_DIR / "config"

INPUTS_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# 3.  DEPENDENCY INSTALLER  (fallback — primary installs are in Dockerfile)
# ─────────────────────────────────────────────────────────────────────────────
# Extracted to installer.py as part of splitting run.py's mixed
# responsibilities (docs/AUDIT_REPORT.md section 13). Imported here so
# `install_missing()` keeps working exactly as before at its call site.
from installer import install_missing  # noqa: F401

# ─────────────────────────────────────────────────────────────────────────────
# 4-6.  TRIAL INDEX, EXCEL->YAML CONVERTER, CACHE INVALIDATOR
# ─────────────────────────────────────────────────────────────────────────────
# Extracted to trial_manager.py as part of splitting run.py's mixed
# responsibilities (docs/AUDIT_REPORT.md section 13). Imported here so every
# call site below keeps working unchanged.
from trial_manager import (  # noqa: F401
    _init_trial_db, _excel_hash, find_new_excel_files, register_trial,
    next_trial_dir, excel_to_yaml, invalidate_molecule_cache,
)


# ─────────────────────────────────────────────────────────────────────────────
# 7, 10.  CORE PIPELINE RUNNER, HOURLY SCHEDULER LOOP
# ─────────────────────────────────────────────────────────────────────────────
# Extracted to pipeline_runner.py as part of splitting run.py's mixed
# responsibilities (docs/AUDIT_REPORT.md section 13). Imported here so every
# call site below keeps working unchanged.
from pipeline_runner import (  # noqa: F401
    _admet_flag,
    _augment_single_drug,
    _bbb_score,
    _bbb_score_enhanced,
    _run_dds_from_yaml,
    run_once,
    run_pipeline_from_excel,
)


# ─────────────────────────────────────────────────────────────────────────────
# 11.  INFRASTRUCTURE  (FastAPI + APScheduler)
# ─────────────────────────────────────────────────────────────────────────────

def start_infra(headless: bool = False) -> None:
    log.info("[INFRA] Starting enterprise infrastructure …")
    try:
        from cerebro_enterprise_infra import (
            _HAS_FASTAPI,
            app,
            start_scheduler,
            write_autostart,
        )

        # Patch scheduler to use our Excel-driven loop
        def _scheduled_run():
            log.info("[Scheduler] Hourly run triggered")
            run_once(force=False)

        write_autostart()

        try:
            from datetime import timedelta

            from apscheduler.schedulers.background import BackgroundScheduler
            sched = BackgroundScheduler()
            sched.add_job(
                _scheduled_run, "interval",
                hours=float(os.environ.get("CEREBRO_PIPELINE_INTERVAL_HOURS","1")),
                id="cerebro_excel_watcher",
                next_run_time=datetime.now() + timedelta(seconds=30),
            )
            sched.start()
            log.info("[Scheduler] Started — checks for new Excel every 1 hour")
        except ImportError:
            log.warning("[Scheduler] apscheduler not available")
            sched = None

        if not headless and _HAS_FASTAPI:
            import uvicorn
            host = os.environ.get("FASTAPI_HOST","0.0.0.0")
            port = int(os.environ.get("FASTAPI_PORT","8000"))
            log.info(f"[API] → http://localhost:{port}/docs")
            uvicorn.run(app, host=host, port=port, log_level="warning")
        else:
            log.info("[INFRA] Headless mode — waiting for hourly trigger")
            try:
                while True:
                    time.sleep(3600)
            except (KeyboardInterrupt, SystemExit):
                pass

        if sched:
            sched.shutdown()

    except ImportError as e:
        log.warning(f"[INFRA] Infrastructure unavailable ({e}) — running standalone")
        try:
            while True:
                time.sleep(3600)
                run_once()
        except (KeyboardInterrupt, SystemExit):
            pass


# ─────────────────────────────────────────────────────────────────────────────
# 12.  AUTO-START WRITER  (cross-platform)
# ─────────────────────────────────────────────────────────────────────────────

def write_autostart() -> None:
    """Register run.py as a boot-persistent background service."""
    import textwrap
    OS  = platform.system()
    py  = sys.executable
    scr = str(SCRIPT_DIR / "run.py")

    if OS == "Windows":
        xml = textwrap.dedent(f"""
        <?xml version="1.0" encoding="UTF-16"?>
        <Task version="1.2"
          xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
          <Triggers>
            <BootTrigger><Enabled>true</Enabled></BootTrigger>
            <RepetitionPattern>
              <Interval>PT1H</Interval>
              <StopAtDurationEnd>false</StopAtDurationEnd>
            </RepetitionPattern>
          </Triggers>
          <Actions>
            <Exec>
              <Command>{py}</Command>
              <Arguments>"{scr}" --headless</Arguments>
              <WorkingDirectory>{SCRIPT_DIR}</WorkingDirectory>
            </Exec>
          </Actions>
          <Settings>
            <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>
            <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
          </Settings>
        </Task>""").strip()
        xp = SCRIPT_DIR / "cerebro_task.xml"
        xp.write_text(xml, encoding="utf-16")
        ps = SCRIPT_DIR / "register_autostart.ps1"
        ps.write_text(
            f'Register-ScheduledTask -Xml (Get-Content "{xp}" -Raw) '
            f'-TaskName "CEREBRO-X" -Force\n')
        log.info(f"[AutoStart] Windows: run PowerShell AS ADMIN: {ps}")

    elif OS == "Darwin":
        plist = textwrap.dedent(f"""
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
          "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
          <key>Label</key>          <string>com.cerebro.enterprise</string>
          <key>ProgramArguments</key>
          <array><string>{py}</string><string>{scr}</string><string>--headless</string></array>
          <key>RunAtLoad</key>      <true/>
          <key>StartInterval</key> <integer>3600</integer>
          <key>WorkingDirectory</key><string>{SCRIPT_DIR}</string>
          <key>StandardOutPath</key><string>{SCRIPT_DIR}/cerebro_run.log</string>
          <key>StandardErrorPath</key><string>{SCRIPT_DIR}/cerebro_run.log</string>
        </dict>
        </plist>""").strip()
        pp = Path.home() / "Library/LaunchAgents/com.cerebro.enterprise.plist"
        pp.parent.mkdir(exist_ok=True)
        pp.write_text(plist, encoding="utf-8")
        log.info(f"[AutoStart] macOS: launchctl load {pp}")

    else:  # Linux
        service = textwrap.dedent(f"""
        [Unit]
        Description=CEREBRO-X Pipeline
        After=network.target
        [Service]
        Type=simple
        ExecStart={py} {scr} --headless
        WorkingDirectory={SCRIPT_DIR}
        Restart=always
        RestartSec=3600
        [Install]
        WantedBy=default.target""").strip()
        sp = Path.home() / ".config/systemd/user/cerebro.service"
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(service, encoding="utf-8")
        log.info("[AutoStart] Linux: systemctl --user enable cerebro.service")


# ─────────────────────────────────────────────────────────────────────────────
# 13.  DOCUMENTATION
# ─────────────────────────────────────────────────────────────────────────────

def write_run_doc() -> None:
    sep = "=" * 70
    txt = (f"{sep}\n  CEREBRO-X |  FILE DOCUMENTATION\n"
           f"  File      : run.py\n"
           f"  Version   : 2.0.0 (Excel-driven, trial-versioned)\n"
           f"  Generated : {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}\n"
           f"  OS        : {platform.system()} | Python: {sys.version.split()[0]}\n"
           f"{sep}\n\n"
           f"{'─'*70}\n  OVERVIEW\n{'─'*70}\n"
           "Master entry point — the ONLY file you need to run.\n"
           "All inputs come from CEREBRO_Input*.xlsx — nothing is hardcoded.\n\n"
           f"{'─'*70}\n  TRIAL VERSIONING\n{'─'*70}\n"
           "Each Excel file is hashed (SHA-256). Unknown hash → new Trial_N/.\n"
           "  Trial_0/  → first Excel processed\n"
           "  Trial_1/  → second distinct Excel (or modified version)\n"
           "  ...and so on indefinitely\n"
           "trial_index.db tracks: hash, drug name, timestamp, output path.\n\n"
           f"{'─'*70}\n  CACHE INVALIDATION\n{'─'*70}\n"
           "Before each trial, molecule cache is wiped for the new drug name:\n"
           "  1. JSON cache files deleted from molecule_cache/\n"
           "  2. SQLite drug_records rows deleted (→ fresh upsert)\n"
           "  3. In-memory cache is auto-cleared (new process per run)\n"
           "This guarantees fresh API fetch every time — no stale data.\n\n"
           f"{'─'*70}\n  PIPELINE FLOW\n{'─'*70}\n"
           "  Excel → YAML (excel_to_yaml)\n"
           "  Cache invalidation (invalidate_molecule_cache)\n"
           "  MoleculeEngine (SMILES/FASTA/name → live API fetch)\n"
           "  CascadeDataEngine.build_mab_dataset([drug_name])\n"
           "  AdvancedMLEngine.train() [leakage-free scaler]\n"
           "  ADMETEngine.run()\n"
           "  PK/PD simulation\n"
           "  DDSEngine (100 formulations from Excel → BBB scored)\n"
           "  Static PNG figures (no GIFs, no 3D sim figures)\n"
           "  Merged PDF report\n"
           "  trial_index.db registration\n\n"
           f"{'─'*70}\n  COMMAND-LINE FLAGS\n{'─'*70}\n"
           "  python run.py                → full mode\n"
           "  python run.py --headless     → no API, scheduler only\n"
           "  python run.py --pipeline-only→ run once, exit\n"
           "  python run.py --force        → force re-run latest Excel\n"
           f"{sep}\n")
    _docs_dir = SCRIPT_DIR / "docs"
    _docs_dir.mkdir(parents=True, exist_ok=True)
    (_docs_dir / "run.py_DOCUMENTATION.txt").write_text(txt, encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# 14.  MAIN
# ─────────────────────────────────────────────────────────────────────────────
# _run_science_and_viz() used to live here (a ScienceOrchestrator +
# VisualisationOrchestrator wrapper). Removed: confirmed via repo-wide grep
# to have zero callers anywhere — the real, live science/visualization path
# is cerebro_science_modules.run_all_science_modules(), called directly
# inside run_pipeline_from_excel (pipeline_runner.py). This also means
# science_engines.ScienceOrchestrator/PBPKEngine/MultiCompartmentPKEngine
# (which _run_science_and_viz was their only caller) need re-checking —
# leaving that for the next audit pass rather than fixing it here, since
# it changes an earlier finding of mine about them being "live."

if __name__ == "__main__":
    args = sys.argv[1:]

    # Pull canonical project title from the single source of truth.
    # If _version.py is somehow unreachable, fall back to the literal.
    try:
        from _version import PROJECT_TITLE as _PROJ_TITLE
    except ImportError:
        _PROJ_TITLE = "CEREBRO-X"

    log.info("=" * 65)
    log.info(f"  {_PROJ_TITLE} — MASTER RUNNER")
    log.info(f"  OS: {platform.system()} | Python: {sys.version.split()[0]}")
    log.info(f"  Dir: {SCRIPT_DIR}")
    log.info("=" * 65)

    write_run_doc()

    log.info("[RUN] Checking/installing dependencies …")
    install_missing()

    force = "--force" in args

    if "--pipeline-only" in args:
        run_once(force=force)
        sys.exit(0)

    if "--dds-only" in args:
        # Find latest trial YAML and re-run DDS only
        conn = sqlite3.connect(TRIAL_INDEX_DB) if TRIAL_INDEX_DB.exists() else None
        if conn:
            last = conn.execute(
                "SELECT output_dir, drug_name FROM trials "
                "ORDER BY trial_id DESC LIMIT 1").fetchone()
            conn.close()
            if last:
                td    = Path(last[0])
                yp    = td / "dds_config.yaml"
                if yp.exists():
                    import yaml
                    with open(yp) as f:
                        cfg = yaml.safe_load(f)
                    df_dds = _run_dds_from_yaml(yp, td, last[1], {}, None)
                    if df_dds is not None:
                        log.info(f"[DDS] Complete: {len(df_dds)} formulations")
                    sys.exit(0)
        log.error("No previous trial found — run full pipeline first")
        sys.exit(1)

    # Default: run once (all new Excel files) then start infrastructure
    write_autostart()
    run_once(force=force)
    start_infra(headless="--headless" in args)

