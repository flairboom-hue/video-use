"""Creative detection proposes the right things and stays quiet otherwise.

A false positive costs the user a click; a wall of noise costs their attention.
Both directions are asserted.
"""
from __future__ import annotations

import pytest

from engine.suggestions import detect


def kinds(sug) -> set[str]:
    return {s.graphic_kind or s.kind for s in sug}


class TestDetection:
    def test_percentage_with_direction_becomes_a_number(self, make_transcript):
        t = make_transcript([("Der Umsatz ist um 40 Prozent gestiegen.", 0.0)])
        s = detect(t)
        assert len(s) == 1
        assert s[0].graphic_kind == "number_animation"
        assert s[0].payload["values"] == ["40"]
        assert s[0].payload["direction"] == "up"

    def test_two_figures_with_a_comparison_word_become_a_comparison(self, make_transcript):
        t = make_transcript([("Wir sind von 60 auf 100 Millionen gewachsen.", 0.0)])
        s = detect(t)
        assert s[0].graphic_kind == "comparison"
        assert s[0].payload["values"] == ["60", "100"]

    def test_percentages_that_add_to_a_whole_become_a_pie(self, make_transcript):
        # Shares of one thing, which is what a pie says and bars do not.
        t = make_transcript([("45 Prozent organisch, 28 Prozent paid, "
                              "17 Prozent referral, 10 Prozent direkt.", 0.0)])
        assert detect(t)[0].graphic_kind == "pie_chart"

    def test_percentages_that_do_not_add_up_are_not_a_pie(self, make_transcript):
        t = make_transcript([("40 Prozent hier, 80 Prozent dort, 90 Prozent überall.", 0.0)])
        assert detect(t)[0].graphic_kind != "pie_chart"

    def test_a_short_list_becomes_an_icon_row(self, make_transcript):
        t = make_transcript([("Erstens brauchen wir Zeit.", 0.0),
                             ("Zweitens fehlt Personal.", 4.0)])
        assert "icon_row" in kinds(detect(t))

    def test_ordinals_across_sentences_become_a_list(self, make_transcript):
        t = make_transcript([("Erstens brauchen wir Zeit.", 0.0),
                             ("Zweitens fehlt Personal.", 4.0)])
        assert kinds(detect(t)) & {"icon_row", "infographic"}

    def test_a_single_ordinal_is_a_figure_of_speech(self, make_transcript):
        t = make_transcript([("Erstens brauchen wir Zeit.", 0.0)])
        assert "infographic" not in kinds(detect(t))

    def test_two_years_become_a_timeline(self, make_transcript):
        t = make_transcript([("Zwischen 2019 und 2024 hat sich viel verändert.", 0.0)])
        assert "timeline" in kinds(detect(t))

    def test_a_place_after_a_preposition_becomes_broll(self, make_transcript):
        t = make_transcript([("Wir waren letztes Jahr in Tokio.", 0.0)])
        s = [x for x in detect(t) if x.kind == "broll"]
        assert s and s[0].payload["query"] == "Tokio"


class TestDevlogVocabulary:
    """A devlog counts commits and months, not euros and percent.

    The original detector required a percent sign, a currency or a direction
    word, which made it silent on almost everything a developer says.
    """

    @pytest.mark.parametrize("sentence", [
        "Ich habe 18 Monate an dem Spiel gearbeitet.",
        "Das sind über 4200 Commits.",
        "Wir haben jetzt 3000 Wishlists auf Steam.",
        "Der Playtest hatte 250 Spieler.",
        "Ich habe 800 Bugs gefixt.",
    ])
    def test_a_figure_with_a_countable_unit_is_worth_a_graphic(self, sentence,
                                                               make_transcript):
        assert detect(make_transcript([(sentence, 0.0)]))

    def test_four_digit_figures_are_recognised(self, make_transcript):
        # The pattern allowed three digits, which is fine for percentages and
        # silent on "4200 Commits".
        s = detect(make_transcript([("Das sind über 4200 Commits.", 0.0)]))
        assert s and s[0].payload["values"] == ["4200"]

    def test_grouped_thousands_are_recognised(self, make_transcript):
        # ASR writes the separator either way.
        assert detect(make_transcript([("Ich habe 4.200 Zeilen Code geschrieben.", 0.0)]))

    def test_the_unit_must_follow_the_figure(self, make_transcript):
        # "Version 3" labels a thing; "3 Versionen" counts them. Scanning
        # backwards as well would turn every ordinal label into a graphic.
        # The unit here sits one word BEFORE the figure, so a backward scan
        # would catch it and a forward-only scan must not.
        labelled = detect(make_transcript([("Danach kam Version 3.", 0.0)]))
        counted = detect(make_transcript([("Danach kamen 3 Versionen.", 0.0)]))
        assert counted, "a counted unit after the figure should fire"
        assert not labelled, "a unit before the figure is a label, not a count"

    def test_a_verb_form_of_growth_still_counts(self, make_transcript):
        # "stieg", not only "gestiegen".
        s = detect(make_transcript([("Die Framerate stieg von 30 auf 60 FPS.", 0.0)]))
        assert s and s[0].graphic_kind == "comparison"

    def test_a_number_without_a_unit_is_still_ignored(self, make_transcript):
        assert detect(make_transcript([("Ich habe zwei Katzen und 3 Hunde.", 0.0)])) == []

    def test_years_still_go_to_the_timeline_not_the_counter(self, make_transcript):
        # Widening the number pattern made years matchable; they must not
        # steal the timeline's anchor.
        s = detect(make_transcript([("Zwischen 2019 und 2024 hat sich viel verändert.", 0.0)]))
        assert s and s[0].graphic_kind == "timeline"


class TestGermanSpeech:
    """German ASR output is not the tidy digits-and-singulars a regex expects."""

    @pytest.mark.parametrize("sentence", [
        "In zwei Stunden kamen neun Fehler heraus.",
        "Die Shopseite muss zwei Wochen sichtbar sein.",
        "Dann kamen alle zehn Erfolge auf einen Schlag.",
    ])
    def test_numbers_spelled_as_words_still_count(self, sentence, make_transcript):
        # Whisper writes small German numbers as words far more often than as
        # digits, so a digits-only detector is deaf to most spoken counts.
        assert detect(make_transcript([(sentence, 0.0)]))

    def test_a_spelled_number_yields_its_digits_for_the_graphic(self, make_transcript):
        s = detect(make_transcript([("Dann kamen alle zehn Erfolge.", 0.0)]))
        assert s and "10" in s[0].payload["values"]

    @pytest.mark.parametrize("sentence", [
        "Der Trailer besteht aus 11 Schnitten.",       # dative plural
        "Ich habe 20 Achievement-Icons gebaut.",       # hyphenated compound
        "Das Spiel hat 12 Gegnertypen.",               # compound
    ])
    def test_inflected_and_compound_units_are_matched(self, sentence, make_transcript):
        # Listing every German inflection is a losing game; a token counts if
        # it opens or closes with a known stem.
        assert detect(make_transcript([(sentence, 0.0)]))

    def test_stem_matching_finds_units_and_leaves_other_nouns_alone(self):
        from engine.suggestions import _unit_of
        # Assert whether a unit is found, not which stem matched — the exact
        # stem depends on vocabulary order and is not the behaviour that matters.
        assert _unit_of("schnitten")           # dative plural of a known unit
        assert _unit_of("achievementicons")    # hyphenated compound, normalised
        assert _unit_of("gegnertypen")
        assert not _unit_of("katzen")
        assert not _unit_of("hunde")
        assert not _unit_of("gartenzwerg")

    def test_spelled_numbers_without_a_unit_stay_silent(self, make_transcript):
        # The unit requirement is what keeps "zwei Katzen" from becoming a chart.
        assert detect(make_transcript([("Ich habe zwei Katzen und drei Hunde.", 0.0)])) == []


class TestComparability:
    """Two figures only make a chart when they measure the same thing."""

    def test_conflicting_units_do_not_become_a_bar_chart(self, make_transcript):
        # Days against bugs is a chart that means nothing.
        s = detect(make_transcript([("In zwei Tagen kamen neun Fehler heraus.", 0.0)]))
        assert s and s[0].graphic_kind == "number_animation"

    def test_conflicting_units_anchor_on_the_figure_the_sentence_is_about(
            self, make_transcript):
        # "neun Fehler" is the payload; "zwei Tage" is the setting.
        s = detect(make_transcript([("In zwei Tagen kamen neun Fehler heraus.", 0.0)]))
        assert s and s[0].anchor_word.lower().strip(".") == "neun"

    def test_two_figures_sharing_a_unit_do_become_a_chart(self, make_transcript):
        s = detect(make_transcript([
            ("Ich habe 31401 Zeilen geschrieben und 5338 wieder gelöscht.", 0.0)]))
        assert s and s[0].graphic_kind == "bar_chart"

    def test_an_article_is_not_a_number(self, make_transcript):
        # "eine Datei" counted as the numeral 1 turned every such sentence
        # into a two-value comparison.
        s = detect(make_transcript([("Das Spiel ist eine Datei mit 26063 Zeilen.", 0.0)]))
        assert s and s[0].graphic_kind == "number_animation"
        assert s[0].payload["values"] == ["26063"]

    @pytest.mark.parametrize("sentence", [
        "Die Draw Calls fielen von 968 auf 730.",
        "Die Shader stiegen von 34 auf 51.",
    ])
    def test_plural_verb_forms_count_as_direction(self, sentence, make_transcript):
        # People say "die Draw Calls fielen", not "ist gefallen".
        s = detect(make_transcript([(sentence, 0.0)]))
        assert s and s[0].graphic_kind == "comparison"


class TestRestraint:
    def test_a_bare_small_number_is_not_worth_a_graphic(self, make_transcript):
        t = make_transcript([("Ich habe zwei Katzen und 3 Hunde.", 0.0)])
        assert detect(t) == []

    def test_a_sentence_opener_is_not_a_place(self, make_transcript):
        t = make_transcript([("Heute war ein guter Tag.", 0.0)])
        assert [x for x in detect(t) if x.kind == "broll"] == []

    def test_output_is_capped(self, make_transcript):
        many = [(f"Der Wert stieg um {i} Prozent.", i * 5.0) for i in range(10, 40)]
        assert len(detect(make_transcript(many), max_suggestions=6)) <= 6

    def test_empty_transcript(self, make_transcript):
        assert detect(make_transcript([])) == []


class TestAnchoring:
    def test_every_suggestion_carries_a_word_anchor(self, make_transcript):
        # Anchors survive a re-cut; timestamps do not.
        t = make_transcript([("Der Umsatz ist um 40 Prozent gestiegen.", 0.0),
                             ("Wir waren in Tokio.", 5.0)])
        assert all(s.anchor_word for s in detect(t))

    def test_occurrence_disambiguates_a_repeated_anchor(self, make_transcript):
        t = make_transcript([("Der Umsatz stieg um 40 Prozent.", 0.0),
                             ("Der Gewinn stieg um 40 Prozent.", 5.0)])
        occ = [s.anchor_occurrence for s in detect(t) if s.anchor_word == "40"]
        assert occ == sorted(occ) and len(set(occ)) == len(occ)
