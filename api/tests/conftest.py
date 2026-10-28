"""The suite never reaches the OMR box: the engraving step (MuseScore over ssh) is switched off unless a test hands a
handler its own engraver (`engraver=FakeEngraver()` in test_engrave.py)."""
import os

import pytest


@pytest.fixture(autouse=True)
def _no_box(monkeypatch):
    if "ENGRAVE" not in os.environ:
        monkeypatch.setenv("ENGRAVE", "off")
