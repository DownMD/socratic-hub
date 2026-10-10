#!/usr/bin/env python3
"""
Prior Knowledge Scanner Engine.
Scans notes/index.json to classify candidate curriculum concepts as
[DUPLICATE], [PREREQUISITE_BRIDGE], [ANALOGY], or [NOVEL].
Adheres strictly to zero-emoji typography, file-backed IPC standards,
standard library execution, and non-crashing execution standards.
"""

import sys
import re
import json
import argparse
import difflib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def get_workspace_root(workspace_arg: Optional[str] = None) -> Path:
    """Resolves workspace root directory safely."""
    if workspace_arg:
        return Path(workspace_arg).resolve()
    return Path(__file__).resolve().parent.parent


def clean_simple(text: str) -> str:
    """Lowercases and strips punctuation."""
    cleaned = re.sub(r'[^\w\s]', ' ', text.lower())
    return " ".join(cleaned.split())


def stem_word(w: str) -> str:
    """Strips suffixes: trailing 'ies' -> 'y', strip 'ing', 'ed', 's'."""
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith("ing"):
        return w[:-3]
    if len(w) > 3 and w.endswith("ed"):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss") and not w.endswith("is"):
        return w[:-1]
    return w


def normalize(text: str) -> str:
    """Lowercases, strips punctuation, and stems word suffixes."""
    cleaned = re.sub(r'[^\w\s]', ' ', text.lower())
    words = [stem_word(w) for w in cleaned.split() if w]
    return " ".join(words)


def make_wikilink(rel_path: str, title: str) -> str:
    """Constructs cross-topic relative wikilink for Obsidian/markdown reference."""
    slug = rel_path.replace("\\", "/")
    if slug.startswith("notes/"):
        slug = slug[len("notes/"):]
    if slug.endswith(".md"):
        slug = slug[:-3]
    return f"[[../{slug}|{title}]]"


def match_concept_against_index(
    concepts: Dict[str, Dict[str, Any]],
    alias_map: Dict[str, str],
    concept: str,
    aliases: Optional[List[str]] = None,
    domain: Optional[str] = None
) -> Tuple[str, List[Dict[str, Any]]]:
    """Matches a single concept against index concepts dictionary and returns (classification, matches)."""
    candidate_concept = concept.strip()
    if not candidate_concept:
        return "[NOVEL]", []

    candidate_domain = domain.strip().lower() if domain else None
    query_aliases = [a.strip() for a in (aliases or []) if a.strip()]

    all_queries = [candidate_concept] + query_aliases
    scored_matches: List[Dict[str, Any]] = []

    for cid, cdata in concepts.items():
        ctitle = str(cdata.get("title") or "")
        cdomain = str(cdata.get("domain") or cdata.get("topic") or "")
        caliases = cdata.get("aliases", [])
        cprereqs = cdata.get("prerequisites", [])
        cpath = str(cdata.get("path") or "")
        cmechanism = str(cdata.get("core_mechanism") or "")

        norm_title = normalize(ctitle)
        norm_id = normalize(cid.replace('-', ' ').replace('_', ' '))
        simple_title = clean_simple(ctitle)
        simple_id = clean_simple(cid.replace('-', ' ').replace('_', ' '))

        is_core_match = False
        is_exact = False
        match_found = False
        highest_score = 0.0

        # 1. Exact match on core concept
        simple_cand = clean_simple(candidate_concept)
        norm_cand = normalize(candidate_concept)

        if simple_cand in (simple_title, simple_id) or norm_cand in (norm_title, norm_id):
            is_core_match = True
            is_exact = True
            match_found = True
            highest_score = 1.0

        # 2. Check alias_map & concept aliases & prerequisites for exact match
        if not match_found:
            cand_lower = candidate_concept.lower()
            if cand_lower in alias_map and alias_map[cand_lower] == cid:
                is_core_match = False
                is_exact = True
                match_found = True
                highest_score = 0.95

            if not match_found:
                for alias in caliases:
                    if simple_cand == clean_simple(alias) or norm_cand == normalize(alias):
                        is_core_match = False
                        is_exact = True
                        match_found = True
                        highest_score = 0.95
                        break

            if not match_found:
                for prereq in cprereqs:
                    prereq_clean = clean_simple(prereq.replace('-', ' ').replace('_', ' '))
                    prereq_norm = normalize(prereq.replace('-', ' ').replace('_', ' '))
                    if simple_cand == prereq_clean or norm_cand == prereq_norm:
                        is_core_match = False
                        is_exact = True
                        match_found = True
                        highest_score = 0.95
                        break

            if not match_found:
                for qa in query_aliases:
                    simple_qa = clean_simple(qa)
                    norm_qa = normalize(qa)
                    if simple_qa in (simple_title, simple_id) or norm_qa in (norm_title, norm_id):
                        is_core_match = False
                        is_exact = True
                        match_found = True
                        highest_score = 0.95
                        break

                    if qa.lower() in alias_map and alias_map[qa.lower()] == cid:
                        is_core_match = False
                        is_exact = True
                        match_found = True
                        highest_score = 0.95
                        break

                    for alias in caliases:
                        if simple_qa == clean_simple(alias) or norm_qa == normalize(alias):
                            is_core_match = False
                            is_exact = True
                            match_found = True
                            highest_score = 0.95
                            break
                    if match_found:
                        break

        # 3. Fuzzy match check if no exact match found
        if not match_found:
            fuzzy_targets = [norm_title, norm_id]
            for a in caliases:
                fuzzy_targets.append(normalize(a))
            for p in cprereqs:
                fuzzy_targets.append(normalize(p.replace('-', ' ').replace('_', ' ')))

            best_ratio = 0.0
            for q in all_queries:
                norm_q = normalize(q)
                for tgt in fuzzy_targets:
                    if not tgt or not norm_q:
                        continue
                    ratio = difflib.SequenceMatcher(None, norm_q, tgt).ratio()
                    if ratio > best_ratio:
                        best_ratio = ratio

            if best_ratio >= 0.85:
                is_core_match = False
                is_exact = False
                match_found = True
                highest_score = best_ratio

        if match_found:
            domains_match = False
            if candidate_domain and cdomain:
                domains_match = (candidate_domain == cdomain.strip().lower())
            elif not candidate_domain:
                domains_match = True

            if domains_match:
                if is_core_match and is_exact:
                    match_type = "[DUPLICATE]"
                else:
                    match_type = "[PREREQUISITE_BRIDGE]"
            else:
                match_type = "[ANALOGY]"

            wikilink = make_wikilink(cpath, ctitle)
            scored_matches.append({
                "query_concept": candidate_concept,
                "match_type": match_type,
                "matched_id": cid,
                "matched_title": ctitle,
                "domain": cdomain,
                "path": cpath,
                "core_mechanism": cmechanism,
                "wikilink": wikilink,
                "_score": highest_score,
                "_is_exact": 1 if is_exact else 0,
            })

    if not scored_matches:
        return "[NOVEL]", []

    scored_matches.sort(key=lambda m: (m["_is_exact"], m["_score"]), reverse=True)

    results: List[Dict[str, Any]] = []
    seen_ids = set()
    for m in scored_matches:
        mcid = m["matched_id"]
        if mcid in seen_ids:
            continue
        seen_ids.add(mcid)
        cleaned_m = {k: v for k, v in m.items() if not k.startswith("_")}
        results.append(cleaned_m)

    classification = results[0]["match_type"] if results else "[NOVEL]"
    return classification, results


def load_index_data(workspace_root: Path) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
    """Loads notes/index.json or returns empty dicts."""
    index_file = workspace_root / "notes" / "index.json"
    if not index_file.exists():
        return {}, {}
    try:
        with open(index_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("concepts", {}), data.get("alias_map", {})
    except Exception as e:
        sys.stderr.write(f"[STANDBY] Warning: Failed to read {index_file}: {e}\n")
        return {}, {}


def scan_prior_knowledge(
    workspace_root: Path,
    concept: str,
    aliases: Optional[List[str]] = None,
    domain: Optional[str] = None
) -> None:
    """Performs prior knowledge matching against notes/index.json for a single concept."""
    concepts, alias_map = load_index_data(workspace_root)
    novel_payload = {"matches": [], "status": "[NOVEL]"}

    if not concepts:
        print(json.dumps(novel_payload, indent=2, ensure_ascii=False))
        return

    classification, matches = match_concept_against_index(
        concepts=concepts,
        alias_map=alias_map,
        concept=concept,
        aliases=aliases,
        domain=domain
    )

    if not matches:
        print(json.dumps(novel_payload, indent=2, ensure_ascii=False))
        return

    print(json.dumps(matches, indent=2, ensure_ascii=False))


def scan_curriculum_batch(
    workspace_root: Path,
    curriculum_path: Path,
    domain: Optional[str] = None,
    output_path: Optional[Path] = None
) -> None:
    """Performs batch prior knowledge matching across all nodes in a curriculum file."""
    if not curriculum_path.is_absolute():
        curriculum_path = workspace_root / curriculum_path

    if not curriculum_path.exists():
        sys.stderr.write(f"[BATCH] Error: Curriculum file not found at {curriculum_path}\n")
        print("[]")
        return

    try:
        with open(curriculum_path, "r", encoding="utf-8") as f:
            c_data = json.load(f)
    except Exception as e:
        sys.stderr.write(f"[BATCH] Error reading {curriculum_path}: {e}\n")
        print("[]")
        return

    nodes = c_data.get("nodes", []) if isinstance(c_data, dict) else (c_data if isinstance(c_data, list) else [])
    concepts, alias_map = load_index_data(workspace_root)
    default_domain = domain or (c_data.get("domain") if isinstance(c_data, dict) else None)

    results: List[Dict[str, Any]] = []

    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id", ""))
        concept_title = str(node.get("title") or node.get("label") or node_id)
        node_aliases = node.get("aliases", [])
        if isinstance(node_aliases, str):
            node_aliases = [node_aliases]
        node_domain = domain or node.get("domain") or default_domain

        if not concepts:
            classification, matches = "[NOVEL]", []
        else:
            classification, matches = match_concept_against_index(
                concepts=concepts,
                alias_map=alias_map,
                concept=concept_title,
                aliases=node_aliases,
                domain=node_domain
            )

        results.append({
            "id": node_id,
            "concept": concept_title,
            "classification": classification,
            "matches": matches
        })

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_p = output_path.with_name(f"{output_path.name}.tmp")
        with open(tmp_p, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        tmp_p.replace(output_path)

    print(json.dumps(results, indent=2, ensure_ascii=False))


def scan_topic_prior_knowledge(
    workspace_root: Path,
    topic_name: str,
    domain: Optional[str] = None,
    output_path: Optional[Path] = None
) -> None:
    """Scans notes/index.json to produce categorized prior knowledge candidates for a topic."""
    concepts, alias_map = load_index_data(workspace_root)
    topic_clean = clean_simple(topic_name)
    topic_tokens = set(normalize(topic_name).split())
    target_domain = domain.lower().strip() if domain else None

    results: List[Dict[str, Any]] = []

    for cid, cdata in concepts.items():
        ctitle = str(cdata.get("title") or "")
        cdomain = str(cdata.get("domain") or cdata.get("topic") or "").lower().strip()
        cmechanism = str(cdata.get("core_mechanism") or "")
        cpath = str(cdata.get("path") or "")

        norm_title = normalize(ctitle)
        title_tokens = set(norm_title.split())

        relevance = 0.0
        if topic_clean in clean_simple(ctitle) or clean_simple(ctitle) in topic_clean:
            relevance = 1.0
        elif topic_tokens and title_tokens and (topic_tokens & title_tokens):
            relevance = len(topic_tokens & title_tokens) / max(len(topic_tokens), 1)

        same_domain = (target_domain is not None and (target_domain in cdomain or cdomain in target_domain))

        if relevance > 0.0 or same_domain or len(results) < 30:
            if norm_title == normalize(topic_name):
                tag = "REUSE_CANONICAL" if same_domain or not target_domain else "DOMAIN_HOMONYM"
            elif same_domain and (relevance >= 0.5 or (topic_tokens & title_tokens)):
                tag = "EXTEND_CONTEXT"
            elif not same_domain and target_domain and (relevance >= 0.7):
                tag = "DOMAIN_HOMONYM"
            elif same_domain:
                tag = "EXTEND_CONTEXT"
            else:
                tag = "NOVEL"

            rel_path = cpath
            if rel_path.startswith(str(workspace_root)):
                try:
                    rel_path = str(Path(cpath).relative_to(workspace_root))
                except Exception:
                    pass

            results.append({
                "concept": ctitle,
                "id": cid,
                "domain": cdomain,
                "tag": tag,
                "wikilink": make_wikilink(rel_path, ctitle),
                "core_mechanism": cmechanism,
                "score": round(relevance, 2)
            })

    results.sort(key=lambda x: (0 if x["tag"] == "REUSE_CANONICAL" else (1 if x["tag"] == "EXTEND_CONTEXT" else 2), -x["score"]))

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_p = output_path.with_name(f"{output_path.name}.tmp")
        with open(tmp_p, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        tmp_p.replace(output_path)

    print(json.dumps(results, indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Prior Knowledge Scanner")
    parser.add_argument("--concept", default=None, help="Candidate concept name")
    parser.add_argument("--topic", default=None, help="Topic name to scan prior knowledge for")
    parser.add_argument("--curriculum", type=str, default=None, help="Path to curriculum JSON for batch scanning")
    parser.add_argument("--manifest", type=str, default=None, help="Path to topic manifest.json for batch scanning")
    parser.add_argument("--batch", action="store_true", help="Batch scan all concepts in curriculum.json")
    parser.add_argument("--aliases", type=str, default=None, help="Comma-separated query aliases")
    parser.add_argument("--domain", type=str, default=None, help="Candidate domain")
    parser.add_argument("--output", type=str, default=None, help="Optional output JSON file path")
    parser.add_argument("--workspace-dir", type=str, default=None, help="Workspace root directory")

    args = parser.parse_args()
    workspace_root = get_workspace_root(args.workspace_dir)

    target_batch_file = args.manifest or args.curriculum
    if args.batch and not target_batch_file:
        target_batch_file = str(workspace_root / "state" / "curriculum.json")

    if args.topic:
        scan_topic_prior_knowledge(
            workspace_root=workspace_root,
            topic_name=args.topic,
            domain=args.domain,
            output_path=Path(args.output) if args.output else None
        )
    elif target_batch_file:
        scan_curriculum_batch(
            workspace_root=workspace_root,
            curriculum_path=Path(target_batch_file),
            domain=args.domain,
            output_path=Path(args.output) if args.output else None
        )
    elif args.concept:
        alias_list = [a.strip() for a in args.aliases.split(',')] if args.aliases else None
        scan_prior_knowledge(
            workspace_root=workspace_root,
            concept=args.concept,
            aliases=alias_list,
            domain=args.domain
        )
    else:
        parser.error("Either --topic, --concept, --manifest, or --curriculum / --batch must be provided.")


if __name__ == "__main__":
    main()

