from app.services.normalise import keywords_from_name, normalise_name, slugify


def test_normalise_strips_stopwords_and_punctuation():
    assert normalise_name("The Wireless Earbuds, with ANC!") == "wireless earbuds anc"


def test_slugify_is_url_safe():
    assert slugify("Silicone Kitchen Organisation Tray") == "silicone-kitchen-organisation-tray"
    assert slugify("!!!") == "product"


def test_keywords_are_deduplicated():
    assert keywords_from_name("Bamboo Bamboo Drawer Divider") == [
        "bamboo",
        "drawer",
        "divider",
    ]
