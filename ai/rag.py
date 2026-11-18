"""Retrieval-Augmented Generation for SmartWaste AI.

Lightweight and Render-friendly: no embedding service, no vector database.
Documents live as Markdown in ``ai/knowledge/``; they are chunked by heading,
vectorised once with TF-IDF (scikit-learn is already a project dependency)
and queried with cosine similarity. Hindi/Hinglish queries are expanded to
English vocabulary first (see ``ai.language.expand_query``) so one index
serves all three conversation languages.

Private administrator database facts are NEVER stored here - they are
injected separately by modules.chatbot.context and cannot be retrieved by
similarity search.
"""

import logging
import os
import re
import threading

import config

logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge")

MIN_SCORE = 0.05  # below this a "match" is really no match

_lock = threading.Lock()
_chunks = None
_vectorizer = None
_matrix = None


class _Chunk:
    __slots__ = ("id", "source", "title", "text")

    def __init__(self, chunk_id, source, title, text):
        self.id = chunk_id
        self.source = source
        self.title = title
        self.text = text

    def as_dict(self, score=None):
        payload = {"id": self.id, "source": self.source, "title": self.title}
        if score is not None:
            payload["score"] = round(float(score), 4)
        return payload


def reset():
    """Drop the cached index (used by tests)."""
    global _chunks, _vectorizer, _matrix
    with _lock:
        _chunks = None
        _vectorizer = None
        _matrix = None


def _split_section(section):
    """Split one ``##`` section into paragraph-sized chunks (~600 chars)."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", section) if p.strip()]
    chunks, current = [], ""
    for para in paragraphs:
        candidate = (current + "\n\n" + para).strip()
        if len(candidate) <= 700:
            current = candidate
        else:
            if current:
                chunks.append(current)
            while len(para) > 700:
                cut = para.rfind(" ", 0, 700)
                if cut < 300:
                    cut = 700
                chunks.append(para[:cut].strip())
                para = para[cut:].strip()
            current = para
    if current:
        chunks.append(current)
    return chunks


def _parse_document(filename, text):
    """Turn a Markdown knowledge file into heading-based chunks."""
    source = filename[:-3] if filename.endswith(".md") else filename
    # First heading (or file name) is the document title.
    title = source.replace("_", " ").replace("-", " ").strip().title()
    first_line = text.strip().splitlines()[0] if text.strip() else ""
    if first_line.startswith("# "):
        title = first_line[2:].strip()

    body = text
    if first_line.startswith("# "):
        body = text.split("\n", 1)[1] if "\n" in text else ""

    parts = re.split(r"(?m)^##\s+", body)
    doc_chunks = []
    if parts and parts[0].strip():
        # Text before the first ``##`` heading belongs to the document intro.
        intro = parts[0].strip()
        for piece in _split_section(intro):
            doc_chunks.append((title, piece))
        parts = parts[1:]
    for part in parts:
        lines = part.split("\n", 1)
        heading = lines[0].strip() or title
        rest = lines[1] if len(lines) > 1 else ""
        for piece in _split_section(rest.strip()):
            doc_chunks.append((heading, piece))
    return source, doc_chunks


def _build_index():
    global _chunks, _vectorizer, _matrix
    from sklearn.feature_extraction.text import TfidfVectorizer

    chunks = []
    if os.path.isdir(KNOWLEDGE_DIR):
        for filename in sorted(os.listdir(KNOWLEDGE_DIR)):
            if not filename.endswith(".md"):
                continue
            try:
                with open(os.path.join(KNOWLEDGE_DIR, filename),
                          encoding="utf-8") as fh:
                    text = fh.read()
                source, parsed = _parse_document(filename, text)
                for heading, piece in parsed:
                    chunks.append(_Chunk(len(chunks), source, heading, piece))
            except OSError:
                logger.exception("could not read knowledge file %s", filename)
    if not chunks:
        logger.warning("No knowledge documents found in %s", KNOWLEDGE_DIR)

    corpus = [f"{c.title}\n{c.text}" for c in chunks] or [""]
    vectorizer = TfidfVectorizer(
        stop_words="english",
        ngram_range=(1, 2),
        min_df=1,
        sublinear_tf=True,
    )
    matrix = vectorizer.fit_transform(corpus)
    _chunks = chunks
    _vectorizer = vectorizer
    _matrix = matrix


def _ensure_index():
    with _lock:
        if _chunks is None:
            _build_index()
        return _chunks, _vectorizer, _matrix


def knowledge_count():
    chunks, _, _ = _ensure_index()
    return len(chunks)


def sources():
    """Distinct knowledge source names (for UI badges)."""
    chunks, _, _ = _ensure_index()
    return sorted({c.source for c in chunks})


def retrieve(query, limit=None):
    """Return the ``limit`` most similar knowledge chunks (may be empty)."""
    from sklearn.metrics.pairwise import cosine_similarity

    limit = limit or config.AI_CHAT_RAG_RESULTS
    query = (query or "").strip()
    if not query:
        return []

    chunks, vectorizer, matrix = _ensure_index()
    if not chunks:
        return []

    from ai.language import expand_query
    expanded = expand_query(query)
    try:
        query_vector = vectorizer.transform([expanded])
        scores = cosine_similarity(query_vector, matrix).flatten()
    except ValueError:  # pragma: no cover - vectorizer rejects empty vocab
        logger.exception("RAG query vectorisation failed")
        return []

    ranked = sorted(
        ((float(score), idx) for idx, score in enumerate(scores) if score > 0),
        reverse=True,
    )
    results = []
    for score, idx in ranked[:limit]:
        if score < MIN_SCORE and results:
            break
        results.append(chunks[idx])
    return results


def format_context(chunks):
    """Render retrieved chunks as the grounded context block for Gemini."""
    if not chunks:
        return ""
    blocks = []
    for i, chunk in enumerate(chunks, 1):
        blocks.append(
            f"[Source {i}: {chunk.source} > {chunk.title}]\n{chunk.text}"
        )
    return "\n\n".join(blocks)
