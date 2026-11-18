import pandas as pd
import streamlit as st
from engine import (
    ATTENDANCE_LOG_PATH,
    MASTER_DRIVERS_PATH,
    load_local_attendance_log,
    load_local_drivers,
    load_local_schedule,
    log_dispatch_action,
    safe_save_dataframe,
)
from modules.fleet import process_driver_data
from modules.schedule import calculate_driver_attendance_metrics

INFRACTION_TYPES = [
    "Late Arrival (< 15 mins)",
    "Late Arrival (15+ mins)",
    "Call-Out (Excused)",
    "Call-Out (Unexcused)",
    "No-Call / No-Show",
    "Incomplete Shift / Left Early",
]


def render_driver_directory_tab():
    st.subheader("👥 Master Driver Directory & Attendance")

    drivers_df = st.session_state.get("drivers_df")
    if drivers_df is None or drivers_df.empty:
        drivers_df = load_local_drivers()
        st.session_state["drivers_df"] = drivers_df

    att_log_df = st.session_state.get("attendance_log_df")
    if att_log_df is None:
        att_log_df = load_local_attendance_log()
        st.session_state["attendance_log_df"] = att_log_df

    # KPI Calculations
    total_drivers = len(drivers_df) if drivers_df is not None else 0
    active_cnt = (
        len(drivers_df[drivers_df["Status"].astype(str).str.upper() == "ACTIVE"])
        if total_drivers > 0
        else 0
    )
    standby_cnt = (
        len(drivers_df[drivers_df["Status"].astype(str).str.upper().isin(["STANDBY", "LEAVE", "ON LEAVE"])])
        if total_drivers > 0
        else 0
    )

    recent_inf_cnt = 0
    if att_log_df is not None and not att_log_df.empty and "Date" in att_log_df.columns:
        parsed_dates = pd.to_datetime(att_log_df["Date"], errors="coerce")
        cutoff_30 = pd.Timestamp.now() - pd.Timedelta(days=30)
        recent_inf_cnt = int((parsed_dates.isna() | (parsed_dates >= cutoff_30)).sum())

    sched_df = load_local_schedule()
    att_metrics_df = calculate_driver_attendance_metrics(sched_df, att_log_df)
    total_sched_shifts = (
        int(att_metrics_df["Scheduled Shifts"].sum()) if not att_metrics_df.empty else 0
    )
    if total_sched_shifts > 0:
        att_rate = max(0.0, 100.0 * (1.0 - (recent_inf_cnt / max(total_sched_shifts * 4, 1))))
        att_rate_str = f"{att_rate:.1f}%"
    else:
        att_rate_str = "100.0%"

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Active Drivers", active_cnt)
    k2.metric("Standby / On Leave", standby_cnt)
    k3.metric("30-Day Infractions", recent_inf_cnt)
    k4.metric("Team Attendance Rate", att_rate_str)

    st.markdown("---")

    sub_nav = st.segmented_control(
        "Driver Section",
        options=["📇 Master Driver Roster", "⏱️ Attendance & Punctuality Log"],
        default="📇 Master Driver Roster",
        label_visibility="collapsed",
        key="driver_dir_sub_nav",
    )
    if not sub_nav:
        sub_nav = "📇 Master Driver Roster"

    # ---------------------------------------------------------
    # 1. MASTER DRIVER DIRECTORY
    # ---------------------------------------------------------
    if sub_nav == "📇 Master Driver Roster":
        hdr_l, hdr_r = st.columns([3, 1])
        with hdr_l:
            f_col1, f_col2 = st.columns([1, 2])
            with f_col1:
                status_filter = st.radio(
                    "Status Filter",
                    options=["ACTIVE", "STANDBY", "INACTIVE", "All"],
                    horizontal=True,
                    key="driver_status_filter",
                )
            with f_col2:
                name_search = st.text_input(
                    "Search Driver",
                    placeholder="Filter by name, ID, or role...",
                    key="driver_search_box",
                ).strip().lower()
        with hdr_r:
            st.markdown("<div style='padding-top: 1.5rem;'></div>", unsafe_allow_html=True)
            save_drivers_btn = st.button(
                "💾 Save Directory",
                type="primary",
                use_container_width=True,
                key="save_drivers_top_btn",
            )

        with st.expander("📤 Import Cortex Associate Roster", expanded=False):
            up_drivers = st.file_uploader(
                "Upload Master Drivers File", type=["xlsx", "xls", "csv"], key="drivers_file_up"
            )
            if up_drivers and st.button("Apply Imported Driver File", type="primary"):
                raw_d = (
                    pd.read_csv(up_drivers)
                    if up_drivers.name.endswith(".csv")
                    else pd.read_excel(up_drivers)
                )
                clean_d = process_driver_data(raw_d)
                safe_save_dataframe(clean_d, MASTER_DRIVERS_PATH)
                load_local_drivers.clear()
                st.session_state["drivers_df"] = clean_d
                st.toast(f"Imported {len(clean_d)} driver profiles!", icon="👥")
                st.rerun()

        disp_drivers = drivers_df.copy()
        if status_filter != "All" and not disp_drivers.empty:
            disp_drivers = disp_drivers[
                disp_drivers["Status"].astype(str).str.upper() == status_filter
            ]
        if name_search and not disp_drivers.empty:
            mask = disp_drivers.apply(
                lambda r: name_search in " ".join(r.astype(str).values).lower(), axis=1
            )
            disp_drivers = disp_drivers[mask]

        driver_col_config = {
            "Driver Name": st.column_config.TextColumn("Driver Name", width="medium"),
            "Transporter ID": st.column_config.TextColumn("Transporter ID", width="medium"),
            "Phone Number": st.column_config.TextColumn("Phone Number", width="medium"),
            "Status": st.column_config.SelectboxColumn(
                "Status", options=["ACTIVE", "STANDBY", "LEAVE", "INACTIVE"], width="small"
            ),
            "Role": st.column_config.SelectboxColumn(
                "Role",
                options=[
                    "Driver Associate",
                    "Step Van Driver",
                    "Sweeper",
                    "Dispatcher",
                    "Operations Manager",
                ],
                width="medium",
            ),
            "Hire Date": st.column_config.TextColumn("Hire Date", width="small"),
            "Preferred Shifts": st.column_config.SelectboxColumn(
                "Schedule Preference",
                options=["Any", "Front Half", "Back Half"],
                width="small",
            ),
            "Overall Score": st.column_config.NumberColumn(
                "Score", min_value=0.0, max_value=100.0, step=0.1, format="%.1f", width="small"
            ),
            "Standing": st.column_config.TextColumn("Standing", width="small"),
        }

        can_add_rows = status_filter == "All" and not name_search
        edited_drivers = st.data_editor(
            disp_drivers,
            column_config=driver_col_config,
            num_rows="dynamic" if can_add_rows else "fixed",
            use_container_width=True,
            hide_index=True,
            key="drivers_master_editor",
        )

        if save_drivers_btn:
            if can_add_rows:
                full_drivers = edited_drivers.copy()
            else:
                full_drivers = drivers_df.copy()
                for _, row in edited_drivers.iterrows():
                    tid = str(row.get("Transporter ID", "")).strip()
                    dname = str(row.get("Driver Name", "")).strip()
                    m = (
                        (full_drivers["Transporter ID"].astype(str).str.strip() == tid)
                        if tid
                        else (full_drivers["Driver Name"].astype(str).str.strip() == dname)
                    )
                    if m.any():
                        for col in edited_drivers.columns:
                            full_drivers.loc[m, col] = row[col]

            safe_save_dataframe(full_drivers, MASTER_DRIVERS_PATH)
            load_local_drivers.clear()
            st.session_state["drivers_df"] = full_drivers
            log_dispatch_action(
                "Updated Master Driver Directory.",
                username=st.session_state.get("user_name"),
            )
            st.toast("Driver directory saved to Cloud Storage!", icon="💾")
            st.rerun()

    # ---------------------------------------------------------
    # 2. ATTENDANCE & PUNCTUALITY LOG
    # ---------------------------------------------------------
    elif sub_nav == "⏱️ Attendance & Punctuality Log":
        active_names = []
        if drivers_df is not None and not drivers_df.empty:
            act = drivers_df[drivers_df["Status"].astype(str).str.upper() == "ACTIVE"]
            active_names = sorted(act["Driver Name"].dropna().astype(str).str.strip().unique().tolist())

        with st.expander("➕ Log Attendance Infraction", expanded=True):
            with st.form("log_attendance_form", clear_on_submit=True):
                ac1, ac2, ac3 = st.columns(3)
                with ac1:
                    att_driver = (
                        st.selectbox("Driver Name", options=active_names)
                        if active_names
                        else st.text_input("Driver Name")
                    )
                with ac2:
                    att_type = st.selectbox("Infraction Type", options=INFRACTION_TYPES)
                with ac3:
                    att_date = st.date_input("Date", value=pd.Timestamp.now().date())

                att_notes = st.text_input(
                    "Notes / Context", placeholder="e.g., Arrived 22 mins after standup"
                )

                if st.form_submit_button("💾 Log Attendance Infraction", type="primary", use_container_width=True):
                    if not str(att_driver).strip():
                        st.error("Driver Name is required.")
                    else:
                        new_rec = pd.DataFrame(
                            [
                                {
                                    "Date": str(att_date),
                                    "Driver Name": str(att_driver).strip(),
                                    "Infraction Type": str(att_type).strip(),
                                    "Logged By": st.session_state.get("user_name", "Dispatch"),
                                    "Notes": str(att_notes).strip(),
                                }
                            ]
                        )
                        updated_att = pd.concat([att_log_df, new_rec], ignore_index=True)
                        safe_save_dataframe(updated_att, ATTENDANCE_LOG_PATH)
                        load_local_attendance_log.clear()
                        st.session_state["attendance_log_df"] = updated_att
                        log_dispatch_action(
                            f"Logged attendance infraction ({att_type}) for {att_driver}.",
                            username=st.session_state.get("user_name"),
                        )
                        st.toast("Attendance infraction logged!", icon="⏱️")
                        st.rerun()

        if not att_metrics_df.empty:
            st.markdown("### 📊 Driver Reliability Summary")
            st.dataframe(att_metrics_df, use_container_width=True, hide_index=True)

        st.markdown("### 📋 Attendance Infraction History")
        if att_log_df is None or att_log_df.empty:
            st.info("No attendance infractions recorded.")
        else:
            st.dataframe(att_log_df.iloc[::-1].reset_index(drop=True), use_container_width=True, hide_index=True)
