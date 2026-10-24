"""City-drawer charts: the mini rain -> risk chart (6 weeks + forecast slots
with a level strip), and in "More details" the larger rain -> risk timeline
and reported cases vs the outbreak line."""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from app import config
from app.components.hover import style_hover
from app.components.ui import fmt_span

INK = "#0F2740"
MUTED = "#8A99A8"
RAIN = "#4FB3E6"
HEAVY_RAIN = "#1F5F8B"
FORECAST_BG = "#EEF3F8"
THRESHOLD = "#E04848"


# MINI RAIN -> RISK (drawer) ++++++++++++++++++++++++++++++++++++++++++++++++++

LEVEL_STRIP_EMPTY = "#E3E9EF"


def mini_risk_figure(timeline):
    """The drawer's "Rain and risk" chart: past weeks + forecast slots.

    Parameters
    ----------
    timeline : pandas.DataFrame
        src.views.risk_timeline output (past rows with rain_mm, heavy and the
        level shown that week; future rows with the forecast level).

    Returns
    -------
    plotly.graph_objects.Figure
        Top row: OBSERVED weekly rain bars (this city's heavy-rain weeks
        darker); forecast weeks are dashed empty slots, since their rain is
        not known yet. Bottom row: a level strip, one block per week in the
        level's colour; forecast blocks are outlined. Weeks are evenly spaced
        and labelled by their first day. An empty timeline gives an empty
        figure of the same size.
    """
    t = timeline.reset_index(drop=True)
    x = list(range(len(t)))
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.78, 0.22],
                        vertical_spacing=0.06)
    past = t[~t.is_future]
    rain = past.rain_mm.fillna(0)
    fig.add_trace(go.Bar(
        x=past.index, y=rain, marker_color=np.where(past.heavy, HEAVY_RAIN, RAIN),
        customdata=[fmt_span(w, year=False) for w in past.week_start],
        hovertemplate="<b>Week of %{customdata}</b><br>%{y:.0f} mm of rain (NASA IMERG)<extra></extra>",
        name="Rain"), row=1, col=1)
    top = max(float(rain.max()) if not rain.empty else 0, 1.0) * 1.12
    for i in t.index[t.is_future]:
        fig.add_shape(type="rect", x0=i - 0.4, x1=i + 0.4, y0=0, y1=top, xref="x", yref="y",
                      line=dict(color="#9AABBD", width=1, dash="dash"),
                      fillcolor="#F6F8FA", layer="below")
    colors = [config.LEVEL_COLORS.get(lvl, LEVEL_STRIP_EMPTY) for lvl in t.alert_level]
    names = [lvl if isinstance(lvl, str) else "No forecast" for lvl in t.alert_level]
    when = [("Forecast for the week of " if f else "Week of ") + fmt_span(w, year=False)
            for f, w in zip(t.is_future, t.week_start)]
    fig.add_trace(go.Bar(
        x=x, y=[1] * len(t), marker=dict(
            color=colors,
            line=dict(color=[INK if f else "#FFFFFF" for f in t.is_future],
                      width=[2 if f else 0 for f in t.is_future])),
        customdata=np.stack([when, names], axis=1) if len(t) else None,
        hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]}<extra></extra>",
        name="Level"), row=2, col=1)
    fig.update_yaxes(visible=False, row=2, col=1, range=[0, 1])
    fig.update_yaxes(visible=False, row=1, col=1, range=[0, top])
    fig.update_xaxes(tickmode="array", tickvals=x,
                     ticktext=[f"{w:%b} {w.day}" for w in t.week_start],
                     tickfont=dict(size=10, color=MUTED), showgrid=False,
                     range=[-0.6, len(t) - 0.4], row=2, col=1)
    fig.update_xaxes(showgrid=False, row=1, col=1)
    fig.update_layout(
        height=170, margin=dict(l=4, r=4, t=4, b=22), paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF", font=dict(family="Inter", size=11, color=INK),
        bargap=0.18, showlegend=False, hovermode="closest")
    return style_hover(fig)


# RAIN -> RISK ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def rain_risk_figure(timeline, heavy_mm):
    """Last weeks of IMERG rain (bars) and expected risk for weeks 1-3 (line).

    Parameters
    ----------
    timeline : pandas.DataFrame
        src.views.risk_timeline output.
    heavy_mm : float
        The city's heavy-rain week (wettest 5%); drawn as a dashed line and
        used to darken heavy bars. NaN hides the line.

    Returns
    -------
    plotly.graph_objects.Figure
        Rain on the left axis (mm/week); the multiplier on the right axis
        ("× usual risk", dotted 1× = a usual week), markers coloured by level.
        When no week has a multiplier (e.g. a low-data city) the line is
        replaced by a note.
    """
    past = timeline[~timeline.is_future]
    ahead = timeline[timeline.is_future]
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(go.Bar(
        x=past.week_start, y=past.rain_mm, name="Rain (mm/week)",
        marker_color=np.where(past.heavy, HEAVY_RAIN, RAIN),
        hovertemplate="<b>Week of %{x|%b %-d}</b><br>%{y:.0f} mm of rain<extra></extra>"),
        secondary_y=False)
    if not ahead.empty:
        half = pd.Timedelta(days=3.5)
        fig.add_vrect(x0=ahead.week_start.min() - half, x1=ahead.week_start.max() + half,
                      fillcolor=FORECAST_BG, line_width=0, layer="below")
        fig.add_annotation(x=ahead.week_start.mean(), y=1.08, yref="paper",
                           text="Forecast", showarrow=False,
                           font=dict(size=10, color=MUTED))
    if not np.isnan(heavy_mm) and not past.empty:
        fig.add_shape(type="line", x0=past.week_start.min() - pd.Timedelta(days=3.5),
                      x1=past.week_start.max() + pd.Timedelta(days=3.5), y0=heavy_mm,
                      y1=heavy_mm, line=dict(color=HEAVY_RAIN, width=1, dash="dash"),
                      yref="y")
        fig.add_annotation(x=past.week_start.min(), y=heavy_mm, yref="y", xanchor="left",
                           yanchor="bottom", text=f"heavy-rain week ({heavy_mm:.0f} mm)",
                           showarrow=False, font=dict(size=9, color=HEAVY_RAIN),
                           bgcolor="rgba(255,255,255,0.85)")

    shown = ahead.dropna(subset=["multiplier"])
    shown = shown[shown.alert_level.isin(config.ALERT_LEVELS)]
    if shown.empty:
        note = ("Too few cases here<br>to forecast a level"
                if (ahead.alert_level == config.CASE_SIGNAL_LEVEL).any()
                else "No forecast for<br>these weeks")
        fig.add_annotation(x=0.98, y=0.55, xref="paper", yref="paper", xanchor="right",
                           text=note, showarrow=False, font=dict(size=10, color=MUTED))
        top = 3.0
    else:
        mult = shown.multiplier.clip(upper=config.MAX_RR_SHOWN)
        fig.add_trace(go.Scatter(
            x=shown.week_start, y=mult, mode="lines+markers+text", name="× usual risk",
            line=dict(color=INK, width=2),
            marker=dict(size=12, color=[config.LEVEL_COLORS[lvl] for lvl in shown.alert_level],
                        line=dict(color="#FFFFFF", width=1.5)),
            text=[f"{m:.1f}×" if m < 1.95 else f"{m:.0f}×" for m in mult],
            textposition="top center", textfont=dict(size=11, color=INK),
            customdata=np.stack([[config.HORIZON_NAMES.get(h, f"In {h} weeks")
                                  for h in shown.horizon.astype(int)], shown.alert_level],
                                axis=1),
            hovertemplate=("<b>%{customdata[0]}</b> (week of %{x|%b %-d})"
                           "<br>%{customdata[1]}: ≈%{y:.1f}× a usual week<extra></extra>")),
            secondary_y=True)
        top = max(3.0, float(mult.max()) * 1.35)
        fig.add_hline(y=1, line=dict(color=MUTED, width=1, dash="dot"), secondary_y=True)
        fig.add_annotation(x=ahead.week_start.min() - pd.Timedelta(days=3), y=1, yref="y2",
                           xanchor="left", yanchor="bottom", text="usual", showarrow=False,
                           font=dict(size=9, color=MUTED))

    fig.update_yaxes(title_text="rain, mm", secondary_y=False, rangemode="tozero",
                     gridcolor="#EDF1F5", title_font=dict(size=10), zeroline=False)
    step = 1 if top <= 4 else 2 if top <= 8 else 5
    fig.update_yaxes(title_text="× usual risk", secondary_y=True, range=[0, top],
                     tick0=0, dtick=step, ticksuffix="×", showgrid=False,
                     title_font=dict(size=10), zeroline=False)
    fig.update_xaxes(showgrid=False, tickformat="%b %d", nticks=6)
    fig.update_layout(
        height=230, margin=dict(l=44, r=44, t=24, b=28), paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF", font=dict(family="Inter", size=11, color=INK),
        bargap=0.25, showlegend=False, hovermode="closest")
    return style_hover(fig)


# REPORTED CASES +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def rainfall_cases_figure(series, origin_week, show_rain=True):
    """Reported cases vs the outbreak line, optionally under weekly IMERG rain.

    Parameters
    ----------
    series : pandas.DataFrame
        src.views.city_timeseries output.
    origin_week : Timestamp
        Forecast origin; drawn as a vertical "Forecast from" line.
    show_rain : bool
        Add the rainfall bars as a top panel (False: cases only, used in the
        city details "Reported cases vs outbreak line" section).

    Returns
    -------
    plotly.graph_objects.Figure
        OBSERVED reported cases (solid before the origin, dotted "reported
        later" from it) and the outbreak line (dashed red). No predicted case
        counts are drawn.
    """
    hist = series[~series.is_future]
    later = series[series.is_future]
    rows = 2 if show_rain else 1
    case_row = rows

    fig = make_subplots(rows=rows, cols=1, shared_xaxes=True,
                        row_heights=[0.36, 0.64] if show_rain else None,
                        vertical_spacing=0.08)
    if show_rain:
        fig.add_trace(go.Bar(x=series.week_start, y=series.rain_mm, marker_color=RAIN,
                             name="Rainfall (mm/week)",
                             hovertemplate="Rain: %{y:.0f} mm<extra></extra>"),
                      row=1, col=1)
        fig.update_yaxes(title_text="mm", row=1, col=1, title_font=dict(size=10))
    fig.add_trace(go.Scatter(x=series.week_start, y=series.threshold,
                             mode="lines", line=dict(color=THRESHOLD, width=1.5, dash="dash",
                                                     shape="hv"),
                             name="Outbreak line",
                             hovertemplate="Outbreak line: more than %{y:.0f} cases<extra></extra>"),
                  row=case_row, col=1)
    fig.add_trace(go.Scatter(x=hist.week_start, y=hist.cases, mode="lines+markers",
                             line=dict(color=INK, width=2), marker=dict(size=4),
                             name="Reported cases",
                             hovertemplate="Reported cases: %{y:.0f}<extra></extra>"),
                  row=case_row, col=1)
    if later.cases.notna().any():
        fig.add_trace(go.Scatter(x=later.week_start, y=later.cases, mode="lines+markers",
                                 line=dict(color=MUTED, width=1.5, dash="dot"),
                                 marker=dict(size=4), name="Reported later",
                                 hovertemplate="Reported later: %{y:.0f} cases<extra></extra>"),
                      row=case_row, col=1)

    for row in range(1, rows + 1):
        fig.add_vline(x=origin_week, line=dict(color=MUTED, width=1, dash="dot"), row=row, col=1)
    fig.add_annotation(x=origin_week, y=1.02, yref="paper", text="Forecast from",
                       showarrow=False, font=dict(size=10, color=MUTED), xanchor="left")
    fig.update_yaxes(title_text="reported cases", row=case_row, col=1, rangemode="tozero",
                     title_font=dict(size=10))
    fig.update_xaxes(showgrid=False, tickformat="%b %Y", nticks=4, hoverformat="%b %-d, %Y")
    fig.update_yaxes(gridcolor="#EDF1F5", zeroline=False)
    fig.update_layout(
        height=300 if show_rain else 210, margin=dict(l=46, r=10, t=20, b=34),
        paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
        font=dict(family="Inter", size=11, color=INK),
        bargap=0.15, hovermode="x unified", showlegend=False)
    return style_hover(fig)


# REPLAY PANELS +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def replay_panels_figure(window, selected):
    """Three aligned panels on one time axis: rain, reported cases, level shown.

    Parameters
    ----------
    window : pandas.DataFrame
        The weeks to draw (src.replay.season_table rows: week_start, rain_mm,
        cases, threshold, above, level_1).
    selected : pandas.Timestamp
        The forecast week being shown; it is outlined in every panel, and the
        weeks after it are faded (the model could not know them yet).

    Returns
    -------
    plotly.graph_objects.Figure
        Top: IMERG rain (mm; darker from config.REPLAY_HEAVY_RAIN_MM).
        Middle: reported cases (red above the outbreak line, dashed line =
        the line). Bottom: the level the app would have shown, one block per
        week, "No forecast" in grey. Empty window gives an empty figure.
    """
    w = window.reset_index(drop=True)
    x = list(range(len(w)))
    sel = int(w.index[w.week_start == pd.Timestamp(selected)][0]) if (
        w.week_start == pd.Timestamp(selected)).any() else None
    fade = [0.35 if sel is not None and i > sel else 1.0 for i in x]
    names = [f"<b>Week of {d:%b} {d.day}</b>" for d in w.week_start]
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, row_heights=[0.42, 0.42, 0.16],
                        vertical_spacing=0.1,
                        subplot_titles=("Rain (mm per week, NASA IMERG)",
                                        "Reported cases (red = above the outbreak line)",
                                        "Level the app would have shown"))
    rain = w.rain_mm.fillna(0)
    fig.add_trace(go.Bar(
        x=x, y=rain, customdata=names, text=[f"{v:.0f}" for v in rain], textposition="outside",
        textfont=dict(size=10, color=MUTED), cliponaxis=False,
        marker=dict(color=[HEAVY_RAIN if v >= config.REPLAY_HEAVY_RAIN_MM else RAIN for v in rain],
                    opacity=fade),
        hovertemplate="%{customdata}<br>%{y:.0f} mm of rain<extra></extra>"), row=1, col=1)
    fig.add_trace(go.Bar(
        x=x, y=w.cases.fillna(0), customdata=names, textposition="outside",
        text=[f"{v:.0f}" for v in w.cases.fillna(0)], textfont=dict(size=10, color=MUTED),
        cliponaxis=False,
        marker=dict(color=[THRESHOLD if a else INK for a in w.above], opacity=fade),
        hovertemplate="%{customdata}<br>%{y:.0f} reported cases<extra></extra>"), row=2, col=1)
    line = w.dropna(subset=["threshold"])
    if not line.empty:
        fig.add_trace(go.Scatter(
            x=[x[i] for i in line.index], y=line.threshold, mode="lines",
            line=dict(color=THRESHOLD, width=1.5, dash="dash", shape="hv"),
            hovertemplate="Outbreak line: more than %{y:.0f} cases<extra></extra>"), row=2, col=1)
    colors = [config.LEVEL_COLORS.get(lv, config.LEVEL_COLORS[config.NO_FORECAST_LEVEL])
              for lv in w.level_1]
    shown = [lv or config.NO_FORECAST_LEVEL for lv in w.level_1]
    chance = ["" if pd.isna(p) else f"<br>{p:.0%} chance of an outbreak week" for p in w.p_1]
    fig.add_trace(go.Bar(
        x=x, y=[1] * len(w), marker=dict(color=colors, opacity=fade),
        customdata=[f"{n}<br>{s}{c}" for n, s, c in zip(names, shown, chance)],
        hovertemplate="%{customdata}<extra></extra>"), row=3, col=1)
    if sel is not None:
        for row in (1, 2, 3):
            fig.add_vrect(x0=sel - 0.5, x1=sel + 0.5, row=row, col=1, fillcolor="#4FB3E6",
                          opacity=0.14, line=dict(color=INK, width=2), layer="below")
    fig.update_yaxes(visible=False, row=3, col=1, range=[0, 1])
    fig.update_yaxes(rangemode="tozero", gridcolor="#EDF1F5", zeroline=False, row=1, col=1)
    fig.update_yaxes(rangemode="tozero", gridcolor="#EDF1F5", zeroline=False, row=2, col=1)
    fig.update_xaxes(showgrid=False, tickmode="array", tickvals=x,
                     ticktext=[f"{d:%b} {d.day}" for d in w.week_start],
                     tickfont=dict(size=10, color=MUTED), range=[-0.6, len(w) - 0.4])
    fig.update_annotations(font=dict(size=12, color=INK), xanchor="left", x=0)
    fig.update_layout(height=520, margin=dict(l=40, r=10, t=26, b=26), bargap=0.2,
                      paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF", showlegend=False,
                      font=dict(family="Inter", size=11, color=INK), hovermode="closest")
    return style_hover(fig)
