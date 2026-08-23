"""Creative detection proposes the right things and stays quiet otherwise.

A false positive costs the user a click; a wall of noise costs their attention.
Both directions are asserted.
"""
from __future__ import annotations

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
