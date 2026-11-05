import streamlit as st
import pandas as pd
from modules.fleet import process_driver_data
from modules.schedule import calculate_driver_attendance_metrics
from engine import (
    MASTER_DRIVERS_PATH, 
    ATTENDANCE_LOG_PATH, 
    load_local_attendance_log, 
    safe_save_dataframe, 
    log_dispatch_action
)

def render_driver_directory_tab():
    st.subheader("👥 Master Driver Directory & Attendance Accountability")
    drivers = st.session_state.get('drivers_df')
    schedule_df = st.session_state.get('schedule_df')
    active_user = st.session_state.get('user_name', 'Admin')

    st.caption("All team members (including OPS Manager, Dispatchers, Lead DAs, and DAs) are managed here.")

    # 1. ADD NEW DRIVER FORM
    with st.expander("➕ Add New Employee / Driver to Directory", expanded=False):
        with st.form("add_driver_form", clear_on_submit=True):
            col_d1, col_d2, col_d3 = st.columns(3)
            new_d_name = col_d1.text_input("Full Name*")
            new_d_trans = col_d2.text_input("Transporter ID")
            new_d_phone = col_d3.text_input("Phone Number")
            
            col_d4, col_d5, col_d6 = st.columns(3)
            new_d_status = col_d4.selectbox("Employment Status", options=["ACTIVE", "STANDBY", "ON LEAVE", "INACTIVE"], index=0)
            new_d_role = col_d5.selectbox("Primary Role", options=["Driver Associate", "Lead DA", "Sweeper Specialist", "Operations Manager", "Dispatcher"], index=0)
            new_d_hire = col_d6.date_input("Hire Date")

            submit_add_d = st.form_submit_button("Add Driver to Master Roster", type="primary", use_container_width=True)

            if submit_add_d:
                if new_d_name.strip():
                    new_d_row = {
                        "Driver Name": new_d_name.strip(),
                        "Transporter ID": new_d_trans.strip(),
                        "Phone Number": new_d_phone.strip(),
                        "Status": new_d_status,
                        "Role": new_d_role,
                        "Hire Date": str(new_d_hire),
                        "Preferred Shifts": "Mon,Tue,Wed,Thu,Fri,Sat,Sun",
                        "Overall Score": 100.0,
                        "Standing": "Fantastic"
                    }
                    updated_drivers = pd.concat([drivers, pd.DataFrame([new_d_row])], ignore_index=True).reset_index(drop=True)
                    st.session_state['drivers_df'] = process_driver_data(updated_drivers)
                    safe_save_dataframe(st.session_state['drivers_df'], MASTER_DRIVERS_PATH)
                    log_dispatch_action(f"Added driver '{new_d_name.strip()}' to Master Directory.", username=active_user)
                    st.success(f"Added {new_d_name.strip()} to Master Driver Directory!")
                    st.rerun()

    def on_drivers_change():
        changes = st.session_state.get("drivers_directory_editor_state")
        if changes and "drivers_df" in st.session_state:
            for row_idx, col_changes in changes.get("edited_rows", {}).items():
                for col_name, new_val in col_changes.items():
                    st.session_state['drivers_df'].at[row_idx, col_name] = new_val

    st.data_editor(
        drivers,
        column_config={
            "Driver Name": st.column_config.TextColumn("Driver Name", required=True),
            "Status": st.column_config.SelectboxColumn("Status", options=["ACTIVE", "STANDBY", "ON LEAVE", "INACTIVE"], required=True),
            "Role": st.column_config.SelectboxColumn("Primary Role", options=["Driver Associate", "Lead DA", "Sweeper Specialist", "Operations Manager", "Dispatcher"], required=True),
            "Overall Score": st.column_config.NumberColumn("Scorecard Rank", format="%.2f"),
        },
        use_container_width=True,
        num_rows="dynamic",
        hide_index=True,
        key="drivers_directory_editor_state",
        on_change=on_drivers_change
    )

    if st.button("💾 Save Master Driver Directory to Disk", type="primary"):
        st.session_state['drivers_df'] = process_driver_data(st.session_state['drivers_df'])
        safe_save_dataframe(st.session_state['drivers_df'], MASTER_DRIVERS_PATH)
        log_dispatch_action("Saved Master Driver Directory updates to disk.", username=active_user)
        st.success("Master Driver Roster saved permanently!")

    # ---------------------------------------------------------
    # 2. DEDICATED DRIVER ATTENDANCE & ACCOUNTABILITY LOG
    # ---------------------------------------------------------
    st.markdown("---")
    st.subheader("📌 Daily Driver Attendance & Infraction Log")
    st.caption("Quickly log call-outs, late arrivals, no-shows, or unexcused absences without touching the daily roster.")

    if 'attendance_log_df' not in st.session_state or st.session_state['attendance_log_df'] is None:
        st.session_state['attendance_log_df'] = load_local_attendance_log()

    attendance_log = st.session_state['attendance_log_df']

    with st.expander("🚨 Record New Attendance Infraction", expanded=True):
        active_driver_options = sorted(drivers[drivers['Status'] == 'ACTIVE']['Driver Name'].tolist()) if 'Status' in drivers.columns else []
        
        with st.form("log_infraction_form", clear_on_submit=True):
            col_i1, col_i2, col_i3 = st.columns(3)
            sel_inf_driver = col_i1.selectbox("Driver Name*", options=active_driver_options if active_driver_options else ["No Active Drivers"])
            sel_inf_type = col_i2.selectbox("Infraction Type*", options=[
                "LATE START", 
                "CALL-OUT (EXCUSED)", 
                "CALL-OUT (UNEXCUSED)", 
                "NO-SHOW", 
                "INCOMPLETE / LEFT EARLY"
            ])
            sel_inf_date = col_i3.date_input("Shift Date", value=pd.Timestamp.now())

            inf_notes = st.text_input("Notes / Context", placeholder="e.g. Called out 10 mins before wave launch via text")

            submit_infraction = st.form_submit_button("🚨 Commit Attendance Infraction to Log", type="primary", use_container_width=True)

            if submit_infraction:
                if sel_inf_driver and sel_inf_driver != "No Active Drivers":
                    # FIXED: Explicitly cast sel_inf_date to str
                    new_inf_row = {
                        "Date": str(sel_inf_date),
                        "Driver Name": sel_inf_driver,
                        "Infraction Type": sel_inf_type,
                        "Logged By": active_user,
                        "Notes": inf_notes.strip()
                    }
                    updated_att_log = pd.concat([attendance_log, pd.DataFrame([new_inf_row])], ignore_index=True).reset_index(drop=True)
                    st.session_state['attendance_log_df'] = updated_att_log
                    safe_save_dataframe(st.session_state['attendance_log_df'], ATTENDANCE_LOG_PATH)
                    
                    log_dispatch_action(f"ATTENDANCE LOGGED: '{sel_inf_driver}' marked '{sel_inf_type}' on {sel_inf_date}.", username=active_user)
                    st.success(f"Logged {sel_inf_type} for {sel_inf_driver}!")
                    st.rerun()

    if not attendance_log.empty:
        st.markdown("#### Historical Infraction Log Ledger")
        
        def on_att_log_change():
            changes = st.session_state.get("attendance_log_editor_state")
            if changes and "attendance_log_df" in st.session_state:
                for row_idx, col_changes in changes.get("edited_rows", {}).items():
                    for col_name, new_val in col_changes.items():
                        st.session_state['attendance_log_df'].at[row_idx, col_name] = new_val

        st.data_editor(
            st.session_state['attendance_log_df'],
            use_container_width=True,
            num_rows="dynamic",
            hide_index=True,
            key="attendance_log_editor_state",
            on_change=on_att_log_change
        )

        if st.button("💾 Save Infraction Ledger Updates", type="secondary"):
            safe_save_dataframe(st.session_state['attendance_log_df'], ATTENDANCE_LOG_PATH)
            st.success("Infraction ledger saved!")
            st.rerun()

    # ---------------------------------------------------------
    # 3. ATTENDANCE & RELIABILITY ANALYTICS TABLE
    # ---------------------------------------------------------
    st.markdown("---")
    st.subheader("📊 Driver Reliability & Attendance Ratings")
    st.caption("Calculates total infractions recorded against weekly schedule assignments.")

    attendance_analytics_df = calculate_driver_attendance_metrics(schedule_df, st.session_state['attendance_log_df'])
    st.dataframe(attendance_analytics_df, use_container_width=True, hide_index=True)