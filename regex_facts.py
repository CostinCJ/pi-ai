import re

FACT_PATTERNS = [
    (r"\bi (?:bought|got|own|have)\s+(?:a |an |the )?([^.,!?]{3,40})", "owns"),
    (r"\bi (?:quit|stopped|started)\s+([^.,!?]{3,40})", "did"),
    (r"\bi'?m?(?: a| an)\s+([a-z]{3,30})\b(?!.*(?:tired|bored|sick))", "is_a"),
    (r"\bi (?:love|hate|prefer)\s+([^.,!?]{3,40})", "prefers"),
]


def extract_facts(text):
    text_lower = text.lower()
    seen_keys = set()
    results = []
    for pattern, category in FACT_PATTERNS:
        for match in re.finditer(pattern, text_lower):
            value = match.group(1).strip().rstrip(".,!? ")
            if len(value) < 3:
                continue
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
