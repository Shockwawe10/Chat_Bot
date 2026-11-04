"""Keyword search (BM25) and reciprocal rank fusion for hybrid retrieval.

Dense embeddings weigh meaning and miss exact words and numbers: "kWp", "email",
a product code. BM25 scores exact word overlap. Hybrid retrieval ranks every chunk
both ways and fuses the two rankings by rank, not by score, because a cosine score
and a BM25 score are on different scales.
"""

import math
import re
from collections import Counter

# Okapi BM25 defaults (Robertson and Zaragoza, 2009) and the RRF constant from
# Cormack, Clarke and Buettcher (2009). Not tuned on the dataset.
K1 = 1.2
B = 0.75
RRF_K = 60
TOKEN = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)*")
STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "can", "do", "does", "for", "from",
    "has", "have", "how", "i", "if", "in", "is", "it", "its", "me", "my", "no", "not", "of", "on",
    "or", "our", "so", "than", "that", "the", "their", "them", "then", "there", "these", "they",
    "this", "to", "us", "was", "we", "what", "when", "where", "which", "who", "why", "will",
    "with", "you", "your"
})


def tokens(text):
    """Lower-case words and numbers ("2.4" and "1,000" stay whole), without stopwords."""
    return [word for word in TOKEN.findall(text.lower()) if word not in STOPWORDS]


class Bm25:
    def __init__(self, ids, texts):
        self.ids = list(ids)
        self.docs = [Counter(tokens(text)) for text in texts]
        self.lengths = [sum(doc.values()) for doc in self.docs]
        self.average = sum(self.lengths) / len(self.lengths) if self.lengths else 0.0
        frequency = Counter(word for doc in self.docs for word in doc)
        count = len(self.docs)
        self.idf = {word: math.log(1 + (count - n + 0.5) / (n + 0.5)) for word, n in frequency.items()}

    def scores(self, question):
        words = tokens(question)
        result = []
        for doc, length in zip(self.docs, self.lengths):
            score = 0.0
            for word in words:
                tf = doc.get(word, 0)
                if tf:
                    norm = K1 * (1 - B + B * length / self.average)
                    score += self.idf[word] * tf * (K1 + 1) / (tf + norm)
            result.append(score)
        return result

    def ranking(self, question):
        """Every chunk id, best first. Ties keep index order, so the ranking is stable."""
        scores = self.scores(question)
        order = sorted(range(len(self.ids)), key=lambda i: -scores[i])
        return [self.ids[i] for i in order]


def fuse(*rankings, k=RRF_K):
    """Reciprocal rank fusion: (chunk id, score) pairs, best first, ties in first-seen order."""
    scores = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1 / (k + rank)
    return sorted(scores.items(), key=lambda item: -item[1])
