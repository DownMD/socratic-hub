import json
from pathlib import Path

def repair():
    kg_path = Path("state/knowledge_graph.json")
    if not kg_path.exists():
        print("knowledge_graph.json does not exist")
        return

    with open(kg_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    nodes = data.get("nodes", [])
    node_ids = {n["id"]: n for n in nodes if "id" in n}

    jlpt_edges = [
        ("topic-nominative-information-structure-wa-vs-ga", "core-case-particles-wo-ni-de"),
        ("core-case-particles-wo-ni-de", "directional-temporal-e-kara-made-to"),
        ("directional-temporal-e-kara-made-to", "nominal-conjunctions-no-ya-ka-mo"),
        ("topic-nominative-information-structure-wa-vs-ga", "copular-predicates-da-desu"),
        ("copular-predicates-da-desu", "verbal-conjugation-classes-godan-ichidan"),
        ("verbal-conjugation-classes-godan-ichidan", "polite-verbal-conjugation-masu"),
        ("core-case-particles-wo-ni-de", "existential-predication-iru-vs-aru"),
        ("polite-verbal-conjugation-masu", "existential-predication-iru-vs-aru"),
        ("prenominal-head-final-adjective-modification", "adjective-tense-inflection-i-vs-na"),
        ("copular-predicates-da-desu", "adjective-tense-inflection-i-vs-na"),
        ("adjective-tense-inflection-i-vs-na", "adverbial-derivation-ku-ni-naru"),
        ("verbal-conjugation-classes-godan-ichidan", "verbal-te-form-onbin"),
        ("existential-predication-iru-vs-aru", "aspectual-syntax-te-iru"),
        ("verbal-te-form-onbin", "aspectual-syntax-te-iru"),
        ("verbal-te-form-onbin", "deontic-modalities-kudasai-mo-ii-wa-ikenai"),
        ("polite-verbal-conjugation-masu", "plain-inflection-paradigm-dict-nai-ta"),
        ("verbal-te-form-onbin", "plain-inflection-paradigm-dict-nai-ta"),
        ("core-case-particles-wo-ni-de", "desiderative-purposive-tai-ni-iku"),
        ("polite-verbal-conjugation-masu", "desiderative-purposive-tai-ni-iku"),
        ("adjective-tense-inflection-i-vs-na", "desiderative-purposive-tai-ni-iku"),
        ("plain-inflection-paradigm-dict-nai-ta", "clausal-subordination-kara-node-ga"),
        ("copular-predicates-da-desu", "clausal-subordination-kara-node-ga"),
        ("core-case-particles-wo-ni-de", "core-case-particles-accusative-wo-and-dative-locative-ni-de"),
        ("directional-temporal-e-kara-made-to", "directional-temporal-comitative-markers-e-kara-made-to"),
    ]

    process_edges = [
        ("little-s-law", "multi-stage-flow-wip"),
        ("multi-stage-flow-wip", "processing-time-station-capacity"),
        ("processing-time-station-capacity", "cycle-time-takt-time"),
        ("processing-time-station-capacity", "bottleneck-identification"),
        ("cycle-time-takt-time", "bottleneck-identification"),
        ("bottleneck-identification", "utilization-starvation-blocking"),
        ("little-s-law", "utilization-starvation-blocking"),
        ("cycle-time-takt-time", "line-balancing-balance-delay"),
        ("utilization-starvation-blocking", "line-balancing-balance-delay"),
        ("cycle-time-takt-time", "process-variability-cv"),
        ("process-variability-cv", "kingman-s-vut-equation"),
        ("utilization-starvation-blocking", "kingman-s-vut-equation"),
        ("kingman-s-vut-equation", "buffer-sizing-decoupling"),
        ("bottleneck-identification", "buffer-sizing-decoupling"),
        ("processing-time-station-capacity", "setups-batching-mechanics"),
        ("bottleneck-identification", "setups-batching-mechanics"),
        ("setups-batching-mechanics", "ebq-smed-reduction"),
        ("bottleneck-identification", "yield-losses-rework-loops"),
        ("multi-stage-flow-wip", "yield-losses-rework-loops"),
        ("utilization-starvation-blocking", "multi-product-mix-implied-utilization"),
        ("bottleneck-identification", "multi-product-mix-implied-utilization"),
        ("multi-product-mix-implied-utilization", "dynamic-shifting-bottlenecks"),
        ("kingman-s-vut-equation", "dynamic-shifting-bottlenecks"),
        ("dynamic-shifting-bottlenecks", "theory-of-constraints-dbr"),
        ("buffer-sizing-decoupling", "theory-of-constraints-dbr"),
        ("ebq-smed-reduction", "theory-of-constraints-dbr"),
        ("processing-time-station-capacity", "processing-time-station-capacity-parallel-servers"),
    ]

    seen = set()
    valid_edges = []
    for s, t in jlpt_edges + process_edges:
        if s in node_ids and t in node_ids and s != t:
            if (s, t) not in seen:
                seen.add((s, t))
                valid_edges.append({
                    "source": s,
                    "target": t,
                    "relation": "prerequisite"
                })

    data["edges"] = valid_edges
    data["links"] = valid_edges

    with open(kg_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Successfully repaired state/knowledge_graph.json: {len(nodes)} nodes, {len(valid_edges)} edges")

if __name__ == "__main__":
    repair()
