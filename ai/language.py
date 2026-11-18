"""Language detection and cross-lingual query expansion for SmartWaste AI.

Supports three conversation languages:
    en       English
    hi       Hindi (Devanagari script)
    hinglish Hindi written in Latin script ("Mere area mein kachra nahi hua")

Detection is heuristic (script + high-signal transliterated tokens) - good
enough to choose a reply language, which is all the assistant needs it for.
The same module expands Hindi/Hinglish waste vocabulary into English terms so
the English knowledge base stays retrievable from any of the three languages.
"""

import re

SUPPORTED_LANGUAGES = ("en", "hi", "hinglish")

LANGUAGE_LABELS = {
    "en": "English",
    "hi": "Hindi",
    "hinglish": "Hinglish",
}

DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")

# Transliterated Hindi/Hinglish tokens that reliably mark Hinglish.
HINGLISH_MARKERS = {
    "kaise", "kaisa", "kaisi", "kya", "kyun", "kyu", "kab", "kahan", "kaun",
    "mera", "meri", "mere", "hamara", "humara", "aapka", "apka", "tumhara",
    "nahi", "nahin", "nhi", "hai", "hain", "ho", "hua", "hui", "hue",
    "kachra", "kachre", "kachray", "safai", "saaf", "ganda", "gandi",
    "chahiye", "chahta", "chahti", "batao", "bataye", "bata", "karo", "karna",
    "huaa", "hua hai", "huaa hai", "collect", "jama", "nikal", "daalo", "dalo",
    "paani", "pani", "ghar", "mohalle", "mohalla", "area", "shehar", "shahar",
    "kabse", "kitna", "kitni", "kaunsa", "kaunsi", "wala", "wali", "vala",
    "matlab", "phir", "fir", "abhi", "aaj", "kal", "parso", "bahut", "bohot",
    "thoda", "thodi", "sahi", "galat", "jaldi", "der", "roj", "roz",
    "chalraha", "karraha", "hoon", "hun", "raha", "rahi", "rahe", "liye", "liya",
    "bhej", "bhejo", "chek", "status", "complaint", "shikayat", "shikayat",
    "haan", "hann", "ji", "theek", "theek hai", "ok", "cancel", "band",
    # Additional high-signal Hinglish function words.
    "aur", "alag", "karein", "kyunki", "lekin", "waise", "aise", "aisa",
    "bhai", "yaar", "karni", "kardo", "karke", "rahe", "hue", "hui",
}

# Markers that are also ordinary English words. On their own they must not
# flip an English message into Hinglish ("Track my complaint", "Show area").
WEAK_MARKERS = {
    "ok", "status", "complaint", "cancel", "area", "collect", "band",
}

# High-signal single tokens (counted once found as whole words).
_MARKER_RE = re.compile(
    r"\b(" + "|".join(sorted(HINGLISH_MARKERS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

# Hindi/Hinglish waste vocabulary -> English retrieval terms.
# Keys are matched as whole words against the user's message (both scripts).
SYNONYMS = {
    # script-agnostic pairs are listed separately below
    "प्लास्टिक": "plastic",
    "प्लास्टिक की": "plastic",
    "कचरा": "garbage waste trash",
    "कचरे": "garbage waste trash",
    "बोतल": "bottle",
    "बोतलें": "bottles",
    "कागज़": "paper",
    "कागज": "paper",
    "कार्डबोर्ड": "cardboard",
    "डिब्बा": "carton box",
    "डिब्बे": "cartons boxes",
    "काँच": "glass",
    "कांच": "glass",
    "धातु": "metal",
    "लोहा": "metal iron",
    "एल्युमिनियम": "aluminium metal",
    "एल्यूमिनियम": "aluminium metal",
    "बैटरी": "battery batteries",
    "सेल": "battery cell",
    "इलेक्ट्रॉनिक": "electronic e-waste",
    "ई-वेस्ट": "e-waste electronic",
    "ईवेस्ट": "e-waste electronic",
    "मोबाइल": "mobile phone electronic",
    "कंप्यूटर": "computer electronic",
    "टीवी": "tv electronic",
    "फ्रिज": "fridge refrigerator appliance",
    "सब्ज़ी": "vegetable food",
    "सब्जी": "vegetable food",
    "खाना": "food",
    "खाद": "compost manure",
    "खाद बनाना": "composting",
    "कम्पोस्ट": "compost composting",
    "गीला": "wet biodegradable",
    "सूखा": "dry recyclable",
    "गीले": "wet biodegradable",
    "सूखे": "dry recyclable",
    "रीसाइकल": "recycle recycling",
    "पुनर्चक्रण": "recycle recycling",
    "पुनर्चक्रित": "recycled recycling",
    "चिकित्सा": "medical healthcare",
    "अस्पताल": "hospital medical",
    "निर्माण": "construction",
    "मलबा": "construction debris rubble",
    "कंक्रीट": "concrete construction",
    "शौचालय": "toilet sanitary",
    "नैपकिन": "sanitary napkin hygiene",
    "पैड": "sanitary pad hygiene",
    "डायपर": "diaper hygiene",
    "कीड़े": "insects maggots",
    "बदबू": "smell odour",
    "जल": "water",
    "पानी": "water",
    "नाली": "drain sewer",
    "नाला": "drain sewer",
    "गटर": "drain sewer gutter",
    "सड़क": "street road",
    "पार्क": "park",
    "सफाई": "cleaning cleanliness",
    "साफ": "clean",
    "गंदा": "dirty",
    "प्लांट": "plant",
    "ट्री": "tree",
    "पेड़": "tree",
    "प्रदूषण": "pollution",
    "प्लास्टिक प्रदूषण": "plastic pollution",
    "धरती": "earth environment",
    "पर्यावरण": "environment environment",
    "कूड़ा": "garbage waste",
    "कूड़े": "garbage waste",
    "फेंक": "throw dispose",
    "फेंकना": "throw dispose",
    "निपटान": "disposal dispose",
    "कैसे": "how",
    "क्यों": "why",
    "कहाँ": "where",
    "कब": "when",
    "मेरा": "my",
    "मेरी": "my",
    # transliterated (Hinglish) forms
    "kachra": "garbage waste trash",
    "kachre": "garbage waste trash",
    "kooda": "garbage waste",
    "kuda": "garbage waste",
    "safai": "cleaning cleanliness",
    "saaf": "clean",
    "ganda": "dirty",
    "botal": "bottle",
    "bottal": "bottle",
    "plastic": "plastic",
    "kagaz": "paper",
    "kagaj": "paper",
    "cardboard": "cardboard",
    "kanch": "glass",
    "dhaatu": "metal",
    "loha": "metal",
    "battery": "battery batteries",
    "batteri": "battery batteries",
    "electronic": "electronic e-waste",
    "ewaste": "e-waste electronic",
    "e-waste": "e-waste electronic",
    "sabzi": "vegetable food",
    "sabjee": "vegetable food",
    "khana": "food",
    "khaana": "food",
    "khaad": "compost manure",
    "compost": "compost composting",
    "geela": "wet biodegradable",
    "gila": "wet biodegradable",
    "sookha": "dry recyclable",
    "sukha": "dry recyclable",
    "recycle": "recycle recycling",
    "recycling": "recycle recycling",
    "surgical": "medical healthcare",
    "medical": "medical healthcare",
    "construction": "construction debris",
    "malba": "construction debris rubble",
    "debris": "construction debris rubble",
    "nali": "drain sewer",
    "naala": "drain sewer",
    "gutter": "drain sewer gutter",
    "pollution": "pollution",
    "pradushan": "pollution",
    "ped": "tree",
    "pere": "tree",
    "kide": "insects maggots",
    "badboo": "smell odour",
    "smell": "smell odour",
    "dump": "dumping garbage",
    "trash": "garbage waste trash",
    "garbage": "garbage waste trash",
    "waste": "waste",
}

_WORD_RE = re.compile(r"[a-zA-Z\u0900-\u097F']+")


def detect(text):
    """Return one of ``en`` / ``hi`` / ``hinglish`` for the given message."""
    text = (text or "").strip()
    if not text:
        return "en"
    letters = [ch for ch in text if ch.isalpha()]
    if letters:
        devanagari = sum(1 for ch in letters if DEVANAGARI_RE.match(ch))
        if devanagari / len(letters) >= 0.35:
            return "hi"
    tokens = {t.lower() for t in _WORD_RE.findall(text)}
    markers = tokens & HINGLISH_MARKERS
    # Weak markers are also ordinary English words ("complaint", "status",
    # "area") - they may support a decision but never make it alone.
    strong = markers - WEAK_MARKERS
    # One strong marker is enough when the message is short; longer messages
    # need a second marker (of either kind) so ordinary English sentences
    # don't get flipped.
    if strong and (len(tokens) <= 6 or len(markers) >= 2):
        return "hinglish"
    return "en"


def label(language):
    return LANGUAGE_LABELS.get(language, LANGUAGE_LABELS["en"])


def instruction(language):
    """System-prompt instruction telling the model which language to reply in."""
    if language == "hi":
        return ("Reply in Hindi using the Devanagari script (हिन्दी). "
                "Keep complaint IDs, tracking codes and technical terms like "
                "SW-00012 exactly as given.")
    if language == "hinglish":
        return ("Reply in Hinglish - conversational Hindi written in the Latin "
                "script (for example: 'Aapki complaint mil gayi, status ye hai'). "
                "Keep complaint IDs, tracking codes and technical terms like "
                "SW-00012 exactly as given.")
    return ("Reply in English. Keep complaint IDs, tracking codes and technical "
            "terms exactly as given.")


def expand_query(text):
    """Append English equivalents of Hindi/Hinglish waste vocabulary.

    The knowledge base is English; expanding the query keeps retrieval useful
    for Hindi and Hinglish questions without shipping a second embedding model.
    """
    text = text or ""
    additions = []
    seen = set()
    lowered = text.lower()
    for token, english in SYNONYMS.items():
        if token.lower() in lowered or token in text:
            for word in english.split():
                if word not in seen:
                    seen.add(word)
                    additions.append(word)
    if not additions:
        return text
    return text + " " + " ".join(additions)
