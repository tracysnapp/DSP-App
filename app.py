import datetime
import os
import extra_streamlit_components as stx
import pandas as pd
import streamlit as st
from engine import (
    ACCESS_CODES_PATH,
    ADMIN_USER,
    DISPATCH_USER,
    USER_CREDENTIALS,
    authenticate_user,
    cleanup_old_snapshots,
    list_snapshot_files,
    load_local_access_codes,
    load_local_attendance_log,
    load_local_drivers,
    load_local_fleet,
    load_local_incidents_log,
    load_local_phones,
    load_local_schedule,
    load_local_scorecards,
    load_snapshot_file,
    log_dispatch_action,
    safe_save_dataframe,
    save_daily_closing_checklist,
    save_snapshot_file,
)
from views.closing_checklist import render_closing_checklist_tab
from views.dispatch_roster import render_dispatch_roster_tab
from views.driver_directory import render_driver_directory_tab
from views.fleet_phones_view import render_fleet_tab
from views.scheduler_view import render_scheduler_tab
from views.scorecards_view import render_scorecards_tab

# Page Configuration
st.set_page_config(
    page_title="JNA Command Center",
    page_icon="🚛",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------
# PERSISTENT COOKIE & SESSION AUTHENTICATION
# ---------------------------------------------------------
cookie_manager = stx.CookieManager()
all_cookies = cookie_manager.get_all()

# Hold execution until browser cookie manager mounts over WebSockets
if all_cookies is None:
  st.stop()

# Initialize Session State
if "authenticated" not in st.session_state:
  st.session_state["authenticated"] = False
if "user_role" not in st.session_state:
  st.session_state["user_role"] = None
if "user_name" not in st.session_state:
  st.session_state["user_name"] = None

# Auto-login from persisted browser cookies
cookie_user = all_cookies.get("jna_auth_user")
cookie_role = all_cookies.get("jna_auth_role")

if cookie_user and cookie_role and not st.session_state["authenticated"]:
  if cookie_user in USER_CREDENTIALS:
    st.session_state["authenticated"] = True
    st.session_state["user_role"] = cookie_role
    st.session_state["user_name"] = USER_CREDENTIALS[cookie_user].get(
        "name", cookie_user
    )

# ---------------------------------------------------------
# LOGIN INTERFACE
# ---------------------------------------------------------
if not st.session_state["authenticated"]:
  st.markdown(
      "<h1 style='text-align: center;'>🚛 JNA Logistics Operational Command"
      " Center</h1>",
      unsafe_allow_html=True,
  )
  st.markdown(
      "<h3 style='text-align: center; color: gray;'>Station DDK6 Operations</h3>",
      unsafe_allow_html=True,
  )
  st.markdown("---")

  col1, col2, col3 = st.columns([1, 2, 1])
  with col2:
    st.subheader("🔐 Desk Authentication")
    with st.form("login_form", clear_on_submit=False):
      username_input = st.text_input("Username", key="login_user")
      password_input = st.text_input(
          "Password", type="password", key="login_pass"
      )
      submit_login = st.form_submit_button(
          "Sign In to Workspace", use_container_width=True, type="primary"
      )

      if submit_login:
        auth_success, role, name = authenticate_user(
            username_input, password_input
        )
        if auth_success:
          st.session_state["authenticated"] = True
          st.session_state["user_role"] = role
          st.session_state["user_name"] = name

          # Set 7-day cookie expiration so browser closing won't wipe login
          expires = datetime.datetime.now() + datetime.timedelta(days=7)
          cookie_manager.set(
              "jna_auth_user",
              username_input.strip(),
              expires_at=expires,
              key="set_user_cookie",
          )
          cookie_manager.set(
              "jna_auth_role",
              role,
              expires_at=expires,
              key="set_role_cookie",
          )

          st.toast(f"Welcome back, {name}!", icon="👋")
          st.rerun()
        else:
          st.error(
              "Invalid credentials. Please verify username and password."
          )
  st.stop()

# ---------------------------------------------------------
# MASTER DATA INITIALIZATION & CALLBACKS
# ---------------------------------------------------------
cleanup_old_snapshots(days_to_keep=30)

if "fleet_df" not in st.session_state or st.session_state["fleet_df"] is None:
  st.session_state["fleet_df"] = load_local_fleet()
if "phones_df" not in st.session_state or st.session_state["phones_df"] is None:
  st.session_state["phones_df"] = load_local_phones()
if (
    "drivers_df" not in st.session_state
    or st.session_state["drivers_df"] is None
):
  st.session_state["drivers_df"] = load_local_drivers()
if (
    "schedule_df" not in st.session_state
    or st.session_state["schedule_df"] is None
):
  st.session_state["schedule_df"] = load_local_schedule()
if (
    "scorecards_df" not in st.session_state
    or st.session_state["scorecards_df"] is None
):
  st.session_state["scorecards_df"] = load_local_scorecards()
if (
    "access_codes_df" not in st.session_state
    or st.session_state["access_codes_df"] is None
):
  st.session_state["access_codes_df"] = load_local_access_codes()
if (
    "attendance_log_df" not in st.session_state
    or st.session_state["attendance_log_df"] is None
):
  st.session_state["attendance_log_df"] = load_local_attendance_log()
if (
    "incidents_log_df" not in st.session_state
    or st.session_state["incidents_log_df"] is None
):
  st.session_state["incidents_log_df"] = load_local_incidents_log()

# --- AUTO-LOAD LATEST HISTORICAL SNAPSHOT ON LAUNCH / REFRESH ---
if "current_roster" not in st.session_state or st.session_state.get("current_roster") is None or st.session_state["current_roster"].empty:
  snapshot_files = list_snapshot_files()
  if snapshot_files:
    # list_snapshot_files() returns sorted reverse order, so index 0 is the newest
    latest_snapshot = snapshot_files[0]
    loaded_latest_df = load_snapshot_file(latest_snapshot)
    if not loaded_latest_df.empty:
      st.session_state["current_roster"] = loaded_latest_df


def update_live_roster(
    new_roster_df, toast_msg="Roster updated successfully!"
):
  """Updates active roster in session state, syncs closing checklist, and saves snapshot to GCS."""
  st.session_state["current_roster"] = new_roster_df.copy()

  from modules.roster import update_closing_checklist_assignments

  update_closing_checklist_assignments(new_roster_df, st.session_state)

  now_filename = f"roster_{pd.Timestamp.now().strftime('%Y-%m-%d_%H%M')}.xlsx"
  save_snapshot_file(new_roster_df, now_filename)

  if (
      "closing_df" in st.session_state
      and not st.session_state["closing_df"].empty
  ):
    save_daily_closing_checklist(st.session_state["closing_df"])

  st.toast(toast_msg, icon="💾")


# ---------------------------------------------------------
# SIDEBAR CONTROL PANEL
# ---------------------------------------------------------
with st.sidebar:
  st.title("🚛 JNA Command Desk")
  st.caption(
      f"Logged in as: **{st.session_state.get('user_name', 'User')}**"
      f" ({st.session_state.get('user_role', 'Role')})"
  )

  if st.button("🚪 Sign Out", type="secondary", use_container_width=True):
    st.session_state["authenticated"] = False
    st.session_state["user_role"] = None
    st.session_state["user_name"] = None

    # Wipe persistent cookies on explicit sign-out
    cookie_manager.delete("jna_auth_user", key="del_user_cookie")
    cookie_manager.delete("jna_auth_role", key="del_role_cookie")
    st.rerun()

  st.markdown("---")
  st.header("📋 Roster Import & History")

  cortex_file = st.file_uploader(
      "Upload Today's Cortex Route Export",
      type=["xlsx", "xls", "csv"],
      help="Upload the raw route export file directly from Cortex.",
  )

  st.markdown("---")
  st.subheader("📜 Historical Roster Snapshots")

  snapshot_files = list_snapshot_files()
  if snapshot_files:
    selected_snapshot = st.selectbox(
        "Load Saved Roster Snapshot",
        options=["Select Snapshot..."] + snapshot_files,
    )
    if selected_snapshot != "Select Snapshot...":
      if st.button("🔄 Restore Roster Snapshot", use_container_width=True):
        loaded_df = load_snapshot_file(selected_snapshot)
        if not loaded_df.empty:
          update_live_roster(
              loaded_df, toast_msg=f"Loaded roster snapshot: {selected_snapshot}"
          )
          log_dispatch_action(
              f"Restored historical roster snapshot: {selected_snapshot}",
              username=st.session_state.get("user_name"),
          )
          st.rerun()
        else:
          st.error("Could not load selected snapshot file.")
  else:
    st.caption("No saved roster snapshots found in Cloud Storage.")

# ---------------------------------------------------------
# MAIN WORKSPACE TABS
# ---------------------------------------------------------
st.title("🚛 JNA Daily Operations & Command Center")

(
    tab_roster,
    tab_closing,
    tab_access,
    tab_scheduler,
    tab_drivers,
    tab_fleet,
    tab_scorecard,
) = st.tabs([
    "📋 Route Assignment & Roster",
    "📝 Daily Closing & Debrief Checklist",
    "🔑 Gate & Access Codes",
    "📅 Master Driver Schedule",
    "👥 Driver Directory & Attendance",
    "🚐 Fleet & Phone Tracker",
    "📊 Driver Performance Scorecards",
])

with tab_roster:
  render_dispatch_roster_tab(cortex_file, update_live_roster)

with tab_closing:
  render_closing_checklist_tab()

with tab_access:
  st.subheader("🔑 Station & Delivery Access Codes")
  access_df = st.session_state.get("access_codes_df")
  if access_df is not None:
    user_role = st.session_state.get("user_role", "Dispatcher")
    active_user = st.session_state.get("user_name", "Dispatcher")
    is_admin = user_role == "Admin"

    if is_admin:
      st.caption(
          "Manage station gate codes, door access, and locker codes (Admin Edit"
          " Mode)."
      )
      edited_access = st.data_editor(
          access_df,
          use_container_width=True,
          hide_index=True,
          num_rows="dynamic",
          key="access_codes_editor_key",
      )
      if st.button("💾 Save Access Codes", type="primary"):
        st.session_state["access_codes_df"] = edited_access.copy()
        safe_save_dataframe(edited_access, ACCESS_CODES_PATH)
        load_local_access_codes.clear()
        log_dispatch_action(
            "Updated Station Access & Gate Codes.", username=active_user
        )
        st.toast("Access codes saved!", icon="🔑")
        st.rerun()
    else:
      st.caption("Read-Only View for Dispatch Desk.")
      st.dataframe(access_df, use_container_width=True, hide_index=True)
  else:
    st.info("No access code records found in master storage.")

with tab_scheduler:
  render_scheduler_tab()

with tab_drivers:
  render_driver_directory_tab()

with tab_fleet:
  render_fleet_tab()

with tab_scorecard:
  render_scorecards_tab()
