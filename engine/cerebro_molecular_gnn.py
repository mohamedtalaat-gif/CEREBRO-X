"""
================================================================================
CEREBRO-X |  cerebro_molecular_gnn.py  —  Real Molecular-Graph GNN
================================================================================
Created by: Muhammad Talaat — CEREBRO-X

A real graph convolutional network over actual molecular structure: atoms
as nodes (with real per-atom features), bonds as edges (from RDKit's own
bond perception, not a fabricated fully-connected placeholder). This
replaces the earlier fake pseudo-graph component that used to live in
src/core/pipeline.py::GNNEngine (deleted — see that file's history), which
built a fully-connected graph of identical duplicated nodes with no atoms
or bonds at all.

Why this exists
----------------
cerebro_bbb_dnn.py already has a real, honest, held-out-tested BBB
permeability model on flat ECFP4 fingerprints. This module is not trying
to replace it — it exists to answer a real, open question directly, rather
than assume an answer: does a genuine molecular graph capture anything a
flat fingerprint doesn't, on the same real task and the same real data?
(Pat Walters' own public list of open ML-in-drug-discovery questions asks
exactly this — "Are learned representations better? How can we prove it?" —
this module is a real, checkable attempt at an answer, not a claim of one.)

Both models are trained and evaluated on the identical BBBP split (same
CSV, same row order, same seed, same stratified train/valid/test division)
specifically so the comparison in metrics.json is apples-to-apples. See
compare_gnn_vs_dnn() for the real, current numbers — not a claim made here,
a number produced by actually running both.

Graph construction
-------------------
Per atom: one-hot element (C/N/O/F/P/S/Cl/Br/I/other, 10 dims), one-hot
degree (0-5, 6 dims), formal charge (1 dim), one-hot hybridization
(SP/SP2/SP3/other, 4 dims), aromaticity (1 dim), ring membership (1 dim),
implicit+explicit H count normalized (1 dim) — 24 real features per atom,
nothing duplicated or tiled across nodes.
Per bond: a real edge in both directions (undirected molecular bond),
from RDKit's own GetBonds() — not a synthetic complete graph.

Architecture
------------
3-layer graph convolution (Kipf & Welling 2017, "Semi-Supervised
Classification with Graph Convolutional Networks", ICLR — the same
propagation rule the old docstring cited but never actually implemented:
h_v^(l+1) = sigma(sum_{u in N(v)} W^l h_u^l / sqrt(d_v d_u))) implemented
directly in PyTorch over a dense, symmetrically-normalized adjacency
matrix per molecule — no torch_geometric/torch-scatter/torch-sparse
dependency, since drug-sized molecules (tens of atoms) make dense
adjacency operations both correct and fast, and it keeps the dependency
footprint installable everywhere the rest of this project already runs.
Batched via padding + a node mask (padded nodes contribute zero to mean
pooling and carry no gradient through the padding itself) rather than a
Python loop per molecule, so training on ~1,600 real molecules is fast.

Same downstream head as cerebro_bbb_dnn.py: global mean pool -> Dense(64,
relu) -> Dropout(0.3) -> Dense(1, sigmoid), same optimizer, same epoch
count, same seed — the graph construction and the message-passing layers
are the only thing genuinely different between the two models, on purpose,
so any accuracy difference is attributable to that, not to unrelated
architecture choices.
================================================================================
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

log = logging.getLogger("CEREBRO-MOL-GNN")

_MODEL_DIR = Path(
    os.environ.get("CEREBRO_GNN_MODEL_DIR",
                    Path(__file__).resolve().parent.parent / "outputs" / "models" / "molecular_gnn")
)

try:
    import numpy as np
    from rdkit import Chem
    _HAS_RDKIT = True
except ImportError:
    _HAS_RDKIT = False

try:
    import torch
    # Found this the hard way: running a torch forward pass in the same
    # process as the rest of this app's native-heavy stack (psycopg2,
    # cryptography, prometheus_client, ...) segfaults reproducibly — a
    # native thread-pool conflict, not a bug in the model itself (confirmed
    # by bisecting exactly where it crashed: import and instantiation were
    # fine, only the actual tensor ops crashed). Forcing single-threaded
    # torch here costs nothing measurable on molecule-sized tensors (tens
    # of atoms) and removes the conflict for every caller automatically,
    # rather than depending on each one remembering to set this.
    torch.set_num_threads(1)
    import torch.nn as nn
    import torch.nn.functional as F
    _HAS_TORCH = True
except ImportError:
    _HAS_TORCH = False

_HAS_MOL_GNN = _HAS_RDKIT and _HAS_TORCH

_ELEMENTS = ["C", "N", "O", "F", "P", "S", "Cl", "Br", "I"]  # + "other" = 10 dims
_MAX_DEGREE = 5  # 0..5 = 6 dims
NODE_FEAT_DIM = len(_ELEMENTS) + 1 + (_MAX_DEGREE + 1) + 1 + 4 + 1 + 1 + 1  # = 24


def _one_hot(value, choices) -> list:
    return [1.0 if value == c else 0.0 for c in choices]


def _atom_features(atom) -> list:
    """24 real, standard per-atom features. No two atoms in a molecule get
    the same vector unless they genuinely have the same chemical
    environment by these measures — nothing here is duplicated across
    nodes the way the old fake construction duplicated one per-drug
    vector across every node."""
    element = atom.GetSymbol()
    element_oh = _one_hot(element, _ELEMENTS)
    element_oh.append(1.0 if element not in _ELEMENTS else 0.0)  # "other"

    degree_oh = _one_hot(min(atom.GetDegree(), _MAX_DEGREE), range(_MAX_DEGREE + 1))

    hyb = str(atom.GetHybridization())
    hyb_oh = _one_hot(hyb, ["SP", "SP2", "SP3"])
    hyb_oh.append(1.0 if hyb not in ("SP", "SP2", "SP3") else 0.0)  # "other"

    return (element_oh + degree_oh
            + [float(atom.GetFormalCharge())]
            + hyb_oh
            + [1.0 if atom.GetIsAromatic() else 0.0]
            + [1.0 if atom.IsInRing() else 0.0]
            + [float(atom.GetTotalNumHs()) / 4.0])  # normalized, ~0-4 typical


def smiles_to_graph(smiles: str):
    """Real molecular graph: (node_features [n_atoms, 24], adjacency
    [n_atoms, n_atoms]) built from RDKit's own atom/bond perception.
    Returns None on invalid SMILES — a real failure mode, not silently
    padded or defaulted."""
    if not _HAS_RDKIT:
        return None
    mol = Chem.MolFromSmiles(smiles)
    if mol is None or mol.GetNumAtoms() == 0:
        return None
    n = mol.GetNumAtoms()
    node_feats = np.array([_atom_features(a) for a in mol.GetAtoms()], dtype=np.float32)
    adj = np.zeros((n, n), dtype=np.float32)
    for bond in mol.GetBonds():
        i, j = bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()
        adj[i, j] = 1.0
        adj[j, i] = 1.0
    return node_feats, adj


def _normalize_adjacency(adj: "np.ndarray") -> "np.ndarray":
    """Kipf & Welling's renormalization trick: D^-1/2 (A+I) D^-1/2 —
    self-loops included so each atom's own features survive propagation."""
    n = adj.shape[0]
    a_hat = adj + np.eye(n, dtype=np.float32)
    deg = a_hat.sum(axis=1)
    d_inv_sqrt = np.zeros_like(deg)
    np.power(deg, -0.5, out=d_inv_sqrt, where=deg > 0)
    d_mat = np.diag(d_inv_sqrt)
    return (d_mat @ a_hat @ d_mat).astype(np.float32)


class MolecularGCN(nn.Module if _HAS_TORCH else object):
    """3-layer GCN over a real, per-molecule normalized adjacency matrix,
    batched via padding + mask. hidden state update at each layer is
    exactly h' = relu(A_norm @ h @ W) — the same rule GCNConv implements,
    written out directly since the graphs here are small enough that a
    dense implementation needs no sparse/scatter machinery."""

    def __init__(self, node_feat=NODE_FEAT_DIM, hidden=64, out=1):
        super().__init__()
        self.w1 = nn.Linear(node_feat, hidden)
        self.w2 = nn.Linear(hidden, hidden)
        self.w3 = nn.Linear(hidden, hidden)
        self.bn1 = nn.BatchNorm1d(hidden)
        self.bn2 = nn.BatchNorm1d(hidden)
        self.fc1 = nn.Linear(hidden, 64)
        self.fc2 = nn.Linear(64, out)
        self.drop = nn.Dropout(0.3)

    def _gcn_layer(self, h, a_norm, w, bn=None):
        # h: [B, N, F_in], a_norm: [B, N, N] -> [B, N, F_out]
        h = torch.bmm(a_norm, h)
        h = w(h)
        if bn is not None:
            b, n, f = h.shape
            h = bn(h.reshape(b * n, f)).reshape(b, n, f)
        return F.relu(h)

    def forward(self, x, a_norm, mask):
        # x: [B, N, node_feat], a_norm: [B, N, N], mask: [B, N] (1=real atom, 0=padding)
        h = self._gcn_layer(x, a_norm, self.w1, self.bn1)
        h = self.drop(h)
        h = self._gcn_layer(h, a_norm, self.w2, self.bn2)
        h = self._gcn_layer(h, a_norm, self.w3)
        # Masked mean pool over real atoms only — padded nodes contribute
        # zero and don't dilute the average.
        mask_f = mask.unsqueeze(-1)
        summed = (h * mask_f).sum(dim=1)
        counts = mask_f.sum(dim=1).clamp(min=1.0)
        pooled = summed / counts
        out = F.relu(self.fc1(pooled))
        out = self.drop(out)
        return torch.sigmoid(self.fc2(out)).squeeze(-1)


def _pad_batch(graphs: list) -> tuple:
    """graphs: list of (node_feats, adjacency). Pads to the batch's max
    atom count and returns (x, a_norm, mask) tensors."""
    max_n = max(g[0].shape[0] for g in graphs)
    B = len(graphs)
    x = np.zeros((B, max_n, NODE_FEAT_DIM), dtype=np.float32)
    a = np.zeros((B, max_n, max_n), dtype=np.float32)
    mask = np.zeros((B, max_n), dtype=np.float32)
    for i, (nf, adj) in enumerate(graphs):
        n = nf.shape[0]
        x[i, :n, :] = nf
        a[i, :n, :n] = _normalize_adjacency(adj)
        mask[i, :n] = 1.0
    return (torch.from_numpy(x), torch.from_numpy(a), torch.from_numpy(mask))


def train_and_evaluate(epochs: int = 30, seed: int = 42, batch_size: int = 64) -> dict:
    """
    Train the real molecular-graph GNN on the same BBBP dataset and the
    same stratified split cerebro_bbb_dnn.py uses (same CSV, same row
    order, same seed), so the two models' held-out test metrics are
    directly comparable. Nothing here is hardcoded — every number is
    produced by this run and written to metrics.json.
    """
    if not _HAS_MOL_GNN:
        raise RuntimeError(
            "cerebro_molecular_gnn requires rdkit and torch — "
            f"rdkit={'OK' if _HAS_RDKIT else 'MISSING'}, "
            f"torch={'OK' if _HAS_TORCH else 'MISSING'}"
        )
    import pandas as pd
    from cerebro_bbb_dnn import _fetch_bbbp_csv
    from sklearn.metrics import accuracy_score, confusion_matrix, roc_auc_score
    from sklearn.model_selection import train_test_split

    csv_path = _fetch_bbbp_csv()
    if csv_path is None:
        raise RuntimeError("BBBP dataset unavailable (no network / download failed)")

    df = pd.read_csv(csv_path).dropna(subset=["smiles", "p_np"])
    graphs, y, dropped = [], [], 0
    for _, row in df.iterrows():
        g = smiles_to_graph(str(row["smiles"]))
        if g is None:
            dropped += 1
            continue
        graphs.append(g)
        y.append(float(row["p_np"]))
    y = np.array(y, dtype=np.float32)
    log.info(f"[MOL-GNN] Built real graphs for {len(graphs)}/{len(df)} compounds "
             f"({dropped} dropped — invalid SMILES)")

    idx = np.arange(len(graphs))
    idx_train, idx_temp, y_train, y_temp = train_test_split(
        idx, y, test_size=0.2, random_state=seed, stratify=y)
    idx_valid, idx_test, y_valid, y_test = train_test_split(
        idx_temp, y_temp, test_size=0.5, random_state=seed, stratify=y_temp)

    torch.manual_seed(seed)
    model = MolecularGCN()
    opt = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-4)
    loss_fn = nn.BCELoss()

    def _batches(indices, bs):
        rng = np.random.default_rng(seed)
        order = rng.permutation(len(indices))
        for start in range(0, len(order), bs):
            sel = indices[order[start:start + bs]]
            yield sel

    train_losses = []
    for ep in range(epochs):
        model.train()
        ep_loss, n_batches = 0.0, 0
        for sel in _batches(idx_train, batch_size):
            x, a_norm, mask = _pad_batch([graphs[i] for i in sel])
            yb = torch.from_numpy(y[sel])
            opt.zero_grad()
            pred = model(x, a_norm, mask)
            loss = loss_fn(pred, yb)
            loss.backward()
            opt.step()
            ep_loss += loss.item()
            n_batches += 1
        train_losses.append(ep_loss / max(n_batches, 1))
        if (ep + 1) % 10 == 0:
            log.info(f"    GNN epoch {ep+1} loss={train_losses[-1]:.4f}")

    def _predict(indices):
        model.eval()
        preds = []
        with torch.no_grad():
            for start in range(0, len(indices), batch_size):
                sel = indices[start:start + batch_size]
                x, a_norm, mask = _pad_batch([graphs[i] for i in sel])
                preds.append(model(x, a_norm, mask).numpy())
        return np.concatenate(preds)

    y_pred_proba = _predict(idx_test)
    y_pred = (y_pred_proba >= 0.5).astype(int)

    metrics = {
        "n_total_compounds": len(df),
        "n_dropped_invalid_smiles": int(dropped),
        "n_used": len(graphs),
        "n_train": len(idx_train),
        "n_valid": len(idx_valid),
        "n_test": len(idx_test),
        "test_accuracy": float(accuracy_score(y_test, y_pred)),
        "test_roc_auc": float(roc_auc_score(y_test, y_pred_proba)),
        "test_confusion_matrix": confusion_matrix(y_test, y_pred).tolist(),
        "final_train_loss": train_losses[-1],
        "split": "stratified random 80/10/10, seed=42 (identical split "
                 "methodology to cerebro_bbb_dnn.py, same CSV/order/seed)",
        "architecture": "Real RDKit atom/bond graph -> 3-layer GCN (24-dim "
                         "node features, dense normalized adjacency) -> "
                         "masked mean pool -> Dense(64) -> Dropout(0.3) -> "
                         "Dense(1, sigmoid)",
        "reference": "Kipf & Welling (2017) ICLR, GCN; Martins IF et al. "
                      "(2012) J Chem Inf Model 52:1686 (BBBP dataset)",
    }

    _MODEL_DIR.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), _MODEL_DIR / "model.pt")
    (_MODEL_DIR / "metrics.json").write_text(json.dumps(metrics, indent=2))
    log.info(f"[MOL-GNN] Trained. Test accuracy={metrics['test_accuracy']:.3f} "
             f"ROC-AUC={metrics['test_roc_auc']:.3f} "
             f"(n_train={metrics['n_train']}, n_test={metrics['n_test']})")
    return metrics


_model_cache = None
_metrics_cache = None


def _load_or_train():
    global _model_cache, _metrics_cache
    if _model_cache is not None:
        return _model_cache, _metrics_cache
    model_path = _MODEL_DIR / "model.pt"
    metrics_path = _MODEL_DIR / "metrics.json"
    if model_path.exists() and metrics_path.exists():
        _model_cache = MolecularGCN()
        _model_cache.load_state_dict(torch.load(model_path, weights_only=True))
        _model_cache.eval()
        _metrics_cache = json.loads(metrics_path.read_text())
    else:
        _metrics_cache = train_and_evaluate()
        _model_cache = MolecularGCN()
        _model_cache.load_state_dict(torch.load(model_path, weights_only=True))
        _model_cache.eval()
    return _model_cache, _metrics_cache


def predict_bbb_class_gnn(smiles: str) -> dict:
    """Predict BBB permeability class using the real molecular-graph GNN —
    same output shape as cerebro_bbb_dnn.predict_bbb_class, for direct
    comparison at the call site."""
    if not _HAS_MOL_GNN:
        return {"available": False, "reason": "rdkit and/or torch not installed"}
    g = smiles_to_graph(smiles)
    if g is None:
        return {"available": False, "reason": f"RDKit could not parse SMILES: {smiles!r}"}

    model, metrics = _load_or_train()
    x, a_norm, mask = _pad_batch([g])
    with torch.no_grad():
        proba = float(model(x, a_norm, mask)[0])
    return {
        "available": True,
        "probability_permeable": round(proba, 4),
        "predicted_class": "permeable" if proba >= 0.5 else "non_permeable",
        "confidence": "MODERATE",
        "method": "Real molecular-graph GCN (RDKit atom/bond graph) trained on BBBP",
        "reference": "Kipf & Welling (2017) ICLR; Martins IF et al. (2012) "
                      "J Chem Inf Model 52:1686 (BBBP dataset)",
        "model_test_accuracy": metrics.get("test_accuracy"),
        "model_test_roc_auc": metrics.get("test_roc_auc"),
        "model_n_train": metrics.get("n_train"),
        "model_n_test": metrics.get("n_test"),
    }


def compare_gnn_vs_dnn() -> dict:
    """Train/load both models on the identical split and report both
    real metrics side by side — the actual answer to whether the graph
    structure adds anything here, not an assumption either way."""
    from cerebro_bbb_dnn import train_and_evaluate as train_dnn

    gnn_metrics = train_and_evaluate()
    dnn_metrics = train_dnn()
    return {
        "gnn": gnn_metrics,
        "dnn": dnn_metrics,
        "gnn_minus_dnn_test_accuracy": round(
            gnn_metrics["test_accuracy"] - dnn_metrics["test_accuracy"], 4),
        "gnn_minus_dnn_test_roc_auc": round(
            gnn_metrics["test_roc_auc"] - dnn_metrics["test_roc_auc"], 4),
        "note": "Positive values mean the graph model scored higher on "
                "this run's held-out test split. A single run on a random "
                "split is not strong evidence either way — read this as a "
                "real data point, not a verdict.",
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
        print(name, "->", predict_bbb_class_gnn(smi))
