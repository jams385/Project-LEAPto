"""Tests for src/aggregate.py using small hand-built frames (no raw files)."""

import pandas as pd
import pytest

from src.aggregate import (barangay_flood_rank, brgy_to_city, city_hazard, city_population,
                           combine_rain_partials, daily_to_weekly_rain,
                           rain_partial_sums, weekly_lepto_cases)


# FIXTURES +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

@pytest.fixture
def lookup():
    loc = pd.DataFrame({
        "Unnamed: 0": [0, 1, 2],
        "adm1_en": ["R", "R", "R"],
        "adm2_en": ["P", "P", "P"],
        "adm3_en": ["City A", "City A", "City B"],
        "adm3_pcode": ["PH000001000", "PH000001000", "PH000002000"],
        "adm4_en": ["a1", "a2", "b1"],
        "adm4_pcode": ["PH000001001", "PH000001102", "PH000002001"],
        "brgy_total_area": [1.0, 3.0, 2.0],
    })
    return brgy_to_city(loc)


# LOOKUPS ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def test_brgy_to_city_columns(lookup):
    assert list(lookup.columns) == ["adm4_pcode", "brgy_name", "adm3_pcode", "city_name",
                                    "province", "region", "brgy_area_km2"]


def test_brgy_to_city_rejects_duplicates(lookup):
    loc = pd.DataFrame({"adm4_pcode": ["x", "x"], "adm4_en": ["n", "n"],
                        "adm3_pcode": ["c", "c"],
                        "adm3_en": ["C", "C"], "adm2_en": ["P", "P"],
                        "adm1_en": ["R", "R"], "brgy_total_area": [1, 1]})
    with pytest.raises(ValueError):
        brgy_to_city(loc)


# RAINFALL +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def test_rain_mean_is_exact_across_chunks(lookup):
    day = "2020-01-05"
    chunk1 = pd.DataFrame({"adm4_pcode": ["PH000001001"], "date": [day], "pr": [10.0]})
    chunk2 = pd.DataFrame({"adm4_pcode": ["PH000001102", "PH000002001"],
                           "date": [day, day], "pr": [20.0, 5.0]})
    daily = combine_rain_partials([rain_partial_sums(chunk1, lookup),
                                   rain_partial_sums(chunk2, lookup)])
    got = dict(zip(daily.adm3_pcode, daily.rain_mm))
    assert got == {"PH000001000": 15.0, "PH000002000": 5.0}


def test_rain_excludes_listed_and_na_barangays(lookup):
    chunk = pd.DataFrame({"adm4_pcode": ["PH000001001", "PH000001102"],
                          "date": ["2020-01-05"] * 2, "pr": [10.0, None]})
    daily = combine_rain_partials([rain_partial_sums(chunk, lookup)])
    assert daily.rain_mm.tolist() == [10.0] and daily.n_brgy.tolist() == [1]
    out = rain_partial_sums(chunk, lookup, excluded={"PH000001001"})
    assert out.empty


def test_combine_empty():
    assert combine_rain_partials([]).empty


def test_daily_to_weekly_sums_sun_to_sat_and_drops_partial_weeks():
    dates = pd.date_range("2020-01-01", "2020-01-18")  # Wed .. Sat
    daily = pd.DataFrame({"adm3_pcode": "C", "date": dates, "rain_mm": 1.0})
    weekly = daily_to_weekly_rain(daily)
    # Partial week starting Sun 2019-12-29 (only Wed-Sat present) is dropped.
    assert weekly.week_start.dt.strftime("%Y-%m-%d").tolist() == ["2020-01-05", "2020-01-12"]
    assert weekly.rain_mm.tolist() == [7.0, 7.0]
    assert weekly.mw_week.tolist() == [2, 3]  # 2020 MW1 starts Sun 2019-12-29


# CASES ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def test_weekly_lepto_cases_aligns_and_marks_wk53_na():
    cities = pd.DataFrame({"adm3_pcode": ["C1"], "city_name": ["City 1"]})
    labels = ["2008-12-22", "2008-12-29", "2009-01-05"]  # 2008 labels shift back 8
    pidsr = pd.DataFrame({
        "date": labels + ["2009-01-05"],
        "adm3_pcode": ["C1"] * 4,
        "disease_common_name": ["LEPTOSPIROSIS"] * 3 + ["DENGUE FEVER"],
        "case_total": [1, 2, 0, 99],
    })
    out = weekly_lepto_cases(pidsr, cities)
    assert out.week_start.dt.strftime("%Y-%m-%d").tolist() == [
        "2008-12-14", "2008-12-21", "2008-12-28", "2009-01-04"]
    assert out.cases.tolist()[:2] == [1, 2]
    assert out.cases.isna().tolist() == [False, False, True, False]
    assert out.cases.iloc[3] == 0  # zero stays zero, not NA
    assert (out.mw_year.iloc[2], out.mw_week.iloc[2]) == (2008, 53)


# POPULATION AND HAZARD ++++++++++++++++++++++++++++++++++++++++++++++++++++++

def test_city_population_sums_and_carries_forward(lookup):
    wp = pd.DataFrame({
        "adm4_pcode": ["PH000001001", "PH000001102", "PH000002001"] * 2,
        "date": ["2019-01-01"] * 3 + ["2020-01-01"] * 3,
        "pop_count_total": [1, 2, 10, 2, None, 20],
    })
    pop = city_population(wp, lookup, carry_forward_to=2022)
    a = pop[pop.adm3_pcode == "PH000001000"].set_index("year")
    assert a.population.to_dict() == {2019: 3, 2020: 2, 2021: 2, 2022: 2}
    assert a.carried_forward.to_dict() == {2019: False, 2020: False, 2021: True, 2022: True}


def test_city_hazard_is_area_weighted(lookup):
    noah = pd.DataFrame({"adm4_pcode": ["PH000001001", "PH000001102", "PH000002001"],
                         "pct_area_flood_hazard_5yr_high": [100.0, 0.0, 50.0]})
    out = city_hazard(noah, lookup).set_index("adm3_pcode")
    # City A: (100*1 + 0*3) / 4 = 25
    assert out.loc["PH000001000", "pct_area_flood_hazard_5yr_high"] == 25.0
    assert out.loc["PH000002000", "pct_area_flood_hazard_5yr_high"] == 50.0


def test_barangay_flood_rank_orders_within_city(lookup):
    noah = pd.DataFrame({"adm4_pcode": ["PH000001001", "PH000001102", "PH000002001",
                                        "PH999999999"],
                         "pct_area_flood_hazard_100yr_high": [10.0, 10.0, 0.0, 90.0]})
    out = barangay_flood_rank(noah, lookup)
    assert len(out) == 3                                   # unknown barangay dropped
    city_a = out[out.adm3_pcode == "PH000001000"]
    # Tie on share (10%): the bigger barangay (a2, 3 km2) ranks first.
    assert city_a.brgy_name.tolist() == ["a2", "a1"] and city_a["rank"].tolist() == [1, 2]
    assert city_a.high_hazard_km2.tolist() == [0.3, 0.1]
    assert out[out.adm3_pcode == "PH000002000"]["rank"].tolist() == [1]
