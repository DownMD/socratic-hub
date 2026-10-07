"""
scripts/clean_knowledge_graph.py

Deterministic deduplication and transitive reduction (Hasse diagram reduction)
for state/knowledge_graph.json.
"""

import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Set, Union

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = BASE_DIR / "state"
KNOWLEDGE_GRAPH_FILE = STATE_DIR / "knowledge_graph.json"

MERGE_MAP = {
    "processing-time-station-capacity-parallel-servers": "processing-time-station-capacity",
    "core-case-particles-accusative-wo-and-dative-locative-ni-de": "core-case-particles-wo-ni-de",
    "directional-temporal-comitative-markers-e-kara-made-to": "directional-temporal-e-kara-made-to"
}
MERGES = MERGE_MAP


def transitive_reduction(edges_or_kg: Union[List[Dict[str, Any]], Dict[str, Any]]) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Computes the transitive reduction of a directed graph (DAG).
    An edge u -> v is a transitive shortcut (redundant) if there exists
    an alternate path from u to v of length >= 2 (i.e. through an intermediate node).
    """
    is_dict = isinstance(edges_or_kg, dict)
    edges: List[Dict[str, Any]] = edges_or_kg.get("edges", []) if is_dict else edges_or_kg

    adj: Dict[str, Set[str]] = defaultdict(set)
    for e in edges:
        s = e.get("source")
        t = e.get("target")
        if s and t and s != t:
            s_id = s.get("id") if isinstance(s, dict) else str(s)
            t_id = t.get("id") if isinstance(t, dict) else str(t)
            if s_id and t_id and s_id != t_id:
                adj[s_id].add(t_id)

    # Precompute transitive reachability for every node in the DAG
    reachable: Dict[str, Set[str]] = {}

    def get_reachable(u: str, visited: Set[str] = None) -> Set[str]:
        if u in reachable:
            return reachable[u]
        if visited is None:
            visited = set()
        visited.add(u)
        res = set()
        for v in adj.get(u, set()):
            res.add(v)
            if v not in visited:
                res.update(get_reachable(v, visited))
        reachable[u] = res
        return res

    for u in list(adj.keys()):
        get_reachable(u)

    reduced_edges: List[Dict[str, Any]] = []
    seen: Set[tuple] = set()

    for e in edges:
        s = e.get("source")
        t = e.get("target")
        s_id = s.get("id") if isinstance(s, dict) else str(s) if s else ""
        t_id = t.get("id") if isinstance(t, dict) else str(t) if t else ""

        if not s_id or not t_id or s_id == t_id:
            continue
        if (s_id, t_id) in seen:
            continue
        seen.add((s_id, t_id))

        # Check if an alternate path of length >= 2 exists:
        # namely, there exists some intermediate w in adj[s_id] with w != t_id and t_id in reachable[w]
        has_alternate = any(t_id in reachable.get(w, set()) for w in adj.get(s_id, set()) if w != t_id)
        if not has_alternate:
            reduced_edges.append(e)

    if is_dict:
        edges_or_kg["edges"] = reduced_edges
        return edges_or_kg
    return reduced_edges


def clean_knowledge_graph(target_path: Path = None) -> Dict[str, Any]:
    """
    Deduplicates concept nodes, remaps edge references, removes self-loops and shortcuts,
    and atomically saves the result to state/knowledge_graph.json.
    """
    file_path = target_path or KNOWLEDGE_GRAPH_FILE
    if not file_path.exists():
        raise FileNotFoundError(f"Knowledge graph file not found at {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        kg = json.load(f)

    nodes = kg.get("nodes", [])
    edges = kg.get("edges", [])

    # 1. Deduplicate & merge nodes
    new_nodes: List[Dict[str, Any]] = []
    nodes_by_id: Dict[str, Dict[str, Any]] = {}

    for n in nodes:
        nid = n.get("id")
        if not nid:
            continue
        # If this is one of the duplicate nodes to be merged away, skip it
        if nid in MERGES:
            continue

        # If this is the canonical target node of a merge, ensure status is "mastered"
        if nid in MERGES.values():
            n["status"] = "mastered"

        nodes_by_id[nid] = n
        new_nodes.append(n)

    # 2. Remap edges and drop self-loops
    remapped_edges: List[Dict[str, Any]] = []
    seen_edges: Set[tuple] = set()

    for e in edges:
        s = e.get("source")
        t = e.get("target")
        s_id = s.get("id") if isinstance(s, dict) else str(s)
        t_id = t.get("id") if isinstance(t, dict) else str(t)

        s_mapped = MERGES.get(s_id, s_id)
        t_mapped = MERGES.get(t_id, t_id)

        if s_mapped and t_mapped and s_mapped != t_mapped:
            if (s_mapped, t_mapped) not in seen_edges:
                seen_edges.add((s_mapped, t_mapped))
                remapped_edges.append({
                    "source": s_mapped,
                    "target": t_mapped,
                    "relation": e.get("relation", "prerequisite")
                })

    # 3. Transitive reduction
    initial_edge_count = len(remapped_edges)
    reduced_edges = transitive_reduction(remapped_edges)
    removed_edge_count = initial_edge_count - len(reduced_edges)

    cleaned_kg = {
        "nodes": new_nodes,
        "edges": reduced_edges
    }

    # 4. Atomic file overwrite
    temp_file = file_path.with_suffix(".tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(cleaned_kg, f, indent=2)
    temp_file.replace(file_path)

    print(f"[CLEAN] Deduplicated nodes: {len(nodes)} -> {len(new_nodes)}")
    print(f"[CLEAN] Transitive reduction: removed {removed_edge_count} shortcut edges ({initial_edge_count} -> {len(reduced_edges)})")
    print(f"[CLEAN] Atomically written to {file_path}")

    return cleaned_kg


if __name__ == "__main__":
    clean_knowledge_graph()
