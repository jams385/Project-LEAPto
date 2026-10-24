"""Map legend. Risk: the alert-level colours (Warning, Watch, Normal, Case signal
only, plus "No report" / "No forecast" only in weeks that have them). Rainfall
and Flood hazard: a colour ramp with its lowest and highest value."""

import numpy as np
import streamlit as st

from app import config
from app.components.ui import esc

# Levels always listed; the other display states only when present.
ALWAYS_SHOWN = ("Warning", "Watch", "Normal", config.CASE_SIGNAL_LEVEL)


# COLOUR KEY +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def legend_levels(snap):
    """The levels the legend lists, in display order.

    Parameters
    ----------
    snap : pandas.DataFrame
        Current snapshot (alert_level).

    Returns
    -------
    list[str]
        ALWAYS_SHOWN, plus No report / No forecast when a city shows them.
    """
    shown = set(snap.alert_level)
    return [lvl for lvl in config.DISPLAY_LEVELS if lvl in ALWAYS_SHOWN or lvl in shown]


def _gradient_css(scale):
    """CSS linear-gradient for a Plotly colourscale.

    Parameters
    ----------
    scale : list[list[float, str]]

    Returns
    -------
    str
    """
    stops = ", ".join(f"{c} {p * 100:.0f}%" for p, c in scale)
    return f"linear-gradient(90deg, {stops})"


def key_html(snap, layer):
    """Colour key HTML for the active layer.

    Parameters
    ----------
    snap : pandas.DataFrame
        Current snapshot (for the levels shown, and the lowest and highest
        value of the Rainfall / Flood hazard layers).
    layer : str
        One of config.MAP_LAYERS.

    Returns
    -------
    str
        Risk: one swatch per level. Rainfall / Flood hazard: a titled colour
        ramp with the lowest and highest value shown.
    """
    if layer == "Risk":
        items = []
        for lvl in legend_levels(snap):
            hatch = ' class="leap-hatch"' if lvl == config.NO_REPORT_LEVEL else ""
            items.append(f'<span class="leap-key-level"><i{hatch} '
                         f'style="--level:{config.LEVEL_COLORS[lvl]}"></i>{esc(lvl)}</span>')
        return f'<div class="leap-key-levels leap-key-col">{"".join(items)}</div>'
    if layer == "Rainfall":
        values, scale = snap.rain_week_mm, config.RAINFALL_COLORSCALE
        title, unit = "Rain last week (NASA IMERG)", " mm"
    else:
        values, scale = snap.hazard_pct, config.FLOOD_COLORSCALE
        title, unit = "High flood-hazard area (100-yr, Project NOAH)", "%"
    lo, hi = (np.nanmin(values), np.nanmax(values)) if values.notna().any() else (0, 0)
    return (f'<div class="leap-key-title">{esc(title)}</div>'
            f'<div class="leap-key-gradient" style="background:{_gradient_css(scale)}"></div>'
            f'<div class="leap-key-labels"><span>{lo:.0f}{unit}</span>'
            f'<span>{hi:.0f}{unit}</span></div>')


# RENDER +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def legend_html(snap, layer="Risk"):
    """The legend box.

    Parameters
    ----------
    snap : pandas.DataFrame
    layer : str

    Returns
    -------
    str
    """
    return f'<div class="leap-key-simple">{key_html(snap, layer)}</div>'


def render_legend(snap, layer="Risk"):
    """Draw the legend in the map's bottom-left corner (placed by style.css).

    Parameters
    ----------
    snap : pandas.DataFrame
        Current snapshot.
    layer : str
        Active map layer.

    Returns
    -------
    None
    """
    with st.container(key="legend_simple"):
        st.html(legend_html(snap, layer))
