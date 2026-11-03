"""Checks the golden dataset against the knowledge base, the chunker and its design.

Run from the repository root:

    python -m evals.validate_golden                 # check everything, exit 1 on any error
    python -m evals.validate_golden --fix-offsets   # recompute span offsets from their quotes
    python -m evals.validate_golden --freeze        # record the holdout hash (once, on purpose)
    python -m evals.validate_golden --agreement evals/annotation/blind_20.csv

What it checks, in the order of evals/golden_design.md:
- schema, ids, enums, and the category, subtype, split and smoke counts
- every gold span: its quote equals text[start:end] and sits inside one chunk

Offsets count characters in the file with line endings normalised to "\\n". Git stores the
knowledge base with LF and a Windows checkout turns it into CRLF, so offsets into the raw file
would differ between a Windows machine and CI. The chunker is run on the same normalised text.
- behaviour consistency: should_refuse, gold spans per behaviour, multi-chunk cases
- documents: each is a gold source for 1 to 6 cases
- word overlap: at least a third of the cases with gold spans are low-overlap
- near misses: plain BM25 puts a distractor chunk in its top 5
- seen cases are in dev; no gold quote is shared across dev and holdout
- reviews: authored_by is known; reviewed_by is empty (a draft) or names the reviewer
- clarify cases have no must_include: a correct clarifying question names no value
- the holdout hash and dataset_version match the frozen ones
It also prints BM25 hit rate@5 by overlap stratum, one of the pre-registered checks.
"""

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np

from app.chunker import ChunkConfig, chunk, parse_document
from evals.chunk_report import KB_DIR
from evals.scoring import contains_fact

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evals" / "golden_dataset.jsonl"
HOLDOUT_HASH = ROOT / "evals" / "golden_holdout.sha256"
GOLD_SPANS = ROOT / "evals" / "gold_spans.jsonl"

DESIGN = {  # (category, subtype): count, from evals/golden_design.md
    ("single fact", "fact"): 14,
    ("single fact", "stated absence"): 6,
    ("numeric", "table lookup"): 10,
    ("numeric", "rule application"): 5,
    ("multi-document", "multi-chunk"): 7,
    ("multi-document", "rule application"): 3,
    ("out of scope", "far"): 4,
    ("out of scope", "near miss"): 6,
    ("false premise", "false premise"): 8,
    ("ambiguous", "ambiguous"): 7,
    ("unsupported language", "other language"): 5,
}
SPLIT = {  # category: (dev, holdout)
    "single fact": (14, 6),
    "numeric": (10, 5),
    "multi-document": (7, 3),
    "out of scope": (7, 3),
    "false premise": (6, 2),
    "ambiguous": (5, 2),
    "unsupported language": (3, 2),
}
BEHAVIOUR = {  # category: expected_behaviour
    "single fact": "answer",
    "numeric": "answer",
    "multi-document": "answer",
    "out of scope": "abstain",
    "false premise": "correct premise",
    "ambiguous": "clarify",
    "unsupported language": "language refusal",
}
REFUSING = {"abstain", "language refusal"}
PERSONAS = {
    "epc",
    "developer",
    "roof_owner",
    "facility",
    "procurement",
    "om",
    "small",
    "foreign",
}
REQUIRED_FIELDS = [
    "id",
    "split",
    "category",
    "subtype",
    "persona",
    "question",
    "expected_behaviour",
    "expected_answer",
    "must_include",
    "source_ids",
    "should_refuse",
    "gold",
    "distractors",
    "required_claims",
    "forbidden_claims",
    "tags",
    "smoke",
    "seen",
    "authored_by",
    "reviewed_by",
    "dataset_version",
]
AUTHORS = {"human", "claude-draft"}
BEHAVIOURS = sorted(set(BEHAVIOUR.values()))
ACCEPT, REWRITE = 0.90, 0.80  # blind agreement: accept at or above, rewrite below
SMOKE_PER_CATEGORY = 3
DOC_MIN, DOC_MAX = 1, 6
LOW_OVERLAP = 1 / 3  # a case is low-overlap at or below this share
LOW_OVERLAP_SHARE = 1 / 3  # of the cases with gold spans
TOP_K = 5

STOPWORD_TEXT = """
a about after all also am an and any are as at be because been before being both but by can
could did do does doing don't each for from get gets got had has have having how i if in into is
it its it's just me more most my no not now of off on once only or other our ours out over own
same should so some such than that the their them then there these they this those through to
too under until up us very was we we'd we're we've were what when where which while who whom why
will with would you your yours yourself right isn't correct actually really quite
"""
STOPWORDS = set(STOPWORD_TEXT.split())
TOKEN = re.compile(r"[a-z0-9µ°²]+(?:[-.][a-z0-9µ°²]+)*")


def tokens(text):
    """Content words, lowercased, with a light plural and verb-ending strip."""
    words = []
    for word in TOKEN.findall(text.lower()):
        if word in STOPWORDS:
            continue
        if len(word) > 4 and word.endswith("ing"):
            word = word[:-3]
        elif len(word) > 4 and word.endswith("ed"):
            word = word[:-2]
        elif len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        words.append(word)
    return words


class BM25:
    """Plain Okapi BM25 over the chunks' index_text. Independent of the system under test."""

    def __init__(self, documents, k1=1.5, b=0.75):
        self.docs = [Counter(tokens(text)) for text in documents]
        self.lengths = np.array([sum(doc.values()) for doc in self.docs], dtype=float)
        self.avg = self.lengths.mean()
        frequency = Counter(word for doc in self.docs for word in doc)
        count = len(self.docs)
        self.idf = {
            w: math.log(1 + (count - n + 0.5) / (n + 0.5)) for w, n in frequency.items()
        }
        self.k1, self.b = k1, b

    def rank(self, query):
        """Return chunk positions from best to worst."""
        scores = np.zeros(len(self.docs))
        norm = self.k1 * (1 - self.b + self.b * self.lengths / self.avg)
        for word in set(tokens(query)):
            if word not in self.idf:
                continue
            tf = np.array([doc.get(word, 0) for doc in self.docs], dtype=float)
            scores += self.idf[word] * tf * (self.k1 + 1) / (tf + norm)
        return list(np.argsort(-scores, kind="stable"))


def load_corpus(kb_dir=KB_DIR, cfg=None):
    """Return {doc_id: (text, chunks)} with line endings normalised to "\\n" before chunking."""
    cfg = cfg or ChunkConfig.from_env()
    corpus = {}
    for path in sorted(kb_dir.glob("*.md")):
        text = (
            path.read_bytes().decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        )
        doc_id = parse_document(text, path.name)[0].doc_id
        corpus[doc_id] = (text, chunk(text, doc_id, cfg))
    return corpus


def load_dataset(path=DATASET):
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def write_dataset(cases, path=DATASET):
    text = "".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases)
    path.write_text(text, encoding="utf-8", newline="\n")


def holdout_hash(cases):
    holdout = [case for case in cases if case["split"] == "holdout"]
    canonical = "\n".join(
        json.dumps(case, ensure_ascii=False, sort_keys=True) for case in holdout
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def spans(case):
    return [span for group in case["gold"] for span in group]


def fix_offsets(cases, corpus):
    """Set start and end of every span from its quote. The quote must occur once in its document."""
    for case in cases:
        for span in spans(case):
            text = corpus[span["doc_id"]][0]
            count = text.count(span["quote"])
            if count != 1:
                raise SystemExit(
                    f"{case['id']}: quote occurs {count} times in {span['doc_id']}: {span['quote']!r}"
                )
            span["start"] = text.index(span["quote"])
            span["end"] = span["start"] + len(span["quote"])


def chunk_of(corpus, doc_id, start, end):
    """The chunk that fully contains [start, end), or None."""
    for item in corpus[doc_id][1]:
        if item.start <= start and end <= item.end:
            return item
    return None


def chunk_containing_quote(corpus, doc_id, quote):
    text = corpus[doc_id][0]
    position = text.find(quote)
    if position == -1:
        return None
    return chunk_of(corpus, doc_id, position, position + len(quote))


def check(cases, corpus):
    """Return (errors, stats). Each error is a readable string."""
    errors = []
    stats = {"overlap": {}, "bm25_rank": {}, "near_miss": {}}
    chunk_list = [
        item for _, (_, doc_chunks) in sorted(corpus.items()) for item in doc_chunks
    ]
    position = {item.id: i for i, item in enumerate(chunk_list)}
    bm25 = BM25([item.index_text for item in chunk_list])

    ids = [case.get("id") for case in cases]
    for duplicate in [i for i, n in Counter(ids).items() if n > 1]:
        errors.append(f"duplicate id {duplicate}")

    for case in cases:
        cid = case.get("id", "?")
        missing = [field for field in REQUIRED_FIELDS if field not in case]
        if missing:
            errors.append(f"{cid}: missing fields {missing}")
            continue
        if (case["category"], case["subtype"]) not in DESIGN:
            errors.append(
                f"{cid}: unknown category/subtype {case['category']}/{case['subtype']}"
            )
            continue
        if case["split"] not in ("dev", "holdout"):
            errors.append(f"{cid}: split must be dev or holdout")
        if case["persona"] not in PERSONAS:
            errors.append(f"{cid}: unknown persona {case['persona']}")
        if case["expected_behaviour"] != BEHAVIOUR[case["category"]]:
            errors.append(
                f"{cid}: behaviour {case['expected_behaviour']} does not fit {case['category']}"
            )
        if case["should_refuse"] != (case["expected_behaviour"] in REFUSING):
            errors.append(f"{cid}: should_refuse disagrees with expected_behaviour")
        if case["seen"] and case["split"] != "dev":
            errors.append(f"{cid}: seen cases must be in dev")
        if case["smoke"] and case["split"] != "dev":
            errors.append(f"{cid}: smoke cases must be in dev")
        if not case["question"].strip() or not case["expected_answer"].strip():
            errors.append(f"{cid}: empty question or expected answer")

        if case["authored_by"] not in AUTHORS:
            errors.append(f"{cid}: authored_by must be one of {sorted(AUTHORS)}")
        reviewer = case["reviewed_by"]
        if reviewer is not None and (not isinstance(reviewer, str) or not reviewer.strip()):
            errors.append(f"{cid}: reviewed_by must be null (a draft) or name the reviewer")

        # must_include facts must appear in the expected answer, as whole values.
        for fact in case["must_include"]:
            if not contains_fact(case["expected_answer"], fact):
                errors.append(f"{cid}: must_include {fact!r} is not in expected_answer")
        if case["expected_behaviour"] == "clarify" and case["must_include"]:
            errors.append(f"{cid}: a clarify case must have no must_include")

        # Gold spans by behaviour.
        has_gold = bool(case["gold"])
        if case["expected_behaviour"] in REFUSING and has_gold:
            errors.append(f"{cid}: a refusing case must have no gold spans")
        if case["expected_behaviour"] not in REFUSING and not has_gold:
            errors.append(f"{cid}: a case that answers needs gold spans")
        if any(not group for group in case["gold"]):
            errors.append(f"{cid}: empty gold group")

        gold_chunks = []
        for group in case["gold"]:
            group_chunks = set()
            for span in group:
                if span["doc_id"] not in corpus:
                    errors.append(f"{cid}: unknown document {span['doc_id']}")
                    continue
                text = corpus[span["doc_id"]][0]
                if text[span["start"] : span["end"]] != span["quote"]:
                    errors.append(
                        f"{cid}: span text does not match {span['doc_id']}"
                        f"[{span['start']}:{span['end']}] (run --fix-offsets?)"
                    )
                    continue
                item = chunk_of(corpus, span["doc_id"], span["start"], span["end"])
                if item is None:
                    errors.append(
                        f"{cid}: span crosses a chunk boundary in {span['doc_id']}: {span['quote']!r}"
                    )
                    continue
                group_chunks.add(item.id)
            gold_chunks.append(group_chunks)

        expected_sources = sorted({f"kb/{span['doc_id']}.md" for span in spans(case)})
        if sorted(case["source_ids"]) != expected_sources:
            errors.append(
                f"{cid}: source_ids {case['source_ids']} should be {expected_sources}"
            )

        if case["category"] == "multi-document":
            if len(case["gold"]) < 2:
                errors.append(f"{cid}: multi-document needs at least 2 gold groups")
            elif gold_chunks and set.intersection(*gold_chunks):
                errors.append(
                    f"{cid}: one chunk satisfies every group, so it is not multi-chunk"
                )

        for distractor in case["distractors"]:
            if (
                distractor["doc_id"] not in corpus
                or chunk_containing_quote(
                    corpus, distractor["doc_id"], distractor["quote"]
                )
                is None
            ):
                errors.append(
                    f"{cid}: distractor not found inside one chunk: {distractor['quote']!r}"
                )

        if has_gold and all(gold_chunks):
            union = set().union(*gold_chunks)
            gold_tokens = set()
            for item in chunk_list:
                if item.id in union:
                    gold_tokens.update(tokens(item.index_text))
            question_tokens = set(tokens(case["question"]))
            share = len(question_tokens & gold_tokens) / max(len(question_tokens), 1)
            stats["overlap"][cid] = share
            ranking = bm25.rank(case["question"])
            first_group = gold_chunks[0]
            stats["bm25_rank"][cid] = 1 + min(
                ranking.index(position[i]) for i in first_group
            )

        if case["subtype"] == "near miss":
            ranking = bm25.rank(case["question"])[:TOP_K]
            top = {chunk_list[i].id for i in ranking}
            wanted = {
                chunk_containing_quote(corpus, d["doc_id"], d["quote"])
                for d in case["distractors"]
            }
            hit = any(item is not None and item.id in top for item in wanted)
            stats["near_miss"][cid] = hit
            if not case["distractors"]:
                errors.append(f"{cid}: a near miss needs at least one distractor")
            elif not hit:
                errors.append(
                    f"{cid}: BM25 top {TOP_K} has none of its distractors, so it is not a near miss"
                )

    versions = {case.get("dataset_version") for case in cases}
    if len(versions) != 1:
        errors.append(f"cases disagree on dataset_version: {sorted(map(str, versions))}")
    errors += check_counts(cases, corpus)
    errors += check_split_leaks(cases)
    if stats["overlap"]:
        low = sum(share <= LOW_OVERLAP for share in stats["overlap"].values())
        if low < LOW_OVERLAP_SHARE * len(stats["overlap"]):
            errors.append(
                f"only {low} of {len(stats['overlap'])} cases with gold spans are low-overlap"
            )
    return errors, stats


def check_counts(cases, corpus):
    errors = []
    found = Counter((case.get("category"), case.get("subtype")) for case in cases)
    for key, want in DESIGN.items():
        if found[key] != want:
            errors.append(
                f"{key[0]} / {key[1]}: {found[key]} cases, design says {want}"
            )
    in_holdout = {
        (case.get("category"), case.get("subtype"))
        for case in cases
        if case.get("split") == "holdout"
    }
    for key in DESIGN:
        if key not in in_holdout:
            errors.append(f"{key[0]} / {key[1]}: no case in the holdout")
    for category, (dev, holdout) in SPLIT.items():
        got = Counter(
            case["split"] for case in cases if case.get("category") == category
        )
        if (got["dev"], got["holdout"]) != (dev, holdout):
            errors.append(
                f"{category}: split {got['dev']}/{got['holdout']}, design says {dev}/{holdout}"
            )
        smoke = [
            case
            for case in cases
            if case.get("category") == category and case.get("smoke")
        ]
        if len(smoke) != SMOKE_PER_CATEGORY:
            errors.append(
                f"{category}: {len(smoke)} smoke cases, design says {SMOKE_PER_CATEGORY}"
            )
        subtypes = {s for (c, s) in DESIGN if c == category}
        if len(subtypes) > 1 and {case["subtype"] for case in smoke} != subtypes:
            errors.append(f"{category}: smoke set does not cover every subtype")
    per_doc = Counter(
        doc for case in cases for doc in {span["doc_id"] for span in spans(case)}
    )
    for doc_id in corpus:
        if not DOC_MIN <= per_doc[doc_id] <= DOC_MAX:
            errors.append(
                f"document {doc_id} is a gold source for {per_doc[doc_id]} cases, "
                f"design says {DOC_MIN} to {DOC_MAX}"
            )
    return errors


def check_split_leaks(cases):
    """Cases that rely on the same gold quote must be in the same split, or tuning on dev leaks."""
    errors = []
    splits = {}
    for case in cases:
        for span in spans(case):
            splits.setdefault((span["doc_id"], span["quote"]), set()).add(
                (case["split"], case["id"])
            )
    for (doc_id, quote), members in splits.items():
        if len({split for split, _ in members}) > 1:
            ids = ", ".join(sorted(cid for _, cid in members))
            errors.append(
                f"gold quote shared across splits by {ids}: {doc_id}: {quote!r}"
            )
    return errors


def read_annotation(cases, path):
    """Rows of a blind annotation file. Every row must name a known case and one behaviour."""
    by_id = {case["id"]: case for case in cases}
    # utf-8-sig: Excel saves UTF-8 with a byte order mark, which would hide the "id" column.
    with open(path, encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    problems = []
    for row in rows:
        label = (row.get("behaviour") or "").strip()
        if row.get("id") not in by_id:
            problems.append(f"unknown case id {row.get('id')!r}")
        elif not label:
            problems.append(f"{row['id']}: behaviour is empty")
        elif label not in BEHAVIOURS:
            problems.append(f"{row['id']}: behaviour {label!r} is not one of {BEHAVIOURS}")
    if not rows:
        problems.append("the file has no rows")
    return rows, problems


def agreement(cases, path):
    """Return (share agreed, problems). A share is only given for a complete, valid file."""
    rows, problems = read_annotation(cases, path)
    if problems:
        return None, problems
    expected = {case["id"]: case["expected_behaviour"] for case in cases}
    disputed = [row for row in rows if row["behaviour"].strip() != expected[row["id"]]]
    share = (len(rows) - len(disputed)) / len(rows)
    print(f"behaviour agreement: {len(rows) - len(disputed)}/{len(rows)} = {share:.0%}")
    for row in disputed:
        print(f"  {row['id']}: annotator {row['behaviour'].strip()!r}, dataset {expected[row['id']]!r}")
    if share >= ACCEPT:
        print(f"accepted (at least {ACCEPT:.0%})")
    elif share >= REWRITE:
        print(f"not accepted: review the disputed cases (accept at {ACCEPT:.0%})")
    else:
        print(f"not accepted: rewrite the disputed cases first (below {REWRITE:.0%})")
    return share, []


def read_frozen(path=HOLDOUT_HASH):
    """Return (digest, dataset_version) recorded by --freeze, or None."""
    if not path.exists():
        return None
    parts = path.read_text(encoding="utf-8").split()
    version = parts[1].removeprefix("dataset_version=") if len(parts) > 1 else None
    return parts[0], version


def check_frozen(cases, path=HOLDOUT_HASH):
    """The holdout may change only with a new dataset_version and a deliberate freeze."""
    frozen = read_frozen(path)
    if frozen is None:
        return ["holdout hash not frozen yet (run --freeze once the set is accepted)"]
    digest, version = frozen
    current = cases[0]["dataset_version"] if cases else None
    if digest != holdout_hash(cases):
        if version == current:
            return ["holdout changed since it was frozen: bump dataset_version and re-freeze on purpose"]
        return [f"holdout changed for dataset_version {current}: run --freeze on purpose"]
    if version != current:
        return [f"dataset_version is {current} but the holdout was frozen at {version}: run --freeze"]
    return []


def report(cases, stats):
    print(
        f"cases: {len(cases)}  dev: {sum(c['split'] == 'dev' for c in cases)}  "
        f"holdout: {sum(c['split'] == 'holdout' for c in cases)}  "
        f"smoke: {sum(c['smoke'] for c in cases)}  seen: {sum(c['seen'] for c in cases)}"
    )
    reviewed = sum(c["reviewed_by"] is not None for c in cases)
    print(f"reviewed: {reviewed} of {len(cases)} (unreviewed cases are drafts and are not scored)")
    overlap = stats["overlap"]
    low = {cid for cid, share in overlap.items() if share <= LOW_OVERLAP}
    print(
        f"low-overlap: {len(low)} of {len(overlap)} cases with gold spans "
        f"(need >= {math.ceil(LOW_OVERLAP_SHARE * len(overlap))})"
    )
    for name, group in (("low-overlap", low), ("high-overlap", set(overlap) - low)):
        ranks = [stats["bm25_rank"][cid] for cid in group]
        if ranks:
            hits = sum(rank <= TOP_K for rank in ranks)
            print(
                f"  BM25 hit rate@{TOP_K}, {name}: {hits}/{len(ranks)} = {hits / len(ranks):.0%}"
            )
    if stats["near_miss"]:
        kept = sum(stats["near_miss"].values())
        print(
            f"near misses with a distractor in BM25 top {TOP_K}: {kept}/{len(stats['near_miss'])}"
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--fix-offsets", action="store_true", help="recompute span offsets from quotes"
    )
    parser.add_argument("--freeze", action="store_true", help="record the holdout hash")
    parser.add_argument(
        "--write-gold-spans",
        action="store_true",
        help="write evals/gold_spans.jsonl for python -m evals.chunk_report",
    )
    parser.add_argument(
        "--agreement", metavar="CSV", help="blind annotation file to compare"
    )
    parser.add_argument(
        "--per-case", action="store_true", help="print overlap and BM25 rank per case"
    )
    args = parser.parse_args(argv)

    corpus = load_corpus(KB_DIR, ChunkConfig.from_env())
    cases = load_dataset()
    if args.fix_offsets:
        fix_offsets(cases, corpus)
        write_dataset(cases)
        print("offsets recomputed from quotes")
    if args.agreement:
        share, problems = agreement(cases, args.agreement)
        for problem in problems:
            print(f"ERROR {problem}")
        return 0 if share is not None and share >= ACCEPT else 1

    errors, stats = check(cases, corpus)
    report(cases, stats)
    if args.per_case:
        for cid in sorted(stats["overlap"]):
            print(
                f"  {cid} overlap={stats['overlap'][cid]:.2f} bm25_rank={stats['bm25_rank'][cid]}"
            )

    if args.write_gold_spans:
        lines = [
            json.dumps(
                {"case": c["id"], "doc_id": s["doc_id"], "quote": s["quote"]},
                ensure_ascii=False,
            )
            for c in cases
            for s in spans(c)
        ]
        GOLD_SPANS.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {len(lines)} spans to {GOLD_SPANS.relative_to(ROOT)}")

    if args.freeze:
        digest, version = holdout_hash(cases), cases[0]["dataset_version"]
        HOLDOUT_HASH.write_text(f"{digest} dataset_version={version}\n", encoding="utf-8", newline="\n")
        print(f"holdout frozen at dataset_version {version}: {digest}")
    else:
        errors += check_frozen(cases)

    for error in errors:
        print(f"ERROR {error}")
    print("OK" if not errors else f"{len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
