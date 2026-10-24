""""Compare all cities": a collapsed section under the Overview (DESIGN_V3).

The expander title is followed by a one-line description (config.COMPARE_LABEL).
Inside: a small chance-by-city chart with a plain caption, then what used to
be the "All cities" tab: one table with the numbers
behind every city (level, ≈N× a usual week, chance of an outbreak week,
the latest reported cases and the outbreak line, IMERG rain vs usual, high
flood-hazard share, confidence). The table is read-only. The map layers moved
to the map's "Map options" menu.
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app import config
from app.components.hover import style_hover
from app.components.ui import fmt_day
from app.data import level_text
from src.views import usual_week_text

# TABLE ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def cities_table(snap, base_rate):
    """One display row per city, most urgent first.

    Parameters
    ----------
    snap : pandas.DataFrame
        Current src.views snapshot.
    base_rate : float | None
        Share of all city-weeks that are outbreak weeks (for ≈N×).

    Returns
    -------
    pandas.DataFrame
        Columns City, Level, vs a usual week, Chance (%), Cases (latest
        week), Unusual at, Rain last week (mm), Rain vs usual, High
        flood-hazard area (%), Confidence, plus adm3_pcode (hidden). Sorted
        by level then chance; missing values stay empty.
    """
    order = {lvl: i for i, lvl in enumerate(config.DISPLAY_LEVELS)}
    s = snap.assign(_o=snap.alert_level.map(order)).sort_values(
        ["_o", "outbreak_prob", "city_name"], ascending=[True, False, True])
    return pd.DataFrame({
        "adm3_pcode": s.adm3_pcode,
        "City": s.city_name,
        "Level": s.alert_level,
        "vs a usual week": [usual_week_text(lvl, p, base_rate) or "–"
                            for lvl, p in zip(s.alert_level, s.outbreak_prob)],
        "Chance (%)": (s.outbreak_prob * 100).round(0),
        "Cases (latest week)": s.latest_cases,
        "Unusual at": s.unusual_at,
        "Rain last week (mm)": s.rain_week_mm.round(0),
        "Rain vs usual": s.rain_status,
        "High flood-hazard area (%)": s.hazard_pct.round(0),
        "Confidence": s.confidence.map(config.CONFIDENCE_NOTES),
    }).reset_index(drop=True)


def chance_figure(table):
    """Small bar chart: forecast chance of an outbreak week for each city.

    Parameters
    ----------
    table : pandas.DataFrame
        cities_table output (City, Level, Chance (%)), most urgent first.

    Returns
    -------
    plotly.graph_objects.Figure | None
        One bar per city with a chance, coloured by alert level, the first
        city of the table at the top. None when no city has a chance.
    """
    shown = table[table["Chance (%)"].notna()].iloc[::-1]
    if shown.empty:
        return None
    fig = go.Figure(go.Bar(
        x=shown["Chance (%)"], y=shown.City, orientation="h",
        marker_color=[config.LEVEL_COLORS.get(lvl, "#8FA3B8") for lvl in shown.Level],
        text=[f"{v:.0f}%" for v in shown["Chance (%)"]], textposition="outside",
        cliponaxis=False, customdata=shown.Level,
        hovertemplate=("<b>%{y}</b><br>%{customdata}<br>%{x:.0f}% chance of an outbreak week"
                       "<extra></extra>")))
    fig.update_layout(
        height=26 * len(shown) + 36, margin=dict(l=0, r=40, t=4, b=4), bargap=0.35,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter", color="#E8EEF5", size=12),
        xaxis=dict(visible=False, range=[0, max(shown["Chance (%)"].max() * 1.2, 5)],
                   fixedrange=True),
        yaxis=dict(fixedrange=True, automargin=True))
    return style_hover(fig)


# RENDER +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def render_compare(snap, horizon):
    """Draw the collapsed "Compare all cities" section.

    Parameters
    ----------
    snap : pandas.DataFrame
    horizon : int

    Returns
    -------
    None. The table is read-only: no row selection and no download.
    """
    base = level_text(horizon)["Warning"]["base_rate"]
    table = cities_table(snap, base)
    cases_week = snap.cases_week.iloc[0] if not snap.empty else None
    with st.expander(config.COMPARE_LABEL, key="compare"):
        st.html('<div class="leap-xp-h">Chance of an outbreak week, by city</div>'
                '<div class="leap-xp-cap">Each bar is the forecast chance that the week is an '
                'outbreak week, coloured by alert level. Cities with no forecast this week are '
                'left out.</div>')
        fig = chance_figure(table)
        if fig is not None:
            st.plotly_chart(fig, key="compare_chart", theme=None,
                            config={"displayModeBar": False})
        st.html('<div class="leap-xp-h">Every number, city by city</div>'
                '<div class="leap-xp-cap">"Chance" and "vs a usual week" are FORECASTS; '
                'cases and rain are OBSERVED. Cases are the latest reported week'
                + (f" (from {fmt_day(cases_week)})" if cases_week is not None else "")
                + '.</div>')
        st.dataframe(
            table, hide_index=True, key="cities_table",
            height=(len(table) + 1) * 35 + 3,  # every city visible, no inner scroll
            column_order=[c for c in table.columns if c != "adm3_pcode"],
            column_config={
                "Chance (%)": st.column_config.NumberColumn(
                    format="%d%%", help="FORECAST: chance that the week is an outbreak week"),
                "vs a usual week": st.column_config.TextColumn(
                    help="FORECAST: chance compared with a usual week (about 7% of weeks)"),
                "Cases (latest week)": st.column_config.NumberColumn(
                    format="%d", help="OBSERVED: reported cases, DOH PIDSR"),
                "Unusual at": st.column_config.NumberColumn(
                    format="%d", help="Cases in a week above the DOH epidemic threshold"),
                "Rain last week (mm)": st.column_config.NumberColumn(
                    format="%d", help="OBSERVED: NASA IMERG"),
                "High flood-hazard area (%)": st.column_config.NumberColumn(
                    format="%d%%", help="Project NOAH, 100-year flood"),
            })
