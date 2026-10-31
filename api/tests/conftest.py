"""The suite never reaches the OMR box: the engraving step (MuseScore over ssh) is switched off unless a test hands a
handler its own engraver (`engraver=FakeEngraver()` in test_engrave.py)."""
import os

import pytest


@pytest.fixture(autouse=True)
def _no_box(monkeypatch):
    if "ENGRAVE" not in os.environ:
        monkeypatch.setenv("ENGRAVE", "off")


@pytest.fixture(autouse=True)
def _no_chat_network(monkeypatch):
    """The chat-completions branch (effort minimal) never reaches Meta from a test: a test that wants it hands
    `llm._chat_transport` its own fake transport."""
    import httpx

    from app import llm

    def refuse(req):
        raise RuntimeError(f"a test reached the network: {req.url}")
    monkeypatch.setattr(llm, "_chat_transport", httpx.MockTransport(refuse))
