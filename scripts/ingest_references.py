#!/usr/bin/env python3
"""
Scalable Academic Reference Ingestion, Auto-Tagging & Catalog Engine.
Supports enterprise-scale multi-collection references (hundreds of 100+ page books).
Includes:
- PDF bookmark/outline extraction with chapter/section hierarchy inheritance
- Discrete page range tracking (page_start, page_end)
- Scanned PDF zero-text guardrail and OCR warnings
- Partitioned storage: references/processed/<collection>/<file_slug>_chunks.json
- Dual-mode tagging (filename brackets [tag1,tag2] + references/tags.json)
- Automatic pruning (garbage collection) of deleted files
- Clean rebuild mode (--rebuild)
- Catalog listing (--list [--collection <name>] [--tag <name>])
- Clean zero-emoji JSON IPC output
"""

import os
import sys
import re
import json
import shutil
import hashlib
from pathlib import Path
import argparse
from typing import Any, Dict, List, Optional, Tuple

# Robust pypdf import check
try:
    import pypdf
except ImportError:
    pypdf = None


def ensure_pypdf():
    """Returns the pypdf module, or None (with an install hint) if it is not installed."""
    if pypdf is None:
        sys.stderr.write(
            "[STANDBY] Warning: pypdf is not installed. "
            "Run `python -m pip install -r requirements.txt`.\n"
        )
    return pypdf


def atomic_write_json(file_path: Path, data: Any) -> None:
    """Atomically writes JSON data via a temporary file and atomic replace."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = file_path.with_name(f"{file_path.name}.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp_path.replace(file_path)


def compute_sha256(file_path: Path) -> str:
    """Computes SHA-256 hash of a file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def clean_text(text: str) -> str:
    """Cleans and normalizes extracted text."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\t", "    ").replace("\u00a0", " ")
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def clean_label(text: str) -> str:
    """Strips markdown and cleans label strings."""
    s = re.sub(r'^(?:Node\s*\d+[:.]\s*|\d+[\.\)]\s*)', '', str(text).strip(), flags=re.IGNORECASE)
    s = re.sub(r'[\\#*_`\[\]]', '', s)
    return s.strip()


def parse_pdf_outline(reader: Any) -> List[Tuple[int, str]]:
    """
    Extracts bookmarks / outline from a pypdf reader.
    Returns sorted list of (page_number_1_indexed, title).
    """
    results: List[Tuple[int, str]] = []

    def _traverse(outline_list: Any):
        if not outline_list:
            return
        for item in outline_list:
            if isinstance(item, list):
                _traverse(item)
            else:
                try:
                    title = getattr(item, "title", None)
                    if not title and isinstance(item, dict):
                        title = item.get("/Title")
                    if not title:
                        title = str(item)
                    title = clean_label(str(title))
                    page_idx = reader.get_destination_page_number(item)
                    if page_idx is not None and page_idx >= 0:
                        results.append((page_idx + 1, title))
                except Exception:
                    pass

    try:
        if hasattr(reader, "outline") and reader.outline:
            _traverse(reader.outline)
    except Exception as e:
        sys.stderr.write(f"[STANDBY] Warning: Failed to parse PDF outline: {e}\n")

    results.sort(key=lambda x: x[0])
    return results


def chunk_pdf(
    file_path: Path,
    file_slug: str,
    collection: str,
    source_file_rel: str,
    document_title: str,
    all_tags: List[str]
) -> Tuple[List[Dict[str, Any]], List[str], int, bool]:
    """
    Extracts PDF text with bookmark / outline hierarchy, discrete page tracking,
    and scanned zero-text detection.
    Returns (chunks, sample_headings, total_pages, ocr_warning).
    """
    pypdf_mod = ensure_pypdf()
    if pypdf_mod is None:
        sys.stderr.write(f"[STANDBY] Warning: Skipping PDF '{file_path.name}' because pypdf is unavailable.\n")
        return [], [], 0, False

    try:
        reader = pypdf_mod.PdfReader(str(file_path))
    except Exception as e:
        sys.stderr.write(f"[STANDBY] Warning: Could not open PDF '{file_path.name}': {e}\n")
        return [], [], 0, False

    total_pages = len(reader.pages)
    if total_pages == 0:
        return [], [], 0, False

    pages_data: List[Tuple[int, str]] = []
    total_chars = 0
    for page_idx, page in enumerate(reader.pages, start=1):
        try:
            txt = page.extract_text() or ""
        except Exception as e:
            sys.stderr.write(f"[STANDBY] Warning: Could not extract page {page_idx} of {file_path.name}: {e}\n")
            txt = ""
        txt = clean_text(txt)
        total_chars += len(txt)
        pages_data.append((page_idx, txt))

    # Scanned PDF / Zero-Text Guardrail
    ocr_warning = False
    if total_pages > 5 and total_chars < 200:
        ocr_warning = True
        sys.stderr.write(f"[WARN] '{file_path.name}' contains unextractable/scanned image pages. OCR processing required.\n")

    # Extract bookmarks
    bookmarks = parse_pdf_outline(reader)

    def get_section_for_page(p: int) -> Optional[str]:
        if not bookmarks:
            return None
        active_title = None
        for b_page, b_title in bookmarks:
            if b_page <= p:
                active_title = b_title
            else:
                break
        return active_title

    sample_headings: List[str] = []
    if bookmarks:
        for _, b_title in bookmarks:
            if b_title not in sample_headings:
                sample_headings.append(b_title)
            if len(sample_headings) >= 5:
                break

    chunks: List[Dict[str, Any]] = []
    current_pages: List[int] = []
    current_texts: List[str] = []
    current_word_count = 0
    current_heading: Optional[str] = None
    chunk_idx = 1

    def flush_chunk():
        nonlocal chunk_idx, current_pages, current_texts, current_word_count, current_heading
        if not current_texts:
            return

        start_p = current_pages[0]
        end_p = current_pages[-1]
        page_str = f"Page {start_p}" if start_p == end_p else f"Pages {start_p}-{end_p}"

        if current_heading:
            heading = current_heading
            breadcrumb = f"{collection} > {document_title} > {heading} > {page_str}"
        else:
            heading = page_str
            breadcrumb = f"{collection} > {document_title} > {page_str}"

        text_body = "\n\n".join(current_texts)
        wc = len(text_body.split())

        chunk_record = {
            "id": f"{file_slug}-chunk-{chunk_idx}",
            "collection": collection,
            "source_file": source_file_rel,
            "document_title": document_title,
            "tags": all_tags,
            "page_start": start_p,
            "page_end": end_p,
            "breadcrumb": breadcrumb,
            "heading": heading,
            "text": text_body,
            "word_count": wc
        }
        chunks.append(chunk_record)
        if heading not in sample_headings and len(sample_headings) < 5:
            sample_headings.append(heading)

        chunk_idx += 1
        current_pages = []
        current_texts = []
        current_word_count = 0

    for page_num, page_text in pages_data:
        if not page_text:
            continue
        words = page_text.split()
        page_wc = len(words)
        page_heading = get_section_for_page(page_num)

        # Boundary 1: Chapter / section change from outline
        if current_heading is not None and page_heading != current_heading and current_word_count > 0:
            flush_chunk()

        current_heading = page_heading

        # Boundary 2: Single page is huge (> 800 words)
        if page_wc > 800:
            flush_chunk()
            step = 550
            i = 0
            part = 1
            while i < len(words):
                sub_words = words[i:i + 600]
                sub_text = " ".join(sub_words)
                page_str = f"Page {page_num}"
                if current_heading:
                    sub_heading = f"{current_heading} (Part {part})" if (i + 600 < len(words) or part > 1) else current_heading
                    breadcrumb = f"{collection} > {document_title} > {sub_heading} > {page_str}"
                else:
                    sub_heading = f"Page {page_num} (Part {part})" if (i + 600 < len(words) or part > 1) else f"Page {page_num}"
                    breadcrumb = f"{collection} > {document_title} > {sub_heading}"

                chunks.append({
                    "id": f"{file_slug}-chunk-{chunk_idx}",
                    "collection": collection,
                    "source_file": source_file_rel,
                    "document_title": document_title,
                    "tags": all_tags,
                    "page_start": page_num,
                    "page_end": page_num,
                    "breadcrumb": breadcrumb,
                    "heading": sub_heading,
                    "text": sub_text,
                    "word_count": len(sub_words)
                })
                if sub_heading not in sample_headings and len(sample_headings) < 5:
                    sample_headings.append(sub_heading)
                chunk_idx += 1
                part += 1
                if i + 600 >= len(words):
                    break
                i += step
            continue

        # Boundary 3: Accumulated word count threshold
        if current_word_count >= 500 and (current_word_count + page_wc > 800):
            flush_chunk()

        current_pages.append(page_num)
        current_texts.append(page_text)
        current_word_count += page_wc

        if current_word_count >= 650:
            flush_chunk()

    if current_texts:
        flush_chunk()

    return chunks, sample_headings, total_pages, ocr_warning


def chunk_markdown_or_text(
    file_path: Path,
    file_slug: str,
    collection: str,
    source_file_rel: str,
    document_title: str,
    all_tags: List[str]
) -> Tuple[List[Dict[str, Any]], List[str], int, bool]:
    """
    Chunks Markdown or Text files. Splits by markdown headings (#, ##, ###)
    or falls back to 600-word blocks with 50-word sliding overlap.
    Returns (chunks, sample_headings, total_pages=1, ocr_warning=False).
    """
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        raw_content = f.read()

    text = clean_text(raw_content)
    if not text:
        return [], [], 1, False

    chunks: List[Dict[str, Any]] = []
    sample_headings: List[str] = []

    heading_pattern = re.compile(r'^(#{1,3})\s+(.+)$', re.MULTILINE)
    matches = list(heading_pattern.finditer(text))

    if not matches:
        # Fallback: chunk into 600-word blocks with 50-word sliding overlap
        words = text.split()
        if len(words) <= 650:
            heading = "Full Document"
            breadcrumb = f"{collection} > {document_title} > {heading}"
            chunks.append({
                "id": f"{file_slug}-chunk-1",
                "collection": collection,
                "source_file": source_file_rel,
                "document_title": document_title,
                "tags": all_tags,
                "page_start": 1,
                "page_end": 1,
                "breadcrumb": breadcrumb,
                "heading": heading,
                "text": text,
                "word_count": len(words)
            })
            sample_headings.append(heading)
        else:
            step = 550
            i = 0
            chunk_idx = 1
            while i < len(words):
                chunk_words = words[i:i + 600]
                chunk_text = " ".join(chunk_words)
                heading = f"Section {chunk_idx}"
                breadcrumb = f"{collection} > {document_title} > {heading}"
                chunks.append({
                    "id": f"{file_slug}-chunk-{chunk_idx}",
                    "collection": collection,
                    "source_file": source_file_rel,
                    "document_title": document_title,
                    "tags": all_tags,
                    "page_start": 1,
                    "page_end": 1,
                    "breadcrumb": breadcrumb,
                    "heading": heading,
                    "text": chunk_text,
                    "word_count": len(chunk_words)
                })
                if heading not in sample_headings and len(sample_headings) < 5:
                    sample_headings.append(heading)
                chunk_idx += 1
                if i + 600 >= len(words):
                    break
                i += step
        return chunks, sample_headings, 1, False

    # Headings are present: split into sections
    chunk_idx = 1
    first_match_start = matches[0].start()
    preamble = text[:first_match_start].strip()
    if preamble and len(preamble.split()) >= 20:
        heading = "Overview"
        breadcrumb = f"{collection} > {document_title} > {heading}"
        chunks.append({
            "id": f"{file_slug}-chunk-{chunk_idx}",
            "collection": collection,
            "source_file": source_file_rel,
            "document_title": document_title,
            "tags": all_tags,
            "page_start": 1,
            "page_end": 1,
            "breadcrumb": breadcrumb,
            "heading": heading,
            "text": preamble,
            "word_count": len(preamble.split())
        })
        sample_headings.append(heading)
        chunk_idx += 1

    for idx, match in enumerate(matches):
        heading_title = clean_label(match.group(2).strip())
        section_start = match.start()
        section_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        section_body = text[section_start:section_end].strip()

        if not section_body:
            continue

        sec_words = section_body.split()
        if len(sec_words) > 850:
            step = 550
            i = 0
            part = 1
            while i < len(sec_words):
                chunk_words = sec_words[i:i + 600]
                chunk_text = " ".join(chunk_words)
                sub_heading = f"{heading_title} (Part {part})" if (i + 600 < len(sec_words) or part > 1) else heading_title
                breadcrumb = f"{collection} > {document_title} > {sub_heading}"
                chunks.append({
                    "id": f"{file_slug}-chunk-{chunk_idx}",
                    "collection": collection,
                    "source_file": source_file_rel,
                    "document_title": document_title,
                    "tags": all_tags,
                    "page_start": 1,
                    "page_end": 1,
                    "breadcrumb": breadcrumb,
                    "heading": sub_heading,
                    "text": chunk_text,
                    "word_count": len(chunk_words)
                })
                if sub_heading not in sample_headings and len(sample_headings) < 5:
                    sample_headings.append(sub_heading)
                chunk_idx += 1
                part += 1
                if i + 600 >= len(sec_words):
                    break
                i += step
        else:
            breadcrumb = f"{collection} > {document_title} > {heading_title}"
            chunks.append({
                "id": f"{file_slug}-chunk-{chunk_idx}",
                "collection": collection,
                "source_file": source_file_rel,
                "document_title": document_title,
                "tags": all_tags,
                "page_start": 1,
                "page_end": 1,
                "breadcrumb": breadcrumb,
                "heading": heading_title,
                "text": section_body,
                "word_count": len(sec_words)
            })
            if heading_title not in sample_headings and len(sample_headings) < 5:
                sample_headings.append(heading_title)
            chunk_idx += 1

    return chunks, sample_headings, 1, False


def extract_document_tags_and_title(
    file_path: Path,
    source_file_rel: str,
    file_slug: str,
    tags_store: Dict[str, Any]
) -> Tuple[List[str], str]:
    """
    Extracts tags from filename brackets [tag1,tag2] and merges with references/tags.json.
    Derives clean title without bracket tags.
    """
    raw_name = file_path.name
    raw_stem = file_path.stem

    # Extract tags from square brackets in filename
    bracket_match = re.search(r'\[(.*?)\]', raw_name)
    filename_tags: List[str] = []
    if bracket_match:
        tag_str = bracket_match.group(1)
        filename_tags = [t.strip().lower() for t in tag_str.split(",") if t.strip()]

    # Extract clean title by removing [tags]
    clean_stem = re.sub(r'\[.*?\]', '', raw_stem).strip()
    clean_title = re.sub(r'\s+', ' ', clean_stem.replace('_', ' ').replace('-', ' ')).strip()
    if not clean_title:
        clean_title = raw_stem

    # Merge tags from references/tags.json
    store_tags: List[str] = []
    lookup_keys = [
        raw_name,
        source_file_rel,
        source_file_rel.removeprefix("references/raw/"),
        raw_stem,
        clean_title,
        file_slug
    ]
    for k in lookup_keys:
        if k in tags_store and isinstance(tags_store[k], list):
            for t in tags_store[k]:
                store_tags.append(str(t).strip().lower())

    merged_tags: List[str] = []
    for t in filename_tags + store_tags:
        t_clean = t.strip().lower()
        if t_clean and t_clean not in merged_tags:
            merged_tags.append(t_clean)

    return merged_tags, clean_title


def ingest_references(workspace_root: Path, rebuild: bool = False) -> Dict[str, Any]:
    """
    Main ingestion engine orchestrating multi-collection discovery, bookmark extraction,
    discrete page tracking, partitioned persistence, incremental caching, pruning, and indexing.
    """
    references_dir = workspace_root / "references"
    raw_dir = references_dir / "raw"
    processed_dir = references_dir / "processed"
    manifest_path = references_dir / ".manifest.json"
    index_path = references_dir / "index.json"
    tags_path = references_dir / "tags.json"

    raw_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    # Initialize tags.json if missing
    tags_store: Dict[str, Any] = {}
    if tags_path.exists():
        try:
            with open(tags_path, "r", encoding="utf-8") as f:
                tags_store = json.load(f)
        except Exception:
            tags_store = {}
    else:
        atomic_write_json(tags_path, {})

    # Rebuild Mode: wipe processed contents and reset manifest
    if rebuild:
        if processed_dir.exists():
            for item in processed_dir.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    try:
                        item.unlink()
                    except Exception:
                        pass
        processed_dir.mkdir(parents=True, exist_ok=True)
        manifest = {}
        atomic_write_json(manifest_path, {})
    else:
        manifest = {}
        if manifest_path.exists():
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
            except Exception:
                manifest = {}

    current_index: Dict[str, Any] = {"collections": {}, "total_documents": 0, "total_chunks": 0}
    if index_path.exists() and not rebuild:
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                current_index = json.load(f)
        except Exception:
            current_index = {"collections": {}, "total_documents": 0, "total_chunks": 0}

    # Discover candidate files in references/raw/
    candidate_files: List[Path] = []
    discovered_sources: set[str] = set()

    for p in sorted(raw_dir.rglob("*")):
        if p.is_file() and p.suffix.lower() in [".pdf", ".md", ".txt"]:
            candidate_files.append(p)
            rel = p.relative_to(raw_dir)
            discovered_sources.add(f"references/raw/{rel.as_posix()}")

    pruned_files_count = 0
    tags_dirty = False

    # Automatic Pruning (Garbage Collection):
    # Check all manifest keys against discovered files
    manifest_keys = list(manifest.keys())
    for source_key in manifest_keys:
        if source_key not in discovered_sources:
            # File deleted from references/raw/
            pruned_files_count += 1
            rel_str = source_key.removeprefix("references/raw/").lstrip("/")
            parts = Path(rel_str).parts
            del_collection = parts[0] if len(parts) > 1 else "general"
            rel_to_del_coll = Path(*parts[1:]) if len(parts) > 1 else Path(parts[0])
            del_slug = re.sub(r'[^a-zA-Z0-9_\-]+', '_', str(rel_to_del_coll.with_suffix("")).lower()).strip('_')

            # 1. Delete chunk file
            del_chunk_file = processed_dir / del_collection / f"{del_slug}_chunks.json"
            if del_chunk_file.exists():
                try:
                    del_chunk_file.unlink()
                except Exception:
                    pass

            # 2. Remove collection folder if empty
            del_coll_dir = processed_dir / del_collection
            if del_coll_dir.exists() and not any(del_coll_dir.iterdir()):
                try:
                    del_coll_dir.rmdir()
                except Exception:
                    pass

            # 3. Remove from manifest
            del manifest[source_key]

            # 5. Remove keys from tags_store if present
            for k in [source_key, rel_str, Path(rel_str).name, del_slug]:
                if k in tags_store:
                    del tags_store[k]
                    tags_dirty = True

            sys.stderr.write(f"[PRUNED] {source_key}\n")

    if tags_dirty:
        atomic_write_json(tags_path, tags_store)

    new_files_count = 0
    skipped_files_count = 0
    collections_map: Dict[str, Dict[str, Any]] = {}
    untagged_documents: List[Dict[str, Any]] = []

    # Map existing index documents for lookup
    existing_docs_by_file: Dict[str, Dict[str, Any]] = {}
    for coll_name, coll_info in current_index.get("collections", {}).items():
        for d in coll_info.get("documents", []):
            if d.get("file"):
                existing_docs_by_file[d["file"]] = d

    for file_path in candidate_files:
        rel_to_raw = file_path.relative_to(raw_dir)
        source_file_rel = f"references/raw/{rel_to_raw.as_posix()}"
        parts = rel_to_raw.parts

        # Collection assignment
        collection = parts[0] if len(parts) > 1 else "general"
        rel_to_coll = Path(*parts[1:]) if len(parts) > 1 else Path(parts[0])
        file_slug = re.sub(r'[^a-zA-Z0-9_\-]+', '_', str(rel_to_coll.with_suffix("")).lower()).strip('_')

        # Partitioned processed storage path
        coll_processed_dir = processed_dir / collection
        coll_processed_dir.mkdir(parents=True, exist_ok=True)
        chunks_file_abs = coll_processed_dir / f"{file_slug}_chunks.json"

        # Tagging & clean title
        all_tags, clean_title = extract_document_tags_and_title(file_path, source_file_rel, file_slug, tags_store)

        file_hash = compute_sha256(file_path)

        # Check existing chunk file for tag sync
        existing_chunks: List[Dict[str, Any]] = []
        if chunks_file_abs.exists():
            try:
                with open(chunks_file_abs, "r", encoding="utf-8") as f:
                    existing_chunks = json.load(f)
            except Exception:
                existing_chunks = []

        existing_tags = existing_chunks[0].get("tags", []) if existing_chunks else None

        # Incremental Hashing check
        if manifest.get(source_file_rel) == file_hash and chunks_file_abs.exists():
            # Check if tags were updated via references/tags.json
            if existing_tags is not None and set(existing_tags) == set(all_tags):
                # Truly unchanged -> SKIP
                skipped_files_count += 1
                doc_record = existing_docs_by_file.get(source_file_rel)
                if not doc_record and existing_chunks:
                    doc_record = {
                        "file": source_file_rel,
                        "title": clean_title,
                        "tags": all_tags,
                        "pages": max((c.get("page_end", 1) for c in existing_chunks), default=1),
                        "chunks": len(existing_chunks),
                        "ocr_warning": False
                    }
                if doc_record:
                    collections_map.setdefault(collection, {"documents": []})["documents"].append(doc_record)
                continue
            elif existing_chunks:
                # File hash is identical, but tags changed in tags.json! Update chunks in place.
                for c in existing_chunks:
                    c["tags"] = all_tags
                atomic_write_json(chunks_file_abs, existing_chunks)
                new_files_count += 1
                doc_record = {
                    "file": source_file_rel,
                    "title": clean_title,
                    "tags": all_tags,
                    "pages": max((c.get("page_end", 1) for c in existing_chunks), default=1),
                    "chunks": len(existing_chunks),
                    "ocr_warning": existing_docs_by_file.get(source_file_rel, {}).get("ocr_warning", False)
                }
                collections_map.setdefault(collection, {"documents": []})["documents"].append(doc_record)
                manifest[source_file_rel] = file_hash
                continue

        # File needs full parsing & chunking
        new_files_count += 1
        manifest[source_file_rel] = file_hash
        suffix = file_path.suffix.lower()

        if suffix == ".pdf":
            chunks, sample_headings, pages, ocr_warning = chunk_pdf(
                file_path, file_slug, collection, source_file_rel, clean_title, all_tags
            )
        else:
            chunks, sample_headings, pages, ocr_warning = chunk_markdown_or_text(
                file_path, file_slug, collection, source_file_rel, clean_title, all_tags
            )

        # Atomic chunk persistence
        atomic_write_json(chunks_file_abs, chunks)

        doc_record = {
            "file": source_file_rel,
            "title": clean_title,
            "tags": all_tags,
            "pages": pages,
            "chunks": len(chunks),
            "ocr_warning": ocr_warning
        }
        collections_map.setdefault(collection, {"documents": []})["documents"].append(doc_record)

        # Untagged document detection
        if len(all_tags) == 0:
            untagged_documents.append({
                "file": source_file_rel,
                "sample_headings": sample_headings[:5]
            })

    # Compile global index according to schema
    formatted_collections: Dict[str, Dict[str, Any]] = {}
    total_docs = 0
    total_chunks = 0

    for coll_name, coll_data in collections_map.items():
        docs = coll_data["documents"]
        coll_chunks = sum(d["chunks"] for d in docs)
        coll_tags = sorted(list(set(t for d in docs for t in d.get("tags", []))))
        formatted_collections[coll_name] = {
            "document_count": len(docs),
            "total_chunks": coll_chunks,
            "available_tags": coll_tags,
            "documents": docs
        }
        total_docs += len(docs)
        total_chunks += coll_chunks

    final_index = {
        "collections": formatted_collections,
        "total_documents": total_docs,
        "total_chunks": total_chunks
    }

    atomic_write_json(index_path, final_index)
    atomic_write_json(manifest_path, manifest)

    return {
        "status": "[REFERENCES]",
        "new_files": new_files_count,
        "skipped_files": skipped_files_count,
        "pruned_files": pruned_files_count,
        "collections": sorted(list(formatted_collections.keys())),
        "total_chunks_indexed": total_chunks,
        "untagged_documents": untagged_documents
    }


def list_catalog(workspace_root: Path, collection_filter: Optional[str] = None, tag_filter: Optional[str] = None) -> Dict[str, Any]:
    """Catalog listing function (--list)."""
    index_path = workspace_root / "references" / "index.json"
    index_data: Dict[str, Any] = {"collections": {}, "total_documents": 0, "total_chunks": 0}

    if index_path.exists():
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                index_data = json.load(f)
        except Exception:
            index_data = {"collections": {}, "total_documents": 0, "total_chunks": 0}

    collections_dict = index_data.get("collections", {})
    matching_docs: List[Dict[str, Any]] = []

    for coll_name, coll_info in collections_dict.items():
        if collection_filter and collection_filter.strip().lower() != coll_name.lower():
            continue
        docs = coll_info.get("documents", [])
        for doc in docs:
            doc_tags = [str(t).lower() for t in doc.get("tags", [])]
            if tag_filter and tag_filter.strip().lower() not in doc_tags:
                continue
            matching_docs.append({
                "collection": coll_name,
                "file": doc.get("file"),
                "title": doc.get("title"),
                "tags": doc.get("tags", []),
                "pages": doc.get("pages", 1),
                "chunks": doc.get("chunks", 0),
                "ocr_warning": doc.get("ocr_warning", False)
            })

    return {
        "status": "[LIST]",
        "collection_filter": collection_filter,
        "tag_filter": tag_filter,
        "total_matches": len(matching_docs),
        "documents": matching_docs
    }


def main():
    parser = argparse.ArgumentParser(description="Scalable Academic Reference Ingestion & Catalog Engine")
    parser.add_argument("--workspace-dir", type=str, default=None, help="Root path of the workspace.")
    parser.add_argument("--rebuild", action="store_true", help="Recursively wipe processed cache and manifest, and re-index from scratch.")
    parser.add_argument("--list", action="store_true", help="List catalog of indexed references.")
    parser.add_argument("--collection", type=str, default=None, help="Filter listing by collection name.")
    parser.add_argument("--tag", type=str, default=None, help="Filter listing by tag.")
    args = parser.parse_args()

    if args.workspace_dir:
        workspace_root = Path(args.workspace_dir).resolve()
    else:
        workspace_root = Path(__file__).resolve().parent.parent

    if args.list:
        catalog = list_catalog(workspace_root, collection_filter=args.collection, tag_filter=args.tag)
        print(json.dumps(catalog, indent=2))
    else:
        result = ingest_references(workspace_root, rebuild=args.rebuild)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
