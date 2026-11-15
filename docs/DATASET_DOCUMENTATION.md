# SmartWaste — Dataset Documentation

> **Status: all datasets currently in the repository are SYNTHETIC.**
> No real citizen complaints, no scraped content and no real personal data are
> used anywhere. Real-world evaluation is **pending** — the collection and
> annotation workflow for it is documented in §6 and `data/ANNOTATION.md`.
> Every metric quoted anywhere in this project comes from the files described
> below and is reproduced by `python experiments/evaluation.py`.

Companion files: `data/README.md` (quick reference), `data/ANNOTATION.md`
(annotation procedure for real data), `docs/ML_EVALUATION.md` (results).

---

## 1. Dataset inventory and provenance

| File | Rows | Provenance (`source` column) | Generator / origin |
|---|---|---|---|
| `data/complaints_training_dataset.csv` | 800 | `synthetic_generator` | `scripts/generate_dataset.py` (seed 42, stdlib only, no network) |
| `data/complaints_holdout_handwritten.csv` | 80 | `handwritten_synthetic` | Written from scratch with different phrasing; **not** assembled from the generator's fragment pools; not produced by any script in the repo |
| `data/duplicate_pairs.csv` | 500 pairs (250 positive / 250 negative) | `construction` column records how each pair was built | `scripts/build_duplicate_pairs.py` (seed 42) from the two files above |

**There is no real-world dataset in the repository.** Rows with
`source=real_annotated` do not exist yet. The schema reserves that tag for
future real data (§6).

## 2. Collection methodology

### Synthetic training corpus (development data)
- Deterministic template/fragment generator (`scripts/generate_dataset.py`,
  seed 42): citizen-voice sentences 8–35 words with location, timeframe,
  impact and occasional Hinglish/typo mentions.
- The generator asserts during creation: no duplicate texts, exact per-class
  counts, valid labels only, word-count bounds, and target rates for the
  stylistic features above.
- Purpose: **development** — pipeline testing, model comparison, CI. It is not
  evidence of real-world performance.

### Handwritten holdout (independent synthetic evaluation)
- 80 rows written independently with different phrasing; zero exact-text
  overlap with the training file (verified), but only ~5.5% of its 4-grams
  occur in the training corpus, so it measures generalisation to new phrasing
  **within the same synthetic distribution**.
- Measured distribution shift (documented here for honesty): training texts
  have median 26 words (range 12–35); holdout texts median 14 (range 9–18) —
  the holdout is systematically shorter.

### Duplicate-pair corpus
- 500 labelled pairs built by construction: positives are paraphrases of the
  same incident (nearby coordinates), negatives come from three buckets —
  different category/far, same category/far, same category/near — so both the
  text gate and the geographic gate are exercised. Coordinates are constructed
  around 28.6139 N, 77.2090 E.

## 3. Schema and label definitions

Both classification CSVs share the schema (UTF-8, header):

| Column | Type | Meaning |
|---|---|---|
| `text` | string | The complaint, 1–3 sentences |
| `category` | string | One of the 8 waste categories (exact strings) |
| `urgency` | string | One of the 4 urgency levels (exact strings) |
| `source` | string | Provenance tag: `synthetic_generator`, `handwritten_synthetic`, or (future) `real_annotated` |

**Category taxonomy (8 classes, identical to `config.CATEGORIES`):**
`Open Garbage`, `Plastic Waste`, `Food Waste`, `Construction Debris`,
`E-Waste`, `Medical Waste`, `Drain & Sewer Waste`, `Street Sweeping`.

**Urgency taxonomy (4 levels, identical to `config.PRIORITIES`):**
`Low`, `Medium`, `High`, `Emergency`.

**Urgency labelling policy** (content-derived, never random — full policy in
`data/README.md` §"Urgency annotation policy"):
- *Emergency* — medical/infectious waste in public places, sewage entering
  homes, drain blockage flooding streets near homes, waste at hospital/school
  gates, dead animals.
- *High* — garbage lying 2–3 days with stench near parks/schools/markets,
  burning waste, plastic-choked drains, large piles attracting animals.
- *Medium* — routine bin/alleys dumping, food odor, debris partially blocking
  a road, recurring litter.
- *Low* — recyclable pickup requests, e-waste pickup, routine sweeping,
  minor littering.

## 4. Class distribution (measured)

**Training (800 rows):**

| Category | Rows | | Urgency | Rows |
|---|---|---|---|---|
| Open Garbage | 160 | | Medium | 311 (38.9%) |
| Street Sweeping | 120 | | Low | 221 (27.6%) |
| Plastic Waste | 100 | | High | 204 (25.5%) |
| Food Waste | 100 | | Emergency | 64 (8.0%) |
| Construction Debris | 90 | | | |
| Drain & Sewer Waste | 90 | | | |
| E-Waste | 70 | | | |
| Medical Waste | 70 | | | |

**Holdout (80 rows):** Open Garbage 16, Plastic 10, Food 10, Street Sweeping
10, Construction 9, Drain & Sewer 9, E-Waste 8, Medical 8; urgency — Low 25,
Medium 22, High 24, Emergency 9.

Urgency is mildly imbalanced (Emergency ≈ 8%), which is why macro-F1 and
per-class metrics are reported alongside accuracy (see `docs/ML_EVALUATION.md`).

## 5. Preprocessing, partitions and leakage controls

- **Single reusable pipeline:** `intelligence/preprocessing.py` (NLTK-aware
  tokenisation with a deterministic regex/stop-word fallback when NLTK data is
  absent) is used as the TF-IDF `preprocessor` at training time and travels
  inside the persisted joblib pipeline, so inference uses the *exact* same
  preprocessing and vectorizer that were fitted for the model.
- **Partitions:**
  1. *Training partition* — 800 rows, stratified 80/20 train/test split
     (`random_state=42`); the 5-fold stratified CV (folds=5, shuffle,
     random_state=42) runs **only on the training fold**, acting as the
     validation signal for model selection.
  2. *Test partition* — the 20% stratified hold-out; metrics computed once per
     candidate after selection rules are fixed.
  3. *Independent evaluation partition* — `complaints_holdout_handwritten.csv`
     (80 rows), never used for training, tuning or selection; scored for
     diagnostics only.
- **Leakage controls:** the vectorizer lives *inside* the sklearn `Pipeline`
  so it is fit per-fold on training text only; preprocessing is stateless;
  model selection uses CV F1-macro on the training partition only; the
  independent holdout never influences selection; forecasting uses a
  chronological split with past-only lag/rolling features (no random split on
  time series).
- **Known caveat (documented, deliberate):** after selection, the deployed
  artifact is refit on *all* 800 rows for maximum training data, while the
  reported test/holdout metrics come from the train-split-fitted candidate.
  The served model therefore has no metric of its own; the reported numbers
  characterise the selection procedure, not the exact deployed weights.

## 6. Real-world evaluation data — PENDING (workflow ready)

No real data is available for this project yet. To add it without breaking
honesty:

1. **Sources (planned):** open municipal open-data portals; the project's own
   exported complaints (`GET /admin/export/complaints.csv` once live);
   controlled volunteer collection of public complaints.
2. **De-identification (privacy rule):** strip names, phone numbers,
   e-mails, house numbers and any direct identifiers before a row ever enters
   a CSV. No real PII may be committed to this repository.
3. **Annotation:** two independent annotators label `category` and `urgency`
   from the policy in §3; disagreements are adjudicated by a third annotator;
   inter-annotator agreement (Cohen's κ) is recorded; classes with < 30
   examples are documented but not trained on; 10% gold rows are re-reviewed.
   Full procedure: `data/ANNOTATION.md`.
4. **Storage:** same CSV schema with `source=real_annotated`; keep the
   synthetic holdout untouched while tuning; record SHA-256 of every dataset
   in `models/training_meta.json` (already done automatically at training).
5. **Reporting:** quote real-data metrics separately from synthetic metrics —
   never merge them into one number.

**Current status: steps 1–2 pending; steps 3–5 implemented and documented.**

## 7. Known limitations

1. All existing numbers are **upper bounds**: synthetic sentences are tidy,
   template-derived and perfectly labelled; real complaints contain spelling
   errors, mixed languages, vague locations and label noise. Test accuracy
   0.96+ must never be presented as real-world accuracy.
2. The holdout is synthetic too — it measures phrasing generalisation, not
   field performance (and carries the length shift noted in §2).
3. Class imbalance: Emergency is 8% of training rows; macro-F1 is the primary
   selection metric for this reason.
4. The duplicate corpus is *constructed* — real duplicate phrasing will be
   messier; the offline pair scorer also fits TF-IDF on the pair alone while
   the live scorer fits on the candidate corpus, so offline and live cosine
   values are close but not byte-identical (the decision rule is shared).
5. No waste-volume/tonnage labels exist anywhere — the system forecasts
   *complaint counts*, never tonnage.

## 8. Privacy considerations

- No real personal data is present in any committed file (verified: all rows
  are machine-generated or hand-paraphrased; no real names/phones/addresses).
- Live complaints (when deployed) store citizen name + mobile for follow-up;
  lists/PDFs mask PII; `/track` requires ID + mobile as second factor.
- Real data, when added, must be de-identified per §6.2 before commit.
- Uploads are stored under UUID filenames; `.env` and `waste.db` are
  git-ignored and were never committed.

## 9. Reproduction commands

```bash
python scripts/generate_dataset.py          # rebuild training CSV (seed 42)
python scripts/build_duplicate_pairs.py     # rebuild pair corpus (seed 42)
python scripts/train_models.py              # retrain models + reports
python experiments/evaluation.py            # recompute every reported metric
```
