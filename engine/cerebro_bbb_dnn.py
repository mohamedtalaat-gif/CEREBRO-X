"""
================================================================================
CEREBRO-X |  cerebro_bbb_dnn.py  —  BBB Permeability DNN Classifier
================================================================================
Created by: Muhammad Talaat — CEREBRO-X

A real, trained, held-out-tested deep neural network for blood-brain barrier
(BBB) permeability classification, on flat molecular descriptors. The earlier
fake GNN pseudo-graph component that used to live in
src/core/pipeline.py::GNNEngine (fully-connected graphs of identical
duplicated nodes, no real atoms or bonds) has been removed entirely rather
than kept in a disclosed-but-broken state — it was dead code either way.
A real, graph-structure GNN now lives in engine/cerebro_molecular_gnn.py,
trained on the same BBBP dataset this module uses, specifically to give an
honest answer to whether a real molecular graph adds anything over this
DNN's flat descriptors on the same task — not assumed, checked.

Data
----
BBBP (Blood-Brain Barrier Penetration), the standard MoleculeNet benchmark:
  Martins IF et al. (2012) "A Bayesian Approach to in Silico Blood-Brain
  Barrier Penetration Modeling." J Chem Inf Model 52(6):1686-1697.
  doi:10.1021/ci300124c
  Wu Z et al. (2018) "MoleculeNet: a benchmark for molecular machine
  learning." Chem Sci 9:513-530. doi:10.1039/C7SC02664A
Hosted by the DeepChem project: https://deepchemdata.s3-us-west-1.amazonaws.com/datasets/BBBP.csv
2,050 compounds with a binary permeable/non-permeable label (p_np).
~11 SMILES fail to parse with RDKit and are dropped — 2,039 used for
training/validation/test in practice (see train_and_evaluate()'s printed
counts, which are the authoritative real numbers for any given run).

IMPORTANT — read before citing this module externally:
  - This is NOT the "19,520 Enamine library compounds" figure that appears
    in earlier outreach material. That figure could not be reproduced or
    justified from anything in this codebase (Enamine's screening library
    is proprietary; there is no dataset of that size or origin anywhere in
    this project). BBBP (~2,039 compounds after cleaning) is the real,
    public, peer-reviewed dataset actually used here. Cite the real number.
  - DeepChem (deepchem.org) is used as the canonical source/host for the
    BBBP CSV, and its dataset-loading conventions are followed. Its
    higher-level Keras model wrapper (dc.models.MultitaskClassifier) is
    NOT used here — as of this writing, DeepChem 2.5.0 (the newest version
    with Python 3.13 wheels) has real, reproducible incompatibilities with
    current TensorFlow's Keras integration (AttributeError in
    KerasModel._create_inputs). The DNN below is implemented directly in
    tf.keras instead. On Python ≤3.12 with an older/matched TensorFlow,
    dc.models.MultitaskClassifier is a drop-in alternative — swap it in if
    your environment supports it.
  - Small-molecule only. BBB permeability by passive diffusion is not a
    meaningful concept for biologics/oligonucleotides (see
    cerebro_value_resolver/categories/bbb_perm.py's BIOLOGIC_CLASSES /
    GENE_CLASSES handling) — this model is not applied to those classes.

Architecture
------------
Input: 2048-bit Morgan/ECFP4 fingerprint (RDKit, radius=2)
Dense(256, relu) -> Dropout(0.3) -> Dense(64, relu) -> Dropout(0.3) -> Dense(1, sigmoid)
Adam optimizer, binary cross-entropy, trained with an 80/10/10
stratified random train/valid/test split (a fixed seed=42 is used for
reproducibility — note MoleculeNet's own documentation recommends a
*scaffold* split for a harder, more realistic generalization test; this
module uses a random split for simplicity and says so plainly here rather
than claiming scaffold-split rigor it doesn't have).

Real held-out test performance from the run that produced the currently
cached model is written to bbb_dnn_model/metrics.json next to the model
weights — read that file for the authoritative numbers rather than any
number quoted in a docstring, which can go stale.
================================================================================
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from pathlib import Path

log = logging.getLogger("CEREBRO-BBB-DNN")

BBBP_URL = "https://deepchemdata.s3-us-west-1.amazonaws.com/datasets/BBBP.csv"
_MODEL_DIR = Path(
    os.environ.get("CEREBRO_BBB_MODEL_DIR",
                    Path(__file__).resolve().parent.parent / "outputs" / "models" / "bbb_dnn")
)
_DATA_CACHE = Path(
    os.environ.get("CEREBRO_BBB_DATA_DIR",
                    Path(__file__).resolve().parent.parent / "outputs" / "data_cache")
)

try:
    import numpy as np
    from rdkit import Chem
    from rdkit.Chem import AllChem
    _HAS_RDKIT = True
except ImportError:
    _HAS_RDKIT = False

try:
    import tensorflow as tf
    from tensorflow import keras
    _HAS_TF = True
except ImportError:
    _HAS_TF = False

_HAS_BBB_DNN = _HAS_RDKIT and _HAS_TF


def _fetch_bbbp_csv() -> Path | None:
    """Download the real BBBP.csv once and cache it locally."""
    _DATA_CACHE.mkdir(parents=True, exist_ok=True)
    dest = _DATA_CACHE / "BBBP.csv"
    if dest.exists():
        return dest
    try:
        log.info(f"[BBB-DNN] Downloading BBBP dataset from {BBBP_URL} …")
        urllib.request.urlretrieve(BBBP_URL, dest)
        return dest
    except Exception as e:
        log.warning(f"[BBB-DNN] Could not download BBBP.csv: {e}")
        return None


def _featurize_smiles(smiles: str):
    """RDKit Morgan/ECFP4 fingerprint, 2048 bits, radius 2. Returns None on
    invalid SMILES (real failure mode — not silently zero-filled)."""
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    fp = AllChem.GetMorganFingerprintAsBitVect(mol, radius=2, nBits=2048)
    return np.array(fp, dtype=np.float32)


def _build_model() -> keras.Model:
    model = keras.Sequential([
        keras.layers.Input(shape=(2048,)),
        keras.layers.Dense(256, activation="relu"),
        keras.layers.Dropout(0.3),
        keras.layers.Dense(64, activation="relu"),
        keras.layers.Dropout(0.3),
        keras.layers.Dense(1, activation="sigmoid"),
    ])
    model.compile(optimizer=keras.optimizers.Adam(learning_rate=1e-3),
                  loss="binary_crossentropy", metrics=["accuracy"])
    return model


def train_and_evaluate(epochs: int = 30, seed: int = 42) -> dict:
    """
    Train the BBB DNN on the real BBBP dataset and evaluate on a genuinely
    held-out test split. Returns the real metrics (and writes them to
    metrics.json next to the saved model) — nothing here is hardcoded or
    pre-computed; every number is produced by this run.
    """
    if not _HAS_BBB_DNN:
        raise RuntimeError(
            "cerebro_bbb_dnn requires rdkit and tensorflow — "
            f"rdkit={'OK' if _HAS_RDKIT else 'MISSING'}, "
            f"tensorflow={'OK' if _HAS_TF else 'MISSING'}"
        )
    import pandas as pd
    from sklearn.metrics import accuracy_score, confusion_matrix, roc_auc_score
    from sklearn.model_selection import train_test_split

    csv_path = _fetch_bbbp_csv()
    if csv_path is None:
        raise RuntimeError("BBBP dataset unavailable (no network / download failed)")

    df = pd.read_csv(csv_path).dropna(subset=["smiles", "p_np"])
    X, y, dropped = [], [], 0
    for _, row in df.iterrows():
        feat = _featurize_smiles(str(row["smiles"]))
        if feat is None:
            dropped += 1
            continue
        X.append(feat)
        y.append(float(row["p_np"]))
    X = np.array(X, dtype=np.float32)
    y = np.array(y, dtype=np.float32)
    log.info(f"[BBB-DNN] Featurized {len(X)}/{len(df)} compounds "
             f"({dropped} dropped — invalid SMILES)")

    X_train, X_temp, y_train, y_temp = train_test_split(
        X, y, test_size=0.2, random_state=seed, stratify=y)
    X_valid, X_test, y_valid, y_test = train_test_split(
        X_temp, y_temp, test_size=0.5, random_state=seed, stratify=y_temp)

    tf.random.set_seed(seed)
    model = _build_model()
    history = model.fit(X_train, y_train, validation_data=(X_valid, y_valid),
                         epochs=epochs, batch_size=64, verbose=0)

    y_pred_proba = model.predict(X_test, verbose=0).flatten()
    y_pred = (y_pred_proba >= 0.5).astype(int)
    metrics = {
        "n_total_compounds": len(df),
        "n_dropped_invalid_smiles": int(dropped),
        "n_used": len(X),
        "n_train": len(X_train),
        "n_valid": len(X_valid),
        "n_test": len(X_test),
        "test_accuracy": float(accuracy_score(y_test, y_pred)),
        "test_roc_auc": float(roc_auc_score(y_test, y_pred_proba)),
        "test_confusion_matrix": confusion_matrix(y_test, y_pred).tolist(),
        "final_train_accuracy": float(history.history["accuracy"][-1]),
        "final_val_accuracy": float(history.history["val_accuracy"][-1]),
        "split": "stratified random 80/10/10, seed=42 (NOT scaffold split)",
        "architecture": "2048-bit ECFP4 -> Dense(256) -> Dropout(0.3) -> Dense(64) -> Dropout(0.3) -> Dense(1, sigmoid)",
        "reference": "Martins IF et al. (2012) J Chem Inf Model 52:1686; Wu Z et al. (2018) Chem Sci 9:513",
        "dataset_source": BBBP_URL,
    }

    _MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model.save(_MODEL_DIR / "model.keras")
    (_MODEL_DIR / "metrics.json").write_text(json.dumps(metrics, indent=2))
    log.info(f"[BBB-DNN] Trained. Test accuracy={metrics['test_accuracy']:.3f} "
             f"ROC-AUC={metrics['test_roc_auc']:.3f} "
             f"(n_train={metrics['n_train']}, n_test={metrics['n_test']})")
    return metrics


_model_cache = None
_metrics_cache = None


def _load_or_train():
    global _model_cache, _metrics_cache
    if _model_cache is not None:
        return _model_cache, _metrics_cache
    model_path = _MODEL_DIR / "model.keras"
    metrics_path = _MODEL_DIR / "metrics.json"
    if model_path.exists() and metrics_path.exists():
        _model_cache = keras.models.load_model(model_path)
        _metrics_cache = json.loads(metrics_path.read_text())
    else:
        _metrics_cache = train_and_evaluate()
        _model_cache = keras.models.load_model(model_path)
    return _model_cache, _metrics_cache


def predict_bbb_class(smiles: str) -> dict:
    """
    Predict BBB permeability class for a small-molecule SMILES string.

    Returns a dict with `probability` (P(permeable), 0-1), `predicted_class`
    ("permeable"/"non_permeable"), `confidence`, and the real training-run
    metrics this prediction's model was evaluated with (test_accuracy,
    test_roc_auc, n_train, n_test) — so callers/reports can cite the actual
    numbers rather than a stale claim.
    """
    if not _HAS_BBB_DNN:
        return {
            "available": False,
            "reason": "rdkit and/or tensorflow not installed",
        }
    feat = _featurize_smiles(smiles)
    if feat is None:
        return {"available": False, "reason": f"RDKit could not parse SMILES: {smiles!r}"}

    model, metrics = _load_or_train()
    proba = float(model.predict(feat.reshape(1, -1), verbose=0)[0, 0])
    return {
        "available": True,
        "probability_permeable": round(proba, 4),
        "predicted_class": "permeable" if proba >= 0.5 else "non_permeable",
        "confidence": "MODERATE",
        "method": "DNN (2048-bit ECFP4 -> 256 -> 64 -> 1, sigmoid) trained on BBBP",
        "reference": "Martins IF et al. (2012) J Chem Inf Model 52:1686 (BBBP dataset); "
                     "Wu Z et al. (2018) Chem Sci 9:513 (MoleculeNet)",
        "model_test_accuracy": metrics.get("test_accuracy"),
        "model_test_roc_auc": metrics.get("test_roc_auc"),
        "model_n_train": metrics.get("n_train"),
        "model_n_test": metrics.get("n_test"),
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    m = train_and_evaluate()
    print(json.dumps(m, indent=2))
    print()
    for name, smi in [
        ("Donepezil", "COc1cc2c(cc1OC)C(=O)C(CC1CCN(Cc3ccccc3)CC1)C2"),
        ("Loperamide (low CNS)", "OC1(CCN(CCC(C1)(c1ccccc1)C(N(C)C)=O)CCC(c1ccccc1)(c1ccccc1)Cl)"),
    ]:
        print(name, "->", predict_bbb_class(smi))
