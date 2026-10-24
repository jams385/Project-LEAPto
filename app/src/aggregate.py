"""Barangay-to-city rollups for rainfall, population, flood hazard and cases.

Every function here is pure: it takes DataFrames and returns DataFrames.
City membership always comes from location.csv (`brgy_to_city`), never from
slicing PSGC codes, because barangay codes do not share a city-code prefix
(e.g. Iloilo City barangays start PH0630221 and PH0630222).
"""

import pandas as pd

from src.weeks import align_cchain_labels, week_grid

# CONSTANTS ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

# Barangays left out of the rainfall average (no CHIRPS coverage; all-NA pr).
RAIN_EXCLUDED_BRGYS = frozenset({"PH097332095"})  # Tumalutab, Zamboanga City

LEPTO_DISEASE_NAME = "LEPTOSPIROSIS"


# LOOKUPS ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def brgy_to_city(location):
    """Build the barangay -> city lookup from location.csv.

    Parameters
    ----------
    location : pandas.DataFrame
        Raw location.csv. Needs adm4_pcode, adm4_en, adm3_pcode, adm3_en,
        adm2_en, adm1_en, brgy_total_area. The junk `Unnamed: 0` column is
        ignored.

    Returns
    -------
    pandas.DataFrame
        Columns adm4_pcode, brgy_name, adm3_pcode, city_name, province,
        region, brgy_area_km2; one row per barangay. Raises ValueError if a
        barangay appears twice.
    """
    out = location.rename(columns={"adm4_en": "brgy_name", "adm3_en": "city_name",
                                   "adm2_en": "province", "adm1_en": "region",
                                   "brgy_total_area": "brgy_area_km2"})
    out = out[["adm4_pcode", "brgy_name", "adm3_pcode", "city_name", "province", "region",
               "brgy_area_km2"]]
    if out.adm4_pcode.duplicated().any():
        raise ValueError("location.csv lists a barangay more than once")
    return out.reset_index(drop=True)


# RAINFALL +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def rain_partial_sums(chunk, lookup, excluded=RAIN_EXCLUDED_BRGYS):
    """Sum daily barangay rainfall per city for one chunk of the climate file.

    Designed for chunked reading: results from many chunks are combined with
    `combine_rain_partials`, so a city-day split across chunks is still exact.

    Parameters
    ----------
    chunk : pandas.DataFrame
        Rows of climate_atmosphere.csv with at least adm4_pcode, date, pr.
    lookup : pandas.DataFrame
        Output of `brgy_to_city`.
    excluded : set[str]
        Barangay codes to drop before averaging.

    Returns
    -------
    pandas.DataFrame
        Columns adm3_pcode, date (datetime64), pr_sum, n_brgy. Rows with NA
        rainfall or barangays missing from `lookup` are dropped. Empty input
        gives an empty frame with the same columns.
    """
    df = chunk.loc[~chunk.adm4_pcode.isin(excluded) & chunk.pr.notna(),
                   ["adm4_pcode", "date", "pr"]]
    df = df.merge(lookup[["adm4_pcode", "adm3_pcode"]], on="adm4_pcode", how="inner")
    out = (df.groupby(["adm3_pcode", "date"], as_index=False)
             .agg(pr_sum=("pr", "sum"), n_brgy=("pr", "size")))
    out["date"] = pd.to_datetime(out["date"])
    return out


def combine_rain_partials(partials):
    """Merge chunk partial sums into the city daily mean rainfall.

    Parameters
    ----------
    partials : list[pandas.DataFrame]
        Outputs of `rain_partial_sums`.

    Returns
    -------
    pandas.DataFrame
        Columns adm3_pcode, date, rain_mm (mean across barangays), n_brgy;
        sorted by city then date. Empty list gives an empty frame.
    """
    cols = ["adm3_pcode", "date", "rain_mm", "n_brgy"]
    if not partials:
        return pd.DataFrame(columns=cols)
    df = (pd.concat(partials, ignore_index=True)
            .groupby(["adm3_pcode", "date"], as_index=False)[["pr_sum", "n_brgy"]].sum())
    df["rain_mm"] = df.pr_sum / df.n_brgy
    return df[cols].sort_values(["adm3_pcode", "date"]).reset_index(drop=True)


def daily_to_weekly_rain(daily):
    """Sum city daily rainfall into DOH morbidity weeks (Sun-Sat).

    Parameters
    ----------
    daily : pandas.DataFrame
        Output of `combine_rain_partials` (adm3_pcode, date, rain_mm).

    Returns
    -------
    pandas.DataFrame
        Columns adm3_pcode, week_start, mw_year, mw_week, rain_mm, n_days.
        Weeks at either end of the record with fewer than 7 days are dropped so
        every weekly total is comparable. Empty input gives an empty frame.
    """
    cols = ["adm3_pcode", "week_start", "mw_year", "mw_week", "rain_mm", "n_days"]
    if daily.empty:
        return pd.DataFrame(columns=cols)
    df = daily.copy()
    df["week_start"] = df.date - pd.to_timedelta((df.date.dt.dayofweek + 1) % 7, unit="D")
    weekly = (df.groupby(["adm3_pcode", "week_start"], as_index=False)
                .agg(rain_mm=("rain_mm", "sum"), n_days=("rain_mm", "size")))
    weekly = weekly[weekly.n_days == 7]
    grid = week_grid(weekly.week_start.min(), weekly.week_start.max())
    return weekly.merge(grid, on="week_start", how="left")[cols].reset_index(drop=True)


# CASES ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def weekly_lepto_cases(pidsr, cities):
    """Extract weekly leptospirosis cases per city on the aligned MW calendar.

    Parameters
    ----------
    pidsr : pandas.DataFrame
        Raw disease_pidsr_totals.csv (date, adm3_pcode, disease_common_name,
        case_total). freq, uuid and source_* columns are ignored.
    cities : pandas.DataFrame
        One row per city with adm3_pcode and city_name.

    Returns
    -------
    pandas.DataFrame
        Columns adm3_pcode, city_name, week_start, mw_year, mw_week, cases
        (nullable Int64). Every city has every week from its first to last
        aligned week; weeks with no source row (week 53 of 2008/2014/2020)
        are <NA>, never 0. Raises ValueError if alignment produces duplicate
        city-weeks.
    """
    lep = pidsr.loc[pidsr.disease_common_name == LEPTO_DISEASE_NAME,
                    ["adm3_pcode", "date", "case_total"]].copy()
    lep["week_start"] = align_cchain_labels(lep.date)
    if lep.duplicated(["adm3_pcode", "week_start"]).any():
        raise ValueError("week alignment produced duplicate city-weeks")
    grid = week_grid(lep.week_start.min(), lep.week_start.max())
    full = cities[["adm3_pcode", "city_name"]].merge(grid, how="cross")
    out = full.merge(lep[["adm3_pcode", "week_start", "case_total"]],
                     on=["adm3_pcode", "week_start"], how="left")
    out = out.rename(columns={"case_total": "cases"})
    out["cases"] = out.cases.astype("Int64")
    return out.sort_values(["adm3_pcode", "week_start"]).reset_index(drop=True)


# POPULATION +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def city_population(worldpop, lookup, carry_forward_to=2022):
    """Sum WorldPop barangay population per city per year.

    Parameters
    ----------
    worldpop : pandas.DataFrame
        Raw worldpop_population.csv (adm4_pcode, date, pop_count_total).
    lookup : pandas.DataFrame
        Output of `brgy_to_city`.
    carry_forward_to : int
        Last year to fill by repeating the latest WorldPop year (2020).

    Returns
    -------
    pandas.DataFrame
        Columns adm3_pcode, year, population, carried_forward (bool). NA
        barangay counts (Barangay 21-A, Tacloban) are skipped in the sum, so
        that city's total is a slight undercount.
    """
    df = worldpop[["adm4_pcode", "date", "pop_count_total"]].merge(
        lookup[["adm4_pcode", "adm3_pcode"]], on="adm4_pcode", how="inner")
    df["year"] = pd.to_datetime(df.date).dt.year
    pop = (df.groupby(["adm3_pcode", "year"], as_index=False)
             .pop_count_total.sum(min_count=1)
             .rename(columns={"pop_count_total": "population"}))
    pop["carried_forward"] = False
    last = pop.year.max()
    extra = [pop[pop.year == last].assign(year=y, carried_forward=True)
             for y in range(last + 1, carry_forward_to + 1)]
    return (pd.concat([pop, *extra], ignore_index=True)
              .sort_values(["adm3_pcode", "year"]).reset_index(drop=True))


# FLOOD HAZARD +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def city_hazard(noah, lookup):
    """Area-weight Project NOAH barangay hazard shares up to the city.

    Parameters
    ----------
    noah : pandas.DataFrame
        Raw project_noah_hazards.csv; hazard columns start `pct_area_` and are
        percentages (0-100) of each barangay's area.
    lookup : pandas.DataFrame
        Output of `brgy_to_city` (supplies brgy_area_km2 as the weight).

    Returns
    -------
    pandas.DataFrame
        One row per city: adm3_pcode plus every pct_area_* column, now the
        percentage of the whole city's area (0-100).
    """
    pct_cols = [c for c in noah.columns if c.startswith("pct_area_")]
    df = noah[["adm4_pcode", *pct_cols]].merge(
        lookup[["adm4_pcode", "adm3_pcode", "brgy_area_km2"]], on="adm4_pcode", how="inner")
    weighted = df[pct_cols].mul(df.brgy_area_km2, axis=0)
    weighted["adm3_pcode"] = df.adm3_pcode
    weighted["brgy_area_km2"] = df.brgy_area_km2
    sums = weighted.groupby("adm3_pcode").sum()
    out = sums[pct_cols].div(sums.brgy_area_km2, axis=0)
    return out.reset_index()


def barangay_flood_rank(noah, lookup, column="pct_area_flood_hazard_100yr_high"):
    """Rank each city's barangays by their share of high flood-hazard area.

    Used for the city panel's "Flood-prone barangays" list: where to focus
    advisories and doxycycline PEP first.

    Parameters
    ----------
    noah : pandas.DataFrame
        Raw project_noah_hazards.csv (adm4_pcode + pct_area_* columns, 0-100).
    lookup : pandas.DataFrame
        Output of `brgy_to_city` (brgy_name, adm3_pcode, brgy_area_km2).
    column : str
        Hazard column to rank by (default: 100-year flood, high hazard).

    Returns
    -------
    pandas.DataFrame
        adm3_pcode, rank (1 = most flood-prone in its city), adm4_pcode,
        brgy_name, high_hazard_pct (0-100, 2 decimals), high_hazard_km2
        (share x barangay area). Ties are broken by the larger hazard area,
        then by name. Barangays without a hazard value are left out.
    """
    df = noah[["adm4_pcode", column]].merge(
        lookup[["adm4_pcode", "brgy_name", "adm3_pcode", "brgy_area_km2"]],
        on="adm4_pcode", how="inner").dropna(subset=[column])
    df = df.assign(high_hazard_pct=df[column].round(2),
                   high_hazard_km2=(df[column] / 100 * df.brgy_area_km2).round(3))
    df = df.sort_values(["adm3_pcode", "high_hazard_pct", "high_hazard_km2", "brgy_name"],
                        ascending=[True, False, False, True])
    df["rank"] = df.groupby("adm3_pcode").cumcount() + 1
    return df[["adm3_pcode", "rank", "adm4_pcode", "brgy_name", "high_hazard_pct",
               "high_hazard_km2"]].reset_index(drop=True)
