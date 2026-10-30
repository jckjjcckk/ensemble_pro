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


def test_prompt_v4d_rules():
    """v4d (docs/features/013-text-eval.md): future start points are marks; roster scope."""
    _, user = build_prompt("Start at bar 12 next time.", FACTS)
    assert 'A start point for a later run ("next time",' in user
    assert "anything the\n  speaker asks to have written or marked" in user
    assert "list every other part of X's group only, never parts of the other group" in user
    assert 'is not a part or member: use "ensemble" and keep that word in' in user
    assert "never the nearest-sounding part" in user


def test_roster_scope_at_the_check():
    """What v4d asks for passes the check; what it replaces (an unknown name as a member) is refused."""
    t = "Marco, bar 20, softer. Too much brass at sixty."
    keep = [mark(position="bar", bar_from=20, bar_to=20, audience=["ensemble"], kind="dynamic",
                 text="Marco softer at 20", quote="Marco, bar 20, softer."),
            mark(position="bar", bar_from=60, bar_to=60, audience=["ensemble"], kind="dynamic",
                 text="Brass softer at 60", quote="Too much brass at sixty.")]
    ok, refused = checked_marks(keep, t, FACTS)
    assert len(ok) == 2 and refused == []
    ok, refused = checked_marks([{**keep[0], "audience": ["member:Marco"]}, {**keep[1], "audience": ["part:Brass"]}],
                                t, FACTS)
    assert ok == [] and len(refused) == 2


def test_everyone_else_stays_in_the_group():
    """'Everyone else' of one choir part is the other voices; the check accepts that set in a mixed book."""
    facts = ScoreFacts(parts=["Violin I", "Violin II", "Viola", "Cello", "Soprano", "Alto", "Tenor", "Bass"],
                       members=[])
    t = "Bring out the altos at bar 12, everyone else lighter."
    m = mark(position="bar", bar_from=12, bar_to=12, audience=["part:Soprano", "part:Tenor", "part:Bass"],
             kind="dynamic", text="Lighter at bar 12", quote=t)
    assert checked_marks([m], t, facts) == ([m], [])
