"""
================================================================================
CEREBRO-X |  KNOWLEDGE GRAPH & GNN ENGINE
================================================================================
File: cerebro_knowledge_graph.py

Builds and queries a Drug–DDS–Target–Disease knowledge graph:

  1. Knowledge Graph Construction
     - Drug ↔ DDS Carrier relationships (formulation compatibility)
     - Drug → Target Protein (binding affinity edges)
     - Drug → Disease (indication edges)
     - DDS → Route of Administration
     - DDS → BBB Mechanism (transcytosis, efflux pump escape, etc.)
     - Surface Ligand → Receptor → BBB Transporter

  2. Graph Neural Networks (GNN)
     - Node classification: predict BBB penetration class per DDS
     - Link prediction: suggest new drug–carrier combinations
     - Graph-level regression: predict BBB Engineering Score from subgraph
     - PyTorch Geometric when available, networkx fallback

  3. Graph Analytics
     - Centrality analysis (which DDS carriers are most versatile?)
     - Community detection (clusters of compatible drug–carrier pairs)
     - Shortest path analysis (drug → target → disease pathways)
     - Pagerank for DDS formulation importance

  4. Multimodal Feature Integration
     - Text features: drug descriptions, mechanism of action (TF-IDF/embeddings)
     - Structure features: molecular fingerprints (RDKit Morgan FP)
     - Numeric features: physicochemical properties (MW, LogP, etc.)
     - Fused via concatenation + MLP or attention-based fusion

References:
  - Zitnik et al. (2018) "Modeling polypharmacy side effects with GNNs"
  - Huang et al. (2020) "Drug-drug interaction prediction via KG embedding"
  - CEREBRO-X internal: BBB Engineering Score (Pardridge 2012 framework)
================================================================================
"""

import json
import logging
import math
import warnings
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

log = logging.getLogger("CEREBRO-KG")
warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────────────────────
# Optional imports
# ─────────────────────────────────────────────────────────────────────────────
try:
    import networkx as nx
    _HAS_NX = True
except ImportError:
    _HAS_NX = False

try:
    import torch
    import torch.nn.functional as F
    from torch import nn
    _HAS_TORCH = True
except ImportError:
    _HAS_TORCH = False

try:
    from torch_geometric.data import Data, HeteroData
    from torch_geometric.nn import GATConv, GCNConv, HeteroConv, Linear, SAGEConv
    from torch_geometric.utils import from_networkx, to_networkx
    _HAS_PYG = True
except ImportError:
    _HAS_PYG = False

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.preprocessing import LabelEncoder, StandardScaler
    _HAS_SKLEARN = True
except ImportError:
    _HAS_SKLEARN = False


# ─────────────────────────────────────────────────────────────────────────────
# 1. Node and Edge Types
# ─────────────────────────────────────────────────────────────────────────────
class NodeType:
    DRUG            = "Drug"
    DDS_CARRIER     = "DDS_Carrier"
    TARGET_PROTEIN  = "Target_Protein"
    DISEASE         = "Disease"
    SURFACE_LIGAND  = "Surface_Ligand"
    BBB_RECEPTOR    = "BBB_Receptor"
    ROUTE           = "Route"
    BBB_MECHANISM   = "BBB_Mechanism"
    FORMULATION     = "Formulation"


class EdgeType:
    TREATS           = "treats"
    TARGETS          = "targets"
    CARRIED_BY       = "carried_by"
    FORMULATED_WITH  = "formulated_with"
    BINDS_TO         = "binds_to"
    CROSSES_VIA      = "crosses_via"
    ADMINISTERED_VIA = "administered_via"
    LIGAND_ON        = "ligand_on"
    RECEPTOR_AT      = "receptor_at"
    SIMILAR_TO       = "similar_to"


@dataclass
class KGNode:
    node_id:    str
    node_type:  str
    properties: dict[str, Any] = field(default_factory=dict)

@dataclass
class KGEdge:
    source:     str
    target:     str
    edge_type:  str
    weight:     float = 1.0
    properties: dict[str, Any] = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Knowledge Graph Builder
# ─────────────────────────────────────────────────────────────────────────────
class CerebroKnowledgeGraph:
    """
    Builds a heterogeneous knowledge graph from CEREBRO-X pipeline data.

    The graph captures:
      Drug → (targets) → Protein
      Drug → (treats) → Disease
      Drug → (carried_by) → DDS_Carrier
      DDS_Carrier → (crosses_via) → BBB_Mechanism
      Formulation → (formulated_with) → DDS_Carrier
      Formulation → (ligand_on) → Surface_Ligand
      Surface_Ligand → (binds_to) → BBB_Receptor

    Node features:
      Drug:        MW, LogP, Half_Life, BBB_native, fingerprint vector
      DDS_Carrier: size_nm, zeta_mV, PDI, EE%, drug_loading%
      Formulation: BBB_Engineering_Score, all DDS params
    """

    def __init__(self):
        self.nodes: dict[str, KGNode] = {}
        self.edges: list[KGEdge] = []
        self.graph: Any | None = None  # networkx graph

    def add_node(self, node_id: str, node_type: str,
                 properties: dict = None):
        self.nodes[node_id] = KGNode(
            node_id=node_id,
            node_type=node_type,
            properties=properties or {},
        )

    def add_edge(self, source: str, target: str, edge_type: str,
                 weight: float = 1.0, properties: dict = None):
        self.edges.append(KGEdge(
            source=source, target=target, edge_type=edge_type,
            weight=weight, properties=properties or {},
        ))

    # ── Builders from pipeline data ──────────────────────────────────────

    def build_from_pipeline_data(
        self,
        drug_df:          pd.DataFrame = None,
        formulation_df:   pd.DataFrame = None,
        drug_profile:     dict = None,
    ):
        """
        Populate the KG from CEREBRO-X pipeline outputs.
        """
        # Drug nodes
        if drug_df is not None:
            for _, row in drug_df.iterrows():
                drug_name = str(row.get("Drug", "unknown"))
                self.add_node(
                    f"drug:{drug_name}", NodeType.DRUG,
                    {
                        "MW_Da":          row.get("MW_Da"),
                        "LogP":           row.get("LogP"),
                        "Half_Life_Days": row.get("Half_Life_Days"),
                        "Molecule_Class": row.get("Molecule_Class", "small_molecule"),
                    }
                )

                # Disease
                indication = row.get("Indication", "")
                if indication:
                    disease_id = f"disease:{indication}"
                    self.add_node(disease_id, NodeType.DISEASE,
                                 {"name": indication})
                    self.add_edge(f"drug:{drug_name}", disease_id,
                                 EdgeType.TREATS)

                # Target protein
                target = row.get("Target_Protein", "")
                if target:
                    target_id = f"protein:{target}"
                    self.add_node(target_id, NodeType.TARGET_PROTEIN,
                                 {"name": target})
                    affinity = row.get("Docking_Affinity_kcal", -8.0)
                    self.add_edge(f"drug:{drug_name}", target_id,
                                 EdgeType.TARGETS,
                                 weight=abs(affinity or 8.0))

        # Formulation nodes + DDS carrier nodes
        if formulation_df is not None:
            carrier_set: set[str] = set()

            for _, row in formulation_df.iterrows():
                form_id = str(row.get("Formulation_ID", "F_unknown"))
                carrier = str(row.get("Carrier_Type", "unknown"))

                # Formulation node
                self.add_node(
                    f"form:{form_id}", NodeType.FORMULATION,
                    {
                        "name":          row.get("Formulation_Name", ""),
                        "size_nm":       row.get("size_nm"),
                        "zeta_mv":       row.get("zeta_potential_mv"),
                        "pdi":           row.get("pdi"),
                        "ee_pct":        row.get("encapsulation_efficiency_pct"),
                        "bbb_score":     row.get("BBB_Engineering_Score"),
                        "drug_loading":  row.get("drug_loading_pct"),
                    }
                )

                # DDS Carrier node (dedup)
                carrier_id = f"carrier:{carrier}"
                if carrier not in carrier_set:
                    self.add_node(carrier_id, NodeType.DDS_CARRIER,
                                 {"name": carrier})
                    carrier_set.add(carrier)

                self.add_edge(f"form:{form_id}", carrier_id,
                              EdgeType.FORMULATED_WITH)

                # Drug → Carrier
                drug_name = str(row.get("Drug", "unknown"))
                self.add_edge(f"drug:{drug_name}", carrier_id,
                              EdgeType.CARRIED_BY,
                              weight=row.get("BBB_Engineering_Score", 50) / 100)

                # Surface ligand
                ligand = str(row.get("Surface_Ligand", ""))
                if ligand and ligand.lower() not in ("none", "nan", ""):
                    lig_id = f"ligand:{ligand}"
                    self.add_node(lig_id, NodeType.SURFACE_LIGAND,
                                 {"name": ligand})
                    self.add_edge(f"form:{form_id}", lig_id,
                                 EdgeType.LIGAND_ON)

                    # Map ligand → BBB receptor
                    receptor_map = {
                        "rvg":        "nAChR",
                        "angiopep":   "LRP1",
                        "transferrin": "TfR1",
                        "apoe":       "LDLR",
                        "glucose":    "GLUT1",
                        "glut1":      "GLUT1",
                        "insulin":    "IR",
                        "lactoferrin": "LfR",
                    }
                    for key, receptor in receptor_map.items():
                        if key in ligand.lower():
                            rec_id = f"receptor:{receptor}"
                            self.add_node(rec_id, NodeType.BBB_RECEPTOR,
                                         {"name": receptor})
                            self.add_edge(lig_id, rec_id, EdgeType.BINDS_TO)
                            break

                # Route
                route = str(row.get("route", "IV"))
                route_id = f"route:{route}"
                self.add_node(route_id, NodeType.ROUTE, {"name": route})
                self.add_edge(f"form:{form_id}", route_id,
                              EdgeType.ADMINISTERED_VIA)

                # BBB mechanism
                mechanism = str(row.get("cns_tropism", ""))
                if mechanism and mechanism.lower() not in ("none", "nan", ""):
                    mech_id = f"mechanism:{mechanism}"
                    self.add_node(mech_id, NodeType.BBB_MECHANISM,
                                 {"name": mechanism})
                    self.add_edge(carrier_id, mech_id, EdgeType.CROSSES_VIA)

        log.info(f"[KG] Built graph: {len(self.nodes)} nodes, "
                 f"{len(self.edges)} edges")

    # ── Convert to NetworkX ──────────────────────────────────────────────

    def to_networkx(self) -> "nx.DiGraph":
        """Convert the KG to a NetworkX directed graph."""
        if not _HAS_NX:
            raise ImportError("networkx required: pip install networkx")

        G = nx.DiGraph()
        for nid, node in self.nodes.items():
            G.add_node(nid, node_type=node.node_type, **node.properties)
        for edge in self.edges:
            G.add_edge(edge.source, edge.target,
                       edge_type=edge.edge_type,
                       weight=edge.weight,
                       **edge.properties)
        self.graph = G
        return G

    # ── Graph Analytics ──────────────────────────────────────────────────

    def centrality_analysis(self) -> dict[str, dict]:
        """
        Compute centrality metrics for all nodes.
        Identifies the most 'connected' drugs, carriers, and ligands.
        """
        if not _HAS_NX or self.graph is None:
            self.to_networkx()

        G = self.graph
        results = {}

        # Degree centrality
        deg = nx.degree_centrality(G)
        # Betweenness
        betw = nx.betweenness_centrality(G, weight="weight")
        # Pagerank
        pr = nx.pagerank(G, weight="weight")

        for node_id in G.nodes:
            results[node_id] = {
                "degree_centrality":     round(deg.get(node_id, 0), 4),
                "betweenness_centrality": round(betw.get(node_id, 0), 4),
                "pagerank":              round(pr.get(node_id, 0), 6),
                "node_type":             G.nodes[node_id].get("node_type", ""),
            }

        return results

    def find_top_carriers(self, top_n: int = 10) -> list[dict]:
        """Rank DDS carriers by graph centrality (versatility)."""
        centrality = self.centrality_analysis()
        carriers = [
            {"node_id": nid, **data}
            for nid, data in centrality.items()
            if data.get("node_type") == NodeType.DDS_CARRIER
        ]
        carriers.sort(key=lambda x: x["pagerank"], reverse=True)
        return carriers[:top_n]

    def find_path(self, source: str, target: str) -> list[str]:
        """Shortest path between two nodes in the KG."""
        if not _HAS_NX or self.graph is None:
            self.to_networkx()
        try:
            return nx.shortest_path(self.graph, source, target)
        except nx.NetworkXNoPath:
            return []

    def community_detection(self) -> dict[str, int]:
        """
        Detect communities (clusters of related drug-carrier pairs).
        Uses Louvain algorithm on undirected projection.
        """
        if not _HAS_NX or self.graph is None:
            self.to_networkx()

        G_undirected = self.graph.to_undirected()
        try:
            from networkx.algorithms.community import louvain_communities
            communities = louvain_communities(G_undirected, weight="weight")
            node_to_community = {}
            for i, comm in enumerate(communities):
                for node in comm:
                    node_to_community[node] = i
            return node_to_community
        except (ImportError, AttributeError):
            # Fallback: connected components
            components = nx.connected_components(G_undirected)
            node_to_community = {}
            for i, comp in enumerate(components):
                for node in comp:
                    node_to_community[node] = i
            return node_to_community

    def suggest_combinations(self, drug_id: str,
                             top_n: int = 5) -> list[dict]:
        """
        Link prediction: suggest new drug–carrier combinations
        based on graph structure (common neighbors, Jaccard).
        """
        if not _HAS_NX or self.graph is None:
            self.to_networkx()

        G = self.graph
        if drug_id not in G:
            return []

        # Get existing carriers for this drug
        existing = set()
        for _, target, data in G.edges(drug_id, data=True):
            if data.get("edge_type") == EdgeType.CARRIED_BY:
                existing.add(target)

        # Score all carriers not yet connected
        all_carriers = [
            nid for nid, data in G.nodes(data=True)
            if data.get("node_type") == NodeType.DDS_CARRIER
            and nid not in existing
        ]

        suggestions = []
        drug_neighbors = set(G.neighbors(drug_id))

        for carrier in all_carriers:
            carrier_neighbors = set(G.predecessors(carrier)) | set(G.neighbors(carrier))
            common = drug_neighbors & carrier_neighbors

            # Jaccard coefficient
            union = drug_neighbors | carrier_neighbors
            jaccard = len(common) / max(len(union), 1)

            # Adamic-Adar index (weighted common neighbors)
            aa_score = sum(
                1.0 / max(math.log(G.degree(cn)), 1e-6)
                for cn in common
            )

            suggestions.append({
                "carrier":      carrier,
                "jaccard":      round(jaccard, 4),
                "adamic_adar":  round(aa_score, 4),
                "common_neighbors": len(common),
                "score":        round(jaccard * 0.4 + aa_score * 0.6, 4),
            })

        suggestions.sort(key=lambda x: x["score"], reverse=True)
        return suggestions[:top_n]


# ─────────────────────────────────────────────────────────────────────────────
# 3. Graph Neural Network Models
# ─────────────────────────────────────────────────────────────────────────────
if _HAS_TORCH and _HAS_PYG:

    class CerebroGNN(nn.Module):
        """
        Heterogeneous Graph Neural Network for BBB score prediction.

        Architecture:
          Input: node features per type (Drug, Carrier, Formulation)
          Layer 1: HeteroConv (SAGEConv per edge type)
          Layer 2: HeteroConv (GATConv per edge type)
          Output: MLP regression → BBB_Engineering_Score

        The heterogeneous approach respects different node types
        (a drug node is fundamentally different from a carrier node).
        """

        def __init__(self, hidden_dim: int = 64, num_heads: int = 4):
            super().__init__()
            self.hidden_dim = hidden_dim

            # Node-type-specific input projections
            self.drug_proj    = nn.Linear(4, hidden_dim)   # MW, LogP, HL, Affinity
            self.carrier_proj = nn.Linear(5, hidden_dim)   # size, zeta, pdi, ee, dl
            self.form_proj    = nn.Linear(8, hidden_dim)   # all DDS params

            # Message passing layers
            self.conv1 = SAGEConv(hidden_dim, hidden_dim)
            self.conv2 = GATConv(hidden_dim, hidden_dim, heads=num_heads,
                                 concat=False)

            # Prediction head
            self.mlp = nn.Sequential(
                nn.Linear(hidden_dim, hidden_dim),
                nn.ReLU(),
                nn.Dropout(0.2),
                nn.Linear(hidden_dim, 1),
            )

        def forward(self, x, edge_index):
            h = self.conv1(x, edge_index)
            h = F.relu(h)
            h = F.dropout(h, p=0.2, training=self.training)
            h = self.conv2(h, edge_index)
            h = F.relu(h)
            out = self.mlp(h)
            return out.squeeze(-1)


    class MultimodalFusion(nn.Module):
        """
        Fuses text + structure + numeric features for drug representation.

        Modalities:
          1. Text: TF-IDF or pre-trained embeddings of drug description/MoA
          2. Structure: Morgan fingerprint vector (RDKit)
          3. Numeric: physicochemical properties (MW, LogP, etc.)

        Fusion: learned attention weights over modality embeddings.
        """

        def __init__(self, text_dim: int = 100, struct_dim: int = 256,
                     numeric_dim: int = 10, hidden_dim: int = 64):
            super().__init__()
            self.text_encoder    = nn.Linear(text_dim, hidden_dim)
            self.struct_encoder  = nn.Linear(struct_dim, hidden_dim)
            self.numeric_encoder = nn.Linear(numeric_dim, hidden_dim)

            # Attention-based fusion
            self.attention = nn.Sequential(
                nn.Linear(hidden_dim * 3, hidden_dim),
                nn.Tanh(),
                nn.Linear(hidden_dim, 3),
                nn.Softmax(dim=-1),
            )

            self.output = nn.Linear(hidden_dim, hidden_dim)

        def forward(self, text_feat, struct_feat, numeric_feat):
            h_text    = F.relu(self.text_encoder(text_feat))
            h_struct  = F.relu(self.struct_encoder(struct_feat))
            h_numeric = F.relu(self.numeric_encoder(numeric_feat))

            # Compute attention weights
            combined = torch.cat([h_text, h_struct, h_numeric], dim=-1)
            weights  = self.attention(combined)  # (batch, 3)

            # Weighted sum
            stacked = torch.stack([h_text, h_struct, h_numeric], dim=1)  # (batch, 3, hidden)
            fused   = (stacked * weights.unsqueeze(-1)).sum(dim=1)       # (batch, hidden)

            return self.output(fused)

elif _HAS_NX:
    # ── NetworkX fallback: graph features without GNN ────────────────────
    class GraphFeatureExtractor:
        """
        Extract graph-structural features for each node using NetworkX.
        These features can be fed into traditional ML models (RF, XGBoost).

        Features per node:
          - degree, in_degree, out_degree
          - clustering coefficient
          - betweenness centrality
          - pagerank
          - number of neighbors per type
        """

        @staticmethod
        def extract(G: "nx.DiGraph") -> pd.DataFrame:
            records = []
            betw = nx.betweenness_centrality(G, weight="weight")
            pr   = nx.pagerank(G, weight="weight")
            clust = nx.clustering(G.to_undirected())

            for node in G.nodes:
                data = G.nodes[node]
                records.append({
                    "node_id":         node,
                    "node_type":       data.get("node_type", ""),
                    "degree":          G.degree(node),
                    "in_degree":       G.in_degree(node),
                    "out_degree":      G.out_degree(node),
                    "betweenness":     betw.get(node, 0),
                    "pagerank":        pr.get(node, 0),
                    "clustering":      clust.get(node, 0),
                })
            return pd.DataFrame(records)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Multimodal Feature Builder (sklearn-based fallback)
# ─────────────────────────────────────────────────────────────────────────────
class MultimodalFeatureBuilder:
    """
    Combines text, structure, and numeric features for ML input.
    Works without PyTorch — uses sklearn TF-IDF + concatenation.
    """

    def __init__(self):
        self.tfidf = TfidfVectorizer(max_features=100) if _HAS_SKLEARN else None
        self.scaler = StandardScaler() if _HAS_SKLEARN else None
        self._fitted = False

    def fit_transform(
        self,
        texts:    list[str],
        numerics: np.ndarray,
        fingerprints: np.ndarray = None,
    ) -> np.ndarray:
        """
        Fit on training data and return fused feature matrix.

        Args:
            texts:        list of drug descriptions / MoA strings
            numerics:     (n, d) numeric property matrix
            fingerprints: (n, fp_dim) Morgan fingerprint matrix (optional)
        """
        features = []

        # Text features (TF-IDF)
        if self.tfidf and texts:
            text_feat = self.tfidf.fit_transform(texts).toarray()
            features.append(text_feat)

        # Numeric features (scaled)
        if self.scaler and numerics is not None:
            num_feat = self.scaler.fit_transform(numerics)
            features.append(num_feat)

        # Fingerprints (pass through)
        if fingerprints is not None:
            features.append(fingerprints)

        self._fitted = True
        return np.hstack(features) if features else numerics

    def transform(
        self,
        texts:    list[str],
        numerics: np.ndarray,
        fingerprints: np.ndarray = None,
    ) -> np.ndarray:
        """Transform new data using fitted parameters (no data leakage)."""
        if not self._fitted:
            raise RuntimeError("Call fit_transform first")

        features = []
        if self.tfidf and texts:
            features.append(self.tfidf.transform(texts).toarray())
        if self.scaler and numerics is not None:
            features.append(self.scaler.transform(numerics))
        if fingerprints is not None:
            features.append(fingerprints)

        return np.hstack(features) if features else numerics


# ─────────────────────────────────────────────────────────────────────────────
# 5. Export & Visualization
# ─────────────────────────────────────────────────────────────────────────────
def export_kg_to_json(kg: CerebroKnowledgeGraph, path: str):
    """Export the knowledge graph to JSON for visualization tools (e.g. D3.js)."""
    data = {
        "nodes": [
            {"id": nid, "type": n.node_type, **n.properties}
            for nid, n in kg.nodes.items()
        ],
        "edges": [
            {"source": e.source, "target": e.target,
             "type": e.edge_type, "weight": e.weight}
            for e in kg.edges
        ],
        "metadata": {
            "n_nodes": len(kg.nodes),
            "n_edges": len(kg.edges),
            "node_types": list(set(n.node_type for n in kg.nodes.values())),
            "edge_types": list(set(e.edge_type for e in kg.edges)),
            "exported_at": datetime.utcnow().isoformat(),
        }
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    log.info(f"[KG] Exported to {path}")