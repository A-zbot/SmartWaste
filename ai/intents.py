"""Trilingual intent, category and slot detection for SmartWaste AI.

Deterministic keyword/regex detection first: it works without an API key,
is testable, and keeps the structured flows (complaint registration,
tracking, admin statistics) honest. Gemini is used only to *explain* the
already-fetched facts and to answer open knowledge questions via RAG.
"""

import re

from config import CATEGORIES, PRIORITIES

# ---------------------------------------------------------------------------
# Intents
# ---------------------------------------------------------------------------
INTENTS = (
    "register_complaint",
    "track_complaint",
    "my_complaints",
    "segregation",
    "sustainability",
    "admin_stats",
    "admin_hotspots",
    "admin_pending",
    "admin_high_priority",
    "admin_recommendations",
    "admin_forecast",
    "greeting",
    "thanks",
    "general",
)

_PATTERNS = [
    ("register_complaint", [
        r"\bfile\b.*\bcomplaint\b", r"\bregister\b.*\bcomplaint\b",
        r"\braise\b.*\bcomplaint\b", r"\breport\b.*\bwaste\b",
        r"\bcomplaint\b.*\bregister\b", r"\bnew complaint\b",
        r"\bcomplaint (?:karna|karo|file|register)\b",
        r"शिकायत दर्ज", r"शिकायत करन", r"complaint kar", r"report karna",
        r"shikayat", r"garbage (?:is |)accumulat", r"kachra (?:jama|bhara|pada)",
        r"कचरा (?:जमा|भरा|पड़ा)", r"safai ki shikayat",
    ]),
    ("track_complaint", [
        r"\btrack\b", r"\bstatus\b.*\bcomplaint\b",
        r"\bcomplaint\b.*\bstatus\b", r"\bwhere is my\b",
        r"\bhas my complaint\b", r"\bstill pending\b",
        r"मेरी शिकायत", r"शिकायत की स्थिति", r"complaint ka status",
        r"status check", r"kab tak", r"resolve (?:hua|hui|ho gaya)",
    ]),
    ("my_complaints", [
        r"\bmy complaints?\b", r"\blist (?:my|the) complaints?\b",
        r"\bcomplaint history\b", r"मेरी शिकायतें", r"meri complaints",
        r"kitni complaints", r"how many complaints (?:did i|i) ",
    ]),
    ("segregation", [
        r"\bsegregat", r"\bwet and dry\b", r"\bdry waste\b", r"\bwet waste\b",
        r"where should i throw", r"how (?:do|should|to) (?:i|we) (?:throw|dispose|separate)",
        r"\bdispose of\b", r"\bwhich bin\b", r"recyclable\b",
        r"कैसे फेंक", r"निपटान कैसे", r"अलग कैसे", r"गीला सूखा",
        r"kaise faheku", r"kaise alag", r"kachra alag", r"kaun sa bin",
        r"kitne bin", r"wet dry", r"separate kaise",
    ]),
    ("sustainability", [
        r"\brecycl", r"\bcompost", r"\bplastic pollution\b",
        r"\b(?:e-?waste|electronic waste)\b.*\b(?:problem|pollution|harm|impact)\b",
        r"\bsustainab", r"\bzero waste\b", r"\breduce reuse\b",
        r"\bcarbon footprint\b", r"\bcommunity cleanliness\b",
        r"पुनर्चक्रण", r"कम्पोस्ट", r"प्रदूषण", r"पर्यावरण",
        r"paryavaran", r"pradushan", r"composting kya", r"recycling kya",
    ]),
    ("admin_high_priority", [
        r"\bhigh[- ]priority\b", r"\burgent complaints?\b",
        r"\bemergency complaints?\b", r"immediate attention",
        r"तुरंत ध्यान", r"उच्च प्राथमिकता", r"urgent complaints kaun si",
    ]),
    ("admin_pending", [
        r"\bpending complaints?\b", r"\bunresolved complaints?\b",
        r"\bopen complaints?\b", r"show pending", r"list pending",
        r"लंबित शिकायतें", r"pending complaints dikhao",
    ]),
    ("admin_hotspots", [
        r"\bhotspot", r"\bcluster", r"most complaints (?:in|from) (?:which|what)",
        r"which area", r"worst area", r"top area",
        r"किस क्षेत्र", r"sabse zyada", r"kaun sa area", r"area wise",
        r"geographical", r"repeated complaints",
    ]),
    ("admin_recommendations", [
        r"\brecommend", r"\badvice\b", r"\bsuggest", r"\bwhat should we do\b",
        r"next steps", r"क्या करना चाहिए", r"kya karna chahiye",
        r"prioritis", r"prioritize",
    ]),
    ("admin_forecast", [
        r"\bforecast", r"\bpredict(?:ion)?s?\b", r"next week",
        r"coming days", r"अनुमान", r"bhavishya", r"demand (?:will|is)",
    ]),
    ("admin_stats", [
        r"\bhow many complaints\b", r"\btotal complaints\b",
        r"\bstatistics\b", r"\bstats\b", r"\bsummary of complaints\b",
        r"\bresolution time\b", r"\baverage resolution\b",
        r"\bmost common (?:complaint|category)\b",
        r"\bcomplaint (?:count|numbers|breakdown)\b",
        r"कितनी शिकायतें", r"कुल शिकायत", r"kitni complaints",
        r"total complaints kitni", r"common category",
    ]),
    ("greeting", [
        r"^\s*(hi|hello|hey|namaste|namaskar|yo|hii+|helo)\b",
        r"^\s*good (?:morning|afternoon|evening)\b",
        r"आपका स्वागत", r"kaise ho", r"kaise hain aap",
    ]),
    ("thanks", [
        r"\bthanks?\b", r"\bthank you\b", r"\bdhanyavaad\b", r"धन्यवाद",
        r"shukriya", r"शुक्रिया", r"bohot achha",
    ]),
]

_COMPILED = {
    intent: [re.compile(p, re.IGNORECASE) for p in patterns]
    for intent, patterns in _PATTERNS
}

# Order matters: structured/admin intents win over generic knowledge intents.
_INTENT_PRIORITY = [
    "register_complaint", "track_complaint", "my_complaints",
    "admin_high_priority", "admin_pending", "admin_hotspots",
    "admin_recommendations", "admin_forecast", "admin_stats",
    "segregation", "sustainability", "greeting", "thanks",
]


def detect_intent(text, role="citizen"):
    """Classify a message into one of ``INTENTS`` for the given role."""
    text = (text or "").strip()
    if not text:
        return "general"
    # Citizens never receive admin intents - the role gate runs before the
    # model ever sees data, and this second gate keeps prompts clean too.
    allowed = _INTENT_PRIORITY if role == "admin" else [
        i for i in _INTENT_PRIORITY if not i.startswith("admin_")
    ] + ["greeting", "thanks"]
    for intent in allowed:
        for pattern in _COMPILED.get(intent, ()):
            if pattern.search(text):
                return intent
    return "general"


# ---------------------------------------------------------------------------
# Complaint category (platform taxonomy + aliases)
# ---------------------------------------------------------------------------
_CATEGORY_KEYWORDS = {
    "Open Garbage": [
        "open garbage", "garbage", "trash", "litter", "overflowing bin",
        "dump", "kachra", "kachra jama", "kooda", "kuda", "kauda",
        "कचरा", "कूड़ा", "गंदगी", "कचरे", "डस्टबिन", "dustbin",
        "safai", "सफाई", "smell", "badboo", "बदबू", "bins full",
        "waste pile", "mixed waste",
    ],
    "Plastic Waste": [
        "plastic", "bottle", "polythene", "bag", "packaging", "wrapper",
        "thermocol", "styrofoam", "में कचरा", "प्लास्टिक", "प्लास्टिक की",
        "botal", "shampoo", "packet", "chips packet", "straw",
    ],
    "Food Waste": [
        "food waste", "vegetable", "fruits", "leftover", "kitchen waste",
        "organic waste", "rotting food", "food rotting", "सब्ज़ी", "सब्जी",
        "खाना", "खाद", "khaana", "sabzi", "kitchen", "peels", "compost",
        "दूध", "doodh", "egg", "अंडा",
    ],
    "Construction Debris": [
        "construction", "debris", "rubble", "concrete", "bricks", "renovation",
        "मलबा", "निर्माण", "malba", " cement", "tiles", "demolition",
        "construction waste",
    ],
    "E-Waste": [
        "e-waste", "ewaste", "electronic", "motherboard", "mobile phone",
        "laptop", "computer", "tv", "fridge", "charger", "circuit",
        "ई-वेस्ट", "ईवेस्ट", "इलेक्ट्रॉनिक", "मोबाइल", "कंप्यूटर",
        "battery", "batteries", "बैटरी", "cell", "inverter",
    ],
    "Medical Waste": [
        "medical", "hospital", "clinic", "syringe", "bandage", "medicine",
        "pharma", "covid", "मेडिकल", "अस्पताल", "surgical", "needle",
        "used mask", "tablet strip",
    ],
    "Drain & Sewer Waste": [
        "drain", "sewer", "sewage", "clog", "gutter", "नाली", "नाला",
        "गटर", "nali", "naala", "blocked drain", "waterlogging", "जलभराव",
        "manhole", "stagnant water",
    ],
    "Street Sweeping": [
        "street", "road sweeping", "sidewalk", "footpath", "park",
        "सड़क", "साफ़-सफ़ाई", "sweeping", "dust on road", "road dust",
        "median", "public place",
    ],
}

_CATEGORY_LOOKUP = []
for _cat, _words in _CATEGORY_KEYWORDS.items():
    for _w in _words:
        _CATEGORY_LOOKUP.append((_w, _cat))
_CATEGORY_LOOKUP.sort(key=lambda pair: len(pair[0]), reverse=True)


def detect_category(text):
    """Map free text to a platform waste category (or None)."""
    text = (text or "").lower()
    if not text:
        return None
    for word, category in _CATEGORY_LOOKUP:
        if word in text:
            return category
    return None


# ---------------------------------------------------------------------------
# Priority / confirmation / small talk slots
# ---------------------------------------------------------------------------
_PRIORITY_WORDS = [
    (r"\bemergency\b|\burgent\b|\bimmediately\b|\basap\b|तुरंत|तात्कालिक|फ़ौरन|foran|turant", "Emergency"),
    (r"\bhigh\b|\bserious\b|\bbadly\b|\bvery bad\b|ज़्यादा|zyada|bahut bura|गंभीर", "High"),
    (r"\blow\b|\bminor\b|\bnot urgent\b|कम|kam|halke", "Low"),
    (r"\bmedium\b|\bnormal\b|\bmoderate\b|मध्यम|madhyam", "Medium"),
]


def detect_priority(text):
    text = (text or "").lower()
    for pattern, priority in _PRIORITY_WORDS:
        if re.search(pattern, text):
            return priority
    return None


_YES_RE = re.compile(
    r"^(?:yes|yep|yup|yeah|sure|confirm|confirmed|ok|okay|proceed|go ahead|"
    r"do it|please do|haan|ha|hann|ji haan|bilkul|zaroor|जी हाँ|हाँ|हां|करें|करो|पक्का)\b",
    re.IGNORECASE,
)
_NO_RE = re.compile(
    r"^(?:no|nope|nah|cancel|stop|abort|don'?t|do not|nahi|nahin|nhi|mat karo|"
    r"नहीं|रद्द|रोको|ना)\b",
    re.IGNORECASE,
)


def is_confirmation(text):
    """True/False for explicit yes/no; None when ambiguous."""
    text = (text or "").strip()
    if not text:
        return None
    if _YES_RE.match(text):
        return True
    if _NO_RE.match(text):
        return False
    return None


def detect_mobile(text):
    match = re.search(r"(?<!\d)(\d{10})(?!\d)", text or "")
    if match:
        return match.group(1)
    match = re.search(r"(?<!\d)(\d{3}[\s-]?\d{3}[\s-]?\d{4})(?!\d)", text or "")
    if match:
        digits = re.sub(r"\D", "", match.group(1))
        if len(digits) == 10:
            return digits
    return None


def detect_tracking_ref(text):
    match = re.search(r"\bSW[-\s]?0*(\d{1,6})\b", text or "", re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.search(r"(?:^|\s)#?0*(\d{1,6})(?:\s|$)", text or "")
    if match and len(match.group(1)) >= 3:
        return int(match.group(1))
    return None


def detect_location(text):
    """Pull a place-like fragment out of free text (best effort)."""
    text = (text or "").strip()
    if not text:
        return None
    patterns = [
        r"(?:near|opposite|behind|next to|beside|in front of|at|by)\s+(.{4,80})",
        r"(?:के पास|के सामने|पीछे|में|नज़दीक)\s+(.{3,60})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = match.group(1).strip(" .,!?")
            value = re.split(r"\s+(?:and|but|since|because|कि|और|लेकिन)\s+",
                             value, maxsplit=1, flags=re.IGNORECASE)[0]
            if 3 <= len(value) <= 80:
                return value[:80]
    return None


def categories_for_prompt():
    return ", ".join(CATEGORIES)


def priorities_for_prompt():
    return ", ".join(PRIORITIES)
