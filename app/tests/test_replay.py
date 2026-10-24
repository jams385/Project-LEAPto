"""Tests for the Replay logic (src/replay.py) and its wording (app/content/replay_text.py)."""

import numpy as np
import pandas as pd
import pytest

from app import config
from app.content.replay_text import BEFORE_2014, entry_text, span, summary_text
from src.contract import load_part
from src.replay import (idle_flag_run, lead_time, outbreak_runs, panel_window, season_table,
                        what_happened)

W0 = pd.Timestamp("2018-06-03")
PCODE = "PHX"
BANNED = ("caused by", "will get", "deadly", "outbreak is coming")


# FIXTURES +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def make_table(levels1, levels2=None, cases=None, above=None, rain=None, thr=2.0):
    """A season table from level lists (None = no forecast)."""
    n = len(levels1)
    weeks = pd.date_range(W0, periods=n, freq="7D")
    cases = cases if cases is not None else [0] * n
    above = above if above is not None else [c > thr for c in cases]
    levels2 = levels2 if levels2 is not None else [None if lv is None else "Normal"
                                                   for lv in levels1]
    return pd.DataFrame({
        "week_start": weeks, "cases": np.array(cases, dtype=float), "threshold": thr,
        "above": above, "level_1": pd.Series(levels1, dtype=object),
        "p_1": [np.nan if lv is None else 0.1 for lv in levels1],
        "level_2": pd.Series(levels2, dtype=object),
        "p_2": [np.nan if lv is None else 0.05 for lv in levels2],
        "rain_mm": rain if rain is not None else [10.0] * n})


# TABLE +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def test_season_table_joins_levels_cases_and_late_rain():
    weeks = pd.date_range(W0, periods=3, freq="7D")
    rows = []
    for h in (1, 2):
        for i, w in enumerate(weeks):
            rows.append({"event": "e", "adm3_pcode": PCODE,
                         "origin_week": w - pd.Timedelta(weeks=h - 1), "horizon": h,
                         "target_week": w, "outbreak_prob": 0.1 * (i + h),
                         "alert_level": ["Normal", "Watch", None][i], "observed_cases": i,
                         "threshold": 1.0, "observed_outbreak": [False, True, pd.NA][i]})
    rain = pd.DataFrame({"adm3_pcode": PCODE, "week_start": weeks,
                         "rain_mm_7d": 1.0, "rain_mm_7d_late": [5.0, 6.0, 7.0]})
    season = {"event": "e", "city": PCODE, "from": str(weeks[0].date()),
              "to": str(weeks[1].date())}
    t = season_table(pd.DataFrame(rows), rain, season)
    assert len(t) == 2                                       # only the season's weeks
    assert t.rain_mm.tolist() == [5.0, 6.0]                  # IMERG Late, what the model used
    assert t.level_1.tolist() == ["Normal", "Watch"] and t.above.tolist() == [False, True]
    assert {"level_2", "p_2"} <= set(t.columns)
    assert season_table(pd.DataFrame(rows), rain, {**season, "event": "none"}).empty


def test_panel_window_follows_the_selection_within_the_season():
    weeks = list(pd.date_range(W0, periods=30, freq="7D"))
    assert panel_window(weeks, weeks[0]) == weeks[:12]                 # clamped at the start
    assert panel_window(weeks, weeks[15]) == weeks[9:21]               # centred
    assert panel_window(weeks, weeks[-1]) == weeks[-12:]               # clamped at the end
    assert panel_window(weeks[:5], weeks[2]) == weeks[:5]              # short season


# LEAD TIME ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def test_idle_flag_run_counts_only_weeks_without_an_outbreak():
    t = make_table(["Normal", "Watch", "Watch", "Warning", "Warning", "Warning"],
                   cases=[0, 0, 0, 5, 5, 0])
    week = t.week_start.iloc[5]
    # Back from week 5: week 4 and 3 are above the line (skipped), 2 and 1 are idle flags.
    assert idle_flag_run(t, week) == 2
    assert idle_flag_run(t, t.week_start.iloc[1]) == 0               # the week before is Normal


def test_lead_time_warned_background_and_missed():
    raised = make_table(["Normal", "Normal", "Watch", "Warning"], ["Normal", "Watch", "Warning",
                        "Warning"], cases=[0, 0, 0, 6])
    out = lead_time(raised, raised.week_start.iloc[3])
    assert out == {"outcome": "warned", "lead": 3, "horizon": 2, "run": 1}   # 2 weeks + 1 delay
    only_h1 = make_table(["Normal", "Watch"], cases=[0, 6])
    assert lead_time(only_h1, only_h1.week_start.iloc[1])["lead"] == 1 + config.CASES_REPORT_DELAY_WEEKS
    background = make_table(["Watch"] * 6, ["Watch"] * 6, cases=[0, 0, 0, 0, 0, 6])
    out = lead_time(background, background.week_start.iloc[5])
    assert out["outcome"] == "background" and out["lead"] is None and out["run"] == 5
    missed = make_table(["Normal"] * 3, cases=[0, 0, 6])
    assert lead_time(missed, missed.week_start.iloc[2])["outcome"] == "missed"


def test_outbreak_runs_split_at_gaps():
    t = make_table(["Normal"] * 7, cases=[5, 5, 0, 5, 0, 5, 5])
    assert [len(r) for r in outbreak_runs(t)] == [2, 1, 2]


# WHAT HAPPENED ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def test_what_happened_finds_every_entry_in_date_order():
    t = make_table(["Normal", "Normal", "Watch", "Warning", "Warning", "Watch"],
                   ["Normal", "Watch", "Warning", "Warning", "Warning", "Watch"],
                   cases=[0, 0, 4, 9, 3, 0], rain=[10, 300, 20, 10, 10, 10])
    entries, summary = what_happened(t, city_total_cases=100)
    rain = next(e for e in entries if e["kind"] == "rain")
    assert rain["week"] == t.week_start.iloc[1] and rain["facts"]["mm"] == 300
    assert rain["facts"]["heavy"]
    assert [e["week"] for e in entries] == sorted(e["week"] for e in entries)
    above = next(e for e in entries if e["kind"] == "above")
    assert above["week"] == t.week_start.iloc[2] and above["facts"]["cases"] == 4
    assert above["facts"]["levels"] == {1: "Watch", 2: "Warning"} and above["facts"]["lead"] == 3
    assert any(e["kind"] == "warning" and e["week"] == t.week_start.iloc[3] for e in entries)
    peak = next(e for e in entries if e["kind"] == "peak_cases")
    assert peak["facts"]["cases"] == 9 and peak["facts"]["times"] == pytest.approx(4.5)
    assert summary["outcome"] == "warned" and summary["lead"] == 3
    assert summary["above_weeks"] == 3 and summary["flagged_weeks"] == 3
    assert not any(e["kind"] == "size" for e in entries)       # 16 of 100 cases: not dominant


def test_size_note_only_when_the_data_supports_it():
    t = make_table(["Normal"] * 5, cases=[0, 40, 50, 0, 0])
    big = [e for e in what_happened(t, city_total_cases=100)[0] if e["kind"] == "size"]
    assert len(big) == 1 and big[0]["facts"]["share"] == pytest.approx(0.9)
    assert big[0]["facts"]["weeks"] == 2
    assert not [e for e in what_happened(t, city_total_cases=1000)[0] if e["kind"] == "size"]
    assert not [e for e in what_happened(t)[0] if e["kind"] == "size"]


def test_a_season_without_outbreak_weeks_still_works():
    t = make_table(["Normal"] * 4, cases=[0, 0, 0, 0], above=[False] * 4)
    entries, summary = what_happened(t)
    assert summary["outcome"] == "none" and not [e for e in entries if e["kind"] == "peak_cases"]
    assert summary_text(summary) == "No week was above the outbreak line in this outbreak event."


def test_season_starting_flagged_is_not_called_a_rise():
    t = make_table(["Watch", "Watch", "Normal"], cases=[0, 0, 0], above=[False] * 3)
    alert = next(e for e in what_happened(t)[0] if e["kind"] == "alert")
    assert alert["facts"]["already"] and "no rise to show" in entry_text(alert)[1]


# REAL DATA +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

@pytest.fixture(scope="module")
def real():
    replay, _ = load_part("replay")
    rain, _ = load_part("rain_imerg")
    cases, _ = load_part("cases")
    out = {}
    for s in config.REPLAY_SEASONS:
        t = season_table(replay, rain, s)
        total = cases[cases.adm3_pcode == s["city"]].cases.sum()
        out[s["event"]] = (t, *what_happened(t, total))
    return out


def test_real_seasons_are_in_design_order_and_cover_their_weeks(real):
    assert [s["event"] for s in config.REPLAY_SEASONS] == ["navotas", "washi", "iloilo"]
    assert [len(real[e][0]) for e in ("navotas", "washi", "iloilo")] == [13, 17, 104]
    for t, _, _ in real.values():
        assert t.week_start.is_monotonic_increasing and t.rain_mm.notna().all()


def test_navotas_2018_warned_with_lead_time_from_data(real):
    t, entries, summary = real["navotas"]
    by = {e["kind"]: e for e in entries}
    assert by["rain"]["week"] == pd.Timestamp("2018-06-10") and by["rain"]["facts"]["mm"] > 300
    assert by["above"]["week"] == pd.Timestamp("2018-06-17")
    assert by["above"]["facts"]["levels"] == {1: "Watch", 2: "Normal"}       # Watch, then Normal
    assert by["above"]["facts"]["lead"] == 1 + config.CASES_REPORT_DELAY_WEEKS
    assert by["largest"]["week"] == pd.Timestamp("2018-07-08")
    assert by["largest"]["facts"]["levels"] == {1: "Warning", 2: "Warning"}
    assert summary["outcome"] == "warned" and summary["lead"] == 3 and summary["horizon"] == 2
    assert by["peak_cases"]["facts"]["cases"] == 9 and "size" not in by


def test_washi_is_shown_as_a_miss(real):
    t, entries, summary = real["washi"]
    by = {e["kind"]: e for e in entries}
    peak = by["peak_cases"]
    assert peak["week"] == pd.Timestamp("2012-01-01") and peak["facts"]["cases"] == 554
    assert peak["facts"]["levels"] == {1: "Normal", 2: "Normal"}              # not foreseen
    assert "did not foresee it" in entry_text(peak)[1]
    assert summary["outcome"] == "background" and summary["lead"] is None
    assert summary["above_weeks"] == 5 and summary["flagged_weeks"] == 3
    assert "No lead time is claimed" in entry_text(by["above"])[1]
    assert by["size"]["facts"]["cases"] == 774 and by["size"]["facts"]["share"] > 0.7
    assert by["rain"]["facts"]["heavy"] is False                              # no extreme rain


def test_iloilo_largest_outbreak_was_missed_at_its_start(real):
    _, entries, summary = real["iloilo"]
    by = {e["kind"]: e for e in entries}
    assert by["largest"]["week"] == pd.Timestamp("2011-08-07")
    assert by["largest"]["facts"]["outcome"] == "missed"
    assert "missed at its start" in entry_text(by["largest"])[1]
    assert summary["outcome"] == "missed" and summary["largest_cases"] == 795
    assert by["above"]["facts"]["outcome"] == "warned"                        # the Jan 2011 one


def test_stage6_levels_match_the_modeling_teams_summary(real):
    # case_study_summary.csv: Navotas 11 of 12 outbreak weeks flagged at h1 in the full
    # window; our 13-week season has 9 above-line weeks, all flagged.
    t = real["navotas"][0]
    assert (t[t.above].level_1.isin(["Watch", "Warning"])).all()
    washi = real["washi"][0]
    assert washi[washi.above].level_1.isin(["Watch", "Warning"]).sum() == 3   # 0.6 of 5


# WORDING +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def test_span_formats_weeks():
    assert span(pd.Timestamp("2018-07-08")) == "Jul 8–14, 2018"
    assert span(pd.Timestamp("2018-12-30")) == "Dec 30, 2018–Jan 5, 2019"


def test_texts_take_numbers_from_data_and_never_overclaim(real):
    for _, entries, summary in real.values():
        texts = [entry_text(e) for e in entries] + [("", summary_text(summary))]
        for title, body in texts:
            assert body and "{" not in title + body
            assert not any(b in (title + body).lower() for b in BANNED)
    navotas = " ".join(b for _, b in (entry_text(e) for e in real["navotas"][1]))
    assert "330 mm" in navotas and "9 reported cases" in navotas
    assert "about 3 weeks before case reports" in summary_text(real["navotas"][2])
    assert "2 weeks ahead" not in summary_text(real["washi"][2])
    assert "3 of 5 weeks above the outbreak line were at Watch or Warning" in summary_text(
        real["washi"][2])
    assert "2011" in BEFORE_2014 or "2014" in BEFORE_2014
