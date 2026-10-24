"""Top bar (DESIGN_V3): logo, page tabs, city search and the account menu.

The account menu holds the role (which actions the drawer suggests), "Your
city" (tagged in the city list and ringed on the map) and sign-out. Data
sources and cut-offs live on the Data reliability page.
"""

import streamlit as st

from app import config
from app.components.ui import esc
from app.data import city_names
from app.state import select_city

# CALLBACKS ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def _on_search():
    """Open the searched city in the drawer on the Overview, then clear the box.

    Returns
    -------
    None
    """
    pcode = st.session_state.get("search")
    if pcode:
        st.session_state.page = config.PAGES[0]
        select_city(pcode)
    st.session_state.search = None


def _sign_out():
    """Demo sign-out: forget the user so the landing screen shows again.

    Returns
    -------
    None
    """
    st.session_state.user = None
    st.session_state.loaded = False


# RENDER +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def render_header():
    """Draw the header row and return the selected page.

    Returns
    -------
    str
        st.session_state.page (one of config.PAGES). Search opens a city
        through select_city; the account menu writes the role.
    """
    names = city_names()
    with st.container(key="header", horizontal=True, vertical_alignment="center", wrap=False):
        st.html('<img src="app/static/logo.png" class="leap-logo" alt="LEAPto">', width="content")
        with st.container(key="nav", width="content"):
            st.segmented_control("Page", config.PAGES, key="page", required=True,
                                 label_visibility="collapsed")
        st.space("stretch")
        st.selectbox("Search the covered cities", list(names), key="search", index=None,
                     format_func=names.get, on_change=_on_search,
                     placeholder=f"Search the {len(names)} covered cities",
                     label_visibility="collapsed", width=340)
        with st.popover("", icon=":material/person:", key="profile", help="Account"):
            st.markdown(f"**{esc(st.session_state.user or 'Guest')}**")
            st.segmented_control("I am a", config.ROLES, key="role", required=True)
            st.caption("Your role decides which actions the city drawer suggests.")
            st.button("Sign out", icon=":material/logout:", on_click=_sign_out,
                      width="stretch")
    return st.session_state.page
