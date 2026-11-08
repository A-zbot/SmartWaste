#!/usr/bin/env python3
"""Deterministic generator for the SmartWaste complaint training dataset.

Run from the repository root:

    python scripts/generate_dataset.py

Writes data/complaints_training_dataset.csv (UTF-8, 800 labelled rows).

Everything here is SYNTHETIC. Sentences are assembled from hand-written
fragment pools with a fixed seed so the output is byte-for-byte stable.
No network access, standard library only.

See data/README.md for the schema, label taxonomy and annotation policy.
"""

import csv
import os
import random
import re
from collections import Counter

random.seed(42)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "data")
OUT_PATH = os.path.join(OUT_DIR, "complaints_training_dataset.csv")

HEADER = ["text", "category", "urgency", "source"]
SOURCE = "synthetic_generator"

CATEGORIES = (
    "Open Garbage",
    "Plastic Waste",
    "Food Waste",
    "Construction Debris",
    "E-Waste",
    "Medical Waste",
    "Drain & Sewer Waste",
    "Street Sweeping",
)
URGENCIES = ("Low", "Medium", "High", "Emergency")

TARGET_CATEGORY_COUNTS = {
    "Open Garbage": 160,
    "Street Sweeping": 120,
    "Plastic Waste": 100,
    "Food Waste": 100,
    "Construction Debris": 90,
    "Drain & Sewer Waste": 90,
    "E-Waste": 70,
    "Medical Waste": 70,
}

# Exact urgency split per category (drives both class totals and the
# overall urgency distribution: Emergency 8%, High 25.5%,
# Medium 38.9%, Low 27.6%).
URGENCY_COUNTS = {
    "Open Garbage": {"Low": 30, "Medium": 58, "High": 56, "Emergency": 16},
    "Street Sweeping": {"Low": 50, "Medium": 50, "High": 20, "Emergency": 0},
    "Plastic Waste": {"Low": 32, "Medium": 40, "High": 28, "Emergency": 0},
    "Food Waste": {"Low": 24, "Medium": 52, "High": 24, "Emergency": 0},
    "Construction Debris": {"Low": 25, "Medium": 43, "High": 22, "Emergency": 0},
    "Drain & Sewer Waste": {"Low": 12, "Medium": 24, "High": 28, "Emergency": 26},
    "E-Waste": {"Low": 34, "Medium": 28, "High": 8, "Emergency": 0},
    "Medical Waste": {"Low": 14, "Medium": 16, "High": 18, "Emergency": 22},
}

# Composition probabilities (tuned so the finished file lands near the
# quality targets: ~70% location, ~50% timeframe, ~60% impact,
# ~12% typo/Hinglish). Template mix: T1 70%, T2 15%, T3 15%.
# T3 always carries a location, so T1/T2 use 0.65 -> overall ~70%.
P_LOC_T12 = 0.65
P_TIME = 0.455
P_IMPACT = 0.60
P_INFORMAL = 0.132  # drawn higher than the 12% target: informal rows that
# push the text past 35 words are rejected and re-drawn.
P_CLOSER = 0.35
MIN_WORDS = 8
MAX_WORDS = 35

OPENERS = [
    "I am writing to report that ",
    "I want to inform you that ",
    "I am concerned to report that ",
    "Please take action, as ",
    "Kindly look into this, since ",
    "I wish to bring to your notice that ",
    "It is bothering us that ",
    "I request you to see that ",
    "This is to report that ",
    "I hope you will act, as ",
    "I keep noticing that ",
    "I am sorry to say that ",
]

CLOSERS = [
    "Please look into this matter.",
    "Kindly attend to it at the earliest.",
    "A quick response would help.",
    "Please do the needful.",
    "Kindly send someone to check.",
    "We hope for a prompt action.",
    "Please take care of it soon.",
    "Thank you for looking into it.",
]

LOCATIONS = [
    "near the city park",
    "in Sector 14 market",
    "behind the bus stand",
    "on MG Road",
    "next to the school gate",
    "outside our residential colony",
    "at the market crossing",
    "beside the community bin",
    "along the main road near the temple",
    "in the lane behind our house",
    "at the colony gate",
    "near the government school",
    "on the footpath by the park",
    "close to the railway crossing",
    "behind the vegetable market",
    "near the bus stand",
    "at the entrance of the residential park",
    "opposite the chemist shop",
    "along our residential street",
    "near the anganwadi centre",
    "beside the temple road",
    "in the bylane near the milk booth",
    "near the primary health centre",
    "at the corner of our block",
    "behind the government hospital",
    "near the municipal office",
    "at the shopping complex gate",
    "on the footpath near the library",
    "beside the park railing",
    "inside the residential complex gate",
    "near the water tank area",
    "in front of our flats",
    "at the T-junction near the park",
    "behind the dairy booth",
    "near the sports ground",
    "along the footpath near the school",
    "at the parking stand",
    "near the bus depot",
    "at the pedestrian crossing by the market",
    "behind the community hall",
    "next to the juice corner",
    "on the service lane near the school",
    "near the town hall",
    "at the auto stand",
    "beside the library crossroad",
]

# (text, is_duration) - duration expressions must not stack on top of a
# duration that already appears inside the core phrase.
DURATION_TIMEFRAMES = [
    ("for the last three days", True),
    ("since last week", True),
    ("since Sunday", True),
    ("for the past week", True),
    ("since yesterday evening", True),
    ("since Monday", True),
    ("for over ten days", True),
    ("since the beginning of this month", True),
    ("since it rained", True),
    ("for the last four days", True),
    ("since last Sunday", True),
    ("for more than a week", True),
    ("since Tuesday", True),
    ("for the last two days", True),
    ("since the month began", True),
]

RECURRING_TIMEFRAMES = [
    ("every morning", False),
    ("every evening", False),
    ("every weekend", False),
    ("every day after sunset", False),
]

NEUTRAL_TIMEFRAMES = [
    ("day and night", False),
]


def pick_timeframe(rng, urgency):
    """Low = routine/recurring only, High/Emergency = mostly durations."""
    if urgency == "Low":
        return rng.choice(RECURRING_TIMEFRAMES)
    if urgency == "Medium":
        pool = DURATION_TIMEFRAMES + RECURRING_TIMEFRAMES + NEUTRAL_TIMEFRAMES
        return rng.choice(pool)
    if rng.random() < 0.75:
        return rng.choice(DURATION_TIMEFRAMES + NEUTRAL_TIMEFRAMES)
    return rng.choice(RECURRING_TIMEFRAMES)

IMPACTS = {
    "Emergency": [
        " and it is a serious health hazard for everyone",
        " and people here are scared of catching an infection",
        " and the children are at risk of falling seriously ill",
        " and it needs immediate action before it spreads",
        " and contaminated water is reaching our homes",
        " and residents are afraid to let the kids play outside",
        " and this can turn into a health emergency in the colony",
        " and nobody is willing to touch the waste",
    ],
    "High": [
        " and the smell is unbearable",
        " and stray animals are tearing the bags apart",
        " and the children playing nearby are coughing",
        " and it is blocking the footpath",
        " and the stench reaches inside our house",
        " and the disease risk is growing every day",
        " and residents are having breathing problems",
        " and a swarm of flies hovers over it",
        " and people pass by holding their nose",
    ],
    "Medium": [
        " and it looks very unhygienic",
        " and flies keep coming to the spot",
        " and it causes inconvenience to passers-by",
        " and the lane looks dirty all day",
        " and it needs regular clearing",
        " and the smell bothers us in the evenings",
        " and people drop litter here because of it",
        " and it is unpleasant for the neighbours",
    ],
    "Low": [
        " but it is not too serious yet",
        " and it is only a minor nuisance",
        " and it can wait for the routine round",
        " and the area just looks untidy",
        " but a quick clean-up would be enough",
        " and it is mostly a cosmetic issue",
        " and no one is affected by it yet",
    ],
}

CORES = {
    "Open Garbage": {
        "Emergency": [
            "a dead goat is lying in the garbage heap by the road",
            "infected dressings and bandages have been dumped with the daily garbage",
            "the carcass of a dog is rotting inside the garbage pile",
            "used medical waste has been left with the garbage at the colony gate",
            "a dead crow is decomposing in the open garbage",
            "torn garbage bags with blood-stained cotton are lying open",
            "the body of a stray animal is buried under the garbage",
            "hospital waste bags were dumped with our household garbage",
            "dead poultry has been thrown into the garbage and it is stinking",
            "biomedical waste including gloves is lying with the garbage in the open",
        ],
        "High": [
            "a huge pile of garbage has been lying uncollected for days",
            "household garbage is overflowing from the bin and the smell is unbearable",
            "someone has been burning garbage every night and smoke enters our flats",
            "mountains of trash are accumulating in the lane and stray animals scatter it",
            "the garbage has not been lifted for four days and it stinks",
            "rotting waste is spread across the footpath and it smells terrible",
            "garbage bags have been dumped on the road",
            "a large dumping pile of trash is attracting dogs and flies",
            "the garbage container is overflowing and waste is all over the road",
            "people have dumped a mountain of household waste at the corner",
        ],
        "Medium": [
            "people keep dumping household garbage in the lane",
            "the community bin is overflowing onto the footpath",
            "garbage is being left beside the bin instead of inside it",
            "someone has littered packets and bottles around the bin area",
            "waste from the shops is dumped on the roadside",
            "the bin is not sealed and garbage spills out",
            "household trash is scattered around the dumpster area",
            "vegetable peels and packets are thrown on the road",
            "the collection van misses our lane and garbage keeps piling up",
            "plastic and food waste are mixed and left next to the bin",
        ],
        "Low": [
            "a few chocolate wrappers and cups are lying near the bench",
            "littering has increased slightly around the bin area",
            "some trash is scattered around but nothing serious",
            "the bin area needs a quick clean-up",
            "minor garbage is lying outside the bin",
            "a couple of garbage bags were left next to the bin",
            "empty packets are flying around",
            "the corner of the street has a small amount of litter",
        ],
    },
    "Street Sweeping": {
        "Emergency": [],
        "High": [
            "thick dust and mud have piled up on the road for ten days",
            "sweeping has been skipped for days and dust reaches inside our shop",
            "the lane is covered in silt since the rains and nobody cleans it",
            "road dust and dirt are lying untouched and the air is dusty",
            "the sweeper has not come for over a week and dust is everywhere",
            "street dirt is left uncollected and the children are coughing",
        ],
        "Medium": [
            "the sweeper does not come regularly to our lane and dust accumulates",
            "dirt and dry leaves are gathering at the corner",
            "road dust is not cleared on schedule",
            "the street is swept only occasionally and litter remains behind",
            "silt from the road is left at the corner",
            "the cleaning staff skip the side lanes and dust builds up",
            "sweeping happens late in the day and dirt stays on the footpath",
            "leaves and dust are collected at one spot and not lifted",
        ],
        "Low": [
            "our lane is due for the routine sweeping round",
            "the street needs its regular dusting and sweeping",
            "the routine sweeping round was missed again",
            "a light layer of dust on the road needs a normal sweep",
            "the sweeper has not come for the usual round",
            "the footpath is due for its scheduled brushing",
            "the regular street cleaning has not happened in our block",
            "the road looks dusty and needs the normal sweeping round",
        ],
    },
    "Plastic Waste": {
        "Emergency": [],
        "High": [
            "plastic bottles and bags are choking the drain and water is backing up",
            "a mountain of plastic waste has been dumped and dogs scatter it",
            "plastic is blocking the naala and dirty water is overflowing",
            "polythene waste is being blown into the drain every day",
            "the drain is jammed with plastic and a foul smell is coming",
            "plastic bags have been lying for days and are attracting stray animals",
            "a heap of plastic is blocking the storm water drain",
            "old plastic and thermocol are clogging the gutter and water stagnates",
        ],
        "Medium": [
            "plastic bottles and wrappers are dumped beside the bin",
            "residents are throwing plastic packets in the lane",
            "shopkeepers leave plastic waste on the footpath",
            "plastic containers are accumulating at the corner of the road",
            "mixed plastic is left near the community bin and blows around",
            "plastic packing material is thrown on the footpath repeatedly",
            "the bin has no segregation so plastic ends up on the ground",
            "plastic cups and plates from the stalls are left behind",
        ],
        "Low": [
            "recyclable plastic from our lane is ready for collection",
            "we have sorted dry plastic bottles for recycling",
            "recyclable plastic is kept separately for pickup",
            "the plastic from our doorstep is ready for recycling pickup",
            "plastic bottles are kept in a bag for the kabadiwala",
            "clean recyclable plastic from our sector is ready for a pickup",
            "dry plastic is stacked near the gate for the scrap dealer",
            "the kabadiwala collection for plastic bottles is pending in our block",
        ],
    },
    "Food Waste": {
        "Emergency": [],
        "High": [
            "rotting food waste has been lying for three days and the stench is unbearable",
            "leftover food is stinking near the school gate and children feel nausea",
            "food waste mixed with garbage has not been cleared for four days",
            "stale food scraps are creating a bad smell for the whole lane",
            "decaying fruit and vegetable waste is lying open and the smell is strong",
            "the garbage with food waste is rotting and flies are everywhere",
        ],
        "Medium": [
            "food waste from the mess is left in the bin and it smells",
            "kitchen and vegetable waste is dumped beside the bin",
            "leftover food is thrown outside the bin",
            "the garbage with food waste needs regular collection",
            "food peels and packets are lying outside",
            "stale rotis and vegetables are left in the open bin",
            "the bin smells because food waste is not covered",
            "canteen waste is emptied into the bin and spills out",
        ],
        "Low": [
            "some food wrappers are lying and need a light clean-up",
            "small food waste should be cleared in the routine round",
            "a few fruit peels are on the footpath",
            "the food waste bin needs its scheduled cleaning",
            "a bit of leftover food is outside the bin and can be swept",
        ],
    },
    "Construction Debris": {
        "Emergency": [],
        "High": [
            "a mound of construction debris is blocking the footpath and children walk on the road",
            "rubble and bricks have been dumped at the lane entrance for over a week",
            "broken concrete and sand are spread outside and it is hard to walk",
            "construction waste is lying uncollected and dust flies into the houses",
            "heavy stones from the site are blocking the way for vehicles",
            "the debris pile has grown and the footpath is unusable",
        ],
        "Medium": [
            "construction debris is partially blocking the road",
            "bricks and mortar waste are dumped on the roadside by the builder",
            "sand and rubble are lying on the footpath from the site",
            "broken tiles and cement bags are left at the corner",
            "the contractor has stacked construction waste beside the road",
            "gravel and plaster waste are spread outside the work site",
            "pieces of brick and wood are lying where the work is going on",
        ],
        "Low": [
            "a small amount of construction sand is lying outside our gate",
            "some leftover bricks are kept near the lane for house work",
            "minor plaster waste is on the footpath",
            "a small amount of construction debris is waiting for a routine pickup",
            "a little rubble from the painting work needs a quick sweep",
        ],
    },
    "Drain & Sewer Waste": {
        "Emergency": [
            "sewage water is entering our ground floor home through the drain",
            "the drain outside our gate has overflowed into the houses",
            "sewer water has flooded the street and dirty water is inside homes",
            "the naala is overflowing into the ground floor flats",
            "blocked drain water has entered the shop and the house next to it",
            "sewage overflow is flooding the homes of our lane",
            "dirty sewer water has reached the kitchen floors of several houses",
            "the manhole outside is overflowing and sewage is coming into our courtyard",
        ],
        "High": [
            "the drain is completely blocked and stinking water is on the road",
            "the choked drain is overflowing and the footpath is unusable",
            "the naala has been blocked for days and foul smell is everywhere",
            "drain water is stagnating and mosquitoes are breeding",
            "the sewer line is overflowing onto the main road",
            "the drain cover is jammed and black water is collecting outside",
            "silt and plastic have blocked the drain and it is overflowing",
        ],
        "Medium": [
            "the drain needs cleaning because the smell comes and goes",
            "silt and waste are blocking the small naala",
            "the drain cover is clogged with leaves and waste",
            "dirty water collects in the drain channel regularly",
            "the gutter is not flowing properly and sludge builds up",
            "the drain near the lane smells when it rains",
        ],
        "Low": [
            "our street is due for the routine drain desilting",
            "the drain needs its regular cleaning",
            "a small blockage in the naala should be cleared in the routine round",
            "routine drain maintenance is due in our colony",
        ],
    },
    "E-Waste": {
        "Emergency": [],
        "High": [
            "people are burning copper wires from old electronics and toxic smoke is coming",
            "broken TVs and wires have been dumped and children play around them",
            "old batteries and chargers are lying open and kids touch them",
            "someone is burning e-waste plastic at night and the smoke is harmful",
        ],
        "Medium": [
            "old electronic parts are dumped in the alley instead of being recycled",
            "the repair shop throws broken fans and wires behind",
            "scrapped phones and chargers are left near the community bin",
            "wires and circuit boards are scattered at the corner",
            "the repair shop leaves damaged appliances on the footpath",
            "old CRT monitors are dumped in the lane",
        ],
        "Low": [
            "our house has an old TV and wires waiting for pickup",
            "we have a fridge and batteries kept at home for collection",
            "the broken microwave and chargers are waiting at our gate",
            "old laptops and cables from our house need e-waste pickup",
            "the old computer and printer are kept near our door for recycling",
            "the dead UPS and batteries are waiting at our gate",
            "we have old chargers and a mixer kept for e-waste pickup",
            "a dead treadmill and cables are waiting for recycling collection",
        ],
    },
    "Medical Waste": {
        "Emergency": [
            "used syringes and bandages have been dumped openly outside the hospital gate",
            "infectious medical waste is lying with the garbage in the open",
            "a bio-hazard bag from the clinic was left at the school gate",
            "blood-stained cotton and medicine vials are dumped on the road",
            "the hospital throws waste bags near the park and they are torn",
            "sharps and dressings are lying near the bus stand and risk infection",
            "used gloves and syringes are lying in the open where children play",
            "torn medical waste bags are scattered by the residential gate",
        ],
        "High": [
            "clinic waste including bottles and cotton is piling up and it smells",
            "the dispensary has not collected medical waste for days and it lies around",
            "used gloves and masks are dumped with the garbage near the market",
            "the nursing home leaves waste packets near the fence and dogs tear them",
            "sharps containers are overflowing and waste is kept too long",
            "medicine bottles and dressings are lying unattended near homes",
        ],
        "Medium": [
            "the clinic stores medical waste too long before pickup",
            "medicine bottles and cotton are left beside the bin",
            "the health centre does not segregate waste before collection",
            "small medical waste from the dressing room is pending pickup",
        ],
        "Low": [
            "the clinic in our sector needs its routine waste pickup",
            "the dispensary needs its scheduled waste collection",
            "a few empty medicine boxes are kept for proper disposal",
            "routine disposal of clinic cotton is due in our sector",
        ],
    },
}

WORD_SWAP = [
    ("garbage", "kachra"),
    ("garbage", "kachra"),
    ("trash", "kachra"),
    ("dirt", "gandagi"),
    ("cleaning", "safai"),
    ("drain", "naala"),
]

HINGLISH_CLAUSES = [
    "Bilkul safai nahi hoti hai.",
    "Bahut gandagi ho rahi hai.",
    "Kachra uthane wala koi nahi aata.",
    "Poore din smell aa rahi hai.",
    "Naala bilkul block ho gaya hai.",
]

# Milder wording so Low-urgency rows never pick up a severe-sounding phrase.
LOW_HINGLISH_CLAUSES = [
    "Bilkul safai nahi hoti hai.",
    "Thoda saaf karwana hai bas.",
    "Kachra kam hai lekin abhi bhi pada hai.",
    "Bas ek baar sweep karwa do.",
]

SMELL_WORDS = ("smell", "stench", "stink", "odour", "odor", "reek")

# Sensory/health impacts that do not fit these categories (construction
# dust, street dust and e-waste are not a stench/animal problem).
IMPACT_EXCLUDE = {
    "Construction Debris": (
        "smell", "stench", "flies", "animal", "disease",
        "infection", "nose", "hygienic", "litter",
    ),
    "Street Sweeping": (
        "smell", "stench", "flies", "animal", "disease",
        "infection", "nose", "hygienic",
    ),
    "E-Waste": (
        "smell", "stench", "flies", "animal", "disease",
        "infection", "nose", "hygienic",
    ),
    "Medical Waste": ("cosmetic",),
}

DURATION_IN_TEXT = re.compile(
    r"\bfor\b[^.,;]*\b(?:days?|weeks?)\b|\bsince\s+\w+", re.I
)

WORD_TOKEN = re.compile(r"([A-Za-z]+)(\W*)$")


def has_smell(text):
    low = text.lower()
    return any(w in low for w in SMELL_WORDS)


def make_typo(rng, word):
    if len(word) < 4:
        return word
    kind = rng.choice(("drop", "dup", "swap"))
    i = rng.randrange(len(word))
    if kind == "drop" and len(word) > 3:
        return word[:i] + word[i + 1 :]
    if kind == "dup":
        return word[:i] + word[i] + word[i:]
    if kind == "swap" and i + 1 < len(word):
        return word[:i] + word[i + 1] + word[i] + word[i + 2 :]
    if len(word) > 3:
        return word[:i] + word[i + 1 :]
    return word


def typo_one(rng, text):
    tokens = text.split()
    candidates = [
        i
        for i, tok in enumerate(tokens)
        if len(re.sub(r"[^A-Za-z]", "", tok)) >= 4
    ]
    if not candidates:
        return text
    idx = rng.choice(candidates)
    match = WORD_TOKEN.match(tokens[idx])
    if not match:
        return text
    core, tail = match.group(1), match.group(2)
    new_core = make_typo(rng, core)
    if new_core == core:
        new_core = core[:-1] if len(core) > 3 else core + core[-1]
    tokens[idx] = new_core + tail
    return " ".join(tokens)


def apply_informal(rng, text, impact, urgency):
    """Return (new_text, changed). Mix of realistic typos and Hinglish."""
    mode = rng.choice(("word", "clause", "typo", "impact"))
    clauses = LOW_HINGLISH_CLAUSES if urgency == "Low" else HINGLISH_CLAUSES
    if mode == "impact" and impact and has_smell(impact):
        new_text = text.replace(impact, " and smell aa rahi hai", 1)
        if new_text != text:
            return new_text, True
    if mode == "word":
        swaps = WORD_SWAP[:]
        rng.shuffle(swaps)
        for src, dst in swaps:
            if re.search(r"\b%s\b" % src, text, flags=re.I):
                new_text = re.sub(
                    r"\b%s\b" % src, dst, text, count=1, flags=re.I
                )
                return new_text, True
        return text + " " + rng.choice(clauses), True
    if mode == "clause":
        return text + " " + rng.choice(clauses), True
    new_text = typo_one(rng, text)
    if new_text != text:
        return new_text, True
    return text + " " + rng.choice(clauses), True


def pick_impact(rng, category, urgency, core):
    excluded = IMPACT_EXCLUDE.get(category, ())
    core_low = core.lower()
    # Do not repeat the word "routine/round" when the core already uses it.
    avoid_routine = any(
        word in core_low
        for word in ("routine", "round", "usual", "scheduled", "regular", "normal")
    )
    candidates = [
        imp
        for imp in IMPACTS[urgency]
        if not any(word in imp.lower() for word in excluded)
        and not (has_smell(core) and has_smell(imp))
        and not (avoid_routine and "routine" in imp.lower())
    ]
    if not candidates:
        candidates = [
            imp
            for imp in IMPACTS[urgency]
            if not any(word in imp.lower() for word in excluded)
        ] or list(IMPACTS[urgency])
    return rng.choice(candidates)


def compose(rng, category, urgency, seen):
    """Build one complaint sentence set. Returns (text, flags)."""
    while True:
        roll = rng.random()
        if roll < 0.70:
            template = 1
        elif roll < 0.85:
            template = 2
        else:
            template = 3

        core = rng.choice(CORES[category][urgency])

        if template == 3:
            loc = rng.choice(LOCATIONS)
        else:
            loc = rng.choice(LOCATIONS) if rng.random() < P_LOC_T12 else ""

        if template == 2:
            time_text, is_duration = pick_timeframe(rng, urgency)
        elif rng.random() < P_TIME:
            time_text, is_duration = pick_timeframe(rng, urgency)
        else:
            time_text, is_duration = "", False
        if time_text and is_duration and DURATION_IN_TEXT.search(core):
            time_text, is_duration = "", False

        impact = ""
        if rng.random() < P_IMPACT:
            impact = pick_impact(rng, category, urgency, core)

        if template == 1:
            text = rng.choice(OPENERS) + core
            if loc:
                text += " " + loc
            if time_text:
                text += " " + time_text
            if impact:
                text += impact
            text += "."
        elif template == 2:
            if time_text:
                text = (
                    time_text[0].upper()
                    + time_text[1:]
                    + ", I noticed that "
                    + core
                )
            else:
                text = "I noticed that " + core
            if loc:
                text += " " + loc
            if impact:
                text += impact
            text += "."
        else:
            text = "I live " + loc + " and " + core
            if time_text:
                text += " " + time_text
            if impact:
                text += impact
            text += "."
            # T3 always carries a location by construction.

        informal = False
        if rng.random() < P_CLOSER:
            closer = rng.choice(CLOSERS)
            if len(text.split()) + len(closer.split()) <= MAX_WORDS:
                text = text + " " + closer

        if rng.random() < P_INFORMAL:
            text, changed = apply_informal(rng, text, impact, urgency)
            informal = changed

        if not (MIN_WORDS <= len(text.split()) <= MAX_WORDS):
            continue
        if text in seen:
            continue

        flags = {
            "loc": bool(loc),
            "time": bool(time_text),
            "impact": bool(impact),
            "informal": informal,
        }
        return text, flags


def build_rows():
    rng = random.Random(42)
    rows = []
    seen = set()
    stats = Counter()

    for category in CATEGORIES:
        for urgency in URGENCIES:
            for _ in range(URGENCY_COUNTS[category][urgency]):
                text, flags = compose(rng, category, urgency, seen)
                seen.add(text)
                rows.append(
                    {
                        "text": text,
                        "category": category,
                        "urgency": urgency,
                        "source": SOURCE,
                    }
                )
                for key, value in flags.items():
                    if value:
                        stats[key] += 1
    return rows, stats


def verify(rows, stats):
    total = len(rows)
    assert total == 800, "expected 800 rows, got %d" % total

    texts = [r["text"] for r in rows]
    assert len(set(texts)) == total, "duplicate texts found"

    cat_counts = Counter(r["category"] for r in rows)
    assert cat_counts == Counter(TARGET_CATEGORY_COUNTS), dict(cat_counts)

    pair_counts = Counter((r["category"], r["urgency"]) for r in rows)
    for category in CATEGORIES:
        for urgency in URGENCIES:
            expected = URGENCY_COUNTS[category][urgency]
            assert pair_counts[(category, urgency)] == expected, (
                category,
                urgency,
                pair_counts[(category, urgency)],
                expected,
            )

    urg_counts = Counter(r["urgency"] for r in rows)
    rates = {u: urg_counts[u] / total for u in URGENCIES}
    assert 0.07 <= rates["Emergency"] <= 0.09, rates
    assert 0.24 <= rates["High"] <= 0.28, rates
    assert 0.38 <= rates["Medium"] <= 0.42, rates
    assert 0.25 <= rates["Low"] <= 0.30, rates

    for row in rows:
        assert row["category"] in CATEGORIES, row
        assert row["urgency"] in URGENCIES, row
        assert row["source"] == SOURCE, row
        words = len(row["text"].split())
        assert MIN_WORDS <= words <= MAX_WORDS, (words, row["text"])
        assert "\n" not in row["text"] and "\r" not in row["text"], row

    loc_rate = stats["loc"] / total
    time_rate = stats["time"] / total
    impact_rate = stats["impact"] / total
    informal_rate = stats["informal"] / total
    assert 0.66 <= loc_rate <= 0.76, loc_rate
    assert 0.46 <= time_rate <= 0.54, time_rate
    assert 0.55 <= impact_rate <= 0.65, impact_rate
    assert 0.10 <= informal_rate <= 0.14, informal_rate

    joined = " ".join(texts).lower()
    for token in ("kachra", "gandagi", "naala", "smell aa rahi hai", "safai nahi hoti"):
        assert token in joined, "missing expected informal token: %s" % token

    return {
        "total": total,
        "categories": cat_counts,
        "urgency": urg_counts,
        "rates": rates,
        "text_flags": {
            "location": round(loc_rate, 4),
            "timeframe": round(time_rate, 4),
            "impact": round(impact_rate, 4),
            "typo_hinglish": round(informal_rate, 4),
        },
    }


def main():
    rows, stats = build_rows()
    summary = verify(rows, stats)

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_PATH, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADER)
        writer.writeheader()
        writer.writerows(rows)

    print("Wrote %d rows to %s" % (summary["total"], OUT_PATH))
    print("category counts:")
    for category in CATEGORIES:
        print("  %-22s %d" % (category, summary["categories"][category]))
    print("urgency counts:")
    for urgency in URGENCIES:
        print(
            "  %-10s %d (%.1f%%)"
            % (
                urgency,
                summary["urgency"][urgency],
                100.0 * summary["rates"][urgency],
            )
        )
    print("text flags:", summary["text_flags"])
    print("All assertions passed.")


if __name__ == "__main__":
    main()
