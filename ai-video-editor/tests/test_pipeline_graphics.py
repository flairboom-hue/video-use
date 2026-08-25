"""Every advertised graphic kind must actually build something.

`available_kinds()` feeds the frontend's menu and the API's `graphic_kinds`
list, but the renderer for a chosen kind lives in `build_graphic`. A kind that
is registered in one and missing from the other passes validation, writes no
file, and fails later on `probe` — a menu entry that does nothing, which is
exactly what this project is not allowed to ship.
"""
from __future__ import annotations

import pytest

from engine import graphics as gfx
from engine import pipeline
from engine.project import Project

# Kinds whose parameters cannot be derived from a detected figure; each must
# say so rather than writing an empty file.
NEEDS_PARAMS = {
    "linked_meters": {"control": "Ladung",
                      "meters": [["Höhe", 9.0, 15.0, ""], ["Weite", 3.0, 8.0, ""]]},
}


@pytest.fixture
def project(tmp_path):
    src = tmp_path / "take.mp4"
    src.write_bytes(b"x")
    p = Project.create(tmp_path / "projects", src)
    p.data["media"] = {"width": 1920, "height": 1080, "fps": 30}
    p.data["suggestions"] = [{
        "id": "s1", "kind": "number", "anchor_word": "zwölf",
        "quote": "zwölf Zeilen in einer Datei",
        "payload": {"values": ["12", "3"], "labels": ["A", "B"]},
    }]
    p.save()
    return p


@pytest.fixture
def recorder(monkeypatch):
    """Run the real generators, but compose one frame instead of encoding.

    Stubbing the generators themselves would let a wrong argument through —
    the point here is that what the pipeline passes is what the generator
    accepts, so only the encode step is replaced.
    """
    from PIL import Image, ImageDraw

    calls = {}

    def one_frame(frame, dur, st, out):
        img = Image.new("RGBA", (st.width, st.height), (0, 0, 0, 0))
        frame(ImageDraw.Draw(img), 1.0, img)      # the held, final state
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"mov")
        return out

    monkeypatch.setattr(gfx, "_render", one_frame)

    def watch(name):
        real = getattr(gfx, name)

        def wrapped(out, *args, **kw):
            calls[name] = (args, kw)
            return real(out, *args, **kw)
        return wrapped

    for name in gfx.GENERATORS:
        monkeypatch.setattr(pipeline.gfx, name, watch(name))
    monkeypatch.setattr(pipeline.media, "probe",
                        lambda p: type("I", (), {"duration": 3.0})())
    return calls


class TestEveryKindBuilds:
    @pytest.mark.parametrize("kind", sorted(gfx.GENERATORS))
    def test_a_registered_kind_writes_a_clip(self, project, recorder, kind):
        overlay = pipeline.build_graphic(project, "s1", kind,
                                         params=NEEDS_PARAMS.get(kind))
        assert kind in recorder, f"{kind} is offered but nothing renders it"
        assert overlay.duration == 3.0
        assert overlay.anchor_word == "zwölf"

    def test_an_unknown_kind_is_refused_before_anything_is_written(self, project):
        with pytest.raises(ValueError):
            pipeline.build_graphic(project, "s1", "definitely_not_a_kind")


class TestParameterHungryKinds:
    def test_linked_meters_says_what_it_needs(self, project, recorder):
        # Silently rendering an empty diagram would be the worse failure.
        with pytest.raises(ValueError) as exc:
            pipeline.build_graphic(project, "s1", "linked_meters")
        assert "control" in str(exc.value) and "meters" in str(exc.value)


    def test_the_declared_list_matches_what_actually_needs_params(self):
        # The picker hides these kinds; if the two lists drift, it either hides
        # a usable kind or offers one that can only fail.
        assert pipeline.PARAM_ONLY_KINDS == set(NEEDS_PARAMS)


class TestFigureFormatting:
    def test_thousands_are_grouped_the_German_way(self):
        assert pipeline._fmt(26063) == "26\u202f063"   # narrow no-break space

    def test_a_whole_number_keeps_no_decimal_tail(self):
        assert pipeline._fmt(7.0) == "7"

    def test_a_fraction_keeps_its_comma(self):
        assert pipeline._fmt(12.4) == "12,4"
