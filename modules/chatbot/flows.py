"""Turn handler for SmartWaste AI: intent routing, the conversational
complaint-registration machine, complaint tracking, RAG knowledge answers
and administrator data explanations.

Design contract:
    * structured flows (registration, tracking, statistics) are
      deterministic - Gemini may enrich wording or extract slots, but the
      facts come from the database and the confirmation gate, never from
      the model;
    * every admin fact is fetched by ``context`` before any model call;
    * replies are localised to the conversation language (en / hi /
      hinglish) while IDs and statuses stay byte-identical.
"""

import json
import re

import config
from ai import gemini_client, intents, prompts, rag
from ai.gemini_client import GeminiUnavailable
from ai.language import instruction as lang_instruction, label as lang_label
from modules.chatbot import context, services

# ---------------------------------------------------------------------------
# Localised strings for the deterministic flows
# ---------------------------------------------------------------------------
_TXT = {
    "greeting_citizen": {
        "en": ("Hello! I'm SmartWaste AI. I can help you segregate waste, "
               "register a complaint, track your complaints, or learn about "
               "recycling. How can I help you make your community cleaner "
               "today?"),
        "hi": ("नमस्ते! मैं SmartWaste AI हूँ। मैं कचरा अलग करने, शिकायत दर्ज "
               "करने, शिकायत की स्थिति देखने और रीसाइकलिंग की जानकारी में मदद "
               "कर सकती हूँ। आज आपके समुदाय को साफ़ रखने में मैं कैसे मदद "
               "करूँ?"),
        "hinglish": ("Hello! Main SmartWaste AI hoon. Main waste segregation, "
                     "complaint register karne, complaint track karne aur "
                     "recycling ki jaankari mein help kar sakta hoon. Aaj main "
                     "aapki locality ko saaf rakhne mein kaise help karun?"),
    },
    "greeting_admin": {
        "en": ("Hello! I'm SmartWaste AI, your operations analyst. Ask me for "
               "complaint statistics, pending or high-priority lists, hotspot "
               "insights, forecasts or recommendations - all computed from "
               "the live database."),
        "hi": ("नमस्ते! मैं SmartWaste AI हूँ, आपका संचालन विश्लेषक। मुझसे "
               "शिकायत आँकड़े, लंबित या उच्च-प्राथमिकता सूची, हॉटस्पॉट जानकारी, "
               "पूर्वानुमान या सुझाव पूछें - सब सीधे लाइव डेटाबेस से।"),
        "hinglish": ("Hello! Main SmartWaste AI hoon, aapka operations "
                     "analyst. Mujhse complaint statistics, pending ya "
                     "high-priority list, hotspot info, forecast ya "
                     "recommendations poochhein - sab live database se."),
    },
    "thanks": {
        "en": "You're welcome! Ask me anything else about waste management.",
        "hi": "आपका स्वागत है! कचरा प्रबंधन के बारे में कुछ भी पूछें।",
        "hinglish": "Welcome! Waste management ke baare mein kuch bhi poochhein.",
    },
    "ask_description": {
        "en": ("First, please describe the problem in a sentence or two "
               "(at least 15 characters) - what exactly is wrong?"),
        "hi": ("पहले कृपया समस्या एक-दो वाक्यों में बताइए (कम से कम 15 "
               "अक्षर) - ठीक क्या गलत है?"),
        "hinglish": ("Pehle problem ek-do lines mein bata dijiye (kam se kam "
                     "15 characters) - exactly kya problem hai?"),
    },
    "ask_category": {
        "en": "Which waste category does this fall under? Choose from: {options}.",
        "hi": "यह किस कचरा श्रेणी में आता है? इनमें से चुनें: {options}।",
        "hinglish": "Ye kaunsi waste category mein aata hai? Inmein se "
                    "choose karein: {options}.",
    },
    "ask_location": {
        "en": ("Where exactly is the waste? Please give a landmark, street "
               "or address."),
        "hi": ("कचरा ठीक कहाँ है? कृपया लैंडमार्क, गली या पता बताइए।"),
        "hinglish": ("Kachra exactly kahan hai? Landmark, street ya address "
                     "bata dijiye."),
    },
    "ask_priority": {
        "en": "How urgent is it? Reply with: Low, Medium, High or Emergency.",
        "hi": "यह कितना ज़रूरी है? उत्तर दें: Low, Medium, High या Emergency.",
        "hinglish": "Ye kitna urgent hai? Reply karein: Low, Medium, High "
                    "ya Emergency.",
    },
    "ask_mobile": {
        "en": ("What 10-digit mobile number should we use for updates on "
               "this complaint?"),
        "hi": ("इस शिकायत के अपडेट के लिए 10 अंकों का मोबाइल नंबर क्या "
               "है?"),
        "hinglish": ("Is complaint ke updates ke liye 10-digit mobile number "
                     "kya hai?"),
    },
    "ask_confirm": {
        "en": ("Here is your complaint summary:\n{summary}\n\nReply YES to "
               "register it, or NO to cancel."),
        "hi": ("आपकी शिकायत का सारांश:\n{summary}\n\nदर्ज करने के लिए YES "
               "लिखें, या रद्द करने के लिए NO।"),
        "hinglish": ("Aapka complaint summary:\n{summary}\n\nRegister karne "
                     "ke liye YES likhein, ya cancel karne ke liye NO."),
    },
    "bad_category": {
        "en": "I couldn't match that to a category. Please choose from: {options}.",
        "hi": "यह श्रेणी से मेल नहीं खाया। कृपया इनमें से चुनें: {options}।",
        "hinglish": "Ye category se match nahi hua. Inmein se choose "
                    "karein: {options}.",
    },
    "bad_description": {
        "en": "Please give at least 15 characters describing the problem.",
        "hi": "कृपया समस्या का वर्णन कम से कम 15 अक्षरों में दें।",
        "hinglish": "Problem ka description kam se kam 15 characters mein "
                    "de dijiye.",
    },
    "bad_location": {
        "en": "Please enter a location of at least 3 characters (a landmark works).",
        "hi": "कृपया कम से कम 3 अक्षरों का स्थान दर्ज करें (लैंडमार्क चलेगा)।",
        "hinglish": "Kam se kam 3 characters ka location daaliye (landmark "
                    "chal jayega).",
    },
    "bad_priority": {
        "en": "Please reply with one of: Low, Medium, High, Emergency.",
        "hi": "कृपया इनमें से कोई एक लिखें: Low, Medium, High, Emergency।",
        "hinglish": "Inmein se koi ek likhein: Low, Medium, High, Emergency.",
    },
    "bad_mobile": {
        "en": "That doesn't look like a 10-digit mobile number. Please re-enter it.",
        "hi": "यह 10 अंकों का मोबाइल नंबर नहीं लगता। कृपया दोबारा डालें।",
        "hinglish": "Ye 10-digit mobile number nahi lagta. Dobara daaliye.",
    },
    "cancelled": {
        "en": "No problem - I've cancelled the complaint. Nothing was "
              "registered. Send me a message whenever you'd like to start "
              "again.",
        "hi": ("कोई बात नहीं - मैंने शिकायत रद्द कर दी। कुछ भी दर्ज नहीं "
               "हुआ। जब चाहें दोबारा शुरू करने के लिए संदेश भेजें।"),
        "hinglish": ("Koi baat nahi - maine complaint cancel kar diya. Kuch "
                     "bhi register nahi hua. Jab chahein dobara start karne "
                     "ke liye message bhejein."),
    },
    "created": {
        "en": ("Your complaint has been registered successfully!\n\n"
               "Tracking ID: {tracking}\nStatus: Submitted\n\nYou can track "
               "it anytime with 'Track my complaint {tracking}' or from My "
               "Complaints."),
        "hi": ("आपकी शिकायत सफलतापूर्वक दर्ज हो गई!\n\nट्रैकिंग ID: "
               "{tracking}\nस्थिति: Submitted\n\nआप कभी भी 'Track my complaint "
               "{tracking}' या My Complaints से इसे ट्रैक कर सकते हैं।"),
        "hinglish": ("Aapki complaint successfully register ho gayi!\n\n"
                     "Tracking ID: {tracking}\nStatus: Submitted\n\nAap "
                     "kabhi bhi 'Track my complaint {tracking}' ya My "
                     "Complaints se track kar sakte hain."),
    },
    "track_ask_ref": {
        "en": ("Which complaint should I check? Send your tracking ID "
               "(for example SW-00042) or complaint number."),
        "hi": ("मैं कौन सी शिकायत देखूँ? अपनी ट्रैकिंग ID (जैसे SW-00042) "
               "या शिकायत नंबर भेजें।"),
        "hinglish": ("Main kaunsi complaint check karun? Apni tracking ID "
                     "(jaise SW-00042) ya complaint number bhejein."),
    },
    "track_not_found": {
        "en": ("I couldn't find a complaint with that ID in your account. "
               "Double-check the ID, or ask me to list your complaints."),
        "hi": ("आपके खाते में उस ID की कोई शिकायत नहीं मिली। ID फिर से "
               "जाँचें, या अपनी शिकायतें सूचीबद्ध करने को कहें।"),
        "hinglish": ("Aapke account mein us ID ki complaint nahi mili. ID "
                     "dobara check karein, ya apni complaints list karne "
                     "ko kahein."),
    },
    "my_complaints_header": {
        "en": "Here are your most recent complaints ({total} total):",
        "hi": "यहाँ आपकी हाल की शिकायतें हैं (कुल {total}):",
        "hinglish": "Ye rahi aapki recent complaints (kul {total}):",
    },
    "my_complaints_empty": {
        "en": ("You haven't registered any complaints yet. Send "
               "'Register a complaint' and I'll walk you through it."),
        "hi": ("आपने अभी तक कोई शिकायत दर्ज नहीं की है। 'Register a complaint' "
               "भेजें, मैं आपको पूरी प्रक्रिया बताऊँगी।"),
        "hinglish": ("Abhi tak aapne kuch complaints register nahi ki hain. "
                     "'Register a complaint' bhejein, main pura process "
                     "bata dunga."),
    },
    "no_intent_match": {
        "en": ("I can help with waste segregation, registering complaints, "
               "tracking your complaints, and recycling/composting questions. "
               "Try one of those, or open the suggested prompts."),
        "hi": ("मैं कचरा अलग करने, शिकायत दर्ज करने, शिकायत ट्रैक करने और "
               "रीसाइकलिंग/कम्पोस्टिंग के सवालों में मदद कर सकती हूँ। "
               "इनमें से कोई आज़माएँ, या दिए गए सुझाव चुनें।"),
        "hinglish": ("Main waste segregation, complaint register, complaint "
                     "track aur recycling/composting questions mein help kar "
                     "sakta hoon. Inmein se kuch try karein, ya diye gaye "
                     "suggestions choose karein."),
    },
    "registration_intro": {
        "en": "Let's register your complaint. I'll ask you a few quick questions.",
        "hi": "आपकी शिकायत दर्ज करते हैं। मैं आपसे कुछ आसान सवाल पूछूँगी।",
        "hinglish": "Chaliye complaint register karte hain. Main aapse kuch "
                    "quick questions poochunga.",
    },
}

_ERROR_TEXT = {
    "no_key": {
        "en": ("The AI assistant is enabled but the server has no "
               "GEMINI_API_KEY configured, so I can't generate answers right "
               "now. Complaint registration and tracking still work. Please "
               "ask the administrator to set the key."),
        "hi": ("AI सहायक चालू है लेकिन सर्वर पर GEMINI_API_KEY सेट नहीं है, "
               "इसलिए अभी उत्तर नहीं बन सकते। शिकायत दर्ज करना और ट्रैक "
               "करना काम करता रहेगा। कृपया व्यवस्थापक से कुंजी सेट करवाएँ।"),
        "hinglish": ("AI assistant on hai lekin server par GEMINI_API_KEY "
                     "set nahi hai, isliye abhi answers generate nahi ho "
                     "sakte. Complaint register aur track kaam karta rahega. "
                     "Administrator se key set karwa lein."),
    },
    "invalid_key": {
        "en": ("The AI service credentials were rejected by Google Gemini. "
               "The administrator needs to update GEMINI_API_KEY. Complaint "
               "registration and tracking still work."),
        "hi": ("Google Gemini ने AI सेवा की कुंजी अस्वीकार कर दी। "
               "व्यवस्थापक को GEMINI_API_KEY अपडेट करना होगा। शिकायत दर्ज "
               "करना और ट्रैक करना काम करता रहेगा।"),
        "hinglish": ("Google Gemini ne AI service key reject kar di. "
                     "Administrator ko GEMINI_API_KEY update karna hoga. "
                     "Complaint register aur track kaam karta rahega."),
    },
    "quota": {
        "en": ("The AI assistant has reached its Gemini API quota for now. "
               "Please try again later - complaint registration and tracking "
               "still work."),
        "hi": ("AI सहायक का Gemini API कोटा अभी समाप्त हो गया है। कृपया "
               "बाद में पुनः प्रयास करें - शिकायत दर्ज करना और ट्रैक करना "
               "काम करता रहेगा।"),
        "hinglish": ("AI assistant ka Gemini API quota abhi khatam ho gaya "
                     "hai. Baad mein try karein - complaint register aur "
                     "track kaam karta rahega."),
    },
    "timeout": {
        "en": ("The AI assistant timed out while contacting Gemini. Please "
               "try again in a moment."),
        "hi": ("Gemini से संपर्क करते समय AI सहायक का समय समाप्त हो गया। "
               "कृपया थोड़ी देर में पुनः प्रयास करें।"),
        "hinglish": ("Gemini se contact karte waqt AI assistant timeout ho "
                     "gaya. Thodi der mein try karein."),
    },
    "model_unavailable": {
        "en": ("The configured Gemini model is not available on this API "
               "account. The administrator should set a valid GEMINI_MODEL."),
        "hi": ("इस API खाते पर कॉन्फ़िगर किया गया Gemini मॉडल उपलब्ध नहीं "
               "है। व्यवस्थापक को सही GEMINI_MODEL सेट करना चाहिए।"),
        "hinglish": ("Is API account par configured Gemini model available "
                     "nahi hai. Administrator ko sahi GEMINI_MODEL set "
                     "karna chahiye."),
    },
    "api_error": {
        "en": ("The AI assistant couldn't reach the AI service right now. "
               "Please try again. Complaint registration and tracking still "
               "work."),
        "hi": ("AI सहायक अभी AI सेवा तक नहीं पहुँच सका। कृपया पुनः प्रयास "
               "करें। शिकायत दर्ज करना और ट्रैक करना काम करता रहेगा।"),
        "hinglish": ("AI assistant abhi AI service tak nahi pahunch paya. "
                     "Dobara try karein. Complaint register aur track kaam "
                     "karta rahega."),
    },
    "disabled": {
        "en": "AI chat is currently disabled on this deployment.",
        "hi": "इस डिप्लॉयमेंट में AI चैट अभी निष्क्रिय है।",
        "hinglish": "Is deployment mein AI chat abhi disabled hai.",
    },
}


def _t(key, lang, **kwargs):
    entry = _TXT.get(key, {})
    text = entry.get(lang) or entry.get("en") or key
    return text.format(**kwargs) if kwargs else text


def _error_text(reason, lang):
    entry = _ERROR_TEXT.get(reason, _ERROR_TEXT["api_error"])
    return entry.get(lang) or entry["en"]


# ---------------------------------------------------------------------------
# Slot extraction (Gemini first, deterministic fallback - always safe)
# ---------------------------------------------------------------------------
def _keyword_slots(text, lang):
    slots = {}
    category = intents.detect_category(text)
    if category:
        slots["category"] = category
    priority = intents.detect_priority(text)
    if priority:
        slots["priority"] = priority
    mobile = intents.detect_mobile(text)
    if mobile:
        slots["mobile"] = mobile
    location = intents.detect_location(text)
    if location:
        slots["location"] = location
    # A generic "register a complaint" command is not a description.
    if len(text) >= 25 and not re.match(
        r"^(?:please\s+)?(?:i\s+want\s+to\s+|file\s+|register\s+|raise\s+)?"
        r"(?:a\s+)?complaint\b",
        text.strip(), re.IGNORECASE,
    ):
        slots["description"] = text
    return slots


def extract_slots(text, lang):
    """Best-effort structured extraction; never raises, never invents."""
    slots = {}
    try:
        raw = gemini_client.generate_text(
            prompts.json_extraction_system(lang),
            [("user", text[:2000])],
            json_mode=True,
            temperature=0.0,
            max_output_tokens=400,
        )
        data = json.loads(raw)
        if isinstance(data, dict):
            from config import CATEGORIES, PRIORITIES
            category = str(data.get("category") or "").strip()
            if category in CATEGORIES:
                slots["category"] = category
            priority = str(data.get("priority") or "").strip()
            if priority in PRIORITIES:
                slots["priority"] = priority
            mobile = intents.detect_mobile(str(data.get("mobile") or ""))
            if mobile:
                slots["mobile"] = mobile
            location = str(data.get("location") or "").strip()
            if 3 <= len(location) <= 80:
                slots["location"] = location
            description = str(data.get("description") or "").strip()
            if len(description) >= 15:
                slots["description"] = description[:2000]
    except (GeminiUnavailable, json.JSONDecodeError, ValueError, TypeError,
            KeyError):
        pass
    # Deterministic extraction always runs too - it fills whatever the model
    # missed and keeps the flow working with no API key at all.
    for key, value in _keyword_slots(text, lang).items():
        slots.setdefault(key, value)
    return slots


# ---------------------------------------------------------------------------
# Complaint registration machine
# ---------------------------------------------------------------------------
SLOT_ORDER = ("description", "category", "location", "priority", "mobile")

_SLOT_QUESTION = {
    "description": "ask_description",
    "category": "ask_category",
    "location": "ask_location",
    "priority": "ask_priority",
    "mobile": "ask_mobile",
}


def _options_text():
    from config import CATEGORIES
    return ", ".join(f"{i}. {c}" for i, c in enumerate(CATEGORIES, 1))


def _summary_text(slots, name, lang):
    lines = []
    labels = {
        "en": {"name": "Name", "mobile": "Mobile", "location": "Location",
               "category": "Category", "priority": "Priority",
               "description": "Description"},
        "hi": {"name": "नाम", "mobile": "मोबाइल", "location": "स्थान",
               "category": "श्रेणी", "priority": "प्राथमिकता",
               "description": "विवरण"},
        "hinglish": {"name": "Naam", "mobile": "Mobile", "location": "Location",
                     "category": "Category", "priority": "Priority",
                     "description": "Description"},
    }[lang]
    order = ("name", "mobile", "location", "category", "priority", "description")
    values = dict(slots)
    values["name"] = name or "-"
    for key in order:
        value = values.get(key)
        if value:
            lines.append(f"{labels[key]}: {value}")
    return "\n".join(lines)


def _next_slot(state):
    for slot in SLOT_ORDER:
        if not state["slots"].get(slot):
            return slot
    return None


def _ask_question(slot, lang):
    key = _SLOT_QUESTION[slot]
    if slot == "category":
        return _t(key, lang, options=_options_text())
    return _t(key, lang)


def start_registration(text, lang, user_id):
    slots = extract_slots(text, lang)
    state = {
        "intent": "register_complaint",
        "step": "collect",
        "slots": slots,
        "lang": lang,
    }
    missing = _next_slot(state)
    if missing is None:
        state["step"] = "confirm"
        return _confirm_message(state, user_id, lang), state
    intro = _t("registration_intro", lang)
    return f"{intro}\n\n{_ask_question(missing, lang)}", state


def _confirm_message(state, user_id, lang):
    profile = context.citizen_profile(user_id) or {}
    summary = _summary_text(state["slots"], profile.get("name"), lang)
    return _t("ask_confirm", lang, summary=summary)


def _summary_meta(state, user_id, lang):
    profile = context.citizen_profile(user_id) or {}
    slots = dict(state["slots"])
    return {
        "type": "complaint_summary",
        "language": lang,
        "fields": [
            {"label": "Name", "value": profile.get("name") or "-"},
            {"label": "Mobile", "value": slots.get("mobile", "-")},
            {"label": "Location", "value": slots.get("location", "-")},
            {"label": "Category", "value": slots.get("category", "-")},
            {"label": "Priority", "value": slots.get("priority", "-")},
            {"label": "Description", "value": slots.get("description", "-")},
        ],
    }


def _submit_registration(state, user_id):
    from modules.complaints import services as complaint_services

    profile = context.citizen_profile(user_id) or {}
    slots = state["slots"]
    form = {
        "name": profile.get("name") or "Citizen",
        "mobile": slots.get("mobile", ""),
        "location": slots.get("location", ""),
        "waste_type": slots.get("category", ""),
        "priority": slots.get("priority", ""),
        "description": slots.get("description", ""),
    }
    return complaint_services.create_complaint(
        form, None, user_id=user_id, ip=None
    )


def continue_registration(state, text, user_id, lang):
    """Advance the slot machine; returns (reply, meta, state_or_None)."""
    answer = (text or "").strip()

    # Global cancel at any step.
    if state.get("step") == "collect":
        if intents.is_confirmation(answer) is False and len(answer) <= 14:
            return _t("cancelled", lang), {"type": "flow_cancelled"}, None

    if state.get("step") == "confirm":
        verdict = intents.is_confirmation(answer)
        if verdict is False:
            return _t("cancelled", lang), {"type": "flow_cancelled"}, None
        if verdict is None:
            return _confirm_message(state, user_id, lang), \
                _summary_meta(state, user_id, lang), state
        result = _submit_registration(state, user_id)
        if not result.get("ok"):
            error = result.get("error", "Could not register the complaint.")
            return (f"{error}\n\n" + _confirm_message(state, user_id, lang),
                    _summary_meta(state, user_id, lang), state)
        tracking = result["tracking_id"]
        report_id = result["report_id"]
        meta = {
            "type": "complaint_created",
            "tracking_id": tracking,
            "report_id": report_id,
            "href": f"/complaint/{report_id}",
            "language": lang,
        }
        return _t("created", lang, tracking=tracking), meta, None

    # step == "collect": answer the first missing slot.
    slot = _next_slot(state)
    if slot is None:  # defensive - should have flipped to confirm
        state["step"] = "confirm"
        return _confirm_message(state, user_id, lang), \
            _summary_meta(state, user_id, lang), state

    if slot == "description":
        if len(answer) < 15:
            return _t("bad_description", lang), None, state
        state["slots"]["description"] = answer[:2000]
        # The description is the one free-text answer - mine it for any
        # other still-empty fields (category, location, priority, mobile)
        # so a complete first answer skips the remaining questions.
        for key, value in extract_slots(answer, lang).items():
            if key != "description" and not state["slots"].get(key):
                state["slots"][key] = value
    elif slot == "category":
        from config import CATEGORIES
        category = intents.detect_category(answer)
        if category is None:
            match = re.match(r"^\s*(\d{1,2})\s*[.)]?\s*$", answer)
            if match and 1 <= int(match.group(1)) <= len(CATEGORIES):
                category = CATEGORIES[int(match.group(1)) - 1]
        if category is None:
            return _t("bad_category", lang, options=_options_text()), None, state
        state["slots"]["category"] = category
    elif slot == "location":
        if len(answer) < 3:
            return _t("bad_location", lang), None, state
        state["slots"]["location"] = answer[:80]
    elif slot == "priority":
        from config import PRIORITIES
        priority = intents.detect_priority(answer)
        if priority is None:
            match = re.match(r"^\s*(\d)\s*[.)]?\s*$", answer)
            if match and 1 <= int(match.group(1)) <= len(PRIORITIES):
                priority = PRIORITIES[int(match.group(1)) - 1]
        if priority is None:
            return _t("bad_priority", lang), None, state
        state["slots"]["priority"] = priority
    elif slot == "mobile":
        mobile = intents.detect_mobile(answer)
        if mobile is None:
            return _t("bad_mobile", lang), None, state
        state["slots"]["mobile"] = mobile

    nxt = _next_slot(state)
    if nxt is None:
        state["step"] = "confirm"
        return (_confirm_message(state, user_id, lang),
                _summary_meta(state, user_id, lang), state)
    return _ask_question(nxt, lang), None, state


# ---------------------------------------------------------------------------
# Complaint tracking
# ---------------------------------------------------------------------------
def _complaint_line(report, lang):
    return (f"{report['tracking_id']} | {report['status']} | "
            f"{report['waste_type']} | {report.get('area') or report.get('location') or '-'}")


def _status_meta(report, lang):
    return {
        "type": "complaint_status",
        "language": lang,
        "item": {
            "tracking_id": report["tracking_id"],
            "report_id": report["id"],
            "status": report["status"],
            "category": report["waste_type"],
            "priority": report["priority"],
            "ai_urgency": report.get("ai_urgency"),
            "area": report.get("area"),
            "location": report.get("location"),
            "created_at": report.get("created_at"),
            "resolved_at": report.get("resolved_at"),
            "admin_remarks": report.get("admin_remarks"),
            "href": f"/complaint/{report['id']}",
        },
        "history": [
            {"status": h.get("new_status"), "remark": h.get("remark"),
             "created_at": h.get("created_at")}
            for h in (report.get("history") or [])[-6:]
        ],
    }


def _status_reply(report, lang):
    header = {
        "en": "Here's the status of your complaint:",
        "hi": "आपकी शिकायत की स्थिति यह है:",
        "hinglish": "Ye rahi aapki complaint ki status:",
    }.get(lang, "en")
    lines = [
        f"{header}",
        "",
        f"ID: {report['tracking_id']}",
        f"Status: {report['status']}",
        f"Category: {report['waste_type']}",
        f"Location: {report.get('area') or report.get('location') or '-'}",
        f"Submitted: {report.get('created_at') or '-'}",
    ]
    if report.get("resolved_at"):
        lines.append(f"Resolved: {report['resolved_at']}")
    if report.get("admin_remarks"):
        lines.append(f"Remark: {report['admin_remarks']}")
    history = report.get("history") or []
    if history:
        lines.append("")
        lines.append({
            "en": "Timeline:",
            "hi": "समयरेखा:",
            "hinglish": "Timeline:",
        }.get(lang, "Timeline:"))
        for item in history[-5:]:
            remark = f" - {item['remark']}" if item.get("remark") else ""
            lines.append(f"- {item['created_at']}: {item['new_status']}{remark}")
    return "\n".join(lines)


def handle_track(text, user_id, lang, state=None):
    ref = intents.detect_tracking_ref(text)
    if ref is None:
        new_state = {"intent": "track_complaint", "step": "await_ref", "lang": lang}
        return _t("track_ask_ref", lang), {"type": "prompt"}, new_state
    report = context.citizen_complaint(user_id, ref)
    if report is None:
        return _t("track_not_found", lang), {"type": "not_found"}, None
    return _status_reply(report, lang), _status_meta(report, lang), None


def handle_my_complaints(user_id, lang):
    payload = context.citizen_complaints(user_id, limit=10)
    items = payload["items"]
    if not items:
        return _t("my_complaints_empty", lang), {"type": "empty"}, None
    header = _t("my_complaints_header", lang,
                total=payload.get("total", len(items)))
    lines = [header, ""]
    for item in items:
        lines.append("- " + _complaint_line(item, lang))
    meta = {
        "type": "complaint_list",
        "language": lang,
        "items": [
            {
                "tracking_id": item["tracking_id"],
                "report_id": item["id"],
                "status": item["status"],
                "category": item["waste_type"],
                "area": item.get("area"),
                "href": f"/complaint/{item['id']}",
            }
            for item in items
        ],
    }
    return "\n".join(lines), meta, None


# ---------------------------------------------------------------------------
# Knowledge answers (RAG + Gemini)
# ---------------------------------------------------------------------------
def handle_knowledge(text, lang, role, history=None):
    chunks = rag.retrieve(text, limit=config.AI_CHAT_RAG_RESULTS)
    rag_context = rag.format_context(chunks)
    system = prompts.citizen_system(lang, rag_context, role=role)
    messages = list(history or [])
    if not messages or messages[-1][0] != "user" or messages[-1][1] != text:
        messages = messages + [("user", text)]
    try:
        reply = gemini_client.generate_text(
            system, messages, temperature=0.3, max_output_tokens=900
        )
    except GeminiUnavailable as exc:
        return _error_text(exc.reason, lang), {
            "type": "error", "reason": exc.reason,
        }, None
    meta = {
        "type": "knowledge",
        "language": lang,
        "sources": sorted({c.source for c in chunks})[:4],
    }
    return reply, meta, None


# ---------------------------------------------------------------------------
# Administrator data answers
# ---------------------------------------------------------------------------
_ADMIN_LABELS = {
    "total_complaints": {"en": "Total complaints", "hi": "कुल शिकायतें",
                         "hinglish": "Total complaints"},
    "open": {"en": "Open (unresolved)", "hi": "खुली (अनसुलझी)",
             "hinglish": "Open (unresolved)"},
    "pending_submitted": {"en": "Pending (Submitted)", "hi": "लंबित (Submitted)",
                          "hinglish": "Pending (Submitted)"},
    "resolved": {"en": "Resolved", "hi": "सुलझी", "hinglish": "Resolved"},
    "rejected": {"en": "Rejected", "hi": "अस्वीकृत", "hinglish": "Rejected"},
    "urgent_open": {"en": "Urgent open", "hi": "तत्काल खुली",
                    "hinglish": "Urgent open"},
    "needs_ai_review": {"en": "Need AI review", "hi": "AI समीक्षा आवश्यक",
                        "hinglish": "Need AI review"},
    "resolution_pct": {"en": "Resolution rate %", "hi": "समाधान दर %",
                       "hinglish": "Resolution rate %"},
    "avg_resolution_hours": {"en": "Avg resolution (hours)",
                             "hi": "औसत समाधान (घंटे)",
                             "hinglish": "Avg resolution (hours)"},
    "missing_coordinates": {"en": "Missing coordinates", "hi": "निर्देशांक अनुपलब्ध",
                            "hinglish": "Missing coordinates"},
    "clusters": {"en": "Hotspot clusters", "hi": "हॉटस्पॉट क्लस्टर",
                 "hinglish": "Hotspot clusters"},
    "recurring_hotspots": {"en": "Recurring hotspots", "hi": "पुनरावृत्ति हॉटस्पॉट",
                           "hinglish": "Recurring hotspots"},
    "unresolved_in_clusters": {"en": "Unresolved in clusters",
                               "hi": "क्लस्टर में अनसुलझी",
                               "hinglish": "Unresolved in clusters"},
    "total_forecast": {"en": "Forecast (next 7 days)", "hi": "पूर्वानुमान (अगले 7 दिन)",
                       "hinglish": "Forecast (next 7 days)"},
    "trend": {"en": "Trend", "hi": "रुझान", "hinglish": "Trend"},
    "peak_date": {"en": "Peak day", "hi": "शिखर दिन", "hinglish": "Peak day"},
}


def _label(key, lang):
    entry = _ADMIN_LABELS.get(key)
    if not entry:
        return key.replace("_", " ").title()
    return entry.get(lang) or entry["en"]


def _fmt(value):
    if value is None:
        return "unavailable"
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def format_admin_data(intent, data, lang):
    """Deterministic, localised rendering used when Gemini is unavailable."""
    lines = []
    if intent == "admin_stats":
        overview = data.get("overview") or {}
        if not overview.get("available", True) and "total_complaints" not in overview:
            return ("No statistics are available right now "
                    "(the query failed or returned no data).", None)
        for key in ("total_complaints", "open", "pending_submitted", "resolved",
                    "rejected", "urgent_open", "needs_ai_review",
                    "resolution_pct", "avg_resolution_hours",
                    "missing_coordinates"):
            if key in overview:
                lines.append(f"- {_label(key, lang)}: {_fmt(overview[key])}")
        breakdowns = data.get("breakdowns") or {}
        if breakdowns.get("available"):
            top_cat = (breakdowns.get("by_category") or [{}])[0]
            top_area = (breakdowns.get("by_area") or [{}])[0]
            if top_cat.get("label"):
                lines.append(
                    f"- {'Most common category' if lang == 'en' else 'सबसे आम श्रेणी' if lang == 'hi' else 'Most common category'}: "
                    f"{top_cat['label']} ({top_cat.get('n', 0)})"
                )
            if top_area.get("label"):
                lines.append(
                    f"- {'Busiest area' if lang == 'en' else 'सबसे व्यस्त क्षेत्र' if lang == 'hi' else 'Busiest area'}: "
                    f"{top_area['label']} ({top_area.get('n', 0)})"
                )
        meta = {"type": "stats", "language": lang,
                "items": [{"label": _label(k, lang), "value": _fmt(overview[k])}
                          for k in overview
                          if k not in ("available", "reason")]}
        return "\n".join(lines) or "No statistics available.", meta

    if intent in ("admin_pending", "admin_high_priority"):
        items = data.get("items") or []
        header = ("Pending complaints:" if intent == "admin_pending"
                  else "High-priority open complaints:")
        if lang == "hi":
            header = ("लंबित शिकायतें:" if intent == "admin_pending"
                      else "उच्च-प्राथमिकता खुली शिकायतें:")
        elif lang == "hinglish":
            header = ("Pending complaints:" if intent == "admin_pending"
                      else "High-priority open complaints:")
        if not items:
            return ("No matching complaints found.", {"type": "empty"})
        lines = [header, ""]
        for item in items:
            lines.append(
                f"- {item.get('tracking_id')} | {item.get('status')} | "
                f"{item.get('waste_type')} | {item.get('area') or item.get('location') or '-'}"
            )
        meta = {
            "type": "complaint_list",
            "language": lang,
            "items": [
                {
                    "tracking_id": item.get("tracking_id"),
                    "status": item.get("status"),
                    "category": item.get("waste_type"),
                    "area": item.get("area"),
                    "href": f"/admin/complaints?q={item.get('tracking_id')}",
                }
                for item in items
            ],
        }
        return "\n".join(lines), meta

    if intent == "admin_hotspots":
        stats = data.get("stats") or {}
        if not data.get("available"):
            return ("Hotspot analysis has not been run yet - open the hotspot "
                    "map and run clustering first.", {"type": "empty"})
        for key in ("clusters", "recurring_hotspots", "unresolved_in_clusters",
                    "complaints_in_clusters"):
            if key in stats:
                lines.append(f"- {_label(key, lang)}: {_fmt(stats[key])}")
        for cluster in (data.get("clusters") or [])[:6]:
            lines.append(
                f"- {cluster['label']}: {cluster['complaint_count']} "
                f"({cluster['unresolved_count']} unresolved, "
                f"{cluster.get('top_category') or '-'})"
            )
        top_areas = data.get("top_areas") or []
        for area in top_areas[:5]:
            lines.append(f"- {area['label']}: {area.get('n', 0)} complaints")
        meta = {
            "type": "stats",
            "language": lang,
            "items": [{"label": _label(k, lang), "value": _fmt(stats[k])}
                      for k in stats if k in _ADMIN_LABELS],
        }
        return "\n".join(lines) or "No hotspot data available.", meta

    if intent == "admin_recommendations":
        items = data.get("items") or []
        if not items:
            message = data.get("message") or "No recommendations right now."
            return message, {"type": "empty"}
        header = ("Recommendations based on live data:"
                  if lang == "en" else
                  "लाइव डेटा आधारित सुझाव:" if lang == "hi" else
                  "Recommendations based on live data:")
        lines = [header, ""]
        for item in items:
            lines.append(f"- [{item['severity'].upper()}] {item['title']}")
            if item.get("action"):
                lines.append(f"  -> {item['action']}")
        meta = {
            "type": "recommendations",
            "language": lang,
            "items": [
                {"severity": item["severity"], "title": item["title"],
                 "detail": item.get("detail"), "action": item.get("action")}
                for item in items
            ],
        }
        return "\n".join(lines), meta

    if intent == "admin_forecast":
        if not data.get("available"):
            message = data.get("message") or (
                "Forecasting is unavailable - not enough history yet.")
            return message, {"type": "empty"}
        for key in ("total_forecast", "trend", "peak_date"):
            if key in data:
                lines.append(f"- {_label(key, lang)}: {_fmt(data[key])}")
        meta = {"type": "stats", "language": lang,
                "items": [{"label": _label(k, lang), "value": _fmt(data[k])}
                          for k in data if k in _ADMIN_LABELS]}
        return "\n".join(lines), meta

    return "No data available for that question.", {"type": "empty"}


def handle_admin_data(intent, text, lang, history=None):
    data = context.data_for_admin_intent(intent)
    system = prompts.admin_system(lang, context.data_as_json(data))
    messages = list(history or [])
    if not messages or messages[-1][1] != text:
        messages = messages + [("user", text)]
    try:
        reply = gemini_client.generate_text(
            system, messages, temperature=0.2, max_output_tokens=900
        )
        # A model can misstate numbers; if it clearly drifts from the data
        # block we fall back to the deterministic rendering instead.
        if intent == "admin_stats":
            overview = data.get("overview") or {}
            total = overview.get("total_complaints")
            if isinstance(total, int) and total > 0 and str(total) not in reply:
                reply, meta = format_admin_data(intent, data, lang)
                return reply, meta, None
        meta = {
            "type": "stats" if intent in ("admin_stats", "admin_forecast",
                                          "admin_hotspots")
            else "recommendations" if intent == "admin_recommendations"
            else "complaint_list",
            "language": lang,
            "data_intent": intent,
            "items": _meta_items(intent, data, lang),
        }
        return reply, meta, None
    except GeminiUnavailable:
        reply, meta = format_admin_data(intent, data, lang)
        return reply, meta, None


def _meta_items(intent, data, lang):
    if intent in ("admin_pending", "admin_high_priority"):
        return [
            {
                "tracking_id": item.get("tracking_id"),
                "status": item.get("status"),
                "category": item.get("waste_type"),
                "area": item.get("area"),
                "href": f"/admin/complaints?q={item.get('tracking_id')}",
            }
            for item in (data.get("items") or [])
        ]
    if intent == "admin_recommendations":
        return [
            {"severity": item["severity"], "title": item["title"],
             "detail": item.get("detail"), "action": item.get("action")}
            for item in (data.get("items") or [])
        ]
    overview = data.get("overview") or data.get("stats") or {}
    if isinstance(overview, dict) and overview:
        return [
            {"label": _label(k, lang), "value": _fmt(v)}
            for k, v in overview.items()
            if k not in ("available", "reason", "parameters")
        ]
    return []


# ---------------------------------------------------------------------------
# Turn dispatcher
# ---------------------------------------------------------------------------
def handle_turn(role, user_id, conversation, text, lang, history=None):
    """Process one user message -> (reply, meta, new_state).

    ``new_state`` is written back onto the conversation; ``None`` clears it.
    """
    state = services.read_state(conversation) if conversation else None

    # 1. An active structured flow always wins.
    if state and state.get("intent") == "register_complaint":
        reply, meta, new_state = continue_registration(state, text, user_id, lang)
        return reply, meta, new_state
    if state and state.get("intent") == "track_complaint":
        reply, meta, new_state = handle_track(text, user_id, lang, state)
        return reply, meta, new_state

    # 2. Intent routing (role-scoped).
    intent = intents.detect_intent(text, role)

    if intent == "register_complaint":
        if role != "citizen":
            reply, meta, new_state = (
                _t("no_intent_match", lang), {"type": "suggestions"}, None
            )
            return reply, meta, new_state
        reply, new_state = start_registration(text, lang, user_id)
        meta = {"type": "flow_started", "language": lang}
        if new_state and new_state.get("step") == "confirm":
            profile = context.citizen_profile(user_id) or {}
            meta = _summary_meta(new_state, user_id, lang)
        return reply, meta, new_state

    if intent == "track_complaint":
        if role != "citizen":
            return _t("no_intent_match", lang), {"type": "suggestions"}, None
        return handle_track(text, user_id, lang)

    if intent == "my_complaints":
        if role != "citizen":
            return _t("no_intent_match", lang), {"type": "suggestions"}, None
        return handle_my_complaints(user_id, lang)

    if intent == "greeting":
        key = "greeting_admin" if role == "admin" else "greeting_citizen"
        return _t(key, lang), {
            "type": "suggestions", "role": role, "language": lang,
        }, None

    if intent == "thanks":
        return _t("thanks", lang), {"type": "plain"}, None

    if intent.startswith("admin_"):
        if role != "admin":
            # Defence in depth: a citizen must never receive admin data.
            return _t("no_intent_match", lang), {"type": "suggestions"}, None
        return handle_admin_data(intent, text, lang, history=history)

    if intent in ("segregation", "sustainability", "general"):
        if intent == "general" and not _is_knowledge_question(text):
            return _t("no_intent_match", lang), {"type": "suggestions"}, None
        return handle_knowledge(text, lang, role, history=history)

    return _t("no_intent_match", lang), {"type": "suggestions"}, None


def _is_knowledge_question(text):
    """Cheap filter so chit-chat does not trigger a RAG call."""
    text = (text or "").strip().lower()
    if len(text) < 6:
        return False
    signals = (
        "?", "how", "what", "why", "where", "which", "can i", "should i",
        "explain", "kaise", "kya", "kyun", "kahan", "kaun", "kyon",
        "कैसे", "क्या", "क्यों", "कहाँ", "कौन", "बताओ", "समझाओ",
    )
    return any(s in text for s in signals)
