import re

# Stop words for the "is_a" capture — common adjectives/feelings that look
# like nouns but aren't identity claims.
IS_A_STOPWORDS = {
    "bit", "bored", "tired", "sick", "hungry", "fan", "lot", "little",
    "while", "moment", "second", "minute", "hour", "day", "week", "year",
    "guy", "dude", "person", "man", "woman", "girl", "boy", "kid",
    "joke", "loser", "idiot", "fool", "mess", "wreck", "disaster",
    "good", "bad", "ok", "fine", "okay", "alright",
    "going", "thinking", "trying", "looking", "feeling", "doing",
    "happy", "sad", "angry", "mad", "stressed", "anxious", "depressed",
    "ready", "done", "finished", "free", "busy", "back", "home", "out",
}

# Generic / overly-broad nouns we don't want as facts.
GENERIC_VALUES = {
    "thing", "stuff", "something", "anything", "nothing", "everything",
    "shit", "crap", "it", "this", "that",
}

FACT_PATTERNS = [
    # "i bought / got / own / have a <noun>"
    (r"\bi (?:bought|got|own|have)\s+(?:a |an |the )?([a-z][a-z0-9 \-']{2,40})", "owns"),
    # "i quit / stopped / started <activity>"
    (r"\bi (?:quit|stopped|started)\s+([a-z][a-z0-9 \-']{2,40})", "did"),
    # "i'm a / i am a <role>" — single-word capture, stop-word filtered
    (r"\bi(?:'m| am)(?: a| an)\s+([a-z]{3,30})\b", "is_a"),
    # "i love / hate / prefer <thing>"
    (r"\bi (?:love|hate|prefer)\s+([a-z][a-z0-9 \-']{2,40})", "prefers"),
]


def _clean(value):
    value = value.strip().rstrip(".,!? ").strip()
    # Strip filler trailing words common in casual speech
    value = re.sub(r"\b(today|now|right now|already|too|tho|though)$", "", value).strip()
    return value


def extract_facts(text):
    text_lower = text.lower()
    seen_keys = set()
    results = []
    for pattern, category in FACT_PATTERNS:
        for match in re.finditer(pattern, text_lower):
            value = _clean(match.group(1))
            if len(value) < 3:
                continue
            if value in GENERIC_VALUES:
                continue
            if category == "is_a" and value in IS_A_STOPWORDS:
                continue
            if category == "is_a" and " " in value:
                continue  # is_a captures should be a single noun
            key = f"{category}_{value[:20].replace(' ', '_')}"
            if key in seen_keys:
                continue
            seen_keys.add(key)
            results.append({
                "key": key,
                "value": f"{category}: {value}",
                "confidence": 0.6,
                "source": "realtime",
            })
    return results
