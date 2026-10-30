"""Voice note proposals (013): the check that refuses a mark before the admin sees it."""

from app.librarian.voice_prompt import ScoreFacts, build_prompt, checked_marks, derive_groups, parse_answer, quote_ok

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


QUARTET = ["Violin I", "Violin II", "Viola", "Cello"]
CHOIR = ["Soprano", "Alto", "Tenor", "Bass"]
CONCERTO = ["Piano", "Flute", "Oboe", "Clarinet", "Bassoon", "Horn", "Trumpet", "Timpani", "Violin I", "Violin II",
            "Viola", "Cello", "Double Bass"]


def test_groups_of_a_string_quartet_and_a_choir():
    assert derive_groups(QUARTET) == [("Strings", QUARTET)]
    assert derive_groups(CHOIR) == [("Voices", CHOIR)]


def test_groups_of_a_mixed_book_are_the_two_v4d_groups():
    assert derive_groups(QUARTET + CHOIR) == [("Strings", QUARTET), ("Voices", CHOIR)]


def test_groups_of_a_piano_concerto_are_soloist_orchestra_and_sections():
    g = dict(derive_groups(CONCERTO))
    assert list(g)[:2] == ["Soloist", "Orchestra"]
    assert g["Soloist"] == ["Piano"] and g["Orchestra"] == CONCERTO[1:]
    assert g["Woodwinds"] == ["Flute", "Oboe", "Clarinet", "Bassoon"] and g["Brass"] == ["Horn", "Trumpet"]
    assert g["Percussion"] == ["Timpani"] and g["Strings"] == ["Violin I", "Violin II", "Viola", "Cello", "Double Bass"]
    assert not any("Piano" in ps for name, ps in g.items() if name != "Soloist")


def test_groups_read_printed_names_and_tell_the_bass_voice_from_the_basses():
    assert derive_groups(["Violini I", "Violini II", "Viole", "Violoncelli", "Bassi"]) == [
        ("Strings", ["Violini I", "Violini II", "Viole", "Violoncelli", "Bassi"])]
    g = dict(derive_groups(["Flauto", "Corno I", "Corno II", "Violin I", "Violin II", "Soprano", "Alto", "Bass"]))
    assert g["Orchestra"] == ["Flauto", "Corno I", "Corno II", "Violin I", "Violin II"] and g["Voices"] == ["Soprano", "Alto", "Bass"]
    assert "Soloist" not in g and dict(derive_groups(["Violin solo", "Flute", "Violin I", "Cello"]))["Soloist"] == ["Violin solo"]
    assert dict(derive_groups(["Alto Saxophone", "Piano"])) == {"Woodwinds": ["Alto Saxophone"], "Keyboard": ["Piano"]}


def test_prompt_v4e_lists_the_groups_and_the_exclusion_rule_refers_to_them():
    _, user = build_prompt("Everyone except the piano, softer at 12.", ScoreFacts(CONCERTO, [], groups=derive_groups(CONCERTO)))
    assert "Groups: Soloist: Piano. Orchestra: Flute, Oboe," in user
    assert "list every other part of the widest group in the score facts that holds X" in user
    assert "a soloist alone in its group\n  is excluded from the Orchestra" in user
    assert "(strings: Violin I,\n  Violin II, Viola, Cello; voices" not in user        # the hardcoded two are gone
    assert "fermenta" not in user                                                    # (c) is not adopted
    assert "Groups:" not in ScoreFacts(QUARTET, []).as_text()                          # None: no line (old evals)


def test_the_eval_rules_are_the_app_rules():
    from experiments.voice import prompts as P                                       # asserts at import
    assert P.RULES_V4E != P.RULES_V4D and "widest group" in P.RULES_V4E
