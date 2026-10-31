from yinju.terms import (
    extract_keywords,
    extract_numbers,
    keyword_coverage,
    number_status,
    tokens,
)


def test_keywords_drop_stopwords_and_duplicates() -> None:
    assert extract_keywords("The the model uses a model with dense vectors") == (
        "model",
        "uses",
        "dense",
        "vectors",
    )


def test_keywords_keep_numbers_and_acronyms() -> None:
    assert extract_keywords("BERT has 340 million parameters in 2026") == (
        "bert",
        "340",
        "million",
        "parameters",
        "2026",
    )


def test_keywords_limit_and_empty_for_chinese() -> None:
    assert len(extract_keywords("alpha beta gamma delta epsilon", limit=3)) == 3
    assert extract_keywords("注意力机制与引用核对") == ()


def test_tokens_are_lowercase() -> None:
    assert tokens("Dense Vectors, BERT-340M") == ["dense", "vectors", "bert", "340", "m"]


def test_numbers_normalize_scale_abbreviations() -> None:
    mentions = extract_numbers("3.3 billion tokens; 340M parameters; 92% accuracy; 1024-hidden")
    keys = {mention.key for mention in mentions}
    assert (3.3, "billion") in keys
    assert (340.0, "million") in keys
    assert (92.0, "percent") in keys
    assert (1024.0, "none") in keys


def test_numbers_keep_data_and_latency_units() -> None:
    mentions = extract_numbers("100TB benchmark, 500TB claim, 20GB data, 3ms latency, 10x")
    keys = {mention.key for mention in mentions}
    assert (100.0, "tb") in keys
    assert (500.0, "tb") in keys
    assert (20.0, "gb") in keys
    assert (3.0, "ms") in keys
    assert (10.0, "x") in keys


def test_numbers_normalize_english_number_words() -> None:
    assert extract_numbers("six identical layers")[0].key == (6.0, "none")
    assert extract_numbers("eight parallel attention heads")[0].key == (8.0, "none")
    assert extract_numbers("twenty-one layers")[0].key == (21.0, "none")
    assert number_status(
        extract_numbers("The Transformer employs eight parallel attention heads."),
        "In this work we employ h = 8 parallel attention layers, or heads.",
    ) == "match"
    assert extract_numbers("one of the models") == ()
    assert extract_numbers("two of them") == ()


def test_number_status_match_conflict_missing_none() -> None:
    claim = extract_numbers("BERT Large has 340 million parameters")
    assert number_status(claim, "BERT Large has 340M parameters") == "match"
    assert number_status(claim, "BERT Large has 350 million parameters") == "conflict"
    assert number_status(claim, "BERT Large uses 24 layers") == "missing"
    assert number_status((), "anything 340 million") == "none"

    assert number_status(extract_numbers("a 500TB record"), "a 100TB record") == "conflict"
    assert number_status(extract_numbers("a 100TB record"), "a 100 TB record") == "match"


def test_keyword_coverage() -> None:
    keywords = ("dense", "retrieval", "vectors")
    assert keyword_coverage(keywords, "Dense retrieval uses vectors") == 1.0
    assert keyword_coverage(keywords, "Dense retrieval") == 2 / 3
    assert keyword_coverage((), "anything") == 0.0
