"""Deterministic UPSC GS topic tagging and question-quality filters.

No model or paid API is involved: every rule is a keyword table applied to the
question text. The taxonomy follows the broad GS syllabus headings so tests can
target a topic such as "Fundamental Rights" instead of only "Polity".
"""

from __future__ import annotations

import re

TOPIC_RULES = (
    ("Polity", "Constitutional Framework", (
        "constitution", "constitutional", "preamble", "amendment",
        "basic structure", "schedule", "article",
    )),
    ("Polity", "Fundamental Rights", (
        "fundamental right", "fundamental rights", "article 14", "article 19",
        "article 21", "article 32", "writ", "habeas corpus", "mandamus",
        "right to equality", "right to life", "right to freedom",
    )),
    ("Polity", "Parliament and Legislature", (
        "parliament", "lok sabha", "rajya sabha", "legislature", "speaker",
        "money bill", "ordinance", "legislative assembly", "question hour",
    )),
    ("Polity", "Judiciary", (
        "supreme court", "high court", "judicial review", "judiciary",
        "chief justice", "tribunal", "judicial activism", "collegium",
    )),
    ("Polity", "Federalism and Centre-State Relations", (
        "federalism", "federal", "centre-state", "center-state", "inter-state",
        "governor", "president's rule", "article 356", "union territory",
    )),
    ("Polity", "Elections and Representation", (
        "election commission", "election", "electoral", "voting", "franchise",
        "delimitation", "anti-defection", "political party", "repoll",
    )),
    ("Polity", "Constitutional Bodies", (
        "constitutional body", "comptroller and auditor", "cag", "upsc",
        "finance commission", "attorney general", "advocate general",
    )),
    ("Polity", "Local Governance", (
        "panchayat", "municipality", "local government", "73rd amendment",
        "74th amendment", "gram sabha", "ward committee",
    )),
    ("Polity", "Governance and Civil Services", (
        "civil service", "governance", "bureaucracy", "right to information",
        "rti", "citizen charter", "e-governance", "accountability",
    )),
    ("History", "Ancient India", (
        "harappan", "indus valley", "vedic", "mauryan", "gupta empire",
        "ashoka", "ancient india", "buddhism", "jainism", "sangam",
    )),
    ("History", "Medieval India", (
        "mughal", "delhi sultanate", "chola", "vijayanagara", "medieval india",
        "bhakti", "sufi", "maratha", "akbar",
    )),
    ("History", "Modern India and Freedom Struggle", (
        "british india", "colonial", "freedom struggle", "indian national congress",
        "gandhi", "non-cooperation", "civil disobedience", "quit india",
        "partition", "revolt of 1857", "swadeshi",
    )),
    ("History", "Art and Culture", (
        "art and culture", "temple architecture", "sculpture", "painting",
        "classical dance", "music", "festival", "heritage", "monument",
        "unesco", "folk art",
    )),
    ("History", "World History", (
        "world history", "renaissance", "industrial revolution", "french revolution",
        "world war", "cold war", "colonialism", "imperialism",
    )),
    ("Geography", "Physical Geography", (
        "physical geography", "plate tectonics", "earthquake", "volcano",
        "monsoon", "rock", "soil", "erosion", "glacier", "atmosphere",
        "ocean current", "latitude", "longitude",
    )),
    ("Geography", "Indian Geography", (
        "indian geography", "himalaya", "ganga", "brahmaputra", "deccan",
        "western ghats", "eastern ghats", "peninsular", "river basin",
        "coastal india", "northeast india",
    )),
    ("Geography", "World Geography", (
        "world geography", "continent", "equator", "tundra", "desert",
        "rainforest", "mediterranean", "pacific", "atlantic", "arctic",
    )),
    ("Geography", "Resources and Agriculture", (
        "mineral", "resource", "crop", "irrigation", "agriculture",
        "land use", "forest cover", "fishing", "energy resource",
    )),
    ("Economy", "Growth and Development", (
        "gdp", "economic growth", "development", "poverty", "inequality",
        "human development", "employment", "unemployment", "labour",
    )),
    ("Economy", "Inflation and Monetary Policy", (
        "inflation", "monetary policy", "rbi", "repo rate", "money supply",
        "banking", "npa", "financial inclusion", "credit",
    )),
    ("Economy", "Fiscal Policy and Budget", (
        "fiscal", "budget", "taxation", "gst", "deficit", "public debt",
        "subsidy", "finance commission", "revenue",
    )),
    ("Economy", "External Sector", (
        "balance of payment", "current account", "export", "import",
        "foreign trade", "exchange rate", "fdi", "forex", "wto",
    )),
    ("Economy", "Agriculture and Food Security", (
        "agriculture", "farmer", "msp", "food security", "public distribution",
        "crop insurance", "horticulture", "livestock",
    )),
    ("Economy", "Industry and Infrastructure", (
        "industry", "manufacturing", "infrastructure", "core industries",
        "msme", "industrial policy", "logistics", "power sector",
    )),
    ("Economy", "Schemes and Welfare", (
        "scheme", "yojana", "welfare", "pension", "insurance scheme",
        "maternity benefit", "scholarship", "ration card",
    )),
    ("Environment", "Ecology and Biodiversity", (
        "ecology", "biodiversity", "ecosystem", "species", "wildlife",
        "biosphere", "wetland", "coral", "mangrove", "protected area",
    )),
    ("Environment", "Climate Change", (
        "climate change", "global warming", "carbon", "emission", "cop",
        "paris agreement", "net zero", "greenhouse", "ozone",
    )),
    ("Environment", "Pollution and Waste", (
        "pollution", "air quality", "waste", "plastic", "effluent",
        "sewage", "e-waste", "noise pollution",
    )),
    ("Environment", "Conservation and Environmental Law", (
        "conservation", "environmental law", "forest act", "wildlife act",
        "environment impact", "national park", "tiger reserve",
    )),
    ("Science & Technology", "Space and Nuclear Technology", (
        "isro", "satellite", "space", "rocket", "nuclear", "reactor",
        "uranium", "missile", "launch vehicle",
    )),
    ("Science & Technology", "Biotechnology and Health", (
        "biotechnology", "gene", "dna", "vaccine", "virus", "bacteria",
        "stem cell", "health", "disease", "antibiotic",
    )),
    ("Science & Technology", "Information Technology", (
        "artificial intelligence", "machine learning", "blockchain",
        "cyber", "internet", "semiconductor", "quantum", "5g", "data protection",
    )),
    ("Science & Technology", "Defence Technology", (
        "defence", "defense", "drdo", "fighter aircraft", "submarine",
        "radar", "army", "navy", "air force",
    )),
    ("International Relations", "India and Neighbourhood", (
        "neighbourhood", "pakistan", "china", "bangladesh", "nepal",
        "sri lanka", "myanmar", "afghanistan", "border dispute",
    )),
    ("International Relations", "Global Groupings and Institutions", (
        "united nations", "unsc", "g20", "brics", "sco", "asean",
        "imf", "world bank", "wto", "quad", "commonwealth",
    )),
    ("International Relations", "Foreign Policy and Diplomacy", (
        "foreign policy", "diplomacy", "bilateral", "strategic partnership",
        "geopolitics", "sanction", "treaty", "visa",
    )),
    ("Current Affairs", "Government Initiatives", (
        "government initiative", "mission launched", "flagship scheme",
        "central sector scheme", "cabinet approved", "recently launched",
    )),
    ("Current Affairs", "Reports and Indices", (
        "report", "ranking", "survey", "statistics", "census",
        "niti aayog", "world bank report",
    )),
    ("Current Affairs", "Internal Security and Disaster Management", (
        "internal security", "terrorism", "insurgency", "disaster",
        "flood relief", "cyclone", "earthquake relief", "ndrf",
    )),
)

_NORMALIZE = re.compile(r"[^a-z0-9]+")

# A stem that depends on a figure, map, graph, or table that is not present in
# the question text cannot be answered honestly in a text-only test.
_FIGURE_REFERENCE = re.compile(
    r"\b(?:as\s+shown\s+in|shown\s+in|given\s+in|given\s+below|shown\s+below|"
    r"refer\s+to|with\s+reference\s+to|look\s+at|observe)\b"
    r"[^.!?]{0,60}?\b(?:map|figure|diagram|graph|chart|table|image|picture|cartoon)\b",
    re.IGNORECASE,
)
_FIGURE_LEAD = re.compile(
    r"^\s*(?:the\s+)?(?:map|figure|diagram|graph|chart|table|image|picture|cartoon)"
    r"\s+(?:given\s+below|below|shown\s+above|above)\b",
    re.IGNORECASE,
)
_FIGURE_INLINE = re.compile(
    r"\b(?:in|from|using)\s+the\s+(?:given\s+)?(?:map|figure|diagram|graph|chart|table)\b",
    re.IGNORECASE,
)


def normalize_text(value):
    return " ".join(_NORMALIZE.sub(" ", (value or "").lower()).split())


def is_self_contained(question_text):
    """Return False when the question needs a visual that is not in the text."""
    text = " ".join((question_text or "").split())
    if not text:
        return False
    if _FIGURE_LEAD.search(text):
        return False
    if _FIGURE_REFERENCE.search(text):
        return False
    if _FIGURE_INLINE.search(text):
        return False
    return True


def classify_topic(question_text, source_subject="", source_topic=""):
    """Return ``(subject, topic)`` using the most specific keyword match."""
    haystack = normalize_text(question_text)
    source_subject = (source_subject or "").strip()
    source_topic = (source_topic or "").strip()

    best = None
    best_score = 0
    for subject, topic, keywords in TOPIC_RULES:
        score = 0
        for keyword in keywords:
            normalized = normalize_text(keyword)
            if not normalized:
                continue
            if f" {normalized} " in f" {haystack} ":
                score += len(normalized.split())
        if score and source_subject and source_subject.casefold() in subject.casefold():
            score += 1
        if score > best_score:
            best = (subject, topic)
            best_score = score

    if best is not None:
        return best
    fallback_subject = source_subject or "General Studies"
    return fallback_subject, (source_topic or fallback_subject)


def canonical_subject(value):
    """Map a free-form label to a taxonomy subject when possible."""
    text = normalize_text(value)
    if not text:
        return None
    for subject, topic, keywords in TOPIC_RULES:
        if normalize_text(subject) == text or normalize_text(topic) == text:
            return subject
        for keyword in keywords:
            if normalize_text(keyword) == text:
                return subject
    return None


def selector_keywords(value):
    """Turn a roadmap topic or weak-area label into matching words."""
    normalized = normalize_text(value)
    if not normalized:
        return []
    subject = canonical_subject(value)
    if subject:
        words = [subject]
        for rule_subject, topic, keywords in TOPIC_RULES:
            if rule_subject == subject and normalize_text(topic) == normalized:
                words.append(topic)
        return words
    words = [word for word in normalized.split() if len(word) >= 3]
    return words[:6]
