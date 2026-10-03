#!/usr/bin/env python3
"""
Scoped Reference Retrieval Engine.
Performs fast, collection-scoped, and tag-filtered lookups against partitioned reference chunks.
Adheres strictly to zero-emoji typography, file-backed IPC standards, and non-crashing execution.
"""

import sys
import re
import json
import argparse
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def normalize_query(query: str) -> Tuple[str, List[str]]:
    """
    Normalizes query by lowercasing and stripping punctuation.
    Returns (cleaned_query_string, list_of_tokens).
    """
    cleaned = re.sub(r'[^\w\s]', ' ', query.lower())
    tokens = [tok for tok in cleaned.split() if tok]
    return cleaned, tokens


def extract_excerpt(text: str, query: str, query_tokens: List[str], target_min: int = 400, target_max: int = 700) -> str:
    """
    Extracts a clean excerpt (~400 to 700 characters) surrounding the best match,
    or the full text if concise.
    """
    text_clean = text.strip()
    if len(text_clean) <= target_max:
        return text_clean

    text_lower = text_clean.lower()
    match_start = -1
    match_end = -1

    # 1. Try exact query string match
    q_str = query.strip().lower()
    if q_str:
        idx = text_lower.find(q_str)
        if idx != -1:
            match_start = idx
            match_end = idx + len(q_str)

    # 2. Try phrase regex with normalized tokens
    if match_start == -1 and len(query_tokens) > 1:
        has_cjk = any(re.search(r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]', t) for t in query_tokens)
        if has_cjk:
            cjk_phrase = "".join(query_tokens).lower()
            idx = text_lower.find(cjk_phrase)
            if idx != -1:
                match_start = idx
                match_end = idx + len(cjk_phrase)
        if match_start == -1:
            phrase_regex = re.compile(r'\b' + r'\s+'.join(re.escape(t) for t in query_tokens) + r'\b', re.IGNORECASE)
            m = phrase_regex.search(text_clean)
            if m:
                match_start = m.start()
                match_end = m.end()

    # 3. Try finding any query token
    if match_start == -1 and query_tokens:
        best_token_idx = -1
        for tok in query_tokens:
            is_cjk = bool(re.search(r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]', tok))
            if is_cjk:
                idx = text_lower.find(tok)
                if idx != -1:
                    if best_token_idx == -1 or idx < best_token_idx:
                        best_token_idx = idx
                        match_end = idx + len(tok)
            else:
                tok_re = re.compile(r'\b' + re.escape(tok) + r'\b', re.IGNORECASE)
                m = tok_re.search(text_clean)
                if m:
                    if best_token_idx == -1 or m.start() < best_token_idx:
                        best_token_idx = m.start()
                        match_end = m.end()
        if best_token_idx != -1:
            match_start = best_token_idx

    # If no match in text at all, take from the beginning
    if match_start == -1:
        match_start = 0
        match_end = 0

    target_len = 550
    match_mid = (match_start + match_end) // 2
    half = target_len // 2
    raw_start = max(0, match_mid - half)
    raw_end = min(len(text_clean), raw_start + target_len)
    if raw_end == len(text_clean):
        raw_start = max(0, raw_end - target_len)

    # Adjust start to sentence or word boundary
    start_pos = raw_start
    if start_pos > 0:
        search_start = max(0, start_pos - 50)
        search_end = min(len(text_clean), start_pos + 50)
        found_boundary = -1
        for m in re.finditer(r'(\. |\n\n|\n)', text_clean[search_start:search_end]):
            found_boundary = search_start + m.end()
        if found_boundary != -1 and found_boundary < match_start:
            start_pos = found_boundary
        else:
            space_idx = text_clean.find(" ", start_pos)
            if space_idx != -1 and space_idx < start_pos + 30:
                start_pos = space_idx + 1

    # Adjust end to sentence or word boundary
    end_pos = raw_end
    if end_pos < len(text_clean):
        search_start = max(0, end_pos - 50)
        search_end = min(len(text_clean), end_pos + 60)
        found_boundary = -1
        for m in re.finditer(r'(\. |\n\n|\n)', text_clean[search_start:search_end]):
            found_boundary = search_start + m.start() + 1
            if found_boundary > match_end:
                break
        if found_boundary != -1 and found_boundary > match_end:
            end_pos = found_boundary
        else:
            space_idx = text_clean.rfind(" ", search_start, end_pos)
            if space_idx != -1 and space_idx > match_end:
                end_pos = space_idx

    snippet = text_clean[start_pos:end_pos].strip()
    if start_pos > 0 and not snippet.startswith("..."):
        snippet = "... " + snippet
    if end_pos < len(text_clean) and not snippet.endswith("..."):
        snippet = snippet + " ..."

    return snippet


def score_chunk(
    chunk: Dict[str, Any],
    query_raw: str,
    query_tokens: List[str]
) -> Tuple[float, str]:
    """
    Computes relevance score and extracts snippet for a chunk according to:
    - Exact Phrase Bonus: +20.0 points if exact query appears in heading, breadcrumb, or body.
    - Heading & Breadcrumb Match: +6.0 points for each query token matching a word in heading or breadcrumb.
    - Body Keyword Density: +1.5 points per occurrence in body, capped at +15.0 points.
    Returns (total_score, excerpt).
    """
    if not query_tokens:
        return 0.0, ""

    heading = str(chunk.get("heading", ""))
    breadcrumb = str(chunk.get("breadcrumb", ""))
    text = str(chunk.get("text", ""))

    heading_lower = heading.lower()
    breadcrumb_lower = breadcrumb.lower()
    text_lower = text.lower()

    # 1. Exact Phrase Bonus (+20.0)
    phrase_bonus = 0.0
    q_str = query_raw.strip().lower()
    if q_str and (q_str in heading_lower or q_str in breadcrumb_lower or q_str in text_lower):
        phrase_bonus = 20.0
    elif len(query_tokens) >= 1:
        has_cjk = any(re.search(r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]', t) for t in query_tokens)
        if has_cjk:
            cjk_phrase = "".join(query_tokens).lower()
            if (cjk_phrase in heading_lower or cjk_phrase in breadcrumb_lower or cjk_phrase in text_lower):
                phrase_bonus = 20.0
        else:
            phrase_regex = re.compile(r'\b' + r'\s+'.join(re.escape(t) for t in query_tokens) + r'\b', re.IGNORECASE)
            if phrase_regex.search(heading) or phrase_regex.search(breadcrumb) or phrase_regex.search(text):
                phrase_bonus = 20.0

    # 2. Heading & Breadcrumb Match (+6.0 per query token)
    heading_score = 0.0
    hb_text = f"{heading_lower} {breadcrumb_lower}"
    hb_words = set(re.findall(r'\b\w+\b', hb_text))
    for tok in set(query_tokens):
        is_cjk = bool(re.search(r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]', tok))
        if is_cjk:
            if tok in hb_text:
                heading_score += 6.0
        else:
            if tok in hb_words:
                heading_score += 6.0

    # 3. Body Keyword Density (+1.5 per occurrence, capped at +15.0)
    total_occurrences = 0
    for tok in set(query_tokens):
        is_cjk = bool(re.search(r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]', tok))
        if is_cjk:
            count = 0
            start = 0
            while True:
                idx = text_lower.find(tok, start)
                if idx == -1:
                    break
                count += 1
                start = idx + len(tok)
            total_occurrences += count
        else:
            matches = re.findall(r'\b' + re.escape(tok) + r'\b', text_lower)
            total_occurrences += len(matches)

    body_score = min(total_occurrences * 1.5, 15.0)

    total_score = phrase_bonus + heading_score + body_score
    if total_score <= 0.0:
        return 0.0, ""

    # Multi-token queries with zero phrase or heading matches require more than 1 incidental body occurrence
    if len(query_tokens) > 1 and phrase_bonus == 0.0 and heading_score == 0.0 and total_score <= 2.0:
        return 0.0, ""

    excerpt = extract_excerpt(text, query_raw, query_tokens)
    return round(total_score, 2), excerpt


def locate_text(
    workspace_root: Path,
    query: str,
    collection: Optional[str] = None,
    tags: Optional[str] = None,
    limit: int = 3
) -> None:
    """
    Scans processed reference chunks, evaluates relevance, and outputs matches as JSON.
    """
    processed_dir = workspace_root / "references" / "processed"

    # Partition-Aware File Discovery
    chunk_files: List[Path] = []
    if collection:
        target_dir = processed_dir / collection
        if target_dir.exists() and target_dir.is_dir():
            chunk_files = sorted(list(target_dir.glob("*_chunks.json")))
    else:
        if processed_dir.exists() and processed_dir.is_dir():
            chunk_files = sorted(list(processed_dir.glob("*/*_chunks.json")))
            if not chunk_files:
                chunk_files = sorted(list(processed_dir.rglob("*_chunks.json")))

    if not chunk_files:
        print("[]")
        sys.exit(0)

    # Normalize Tags Filter
    filter_tags: List[str] = []
    if tags:
        filter_tags = [t.strip().lower() for t in tags.split(",") if t.strip()]

    # Normalize Query
    _, query_tokens = normalize_query(query)
    if not query_tokens:
        print("[]")
        sys.exit(0)

    scored_chunks: List[Dict[str, Any]] = []

    for c_path in chunk_files:
        try:
            with open(c_path, "r", encoding="utf-8", errors="replace") as f:
                data = json.load(f)
        except Exception:
            continue

        if not isinstance(data, list):
            continue

        for chunk in data:
            if not isinstance(chunk, dict):
                continue

            # Tag Filtering
            if filter_tags:
                chunk_tags = [str(t).strip().lower() for t in chunk.get("tags", []) if isinstance(t, str)]
                if not any(t in chunk_tags for t in filter_tags):
                    continue

            try:
                score, excerpt = score_chunk(chunk, query, query_tokens)
                if score > 0.0:
                    scored_chunks.append({
                        "id": chunk.get("id", ""),
                        "collection": chunk.get("collection", ""),
                        "document_title": chunk.get("document_title", ""),
                        "source_file": chunk.get("source_file", ""),
                        "page_start": chunk.get("page_start", 1),
                        "page_end": chunk.get("page_end", 1),
                        "breadcrumb": chunk.get("breadcrumb", ""),
                        "heading": chunk.get("heading", ""),
                        "score": score,
                        "excerpt": excerpt
                    })
            except Exception:
                continue

    if not scored_chunks:
        print("[]")
        sys.exit(0)

    # Sort descending by score
    scored_chunks.sort(key=lambda x: x["score"], reverse=True)
    top_matches = scored_chunks[:limit]

    print(json.dumps(top_matches, indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Scoped Reference Retrieval Engine")
    parser.add_argument("--query", required=True, help="Search concept or phrase")
    parser.add_argument("--collection", default=None, help="Target collection name filter")
    parser.add_argument("--tags", default=None, help="Comma-separated tag filter")
    parser.add_argument("--limit", type=int, default=3, help="Max matches to return (default: 3)")
    parser.add_argument("--workspace-dir", default=None, help="Workspace root directory")

    args = parser.parse_args()

    if args.workspace_dir:
        workspace_root = Path(args.workspace_dir).resolve()
    else:
        workspace_root = Path(__file__).resolve().parent.parent

    locate_text(
        workspace_root=workspace_root,
        query=args.query,
        collection=args.collection,
        tags=args.tags,
        limit=args.limit
    )


if __name__ == "__main__":
    main()
