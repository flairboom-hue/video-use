"""The torch-free transcription backend.

It exists because WhisperX is a heavy install that fails in ordinary places.
What matters here is that it produces the SAME thing WhisperX does — the flat
Scribe word list the rest of the skill reads — because everything downstream
was built against that shape and does not know which engine filled it.
"""
from __future__ import annotations

import pytest

import transcribe_fasterwhisper as fw
from transcribe_whisperx import whisperx_to_scribe


class Word:
    def __init__(self, word, start, end):
        self.word, self.start, self.end = word, start, end


class Segment:
    def __init__(self, words, text=""):
        self.words, self.text = words, text


class TestAdapter:
    """faster-whisper objects -> the dict shape the shared converter wants."""

    def test_words_keep_their_text_and_timings(self):
        out = fw.segments_to_result([Segment([Word(" Das", 0.0, 0.2)])], "de")
        assert out["language"] == "de"
        assert out["segments"][0]["words"] == [
            {"word": " Das", "start": 0.0, "end": 0.2}]

    def test_a_segment_without_words_does_not_crash(self):
        # faster-whisper sets .words to None when word_timestamps is off; a
        # caller that forgets the flag should get an empty transcript, not a
        # TypeError halfway through a render.
        seg = Segment(None, "text")
        assert fw.segments_to_result([seg], "de")["segments"][0]["words"] == []

    def test_the_result_feeds_the_shared_converter(self):
        # The point of adapting rather than writing a second converter: the
        # Scribe details (gaps as spacing entries, undated words kept) exist
        # once, so the two engines cannot drift apart.
        raw = fw.segments_to_result(
            [Segment([Word("Das", 0.0, 0.2), Word("hier", 0.9, 1.1)])], "de")
        scribe = whisperx_to_scribe(raw, language="de", engine=fw.ENGINE)
        kinds = [w["type"] for w in scribe["words"]]
        assert kinds == ["word", "spacing", "word"], "the gap became no spacing entry"
        assert scribe["_engine"] == "faster-whisper"
        assert scribe["language_code"] == "de"


class TestEngineMarker:
    def test_the_two_engines_are_told_apart_in_the_file(self):
        # A transcript on disk should say what made it: the word timings from
        # the two engines differ slightly, and a caption that is off by a frame
        # is worth being able to attribute.
        assert whisperx_to_scribe({"segments": []})["_engine"] == "whisperx"
        assert whisperx_to_scribe({"segments": []},
                                  engine="faster-whisper")["_engine"] == "faster-whisper"


class TestDevice:
    def test_cpu_gets_int8(self):
        # float16 on CPU is not slower, it is unusable.
        assert fw.pick_compute("cpu") == ("cpu", "int8")

    def test_cuda_gets_float16(self):
        assert fw.pick_compute("cuda") == ("cuda", "float16")

    def test_auto_resolves_to_something_usable(self):
        device, compute = fw.pick_compute("auto")
        assert device in ("cpu", "cuda")
        assert compute in ("int8", "float16")


class TestSignatureCompatibility:
    def test_it_accepts_the_arguments_only_whisperx_understands(self):
        # The caller should not have to know which engine it got. batch_size
        # and diarize mean nothing here, so they are swallowed rather than
        # raising a TypeError from inside the pipeline.
        import inspect
        params = inspect.signature(fw.transcribe_one).parameters
        assert any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()), \
            "extra WhisperX arguments would raise instead of being ignored"

    def test_the_shared_arguments_are_named_the_same(self):
        import inspect

        import transcribe_whisperx as wx
        mine = set(inspect.signature(fw.transcribe_one).parameters)
        theirs = set(inspect.signature(wx.transcribe_one).parameters)
        for shared in ("video", "edit_dir", "model_name", "language", "device",
                       "compute_type", "force", "verbose"):
            assert shared in mine and shared in theirs, shared
