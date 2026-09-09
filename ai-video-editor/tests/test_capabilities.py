"""How the machine is graded.

The profile scales work to the hardware. Getting a tier boundary slightly
wrong is invisible: nothing fails, the job just runs with a weaker model and
puts a wrong word in a burned-in caption.
"""
from __future__ import annotations

from unittest.mock import patch

from engine.capabilities import Hardware, quality_profile


def _profile(**hw):
    base = dict(cpu_count=4, ram_gb=15.7, cuda=False, vram_gb=0.0, gpu="")
    base.update(hw)
    caps = patch("engine.capabilities.detect")
    with caps as detect:
        detect.return_value.hardware = Hardware(**base)
        return quality_profile()


class TestWhisperTier:
    def test_a_sixteen_gig_machine_is_treated_as_one(self):
        # It reports 15.5-15.8 once firmware has taken its share, so a
        # threshold at 16 excluded every machine that is actually 16 GB.
        # Measured on this one at 15.7: it fell to `base`, and `base` writes
        # "Zahlen" where the speaker said "Zeilen".
        assert _profile(ram_gb=15.7)["whisper_model"] == "small"
        assert _profile(ram_gb=15.0)["whisper_model"] == "small"

    def test_a_genuinely_small_machine_still_gets_the_small_model(self):
        assert _profile(ram_gb=7.5)["whisper_model"] == "base"

    def test_cpu_never_asks_for_float16(self):
        # It is not slower on CPU, it does not run.
        for ram in (4.0, 15.7, 64.0):
            p = _profile(ram_gb=ram)
            if p["device"] == "cpu":
                assert p["compute_type"] == "int8"

    def test_a_gpu_outranks_any_amount_of_ram(self):
        assert _profile(ram_gb=4.0, cuda=True, vram_gb=12.0)["device"] == "cuda"
        assert _profile(ram_gb=4.0, cuda=True, vram_gb=12.0)["whisper_model"] == "large-v3"

    def test_every_tier_names_a_real_model_and_encoder(self):
        for hw in (dict(ram_gb=4.0), dict(ram_gb=15.7),
                   dict(cuda=True, vram_gb=6.0), dict(cuda=True, vram_gb=12.0)):
            p = _profile(**hw)
            assert p["whisper_model"] in {"base", "small", "medium", "large-v3"}
            assert p["encoder"] in {"libx264", "h264_nvenc"}
            assert p["proxy_height"] in {360, 540, 720}
