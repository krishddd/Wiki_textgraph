from textgraph.l2_linguistic import modality, polarity, segment


def test_segment_basic_sentences() -> None:
    text = "Acme wired funds. Beta received them. Done."
    spans = [text[s.start : s.end] for s in segment(text)]
    assert spans == ["Acme wired funds.", "Beta received them.", "Done."]


def test_segment_respects_abbreviations() -> None:
    text = "Mr. John Doe is a director. He acted alone."
    spans = segment(text)
    # "Mr." must not split; two sentences total.
    assert len(spans) == 2


def test_segment_splits_after_org_suffix() -> None:
    # Regression: "Ltd." / "Corp." routinely end sentences (unlike titles), so they
    # must not be treated as abbreviations — otherwise relation subjects run on.
    text = "Funds went to Beta Ltd. Acme Corp then acted."
    spans = [text[s.start : s.end] for s in segment(text)]
    assert len(spans) == 2
    assert spans[1].startswith("Acme Corp")


def test_segment_covers_whole_text() -> None:
    text = "No trailing punctuation here"
    spans = segment(text)
    assert len(spans) == 1
    assert text[spans[0].start : spans[0].end] == text


def test_segment_empty() -> None:
    assert segment("") == []


def test_polarity_detects_negation() -> None:
    assert polarity("did not transfer any funds") == "neg"
    assert polarity("transferred the funds") == "pos"


def test_modality_detects_hedging() -> None:
    assert modality("may be linked to Sigma") == "hedged"
    assert modality("is the director of Beta") == "asserted"
