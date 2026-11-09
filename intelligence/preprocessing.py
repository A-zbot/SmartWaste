"""Text preprocessing for complaint NLP.

Built on NLTK (tokenisation, stop-word removal, WordNet lemmatisation) with a
deterministic fallback so the application still runs if NLTK corpora are not
installed on the host. Every function is pure - no I/O, no randomness - so the
same complaint always produces the same feature string at training and at
inference time (preventing train/serve skew).
"""

import re
import socket
import unicodedata

import nltk

# ---------------------------------------------------------------------------
# NLTK data bootstrap (quiet, short timeout, never fatal)
# ---------------------------------------------------------------------------
_REQUIRED_RESOURCES = (
    "corpora/stopwords",
    "tokenizers/punkt",
    "tokenizers/punkt_tab",
    "corpora/wordnet",
    "corpora/omw-1.4",
)
_NLTK_PACKAGES = ("stopwords", "punkt", "punkt_tab", "wordnet", "omw-1.4")

_FALLBACK_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "so", "of", "to", "in",
    "on", "at", "by", "for", "with", "about", "as", "is", "are", "was", "were",
    "be", "been", "being", "am", "it", "its", "this", "that", "these", "those",
    "i", "me", "my", "we", "our", "you", "your", "he", "she", "they", "them",
    "their", "what", "which", "who", "whom", "how", "when", "where", "why",
    "do", "does", "did", "doing", "have", "has", "had", "having", "can",
    "could", "should", "would", "will", "shall", "may", "might", "must",
    "from", "up", "down", "out", "off", "over", "under", "again", "further",
    "once", "here", "there", "all", "any", "both", "each", "few", "more",
    "most", "other", "some", "such", "than", "too", "very", "just", "also",
    "into", "only", "own", "same", "s", "t", "don", "now",
}

# Negation carries meaning in complaints ("not cleaned", "no pickup") and is
# therefore deliberately kept even though it appears in NLTK's stop-word list.
_PRESERVED = {"no", "nor", "not", "never", "none", "cannot", "without", "against"}

_URL_RE = re.compile(r"(?:https?://|www\.)\S+")
_HTML_RE = re.compile(r"<[^>]+>")
_EMAIL_RE = re.compile(r"\S+@\S+\.\S+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]")
_WS_RE = re.compile(r"\s+")

_nltk_ready = None
_stop_words = set(_FALLBACK_STOPWORDS)
_lemmatizer = None
_word_tokenize = None


def _ensure_nltk():
    """Verify (and if possible download) the NLTK resources we rely on."""
    global _nltk_ready, _stop_words, _lemmatizer, _word_tokenize
    if _nltk_ready is not None:
        return _nltk_ready

    missing = []
    for resource in _REQUIRED_RESOURCES:
        try:
            nltk.data.find(resource)
        except LookupError:
            missing.append(resource)

    if missing:
        previous = socket.getdefaulttimeout()
        socket.setdefaulttimeout(10)
        try:
            for package in set(_NLTK_PACKAGES):
                try:
                    nltk.download(package, quiet=True)
                except Exception:
                    pass
        finally:
            socket.setdefaulttimeout(previous)

    stopwords_ok = True
    try:
        from nltk.corpus import stopwords as nltk_stopwords
        _stop_words = set(nltk_stopwords.words("english")) - _PRESERVED
    except Exception:
        _stop_words = set(_FALLBACK_STOPWORDS) - _PRESERVED
        stopwords_ok = False

    lemmatizer_ok = True
    try:
        from nltk.stem import WordNetLemmatizer
        WordNetLemmatizer().lemmatize("tests")
        _lemmatizer = WordNetLemmatizer()
    except Exception:
        _lemmatizer = None
        lemmatizer_ok = False

    tokenizer_ok = True
    try:
        from nltk.tokenize import word_tokenize
        word_tokenize("sanity check tokens")
        _word_tokenize = word_tokenize
    except Exception:
        _word_tokenize = None
        tokenizer_ok = False

    _nltk_ready = stopwords_ok and lemmatizer_ok and tokenizer_ok
    return _nltk_ready


def nltk_available():
    return _ensure_nltk()


def tokenize(text):
    _ensure_nltk()
    if _word_tokenize is not None:
        try:
            return _word_tokenize(text)
        except LookupError:
            pass
    return re.findall(r"[a-z0-9]+", text)


def clean_text(text):
    """Lower-case, strip markup/URLs, fold accents, keep letters and digits."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", str(text))
    text = text.encode("ascii", "ignore").decode("ascii", "ignore")
    text = _URL_RE.sub(" ", text)
    text = _EMAIL_RE.sub(" ", text)
    text = _HTML_RE.sub(" ", text)
    text = text.lower()
    text = _NON_ALNUM_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return text


def content_tokens(text):
    """Lemmatised, stop-word filtered content tokens."""
    _ensure_nltk()
    tokens = []
    for raw in tokenize(clean_text(text)):
        token = raw.strip(".").strip()
        if len(token) < 2 or token.isdigit():
            if token.isdigit():
                tokens.append(token)
            continue
        if token in _stop_words:
            continue
        if _lemmatizer is not None:
            token = _lemmatizer.lemmatize(token)
        tokens.append(token)
    return tokens


def preprocess(text):
    """Canonical feature string consumed by the TF-IDF vectoriser."""
    return " ".join(content_tokens(text))


def _overlaps_selected(term, selected):
    """True when *term* is already covered by a longer selected phrase."""
    tokens = term.split()
    for other in selected:
        other_tokens = other.split()
        smaller, larger = (
            (tokens, other_tokens) if len(tokens) <= len(other_tokens)
            else (other_tokens, tokens)
        )
        for i in range(len(larger) - len(smaller) + 1):
            if larger[i:i + len(smaller)] == smaller:
                return True
    return False


def extract_keywords(text, vectorizer=None, top_k=6):
    """Top weighted terms for a complaint.

    When a fitted TF-IDF vectoriser is supplied the weights come straight
    from the trained model's feature space (real feature contributions).
    Without a model we fall back to content-token frequency purely for
    display, and callers label it as such.
    """
    if not text:
        return []

    if vectorizer is not None:
        try:
            matrix = vectorizer.transform([preprocess(text)])
            row = matrix.toarray()[0]
            feature_names = vectorizer.get_feature_names_out()
            order = row.argsort()[::-1]
            results = []
            for idx in order:
                if row[idx] <= 0 or len(results) >= top_k:
                    break
                term = str(feature_names[idx])
                if _overlaps_selected(term, [r["term"] for r in results]):
                    continue
                results.append({
                    "term": term,
                    "weight": round(float(row[idx]), 4),
                    "source": "model_tfidf",
                })
            if results:
                return results
        except Exception:
            pass

    counts = {}
    for token in content_tokens(text):
        counts[token] = counts.get(token, 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top_k]
    return [
        {"term": term, "weight": float(count), "source": "frequency_fallback"}
        for term, count in ordered
    ]


def describe():
    """Diagnostics for the admin 'models' page."""
    return {
        "nltk_available": bool(_nltk_ready),
        "stopwords": len(_stop_words),
        "lemmatiser": _lemmatizer.__class__.__name__ if _lemmatizer else None,
        "tokenizer": getattr(_word_tokenize, "__name__", "regex_fallback"),
    }
