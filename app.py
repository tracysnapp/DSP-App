import datetime
import extra_streamlit_components as stx
import pandas as pd
import streamlit as st
from engine import (
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
    load_local_scorecards,
    load_snapshot_file,
    log_dispatch_action,
    save_daily_closing_checklist,
    save_snapshot_file,
)
from modules.roster import update_closing_checklist_assignments
from views.access_codes import render_access_codes_tab
from views.closing_checklist import render_closing_checklist_tab
from views.dispatch_roster import render_dispatch_roster_tab
from views.driver_directory import render_driver_directory_tab
from views.fleet_phones_view import render_fleet_tab
from views.rescues_view import render_rescues_tab
from views.scheduler_view import render_scheduler_tab
from views.scorecards_view import render_scorecards_tab

# Page Configuration
st.set_page_config(
    page_title="JNA Command Center",
    page_icon="🚛",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Tighten default Streamlit top padding and polish navigation bar spacing
st.markdown(
    """
    <style>
        .block-container {
            padding-top: 1.5rem;
            padding-bottom: 1.5rem;
        }
        header[data-testid="stHeader"] {
            height: 2.5rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------
# PERSISTENT COOKIE & SESSION AUTHENTICATION
# ---------------------------------------------------------
cookie_manager = stx.CookieManager()
all_cookies = cookie_manager.get_all()

if all_cookies is None:
  st.stop()

if "authenticated" not in st.session_state:
  st.session_state["authenticated"] = False
if "user_role" not in st.session_state:
  st.session_state["user_role"] = None
if "user_name" not in st.session_state:
  st.session_state["user_name"] = None

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
if "snapshots_cleaned" not in st.session_state:
  cleanup_old_snapshots(days_to_keep=30)
  st.session_state["snapshots_cleaned"] = True

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
    "scorecards_df" not in st.session_state
    or st.session_state["scorecards_df"] is None
):
  st.session_state["scorecards_df"] = load_local_scorecards()
if (
    "access_df" not in st.session_state
    or st.session_state["access_df"] is None
):
  st.session_state["access_df"] = load_local_access_codes()
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

if "active_roster_label" not in st.session_state:
  st.session_state["active_roster_label"] = "None Loaded"

# --- AUTO-LOAD LATEST HISTORICAL SNAPSHOT ON INITIAL LAUNCH / REFRESH ONLY ---
if "current_roster" not in st.session_state:
  snapshot_files = list_snapshot_files()
  if snapshot_files:
    latest_snapshot = snapshot_files[0]
    loaded_latest_df = load_snapshot_file(latest_snapshot)
    if not loaded_latest_df.empty:
      st.session_state["current_roster"] = loaded_latest_df
      st.session_state["active_roster_label"] = latest_snapshot
    else:
      st.session_state["current_roster"] = None
  else:
    st.session_state["current_roster"] = None


def update_live_roster(
    new_roster_df,
    toast_msg="Roster updated successfully!",
    source_label=None,
):
  """Updates active roster in session state, syncs closing checklist, and saves snapshot to GCS."""
  st.session_state["current_roster"] = new_roster_df.copy()
  update_closing_checklist_assignments(new_roster_df, st.session_state)

  now_filename = f"roster_{pd.Timestamp.now().strftime('%Y-%m-%d_%H%M')}.xlsx"
  save_snapshot_file(new_roster_df, now_filename)
  st.session_state["active_roster_label"] = (
      source_label if source_label else now_filename
  )

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

  sb_col1, sb_col2 = st.columns(2)
  with sb_col1:
    if st.button(
        "🔄 Sync Cloud",
        use_container_width=True,
        help="Clear local cache and pull latest files from Cloud Storage.",
    ):
      st.cache_data.clear()
      for key in [
          "fleet_df",
          "phones_df",
          "drivers_df",
          "scorecards_df",
          "access_df",
          "attendance_log_df",
          "incidents_log_df",
      ]:
        st.session_state[key] = None
      st.toast("Cloud data refreshed!", icon="🔄")
      st.rerun()

  with sb_col2:
    if st.button("🚪 Sign Out", type="secondary", use_container_width=True):
      st.session_state["authenticated"] = False
      st.session_state["user_role"] = None
      st.session_state["user_name"] = None

      cookie_manager.delete("jna_auth_user", key="del_user_cookie")
      cookie_manager.delete("jna_auth_role", key="del_role_cookie")
      st.rerun()

  st.markdown("---")

  # Live Active Roster Status Indicator
  current_roster = st.session_state.get("current_roster")
  if current_roster is not None and not current_roster.empty:
    st.success(
        f"**Active Roster ({len(current_roster)} routes)**\n\n"
        f"`{st.session_state.get('active_roster_label', 'Active')}`"
    )
  else:
    st.warning("**No Active Roster Loaded**\n\nUpload Cortex export below.")

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
              loaded_df,
              toast_msg=f"Loaded roster snapshot: {selected_snapshot}",
              source_label=selected_snapshot,
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
# COMPACT WORKSPACE HEADER & NAVIGATION
# ---------------------------------------------------------
hdr_left, hdr_right = st.columns([3, 1])
with hdr_left:
  st.markdown("## 🚛 JNA Operations Command Center")
with hdr_right:
  today_str = datetime.date.today().strftime("%a, %b %d, %Y")
  st.markdown(
      f"<div style='text-align: right; padding-top: 0.75rem; color: gray;'>"
      f"<strong>Station DDK6</strong> &bull; {today_str}</div>",
      unsafe_allow_html=True,
  )

NAV_OPTIONS = [
    "📋 Dispatch Roster",
    "🚐 Fleet & Phones",
    "👥 Drivers & Attendance",
    "🚚 Rescues Log",
    "🔑 Access Codes",
    "📝 Closing Checklist",
    "📅 Scheduling",
    "📊 Scorecards",
]

active_view = st.segmented_control(
    "Workspace Navigation",
    options=NAV_OPTIONS,
    default=NAV_OPTIONS[0],
    label_visibility="collapsed",
    key="main_workspace_nav",
)

# Fallback if user clicks the active pill to deselect it
if not active_view:
  active_view = NAV_OPTIONS[0]

st.markdown("---")

# Render ONLY the active view to eliminate background GCS calls & lag
if active_view == "📋 Dispatch Roster":
  render_dispatch_roster_tab(cortex_file, update_live_roster)
elif active_view == "🚐 Fleet & Phones":
  render_fleet_tab()
elif active_view == "👥 Drivers & Attendance":
  render_driver_directory_tab()
elif active_view == "🚚 Rescues Log":
  render_rescues_tab()
elif active_view == "🔑 Access Codes":
  user_role = st.session_state.get("user_role", "Dispatcher")
  render_access_codes_tab(is_admin=(user_role == "Admin"))
elif active_view == "📝 Closing Checklist":
  render_closing_checklist_tab()
elif active_view == "📅 Scheduling":
  render_scheduler_tab()
elif active_view == "📊 Scorecards":
  render_scorecards_tab()
