from textgraph.core.config import Config


def test_config_hash_is_deterministic() -> None:
    assert Config().config_hash() == Config().config_hash()


def test_config_hash_changes_with_settings() -> None:
    assert Config().config_hash() != Config(llm_enabled=True).config_hash()
    assert Config().config_hash() != Config(seed=1).config_hash()


def test_model_pins_order_does_not_matter() -> None:
    # Canonical JSON sorts keys, so pin insertion order can't change the hash.
    a = Config(model_pins={"ner": "gliner-v1", "coref": "fastcoref-v2"})
    b = Config(model_pins={"coref": "fastcoref-v2", "ner": "gliner-v1"})
    assert a.config_hash() == b.config_hash()


def test_defaults_are_local_first() -> None:
    # G2: no LLM by default.
    assert Config().llm_enabled is False
