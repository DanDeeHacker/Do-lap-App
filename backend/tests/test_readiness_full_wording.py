"""feedback #223 (note: "Při 100 % ukazuje -"): at 100 % readiness two equal mornings showed a
bare "▬" instead of words. The app has no browser test runner, so this pins the source: a zero
change carries words only, and a full readiness that nothing lowers says so."""
import os

ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "src")


def _src(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def test_a_zero_change_has_no_bare_bar_glyph():
    for name in ("App.tsx", "capacity.tsx"):
        assert "▬" not in _src(name), name
    assert 'delta < 0 ? "▼ " : ""}ráno' in _src("capacity.tsx")
    assert "{!!delta && <span>" in _src("App.tsx")


def test_full_readiness_that_nothing_lowers_says_so():
    app = _src("App.tsx")
    assert "Plná — nic ji dnes nesnižuje." in app
    assert 'data-testid="readiness-full"' in app
    # only when the score is 100, no session or day drop applies and no signal is below its norm
    assert "score >= 100 && !drop" in app and "v > 0.05" in app
