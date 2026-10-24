"""Landing + Sign in / Sign up (design D, satellite background). Demo only:
any email and password work, nothing is stored outside st.session_state."""

import streamlit as st

from app.components.ui import esc

ROLE_LABELS = {"Resident": "Resident", "Health office": "City health office"}

# Feature-chip icons are static SVG files (inline svg is sanitised away).
_ICONS = {"chart": "icon_chart.svg", "bell": "icon_bell.svg", "shield": "icon_shield.svg"}


# HTML PIECES ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def hero_html():
    """Left-side hero shared by the landing and loading screens.

    Returns
    -------
    str
        Logo, alert-level stripe, headline, description and feature chips.
    """
    chips = "".join(f'<span class="leap-hero-chip"><img src="app/static/{_ICONS[i]}" '
                    f'alt="">{esc(t)}</span>'
                    for i, t in [("chart", "City risk updates"), ("bell", "Flood alerts"),
                                 ("shield", "Safety steps")])
    return f'''<div class="leap-hero">
      <img src="app/static/logo.png" class="leap-hero-logo" alt="LEAPto">
      <div class="leap-stripes"><i style="background:#3BAA5C"></i>
        <i style="background:#F2994A"></i><i style="background:#E04848"></i></div>
      <div class="leap-hero-eyebrow">PROJECT LEAPTO</div>
      <h1 class="leap-hero-title">Know your leptospirosis risk before the flood reaches you.</h1>
      <p class="leap-hero-sub">City-level risk updates and simple steps to stay safe, for residents
        and city health offices.</p>
      <div class="leap-hero-chips">{chips}</div>
    </div>'''


# ACTIONS ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def _go(view):
    """Switch between the sign-in and sign-up cards.

    Parameters
    ----------
    view : str
        "signin" or "signup".

    Returns
    -------
    None
    """
    st.session_state.auth_view = view
    st.session_state.auth_error = None


def _enter(user, role=None):
    """Demo sign-in: remember the user (and role) and show the loading screen.

    Parameters
    ----------
    user : str
        Display name.
    role : str | None
        "Resident" / "Health office"; None keeps the current role.

    Returns
    -------
    None
    """
    ss = st.session_state
    ss.user = user
    if role:
        ss.role = role
    ss.loaded = False
    ss.auth_error = None


def _clear_error():
    """Hide the validation message as soon as the user edits a field.

    Returns
    -------
    None
    """
    st.session_state.auth_error = None


def _toggle_office():
    """The "Use your office account" shortcut: role = Health office.

    Returns
    -------
    None
    """
    ss = st.session_state
    ss.role = "Resident" if ss.role == "Health office" else "Health office"


def _on_signin():
    """Validate the demo sign-in form (any email with "@" and any password).

    Returns
    -------
    None. Sets auth_error instead of signing in when a field is missing.
    """
    ss = st.session_state
    email, password = (ss.get("si_email") or "").strip(), ss.get("si_password") or ""
    if "@" not in email or not password:
        ss.auth_error = "Enter an email address and any password (demo sign-in)."
        return
    _enter(email.split("@")[0])


def _on_signup():
    """Validate the demo sign-up form and sign the new user in.

    Returns
    -------
    None. Sets auth_error when a field is missing or passwords differ.
    """
    ss = st.session_state
    name = (ss.get("su_user") or "").strip()
    email = (ss.get("su_email") or "").strip()
    pw, pw2 = ss.get("su_pw") or "", ss.get("su_pw2") or ""
    if not name or "@" not in email or not pw:
        ss.auth_error = "Fill in a username, an email address and a password."
    elif pw != pw2:
        ss.auth_error = "The two passwords do not match."
    else:
        _enter(name, ss.get("su_role") or "Resident")


# RENDER +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def _divider(text):
    """Thin rule with centred text ("New to LEAPto?").

    Parameters
    ----------
    text : str

    Returns
    -------
    None
    """
    st.html(f'<div class="leap-or"><span>{esc(text)}</span></div>')


def render_auth():
    """Draw the landing screen with the sign-in or sign-up card.

    Returns
    -------
    None. All buttons are wired: Sign In, Create an account / Sign in
    instead, Explore demo, and the office-account shortcut.
    """
    ss = st.session_state
    ss.setdefault("auth_view", "signin")
    with st.container(key="auth"):
        left, _, right = st.columns([1.3, 0.25, 0.95])
        with left:
            st.html(hero_html())
        with right, st.container(key="authcard"):
            if ss.auth_view == "signup":
                st.html('<div class="leap-auth-title">Create your account</div>'
                        '<div class="leap-auth-sub">Get city-level risk updates and safety '
                        'steps for where you live.</div>')
                st.text_input("Username", key="su_user", placeholder="Choose a username",
                              on_change=_clear_error)
                st.text_input("Email", key="su_email", placeholder="you@example.com",
                              on_change=_clear_error)
                st.text_input("Password", key="su_pw", type="password",
                              placeholder="Create a password", on_change=_clear_error)
                st.text_input("Confirm password", key="su_pw2", type="password",
                              placeholder="Re-enter your password", on_change=_clear_error)
                st.segmented_control("I am a", list(ROLE_LABELS), key="su_role",
                                     default="Resident", format_func=ROLE_LABELS.get,
                                     required=True, width="stretch")
                if ss.get("auth_error"):
                    st.error(ss.auth_error)
                st.button("Create Account", type="primary", width="stretch",
                          on_click=_on_signup, key="do_signup")
                _divider("Already have an account?")
                st.button("Sign in instead", width="stretch", on_click=_go, args=("signin",),
                          key="to_signin")
            else:
                st.html('<div class="leap-auth-title">Welcome back</div>'
                        '<div class="leap-auth-sub">Sign in to see your city\'s latest '
                        'risk level.</div>')
                st.text_input("Email", key="si_email", placeholder="you@example.com",
                              on_change=_clear_error)
                st.text_input("Password", key="si_password", type="password",
                              placeholder="Password", on_change=_clear_error)
                st.caption("Demo sign-in: any email and password work. Nothing is stored.")
                if ss.get("auth_error"):
                    st.error(ss.auth_error)
                st.button("Sign In", type="primary", width="stretch", on_click=_on_signin,
                          key="do_signin")
                _divider("New to LEAPto?")
                st.button("Create an account", width="stretch", on_click=_go,
                          args=("signup",), key="to_signup")
                st.button("Explore demo without an account", width="stretch",
                          on_click=_enter, args=("Guest",), key="explore",
                          icon=":material/travel_explore:")
                office = ss.get("role") == "Health office"
                with st.container(key="officebox", horizontal=True,
                                  vertical_alignment="center"):
                    st.html('<div class="leap-office-text">'
                            + ("✓ Signing in as a <b>city health office</b>."
                               if office else "Signing in for a city health office?")
                            + "</div>")
                    st.button("Use a resident account" if office else "Use your office account",
                              type="tertiary", on_click=_toggle_office, key="office")
