"""B13: whole-word keyword matching."""
from viraltracker.services.seo_pipeline.text_match import keyword_in_text


class TestKeywordInText:
    def test_whole_word_match(self):
        assert keyword_in_text("key", "where is the key?") is True

    def test_no_substring_match(self):
        assert keyword_in_text("key", "the keys are here") is False
        assert keyword_in_text("key", "a monkey escaped") is False
        assert keyword_in_text("game", "playing games today") is False

    def test_multiword_phrase(self):
        assert keyword_in_text("online gaming", "best ONLINE GAMING tips") is True
        assert keyword_in_text("online gaming", "online and gaming separately") is False

    def test_case_insensitive(self):
        assert keyword_in_text("Minecraft", "love minecraft a lot") is True

    def test_punctuation_boundaries(self):
        # keyword flanked by punctuation still matches (lookarounds, not \b)
        assert keyword_in_text("game", "(game) night") is True
        assert keyword_in_text("game", "the game, really") is True

    def test_keyword_with_trailing_nonword(self):
        assert keyword_in_text("kids'", "the kids' room") is True

    def test_empty_inputs(self):
        assert keyword_in_text("", "text") is False
        assert keyword_in_text("key", "") is False
