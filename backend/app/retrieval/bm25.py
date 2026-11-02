"""In-memory Okapi BM25 over the retrieval units (lexical half of hybrid retrieval).

Small corpus (~1.5k chunks), so a plain inverted index in Python is fast (< 5 ms/query) and
needs no extra dependency. Tokens are Unicode word characters plus the Devanagari and Kannada
blocks; English stop words are dropped and a light suffix rule merges plurals.
"""

import math
import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

# Python's \w omits Indic combining vowel signs and viramas (Unicode Mn/Mc), which would split
# "तलाक" into fragments, so the Devanagari and Kannada blocks are included whole.
_TOKEN_RE = re.compile(r"[\w\u0900-\u097F\u0C80-\u0CFF]+")

# Function words only: legal terms ("may", "shall", "not") stay — they matter in statutes.
# fmt: off
STOP_WORDS = frozenset((
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have", "he", "her",
    "his", "i", "in", "into", "is", "it", "its", "me", "my", "of", "on", "or", "our", "she",
    "that", "the", "their", "them", "they", "this", "to", "was", "we", "were", "what", "when",
    "where", "which", "who", "whom", "why", "will", "with", "you", "your", "can", "do", "does",
    "did", "am", "been", "being", "there", "these", "those", "than", "then", "so", "if",
    "about", "get", "got",
))
# fmt: on


def _normalise(token: str) -> str:
    # Plural folding for ASCII words only ("grounds" → "ground"; "ss" endings kept).
    if token.isascii() and len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    tokens = (t.lower() for t in _TOKEN_RE.findall(text))
    return [_normalise(t) for t in tokens if t not in STOP_WORDS and t != "_"]


@dataclass(frozen=True)
class LexicalHit:
    index: int  # position in the documents passed to BM25Index
    score: float


class BM25Index:
    def __init__(self, documents: Sequence[str], k1: float = 1.5, b: float = 0.75) -> None:
        self._k1 = k1
        self._b = b
        self._doc_len: list[int] = []
        self._postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for i, doc in enumerate(documents):
            counts = Counter(tokenize(doc))
            self._doc_len.append(sum(counts.values()))
            for term, tf in counts.items():
                self._postings[term].append((i, tf))
        n = len(self._doc_len)
        self._avg_len = (sum(self._doc_len) / n) if n else 0.0
        # BM25+ style idf floor at 0 so very common terms never subtract score.
        self._idf = {
            term: max(0.0, math.log((n - len(p) + 0.5) / (len(p) + 0.5) + 1.0))
            for term, p in self._postings.items()
        }

    def __len__(self) -> int:
        return len(self._doc_len)

    def search(self, query: str, limit: int) -> list[LexicalHit]:
        scores: dict[int, float] = defaultdict(float)
        for term in set(tokenize(query)):
            idf = self._idf.get(term)
            if not idf:
                continue
            for i, tf in self._postings[term]:
                norm = self._k1 * (1 - self._b + self._b * self._doc_len[i] / self._avg_len)
                scores[i] += idf * tf * (self._k1 + 1) / (tf + norm)
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
        return [LexicalHit(index=i, score=s) for i, s in ranked]
