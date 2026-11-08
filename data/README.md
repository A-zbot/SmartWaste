# SmartWaste Datasets

> **IMPORTANT: ALL DATA IN THIS FOLDER IS SYNTHETIC.**
> Both CSVs below are machine-generated / hand-paraphrased fake complaints,
> not real citizen reports. No real personal data, no real incidents and no
> scraped content is used anywhere. See the caveat at the bottom of this file
> before trusting any model metric.

## Files

| File | Rows | Purpose |
|---|---|---|
| `complaints_training_dataset.csv` | 800 | Training + validation data, generated deterministically by `scripts/generate_dataset.py` (seed 42) |
| `complaints_holdout_handwritten.csv` | 80 | Held-out evaluation set. Written from scratch with different phrasing so it is not assembled from the generator's fragment pools (still synthetic) |

Regenerate the training file at any time with:

```bash
python scripts/generate_dataset.py
```

The script is deterministic (stdlib + `csv` only, no network) and asserts: no
duplicate texts, exact per-class counts, valid label values, 8-35 words per
row, and the target text-quality rates (location / timeframe / impact /
typo-Hinglish mention rates).

## File schema

Both files share the same CSV schema (UTF-8, comma separated, header row):

| Column | Type | Values |
|---|---|---|
| `text` | string | The complaint, 1-3 sentences, citizen voice, 8-35 words |
| `category` | string | One of the 8 categories below |
| `urgency` | string | One of the 4 urgency levels below |
| `source` | string | Where the row came from: `synthetic_generator` (training file) or `handwritten_synthetic` (holdout file) |

### Category taxonomy (8 classes, exact strings)

`Open Garbage`, `Plastic Waste`, `Food Waste`, `Construction Debris`,
`E-Waste`, `Medical Waste`, `Drain & Sewer Waste`, `Street Sweeping`

### Urgency taxonomy (4 levels, exact strings)

`Low`, `Medium`, `High`, `Emergency`

### Training class counts (total 800)

| Category | Rows |
|---|---|
| Open Garbage | 160 |
| Street Sweeping | 120 |
| Plastic Waste | 100 |
| Food Waste | 100 |
| Construction Debris | 90 |
| Drain & Sewer Waste | 90 |
| E-Waste | 70 |
| Medical Waste | 70 |

Overall urgency split in the training file:
Emergency 64 (8.0%), High 204 (25.5%), Medium 311 (38.9%), Low 221 (27.6%).

### Holdout class counts (total 80)

Open Garbage 16, Plastic Waste 10, Food Waste 10, Street Sweeping 10,
Construction Debris 9, Drain & Sewer Waste 9, E-Waste 8, Medical Waste 8.

Holdout urgency split: Emergency 9, High 24, Medium 22, Low 25.

## Urgency annotation policy

Urgency is derived from the content of the complaint - it must never be
assigned at random. Use this policy to label both existing and new rows:

- **Emergency** - medical/infectious waste dumped publicly, sewage or
  overflow entering homes, drain blockage causing street flooding near homes,
  waste at hospital/school gates, dead animals.
- **High** - garbage lying for more than 2-3 days with stench near
  parks/schools/markets/residential areas, burning of waste, plastic choking
  drains, large dumping piles attracting stray animals.
- **Medium** - routine dumping in bins/alleys, food waste odor, construction
  debris partially blocking a road, recurring litter.
- **Low** - recyclable plastic collection requests, e-waste pickup requests,
  routine street sweeping/dust, minor littering, cosmetic cleanliness.

The generator encodes this policy per class (e.g. every `Emergency` row comes
from Open Garbage, Medical Waste or Drain & Sewer Waste, and its wording
describes dead bodies, infection or sewage entering homes).

## Adding real annotated data

1. Collect genuine complaints and annotate each one with `category` and
   `urgency` using the policy above.
2. Write them to a CSV with **exactly the same header/schema**:
   `text,category,urgency,source`. Put something like `real_annotated` (or the
   real source name) in the `source` column so synthetic and real rows can be
   told apart.
3. Either **append** the rows to `complaints_training_dataset.csv` or
   **replace** the file entirely - both work, as long as the schema and the
   exact label strings above are preserved.
4. Keep `complaints_holdout_handwritten.csv` (or a real holdout) untouched
   while tuning so evaluation stays honest.
5. Retrain (see below). If you replace rather than append, update the class
   counts documented in this file.

## Retraining

```bash
python scripts/train_models.py
```

This reads the labelled CSV(s) described above and (re)trains the category and
urgency models used by the app.

## Honest caveat about synthetic data

Training and evaluating on synthetic text **overestimates real-world
performance**. Generated sentences are grammatically tidy, drawn from a small
set of templates, and their labels are perfectly consistent by construction -
real citizen complaints contain spelling errors, mixed languages, vague
locations, missing context and noisy labels. Any accuracy/F1 number obtained
from these files is an upper bound on what the model will achieve on live
data. Treat it as a smoke test for the pipeline, not as a quality claim, and
re-evaluate on real annotated complaints as soon as they are available.
