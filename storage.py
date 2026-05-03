"""
storage.py — Itinerary persistence via GitHub API (deployed) or local JSON file (dev).

Priority on load:
  1. GitHub API  — when secrets["github"] is configured (Streamlit Cloud)
  2. itinerary.json on disk — local development
  3. Returns None  — app falls back to hardcoded data

Priority on save:
  1. GitHub API  — pushes a commit to the repo
  2. Local file  — writes itinerary.json next to this file
"""

import json
import base64
import pathlib
import requests
import streamlit as st

_LOCAL_FILE = pathlib.Path(__file__).parent / "itinerary.json"


# ── GitHub helpers ─────────────────────────────────────────────────────────────

def _gh_headers() -> dict:
    token = st.secrets["github"]["token"]
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }


def _gh_url() -> str:
    repo = st.secrets["github"]["repo"]          # "owner/repo-name"
    path = st.secrets["github"].get("path", "itinerary.json")
    return f"https://api.github.com/repos/{repo}/contents/{path}"


# ── Public API ─────────────────────────────────────────────────────────────────

def is_configured() -> bool:
    try:
        _ = st.secrets["github"]["token"]
        _ = st.secrets["github"]["repo"]
        return True
    except Exception:
        return False


def load_itinerary() -> list[dict] | None:
    """Return the days list, or None if nothing is available."""
    if is_configured():
        try:
            resp = requests.get(_gh_url(), headers=_gh_headers(), timeout=10)
            if resp.status_code == 200:
                raw = base64.b64decode(resp.json()["content"]).decode("utf-8")
                days = json.loads(raw)
                # Cache the SHA so save_itinerary can use it without a second GET
                st.session_state["_gh_sha"] = resp.json()["sha"]
                return days
        except Exception as e:
            st.warning(f"Could not load from GitHub: {e}")

    # Fallback: local file
    if _LOCAL_FILE.exists():
        try:
            return json.loads(_LOCAL_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    return None


def save_itinerary(days: list[dict]) -> bool:
    """Persist days. Returns True on success."""
    content = json.dumps(days, indent=2, ensure_ascii=False)

    if is_configured():
        try:
            encoded = base64.b64encode(content.encode()).decode()
            body = {
                "message": "Update itinerary via Trip Planner app",
                "content": encoded,
            }
            sha = st.session_state.get("_gh_sha")
            if sha:
                body["sha"] = sha
            resp = requests.put(_gh_url(), headers=_gh_headers(), json=body, timeout=10)
            if resp.status_code in (200, 201):
                st.session_state["_gh_sha"] = resp.json()["content"]["sha"]
                return True
            st.error(f"GitHub save failed: {resp.status_code} — {resp.json().get('message')}")
            return False
        except Exception as e:
            st.error(f"Could not save to GitHub: {e}")
            return False

    # Fallback: write local file (useful during development)
    try:
        _LOCAL_FILE.write_text(content, encoding="utf-8")
        return True
    except Exception as e:
        st.error(f"Could not write local file: {e}")
        return False
