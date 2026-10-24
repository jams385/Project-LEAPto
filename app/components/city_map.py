"""The Overview map: 12 city polygons + labelled markers, coloured by alert level.

Uses Plotly's MapLibre traces (Choroplethmap + Scattermap). The only basemap
is Esri World Imagery (satellite) as a raster layer, with its attribution
(config.BASEMAP_URL / BASEMAP_ATTRIBUTION). Selection is by clicking a marker
(on_select). Risk colours cities by alert level; Rainfall and Flood hazard colour
the city areas on a continuous ramp. With no city selected, a hint says "Click a city to see its details".
"""

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from app import config
from app.components.hover import city_hovers, style_hover
from app.data import level_text
from app.state import horizon_number, select_city, set_map_view

# FIGURE +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def map_label(name):
    """Short map label: "City of Navotas" -> "Navotas", "Davao City" -> "Davao".

    Parameters
    ----------
    name : str

    Returns
    -------
    str
    """
    name = str(name)
    name = name[len("City of "):] if name.startswith("City of ") else name
    return name[:-len(" City")] if name.endswith(" City") else name


def _layer_values(snap, layer):
    """Pick the colouring values for the Rainfall or Flood hazard layer.

    Parameters
    ----------
    snap : pandas.DataFrame
        src.views snapshot.
    layer : str
        "Rainfall" or "Flood hazard" ("Risk" colours by alert level instead).

    Returns
    -------
    tuple[pandas.Series, list]
        (values, colourscale).
    """
    if layer == "Rainfall":
        return snap.rain_week_mm, config.RAINFALL_COLORSCALE
    return snap.hazard_pct, config.FLOOD_COLORSCALE


def build_map(snap, geojson, zooms, *, layer, selected, view=None,
              revision=0, height=None, hint=None, base_rate=None):
    """Build the Plotly map figure.

    Parameters
    ----------
    snap : pandas.DataFrame
        src.views snapshot for the current origin/horizon.
    geojson : dict
        City polygons (properties.adm3_pcode).
    zooms : dict[str, float]
        Zoom level that fits each city (app.data.load_geojson).
    layer : str
        "Risk" colours polygons and markers by alert level; "Rainfall" /
        "Flood hazard" colour polygons on a continuous scale.
    selected : str | None
        adm3_pcode of the open city: its marker is enlarged with a solid neutral
        outline, and the map zooms to it.
    view : str | None
        A key of config.MAP_VIEWS to show; None zooms to `selected` (or shows
        the default view when nothing is selected).
    revision : int
        Bumped by the view buttons so a repeated click re-centres the map.
    height : int | None
        Pixels; config.MAP_HEIGHT_PX if None.
    hint : str | None
        Text shown at the top of the map (e.g. config.MAP_HINT); None hides it.
    base_rate : float | None
        Share of all city-weeks that are outbreak weeks, for the hover's "≈N× a usual
        week"; the hover leaves that line out when None.

    Returns
    -------
    plotly.graph_objects.Figure
        City areas first (level colours for Risk, a ramp for Rainfall / Flood hazard), then the marker outlines (a halo for every
        city, a neutral disc for the open one), then the clickable, labelled
        marker trace (whose customdata[0] is adm3_pcode). "No report" cities
        are drawn fainter than the other levels. Panning and zooming out are
        limited to config.MAP_BOUNDS.
    """
    fig = go.Figure()
    hover = city_hovers(snap, base_rate, layer)
    colors = snap.alert_level.map(config.LEVEL_COLORS).fillna(
        config.LEVEL_COLORS[config.CASE_SIGNAL_LEVEL])

    if layer == "Risk":
        for level in config.DISPLAY_LEVELS:
            part = snap[snap.alert_level == level]
            if part.empty:
                continue
            color = config.LEVEL_COLORS[level]
            faint = level == config.NO_REPORT_LEVEL
            fig.add_trace(go.Choroplethmap(
                geojson=geojson, featureidkey="properties.adm3_pcode",
                locations=part.adm3_pcode, z=[1] * len(part),
                colorscale=[[0, color], [1, color]], showscale=False,
                marker=dict(opacity=0.25 if faint else 0.55,
                            line=dict(color=color, width=1.5)),
                hovertext=[hover[snap.index.get_loc(i)] for i in part.index],
                hovertemplate="%{hovertext}<extra></extra>"))
    else:
        values, scale = _layer_values(snap, layer)
        fig.add_trace(go.Choroplethmap(
            geojson=geojson, featureidkey="properties.adm3_pcode",
            locations=snap.adm3_pcode, z=values, colorscale=scale, showscale=False,
            marker=dict(opacity=0.75, line=dict(color="#9ED0F0", width=1)),
            hovertext=hover, hovertemplate="%{hovertext}<extra></extra>"))
    size = config.MAP_MARKER_SIZE

    # Outlines (drawn under the markers so clicks still hit the marker). Plotly
    # map markers have no border, so an outline is a solid disc a little larger
    # than the marker: a thin halo behind every city so the level colours read
    # on the imagery, and a larger neutral disc behind the open city.
    fig.add_trace(go.Scattermap(
        lat=snap.lat, lon=snap.lon, mode="markers",
        marker=dict(size=size + 4, color=config.MAP_HALO, opacity=0.8), hoverinfo="skip"))
    chosen = (snap.adm3_pcode == selected).to_numpy()
    if chosen.any():
        fig.add_trace(go.Scattermap(
            lat=snap.lat[chosen], lon=snap.lon[chosen], mode="markers",
            marker=dict(size=size + config.MAP_SELECTED_RING_EXTRA,
                        color=config.MAP_INK, opacity=1), hoverinfo="skip"))

    fig.add_trace(go.Scattermap(
        lat=snap.lat, lon=snap.lon, mode="markers+text",
        marker=dict(size=size, color=colors if layer == "Risk" else "#E8EEF5",
                    opacity=0.9),
        text=[map_label(n) for n in snap.city_name], textposition="middle right",
        textfont=dict(color=config.MAP_INK, size=12),
        customdata=np.stack([snap.adm3_pcode, snap.city_name], axis=1),
        hovertext=hover, hovertemplate="%{hovertext}<extra></extra>",
        selected=dict(marker=dict(opacity=1)), unselected=dict(marker=dict(opacity=0.9)),
        name="cities"))

    if view is None and selected in set(snap.adm3_pcode):
        row = snap[snap.adm3_pcode == selected].iloc[0]
        center = {"lat": row.lat, "lon": row.lon}
        zoom = zooms.get(selected, 9)
    else:
        spot = config.MAP_VIEWS.get(view, config.MAP_VIEWS[config.DEFAULT_MAP_VIEW])
        center, zoom = {"lat": spot["lat"], "lon": spot["lon"]}, spot["zoom"]

    map_layout = dict(center=center, zoom=zoom, style="white-bg", bounds=config.MAP_BOUNDS,
                      layers=[dict(below="traces", sourcetype="raster", source=[config.BASEMAP_URL],
                                   sourceattribution=config.BASEMAP_ATTRIBUTION)])
    fig.update_layout(
        map=map_layout, margin=dict(l=0, r=0, t=0, b=0), height=height or config.MAP_HEIGHT_PX,
        paper_bgcolor="rgba(0,0,0,0)", showlegend=False,
        # View resets only when the selection or quick view changes (or a view
        # button is clicked again); other pans/zooms survive reruns.
        uirevision=f"{selected}|{view}|{revision}",
        clickmode="event+select")
    style_hover(fig)
    if hint:
        # Top-right: the quick-view buttons sit over the top-left corner.
        fig.add_annotation(text=hint, x=0.985, y=0.975, xref="paper", yref="paper",
                           xanchor="right", yanchor="top", showarrow=False,
                           font=dict(family="Inter", size=13, color="#E8EEF5"),
                           bgcolor="rgba(9, 26, 44, 0.82)", bordercolor="rgba(255,255,255,0.18)",
                           borderwidth=1, borderpad=6)
    return fig


# RENDER +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def render_map(snap, geojson, zooms, *, layer=None, height=None, key_prefix="map"):
    """Draw the map and turn a marker click into a city selection.

    Parameters
    ----------
    snap : pandas.DataFrame
        src.views snapshot.
    geojson, zooms
        From app.data.load_geojson.
    layer : str | None
        Force a layer (the Overview always shows "Risk"); None uses the
        layer toggle (st.session_state.layer).
    height : int | None
        Map height in pixels.
    key_prefix : str
        Distinguishes the map on each page so a click on one page is never
        replayed on another.

    Returns
    -------
    None. Quick-view buttons (Philippines / Luzon / Visayas / Mindanao) and
    a "Map options" menu (layer) sit over the map. On a new marker
    click it calls select_city(..., from_map=True) and reruns so the city
    drawer opens and the map zooms in.
    """
    ss = st.session_state
    with st.container(key="mapviews", horizontal=True, gap="small"):
        for name in config.MAP_VIEWS:
            st.button(name, key=f"view_{name}", on_click=set_map_view, args=(name,),
                      type="primary" if ss.get("map_view") == name else "secondary")
        with st.popover("", icon=":material/layers:", key="mapopts", help="Map options"):
            st.segmented_control("Colour cities by", config.MAP_LAYERS, key="layer",
                                 required=True)
    fig = build_map(snap, geojson, zooms, layer=layer or ss.layer,
                    base_rate=level_text(horizon_number())["Warning"]["base_rate"],
                    selected=ss.selected, view=ss.get("map_view"),
                    revision=ss.get("view_nonce", 0), height=height,
                    hint=None if ss.selected else config.MAP_HINT)
    event = st.plotly_chart(
        fig, key=f"{key_prefix}_{ss.map_version}", on_select="rerun",
        selection_mode="points",
        width="stretch",
        # MapLibre maps have no modebar zoom buttons; scroll / pinch zooms.
        config={"scrollZoom": True, "displayModeBar": False})

    points = (event or {}).get("selection", {}).get("points", []) if event else []
    picked = tuple(p["customdata"][0] for p in points
                   if isinstance(p.get("customdata"), (list, tuple)) and p["customdata"])
    if picked and picked != ss.map_handled:
        ss.map_handled = picked
        select_city(picked[-1], from_map=True)
        st.rerun()
