import regex_facts


def _keys(text):
    return {f["key"] for f in regex_facts.extract_facts(text)}


def test_is_a_filters_stopwords():
    """Casual phrases should not produce identity facts."""
    for msg in [
        "i'm a bit tired",
        "i am a fan of that",
        "i'm a loser today",
        "i'm a mess right now",
        "i'm a happy guy",
    ]:
        keys = _keys(msg)
        assert not any(k.startswith("is_a_") for k in keys), f"unexpected is_a from: {msg}"


def test_is_a_accepts_real_role():
    facts = regex_facts.extract_facts("i'm a student honestly")
    assert any(f["key"].startswith("is_a_") for f in facts)


def test_owns_basic():
    facts = regex_facts.extract_facts("i bought a new amp yesterday")
    assert any(f["key"].startswith("owns_") for f in facts)


def test_generic_value_filtered():
    keys = _keys("i love it")
    assert not keys, "generic 'it' should not produce a fact"


def test_did_pattern():
    facts = regex_facts.extract_facts("i quit smoking")
    assert any(f["key"].startswith("did_") and "smoking" in f["value"] for f in facts)
