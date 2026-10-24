"""Make the app folder and its parent importable (`import src...`, `import app...`)."""

import sys
from pathlib import Path

# The app folder (for `src`) and its parent (this folder is the `app` package).
for _p in (Path(__file__).resolve().parents[1], Path(__file__).resolve().parents[2]):
    sys.path.insert(0, str(_p))

# Import the app's data modules before any test patches them. Modules that do
# `from x import f` keep the first f they see, so importing them for the first time
# inside a patched test would keep the patch for the rest of the run.
import app.data  # noqa: E402,F401


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_streamlit_cache():
    """Start every test with an empty st.cache_data.

    Tests that point the app at other data folders (monkeypatched config) would
    otherwise read, or leave behind, cached tables from a neighbouring test, so
    a test could pass or fail depending on which tests ran before it.
    """
    import streamlit as st
    st.cache_data.clear()
    yield
