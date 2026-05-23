import streamlit as st

st.set_page_config(
    page_title="Aku Turis Vietnam",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="expanded",
)

pg = st.navigation([
    st.Page("itinerary.py",          title="Itinerary",    icon="🗺️"),
    st.Page("pages/place_finder.py", title="Place Finder", icon="🔍"),
])
pg.run()
