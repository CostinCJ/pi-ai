from llm import is_in_character, _clean


def test_rejects_empty():
    assert not is_in_character("")
    assert not is_in_character("   ")


def test_rejects_poetic_today_message():
    assert not is_in_character(
        "today is perfect, the air is crisp, and the city is "
        "alive with energy. you're doing great, just like the city."
    )


def test_rejects_marketing_compliment():
    assert not is_in_character(
        "Trivium and Of Mice & Men—your playlist is a masterpiece."
    )


def test_accepts_lache_voice():
    assert is_in_character("running fine, nothing broken yet. you good?")
    assert is_in_character("bars or just driving around?")


def test_clean_collapses_thinking_only_output_to_empty():
    """When Qwen3 emits only think tags (despite /no_think), _clean must
    return an empty string so chat_with_retry's validator catches it."""
    raw = "<think>let me think about this carefully...</think>\n   \n  "
    assert _clean(raw) == ""


def test_clean_strips_lache_prefix_case_insensitive():
    assert _clean("Lache: hey") == "hey"
    assert _clean("LACHE: yo") == "yo"
