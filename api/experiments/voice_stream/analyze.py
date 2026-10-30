"""Tables for docs/features/013-always-on.md from results/*.json. No paid calls.

    uv run python -m experiments.voice_stream.analyze
"""

from __future__ import annotations

import json
import re
import statistics as st

import numpy as np

from ..voice.textnorm import wer
from .common import RESULTS, base_id, labels

R = RESULTS
lab = labels()


def md(rows: list[list], head: list[str]) -> str:
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(st.median(xs), 2) if xs else "-"


def p90(xs):
    xs = [x for x in xs if x is not None]
    return round(float(np.percentile(xs, 90)), 2) if xs else "-"


def q1() -> str:
    five = json.loads((R / "modes_five.json").read_text())
    rows = []
    for uid, r in five.items():
        bd = r["batch_DIARIZATION"]
        rows.append([uid, f"{st.mean(x['seconds'] for x in bd):.2f}", r["batch_PUSH_TO_TALK"][0]["seconds"],
                     r["rt_PUSH_TO_TALK"]["first_partial_after_onset"], r["rt_PUSH_TO_TALK"]["final_after_endStream"],
                     r["rt_ENDPOINTING"]["first_partial_after_speechStart"],
                     "/".join(str(x) for x in r["rt_ENDPOINTING"]["complete_lag_per_turn"]),
                     r["rt_DIARIZATION"].get("complete_lag_per_turn") and "/".join(
                         str(x) for x in r["rt_DIARIZATION"]["complete_lag_per_turn"]),
                     "{}/{}".format(*bd[0]["wer"]), "{}/{}".format(*r["rt_PUSH_TO_TALK"]["wer"]),
                     "{}/{}".format(*r["rt_ENDPOINTING"]["wer"]), "{}/{}".format(*r["rt_DIARIZATION"]["wer"])])
    t1 = md(rows, ["line", "batch DIAR s (upload to answer, mean of 2)", "batch PTT s", "rt PTT first partial after onset s",
                   "rt PTT final after endStream s", "rt ENDP first partial after speechStart s",
                   "rt ENDP speechComplete after turn end s", "rt DIAR speechComplete after turn end s",
                   "WER batch DIAR", "WER rt PTT", "WER rt ENDP", "WER rt DIAR"])
    # all clips, ENDPOINTING
    rt = json.loads((R / "realtime_endpointing.json").read_text())
    tm = (R.parent.parent / "voice" / "results" / "transcripts.md").read_text()
    batch_wer = {m.group(1): (int(m.group(2)), int(m.group(3)))
                 for m in re.finditer(r"^\| (v\w+) \| (\d+)/(\d+) \|", tm, re.M)}
    ids = [u for u in rt if u.startswith("v")]
    e_rt = sum(rt[u]["wer"][0] for u in ids)
    n_rt = sum(rt[u]["wer"][1] for u in ids)
    base = [u for u in ids if not u.endswith("c")]
    retk = [u for u in ids if u.endswith("c")]

    def w(us, src):
        if src == "rt":
            e, n = sum(rt[u]["wer"][0] for u in us), sum(rt[u]["wer"][1] for u in us)
        else:
            e, n = sum(batch_wer[u][0] for u in us), sum(batch_wer[u][1] for u in us)
        return f"{e / n:.3f} ({e}/{n})"

    lags = [x for u in rt for x in rt[u].get("complete_lag_per_turn", [])]
    fp = [rt[u]["first_partial_after_speechStart"] for u in rt if rt[u].get("first_partial_after_speechStart") is not None]
    multi = [u for u in ids if len(rt[u].get("turn_texts", [])) > 1]
    music = [u for u in rt if u in ("n16", "n17", "n18")]
    t2 = md([["base 30", w(base, "batch"), w(base, "rt")], ["retakes 10", w(retk, "batch"), w(retk, "rt")]],
            ["set", "WER batch DIARIZATION (eval, 2026-10-29)", "WER realtime ENDPOINTING (today)"])
    extra = (f"All {len(rt)} clips: speechComplete arrives {med(lags)} s (median; p90 {p90(lags)}, max {max(lags)}) after "
             f"the turn end the server reports; first partial {med(fp)} s (median) after speechStart. "
             f"{len(multi)} of {len(ids)} eval clips came back as more than one turn: {', '.join(multi)}. "
             f"Piano and instrument clips ({', '.join(music)}): "
             + ", ".join(f"{u} {sum(1 for e in rt[u]['events'] if e.get('type') == 'speechStart')} turns" for u in music) + ".")
    return t1 + "\n\n" + t2 + "\n\n" + extra


def partial_vs_final() -> str:
    from ..voice.textnorm import wer as w
    rt = json.loads((R / "realtime_endpointing.json").read_text())
    gains, equal, n = [], 0, 0
    for u, r in rt.items():
        ev = r["events"]
        for c in [e for e in ev if e.get("type") == "speechComplete"]:
            n += 1
            ps = [e for e in ev if e.get("type") == "transcript" and not e.get("final") and e["t"] <= c["t"] + 1e-6]
            hit = next((p for p in ps if w(c["transcript"], p["transcript"])[0] == 0), None)
            if hit:
                equal += 1
                gains.append(c["t"] - hit["t"])
    return (f"Turns whose final text (words, numbers folded) already appeared as a partial: {equal}/{n}; the matching "
            f"partial came {med(gains)} s (median; p90 {p90(gains)}) before speechComplete.")


def q2() -> str:
    d = json.loads((R / "spark_latency.json").read_text())
    names = list(dict.fromkeys(r["variant"] for r in d))
    rows = []
    for nme in names:
        rs = [r for r in d if r["variant"] == nme]
        rows.append([nme, len(rs), med([r["seconds"] for r in rs]), p90([r["seconds"] for r in rs]),
                     med([r["first_object"] for r in rs]), med([r["input_tokens"] for r in rs]),
                     med([r["output_tokens"] for r in rs]), f"{sum(bool(r['all_fields']) for r in rs)}/{len(rs)}",
                     f"{st.mean(r['usd'] for r in rs):.4f}"])
    return md(rows, ["variant", "calls", "median s", "p90 s", "median s to first complete JSON object",
                     "input tok", "output tok (incl. reasoning)", "all 5 fields right", "mean $/call"])


def full(tag: str) -> list[dict]:
    return json.loads((R / f"full_{tag}.json").read_text())


def q2_full() -> str:
    rows = []
    for tag in ("v4_minimal", "v4c_minimal", "v4c_low"):
        rs = full(tag)
        pos = [r for r in rs if not r["score"]["negative"]]
        neg = [r for r in rs if r["score"]["negative"]]
        b = [r for r in pos if not r["id"].endswith("c")]
        c = [r for r in pos if r["id"].endswith("c")]
        called = [r for r in rs if "seconds" in r]
        rows.append([tag, f"{sum(bool(r['score'].get('all_fields')) for r in b)}/{len(b)}",
                     f"{sum(bool(r['score'].get('all_fields')) for r in c)}/{len(c)}",
                     f"{sum(r['score']['ok'] for r in neg)}/{len(neg)}", med([r['seconds'] for r in called]),
                     p90([r['seconds'] for r in called]), f"{st.mean(r['usd'] for r in called):.4f}"])
    return md(rows, ["prompt, effort (chat, stream)", "base 26 all fields", "retakes 9 all fields",
                     "negatives no mark (5 CK + 15 synthetic + 3 music)", "median s", "p90 s", "mean $/call"])


GATE_WORDS = re.compile(
    r"\b(\d+|bar|bars|letter|pickup|pick up|piano|forte|pianissimo|fortissimo|mezzo|crescendo|cresc|diminuendo|dim|"
    r"sforzando|sforzato|subito|accent|staccato|legato|pizz\w*|arco|mute|vibrato|harmonic|fermata|ritard\w*|rit|"
    r"rall\w*|tempo|slower|faster|rush|drag|breath\w*|breathe|bow|bowing|cut|cutting|skip|repeat|coda|"
    r"double bar|key change|octave|entry|come in|louder|softer|quieter|hold|weight|"
    r"violins?|violas?|cellos?|basses|bass|sopranos?|altos?|tenors?|firsts|seconds|fiddles|everyone|everybody|"
    r"whole choir|tutti|lin|in[eè]s)\b", re.I)


def q3() -> str:
    out = []
    for tag in ("v4c_minimal", "v4c_low"):
        rs = full(tag)
        pos = [r for r in rs if not r["score"]["negative"]]
        neg = [r for r in rs if r["score"]["negative"]]
        # per line: produced card? its confidence (max over marks), correct?
        def conf(r):
            cs = [c for c in r.get("confs") or [] if isinstance(c, (int, float))]
            return max(cs) if cs else None
        rows = []
        for t in (0.0, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95):
            tp = [r for r in pos if conf(r) is not None and conf(r) >= t]
            fpos = [r for r in neg if conf(r) is not None and conf(r) >= t]
            right = [r for r in tp if r["score"].get("all_fields")]
            cards = len(tp) + len(fpos)
            rows.append([t, f"{len(tp)}/{len(pos)}", len(fpos),
                         f"{len(tp) / cards:.2f}" if cards else "-",
                         f"{len(right)}/{len(tp)}" if tp else "-",
                         f"{len(right) / cards:.2f}" if cards else "-"])
        dist_ok = [conf(r) for r in pos if r["score"].get("all_fields") and conf(r) is not None]
        dist_bad = [(r["id"], conf(r)) for r in pos if not r["score"].get("all_fields")]
        dist_neg = [(r["id"], r.get("none_conf")) for r in neg if r.get("none_conf") is not None]
        out.append(f"**{tag}**\n\n" + md(rows, [
            "threshold", "instruction lines with a card (recall)", "cards on non-instructions",
            "card precision (is an instruction)", "cards fully right", "auto-apply precision (fully right / applied)"])
            + f"\n\nConfidence of fully right marks: {sorted(dist_ok)}\n\nLines not fully right (id, confidence): "
            f"{dist_bad}\n\nNegatives' none-confidence: {sorted(c for _, c in dist_neg)}")
    # the cheap text gate before Spark
    rt = json.loads((R / "realtime_endpointing.json").read_text())
    pos_ids = [u for u in rt if u.startswith("v") and lab[base_id(u)]["expect"] != "none"]
    neg_ids = [u for u in rt if u.startswith("n") or (u.startswith("v") and lab[base_id(u)]["expect"] == "none")]
    passed_pos = [u for u in pos_ids if GATE_WORDS.search(rt[u]["transcript"])]
    passed_neg = [u for u in neg_ids if rt[u]["transcript"] and GATE_WORDS.search(rt[u]["transcript"])]
    empty = [u for u in neg_ids if not rt[u]["transcript"]]
    out.append(f"Cheap text gate (a regex of numbers, part names and musical words; no call): instruction lines "
               f"passed {len(passed_pos)}/{len(pos_ids)}; non-instructions passed {len(passed_neg)}/{len(neg_ids)} "
               f"({len(empty)} had no transcript at all), stopped before Spark: "
               f"{sorted(set(neg_ids) - set(passed_neg) - set(empty))}; passed: {sorted(passed_neg)}.")
    return "\n\n".join(out)


def q4() -> str:
    d = json.loads((R / "chunking.json").read_text())
    keys = ["chunker", "min_silence_ms", "segments", "found", "false_splits", "merged_segments",
            "segments_on_music_only", "music_seconds_sent", "end_decided_after_speech_end_median",
            "end_decided_after_speech_end_p90", "seconds_sent"]
    rows = [[r[k] for k in keys] + [", ".join(r["split_ids"])] for r in d["rows"]]
    t = md(rows, ["chunker", "silence cut-off ms", "segments", "lines found (of 17)", "extra pieces (splits)",
                  "segments joining 2 lines", "segments on music only", "music s sent", "end decided after speech end, median s",
                  "p90 s", "audio s sent (of 146)", "lines split"])
    se = json.loads((R / "stream_eval.json").read_text())
    rows = []
    for n, label in (("A", "each turn alone"), ("B", "turn joined with previous if gap <= 2 s, latest reading wins"),
                     ("C", "rolling group: gap <= 1 s, up to 3 turns, group re-read at each turn")):
        pos = [r[n] for r in se["lines"] if not r[n]["negative"]]
        neg = [r[n] for r in se["lines"] if r[n]["negative"]]
        rows.append([label, f"{sum(bool(s['all_fields']) for s in pos)}/{len(pos)}",
                     f"{sum(s['ok'] for s in neg)}/{len(neg)}", se["stray_marks"][n]])
    return (t + f"\n\nSilero cost: {d['silero_ms_per_32ms_frame']} ms of CPU per 32 ms frame (this Mac, one thread).\n\n"
            + md(rows, ["Spark on Meta's turns of long.wav (v4c, minimal)", "12 instruction lines all fields",
                        "5 spoken negatives no mark", "marks on music"]))


if __name__ == "__main__":
    print("## Q1\n", q1(), "\n", partial_vs_final())
    print("\n## Q2\n", q2(), "\n\n", q2_full())
    print("\n## Q3\n", q3())
    print("\n## Q4\n", q4())
