from llm import is_in_character


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
