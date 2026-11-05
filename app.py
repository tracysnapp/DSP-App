import time
import streamlit as st
import pandas as pd
import extra_streamlit_components as stx

from engine import (
    authenticate_user, cleanup_old_snapshots,
    save_snapshot_file, list_snapshot_files, load_snapshot_file,
    load_local_fleet, load_local_phones, load_local_drivers,
    load_local_schedule, load_local_scorecards, load_local_access_codes
)
from modules.roster import update_closing_checklist_assignments

# Import Clean UI View Modules
from views.ops_overview import render_ops_overview_tab
from views.dispatch_roster import render_dispatch_roster_tab
from views.closing_checklist import render_closing_checklist_tab
from views.access_codes import render_access_codes_tab
from views.driver_directory import render_driver_directory_tab
from views.scheduler_view import render_scheduler_tab
from views.scorecards_view import render_scorecards_tab
from views.fleet_phones_view import render_fleet_tab, render_phones_tab

st.set_page_config(page_title="JNA Logistics Command Center", layout="wide")

st.markdown("""
    <style>
        .stAppDeployButton { display: none !important; }
        [data-testid="stHeader"] { background-color: rgba(0,0,0,0); }
        @media print {
            .page-break { page-break-after: always !important; break-after: page !important; }
            tr { page-break-inside: avoid !important; break-inside: avoid !important; }
        }
    </style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# AUTHENTICATION GUARD WITH COOKIE PERSISTENCE
# ---------------------------------------------------------
cookie_manager = stx.CookieManager()

if 'authenticated' not in st.session_state:
    st.session_state['authenticated'] = False
    st.session_state['user_role'] = None
    st.session_state['user_name'] = None

# Retrieve all cookies to verify component readiness
all_cookies = cookie_manager.get_all()

# If session is lost, attempt to read stored cookies
if not st.session_state['authenticated']:
    auth_cookie_user = cookie_manager.get(cookie="jna_auth_user")
    auth_cookie_role = cookie_manager.get(cookie="jna_auth_role")

    if auth_cookie_user and auth_cookie_role:
        st.session_state['authenticated'] = True
        st.session_state['user_name'] = auth_cookie_user
        st.session_state['user_role'] = auth_cookie_role
        st.rerun()

# Render Login Form if unauthenticated
if not st.session_state['authenticated']:
    st.title("🚛 JNA Logistics Command Center")
    st.subheader("🔒 User Authentication Required")
    
    col_c1, col_c2, col_c3 = st.columns([1, 2, 1])
    with col_c2:
        with st.form("login_form"):
            st.markdown("### Dispatch Portal Sign-In")
            u_input = st.text_input("Username")
            p_input = st.text_input("Password", type="password")
            remember_me = st.checkbox("Keep me signed in on this browser (7 days)", value=True)
            
            if st.form_submit_button("Sign In to Workspace", use_container_width=True, type="primary"):
                is_auth, role, name = authenticate_user(u_input, p_input)
                if is_auth:
                    st.session_state['authenticated'] = True
                    st.session_state['user_role'] = role
                    st.session_state['user_name'] = name
                    
                    if remember_me:
                        cookie_manager.set("jna_auth_user", name, key="set_user", max_age=604800)
                        cookie_manager.set("jna_auth_role", role, key="set_role", max_age=604800)
                    
                    st.rerun()
                else:
                    st.error("Invalid username or password.")
    st.stop()

# ---------------------------------------------------------
# GLOBAL HELPERS & DATA INITIALIZATION
# ---------------------------------------------------------
def update_live_roster(new_roster_df, toast_msg="Roster updated successfully!"):
    if new_roster_df is None:
        return
    st.session_state['current_roster'] = new_roster_df
    update_closing_checklist_assignments(new_roster_df, st.session_state)
    
    # Save snapshot blob to GCS bucket via engine helper
    save_snapshot_file(new_roster_df, f"roster_{pd.Timestamp.now().strftime('%Y-%m-%d_%H%M')}.xlsx")
    if toast_msg:
        st.toast(toast_msg, icon="✅")

# Clean up snapshots older than 30 days in GCS/Local (Handled inside engine.py)
cleanup_old_snapshots(days_to_keep=30)

# Load master data files from GCS bucket on session cold start
if 'fleet_df' not in st.session_state or st.session_state['fleet_df'] is None:
    st.session_state['fleet_df'] = load_local_fleet()

if 'phones_df' not in st.session_state or st.session_state['phones_df'] is None:
    st.session_state['phones_df'] = load_local_phones()

if 'drivers_df' not in st.session_state or st.session_state['drivers_df'] is None:
    st.session_state['drivers_df'] = load_local_drivers()

if 'schedule_df' not in st.session_state or st.session_state['schedule_df'] is None:
    st.session_state['schedule_df'] = load_local_schedule()

if 'scorecards_df' not in st.session_state or st.session_state['scorecards_df'] is None:
    st.session_state['scorecards_df'] = load_local_scorecards()

if 'access_df' not in st.session_state or st.session_state['access_df'] is None:
    st.session_state['access_df'] = load_local_access_codes()

# ---------------------------------------------------------
# NAVIGATION & SIDEBAR SETUP
# ---------------------------------------------------------
st.title("🚛 JNA Logistics Command Center")
user_role = st.session_state['user_role']
is_admin = (user_role == "Admin")

st.sidebar.markdown(f"👤 **User:** {st.session_state['user_name']}")
st.sidebar.markdown(f"🛡️ **Access Level:** `{user_role}`")

if st.sidebar.button("🚪 Sign Out", use_container_width=True):
    cookie_manager.delete("jna_auth_user", key="del_user")
    cookie_manager.delete("jna_auth_role", key="del_role")
    st.session_state['authenticated'] = False
    st.session_state['user_role'] = None
    st.session_state['user_name'] = None
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.header("🧭 Portal Navigation")

if is_admin:
    active_portal = st.sidebar.radio("Select Portal Workspace", options=["🚚 Dispatch Operations Portal", "⚙️ Admin & Management Portal"], index=0)
else:
    active_portal = "🚚 Dispatch Operations Portal"
    st.sidebar.info("📌 Currently in **Dispatch Operations Portal**")

st.sidebar.markdown("---")

if active_portal == "🚚 Dispatch Operations Portal":
    st.sidebar.header("📁 Daily Operations")
    cortex_file = st.sidebar.file_uploader("Upload Today's Cortex Routes (.csv, .xlsx, or .xls)", type=["csv", "xlsx", "xls"])
    st.sidebar.markdown("---")
    st.sidebar.header("📜 Roster History & Snapshots")

    # Fetch blob objects from GCS bucket
    history_files = list_snapshot_files()
    if history_files:
        selected_history = st.sidebar.selectbox("Load Previous Snapshot", options=["Select a date/time..."] + history_files)
        if selected_history != "Select a date/time..." and st.sidebar.button("📂 Load Historical Roster"):
            hist_df = load_snapshot_file(selected_history)
            if not hist_df.empty:
                hist_df = hist_df.fillna("").replace(["nan", "NaN", "None", "<NA>"], "")
                if 'Helper' not in hist_df.columns and 'Driver' in hist_df.columns:
                    hist_df.insert(hist_df.columns.get_loc('Driver') + 1, 'Helper', '')
                update_live_roster(hist_df, toast_msg=f"Loaded snapshot: {selected_history}")
                st.rerun()
    else:
        st.sidebar.caption("⚠️ No snapshots found in storage.")
else:
    cortex_file = None

st.sidebar.markdown("---")

# ---------------------------------------------------------
# PORTAL TAB RENDERING
# ---------------------------------------------------------
if active_portal == "🚚 Dispatch Operations Portal":
    tab_ops, tab_dispatch, tab_closing, tab_access, tab_fleet = st.tabs([
        "📊 Daily Ops Overview", "📋 Daily Dispatch Roster", "📝 Closing Checklist", "🔑 Gate & Access Codes", "🚐 Fleet Status Tracker"
    ])
    with tab_ops:
        render_ops_overview_tab()
    with tab_dispatch:
        render_dispatch_roster_tab(cortex_file, update_live_roster)
    with tab_closing:
        render_closing_checklist_tab()
    with tab_access:
        render_access_codes_tab(is_admin)
    with tab_fleet:
        render_fleet_tab(is_admin=is_admin)

elif active_portal == "⚙️ Admin & Management Portal" and is_admin:
    tab_drivers, tab_schedule, tab_scorecards, tab_fleet, tab_phones = st.tabs([
        "👥 Master Driver Directory", "📅 Weekly Shift Scheduler & Discord", "🏆 Scorecards & Leaderboard", "🚐 Fleet & Vehicle Tracker", "📱 Phone & Device Roster"
    ])
    with tab_drivers:
        render_driver_directory_tab()
    with tab_schedule:
        render_scheduler_tab()
    with tab_scorecards:
        render_scorecards_tab()
    with tab_fleet:
        render_fleet_tab(is_admin=True)
    with tab_phones:
        render_phones_tab()
