"""Build the labelled duplicate-pair evaluation set for Module C.

Writes data/duplicate_pairs.csv - a hand-specified, deterministic set of
complaint pairs with an expert duplicate / not-duplicate label.

PROVENANCE (read this before trusting any number):
    The underlying complaint texts come from the SYNTHETIC corpus in
    data/complaints_training_dataset.csv and data/complaints_holdout_handwritten.csv.
    Positive pairs are constructed by applying a documented surface variation
    to one complaint (the pair therefore describes the same incident).
    Negative pairs join two different complaints; their coordinates are
    CONSTRUCTED (same spot for positives, ~300 m apart for "near" negatives,
    >2 km apart for "far" negatives) so the geographic gate can be exercised.
    Every row records how it was built in the `construction` column.

    This measures whether the scoring rule behaves as designed on this
    corpus - it is NOT a measurement of real-world duplicate detection
    accuracy. See data/ANNOTATION.md for the workflow to replace it with
    labelled real complaints.

Usage:
    python scripts/build_duplicate_pairs.py
"""

import csv
import os
import random
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

DATA_DIR = os.path.join(REPO_ROOT, "data")
TRAIN_CSV = os.path.join(DATA_DIR, "complaints_training_dataset.csv")
HOLDOUT_CSV = os.path.join(DATA_DIR, "complaints_holdout_handwritten.csv")
OUTPUT_CSV = os.path.join(DATA_DIR, "duplicate_pairs.csv")

SEED = 42
BASE_LAT, BASE_LON = 28.6139, 77.2090

# Hand-written surface variations (positive construction only).
INFORMAL_TAILS = [
    " please send someone today, thanks.",
    " kindly look into this at the earliest.",
    " it keeps happening every week now.",
    " the residents are really annoyed by this.",
]
OPENERS = [
    "Reporting this again since it has not been fixed. ",
    "This has been going on for a while. ",
    "Requesting urgent attention for this issue. ",
]


def load_rows(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return [row for row in csv.DictReader(fh) if row.get("text", "").strip()]


def drop_clause(text):
    """Remove the first sentence or clause - same complaint, shorter wording."""
    if ". " in text:
        head, rest = text.split(". ", 1)
        if rest and len(rest.split()) >= 5:
            return rest[0].lower() + rest[1:]
    if "," in text:
        head, rest = text.split(",", 1)
        if rest and len(rest.split()) >= 5:
            return rest.strip()
    words = text.split()
    return " ".join(words[len(words) // 3:]) if len(words) > 12 else text


def inject_typos(text, rng):
    """Introduce 1-2 realistic typos (adjacent letter swap)."""
    words = text.split()
    candidates = [i for i, w in enumerate(words) if len(w) > 4 and w.isalpha()]
    for index in rng.sample(candidates, min(2, len(candidates))):
        word = words[index]
        pos = rng.randrange(1, len(word) - 1)
        words[index] = word[:pos] + word[pos + 1] + word[pos] + word[pos + 2:]
    return " ".join(words)


def make_variant(text, kind, rng):
    if kind == "drop_clause":
        return drop_clause(text)
    if kind == "typo":
        return inject_typos(text, rng)
    if kind == "informal":
        return text.rstrip() + rng.choice(INFORMAL_TAILS)
    if kind == "opener":
        return rng.choice(OPENERS) + text
    raise ValueError(kind)


def offset_coords(base_lat, base_lon, metres, bearing_deg):
    """Deterministic small offset in metres at a given bearing."""
    import math
    d_lat = (metres * math.cos(math.radians(bearing_deg))) / 111_320.0
    d_lon = (metres * math.sin(math.radians(bearing_deg))) / (
        111_320.0 * math.cos(math.radians(base_lat))
    )
    return round(base_lat + d_lat, 6), round(base_lon + d_lon, 6)


def main():
    rng = random.Random(SEED)
    train = load_rows(TRAIN_CSV)
    holdout = load_rows(HOLDOUT_CSV)
    rows_out = []
    pair_id = 0

    def add(text_a, text_b, cat_a, cat_b, coords_a, coords_b, label, construction):
        nonlocal pair_id
        pair_id += 1
        rows_out.append({
            "pair_id": f"P{pair_id:04d}",
            "text_a": text_a,
            "text_b": text_b,
            "category_a": cat_a,
            "category_b": cat_b,
            "lat_a": coords_a[0], "lon_a": coords_a[1],
            "lat_b": coords_b[0], "lon_b": coords_b[1],
            "label": label,
            "construction": construction,
            "origin": "synthetic_construction",
        })

    # --- positives: same incident, surface variation, identical coordinates
    kinds = ["drop_clause", "typo", "informal", "opener"]
    pool = train + holdout
    rng.shuffle(pool)
    for row in pool[:250]:
        kind = kinds[pair_id % len(kinds)]
        variant = make_variant(row["text"], kind, rng)
        if not variant or variant.strip() == row["text"].strip():
            variant = row["text"].rstrip() + rng.choice(INFORMAL_TAILS)
        same = (BASE_LAT, BASE_LON)
        add(row["text"], variant, row["category"], row["category"],
            same, same, 1, f"positive/{kind}")

    # --- negatives -------------------------------------------------------
    # 1. different category, far apart
    by_category = {}
    for row in pool:
        by_category.setdefault(row["category"], []).append(row)
    categories = sorted(by_category)
    for _ in range(85):
        cat_a, cat_b = rng.sample(categories, 2)
        a = rng.choice(by_category[cat_a])
        b = rng.choice(by_category[cat_b])
        add(a["text"], b["text"], cat_a, cat_b,
            (BASE_LAT, BASE_LON),
            offset_coords(BASE_LAT, BASE_LON, 5000, rng.uniform(0, 360)),
            0, "negative/different_category_far")

    # 2. same category, far apart (same problem type, different incident)
    for _ in range(85):
        cat = rng.choice(categories)
        a, b = rng.sample(by_category[cat], 2)
        add(a["text"], b["text"], cat, cat,
            (BASE_LAT, BASE_LON),
            offset_coords(BASE_LAT, BASE_LON, 5000, rng.uniform(0, 360)),
            0, "negative/same_category_far")

    # 3. same category, ~300 m apart: the geographic gate passes, so only the
    #    text signal can reject the pair (the hard negative case).
    for _ in range(80):
        cat = rng.choice(categories)
        a, b = rng.sample(by_category[cat], 2)
        add(a["text"], b["text"], cat, cat,
            (BASE_LAT, BASE_LON),
            offset_coords(BASE_LAT, BASE_LON, 300, rng.uniform(0, 360)),
            0, "negative/same_category_near")

    rng.shuffle(rows_out)
    fieldnames = ["pair_id", "text_a", "text_b", "category_a", "category_b",
                  "lat_a", "lon_a", "lat_b", "lon_b", "label", "construction",
                  "origin"]
    with open(OUTPUT_CSV, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows_out)

    positives = sum(1 for r in rows_out if r["label"] == 1)
    print(f"Wrote {len(rows_out)} pairs ({positives} duplicate / "
          f"{len(rows_out) - positives} not duplicate) -> {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
