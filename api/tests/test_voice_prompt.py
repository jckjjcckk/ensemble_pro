"""Voice note proposals (013): the check that refuses a mark before the admin sees it."""

from app.librarian.voice_prompt import ScoreFacts, build_prompt, checked_marks, parse_answer, quote_ok

FACTS = ScoreFacts(parts=["Violin I", "Violin II", "Viola", "Cello"], members=["Lin", "Inès"])
T = "Second violins from 42 to 48 we are cutting that. Go straight to 49."


def mark(**kw):
    m = {"position": "range", "bar_from": 42, "bar_to": 48, "audience": ["part:Violin II"], "kind": "cut",
         "text": "Cut 42–48", "quote": "from 42 to 48 we are cutting that"}
    return {**m, **kw}


def test_good_mark_stands():
    ok, refused = checked_marks([mark()], T, FACTS)
    assert len(ok) == 1 and refused == []


def test_none_is_no_marks():
    assert checked_marks({"none": True}, T, FACTS) == ([], [])


def test_refusals():
    bad = [mark(quote="from 40 to 48"), mark(bar_to=241), mark(audience=["part:Flute"]), mark(audience=["member:Ada"]),
           mark(kind="tempo"), mark(position="bar", bar_from=None), mark(bar_from=50), mark(text=" ")]
    ok, refused = checked_marks(bad, T, FACTS)
    assert ok == [] and len(refused) == len(bad)


def test_quote_is_verbatim_up_to_case_and_outer_punctuation():
    assert quote_ok("Go straight to 49.", T)
    assert quote_ok('"second violins from 42"', T)
    assert not quote_ok("go straight to forty-nine", T)


def test_member_and_ensemble_audiences():
    ok, _ = checked_marks([mark(audience=["member:Inès"]), mark(audience=["ensemble", "part:Cello"])], T, FACTS)
    assert len(ok) == 2


def test_parse_answer_tolerates_fences():
    assert parse_answer('```json\n[{"none": true}]\n```') == [{"none": True}]
    assert parse_answer('ok: {"none": true} trailing') == {"none": True}


def test_prompt_carries_facts_and_transcript():
    system, user = build_prompt("bar 9, mezzo forte", FACTS)
    assert "JSON only" in system and "Violin II" in user and '"bar 9, mezzo forte"' in user and "Rules:" in user
