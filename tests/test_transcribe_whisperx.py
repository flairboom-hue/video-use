"""transcribe_whisperx.py — the Scribe-format contract.

WhisperX is only useful here if its output is indistinguishable from Scribe's
to everything downstream. These tests check the converter against the *real*
consumers (pack_transcripts, render) rather than against an idea of the
format, because that is where a mismatch would actually bite.

WhisperX inference itself is not exercised — the models are far too large for
CI. The schema contract is the part this repo owns.
"""

from __future__ import annotations

from pack_transcripts import group_into_phrases
from render import _words_in_range
from transcribe_whisperx import MIN_SPACING, normalize_speaker, whisperx_to_scribe


def wx(segments):
    return {"language": "de", "segments": segments}


class TestSpeakerNormalization:
    def test_whisperx_labels_map_to_the_form_pack_transcripts_prints(self):
        # pack_transcripts strips a 'speaker_' prefix and prints the remainder,
        # so the zero padding has to go or every speaker renders as S0.
        assert normalize_speaker("SPEAKER_00") == "speaker_0"
        assert normalize_speaker("SPEAKER_01") == "speaker_1"
        assert normalize_speaker("SPEAKER_12") == "speaker_12"

    def test_absent_and_unrecognized_labels_pass_through(self):
        assert normalize_speaker(None) is None
        assert normalize_speaker("bob") == "bob"


class TestConversion:
    def test_gaps_become_explicit_spacing_entries(self):
        # Not cosmetic: pack_transcripts breaks phrases on these, and phrase
        # boundaries are what the editor cuts on.
        out = whisperx_to_scribe(wx([
            {"words": [{"word": "eins", "start": 1.0, "end": 1.2},
                       {"word": "zwei", "start": 2.8, "end": 3.0}]},
        ]))
        gaps = [w for w in out["words"] if w["type"] == "spacing"]
        assert len(gaps) == 1
        assert gaps[0]["start"] == 1.2 and gaps[0]["end"] == 2.8

    def test_sub_threshold_gaps_are_not_emitted(self):
        out = whisperx_to_scribe(wx([
            {"words": [{"word": "a", "start": 1.0, "end": 1.10},
                       {"word": "b", "start": 1.10 + MIN_SPACING / 2, "end": 1.3}]},
        ]))
        assert not [w for w in out["words"] if w["type"] == "spacing"]

    def test_word_without_timestamps_is_kept_and_anchored(self):
        # Alignment commonly leaves digits undated. Dropping them would lose
        # caption text; anchoring keeps the word at a known position.
        out = whisperx_to_scribe(wx([
            {"words": [{"word": "Wir", "start": 4.0, "end": 4.3},
                       {"word": "42"},
                       {"word": "behoben", "start": 4.6, "end": 5.2}]},
        ]))
        words = [w for w in out["words"] if w["type"] == "word"]
        assert [w["text"] for w in words] == ["Wir", "42", "behoben"]
        assert out["_undated_words"] == 1
        undated = words[1]
        assert undated["start"] == undated["end"] == 4.3

    def test_reversed_timestamps_are_clamped_not_propagated(self):
        out = whisperx_to_scribe(wx([{"words": [{"word": "x", "start": 2.0, "end": 1.0}]}]))
        w = [x for x in out["words"] if x["type"] == "word"][0]
        assert w["end"] >= w["start"]

    def test_empty_result_is_valid_not_a_crash(self):
        out = whisperx_to_scribe(wx([]))
        assert out["words"] == [] and out["text"] == ""

    def test_engine_marker_lets_the_two_sources_be_told_apart(self):
        assert whisperx_to_scribe(wx([]))["_engine"] == "whisperx"


class TestDownstreamConsumers:
    """The contract that actually matters: the real readers accept the output."""

    def _two_speaker_result(self):
        return wx([
            {"speaker": "SPEAKER_00", "words": [
                {"word": "Neunzig", "start": 1.00, "end": 1.40, "speaker": "SPEAKER_00"},
                {"word": "Prozent", "start": 1.42, "end": 1.90, "speaker": "SPEAKER_00"},
                {"word": "davon.", "start": 1.92, "end": 2.40, "speaker": "SPEAKER_00"}]},
            # 1.6s of silence, then a different speaker
            {"speaker": "SPEAKER_01", "words": [
                {"word": "Wir", "start": 4.00, "end": 4.30, "speaker": "SPEAKER_01"},
                {"word": "behoben.", "start": 4.60, "end": 5.20, "speaker": "SPEAKER_01"}]},
        ])

    def test_pack_transcripts_splits_on_the_reconstructed_silence(self):
        out = whisperx_to_scribe(self._two_speaker_result())
        phrases = group_into_phrases(out["words"], silence_threshold=0.5)
        assert len(phrases) == 2
        assert phrases[0]["text"].startswith("Neunzig Prozent")
        assert phrases[1]["text"].startswith("Wir")

    def test_pack_transcripts_splits_on_speaker_change(self):
        out = whisperx_to_scribe(self._two_speaker_result())
        phrases = group_into_phrases(out["words"], silence_threshold=0.5)
        assert phrases[0]["speaker_id"] == "speaker_0"
        assert phrases[1]["speaker_id"] == "speaker_1"

    def test_render_word_filter_sees_only_word_entries_in_range(self):
        out = whisperx_to_scribe(self._two_speaker_result())
        got = _words_in_range(out, 0.9, 2.5)
        assert [w["text"] for w in got] == ["Neunzig", "Prozent", "davon."]
        assert all(w["type"] == "word" for w in got)
