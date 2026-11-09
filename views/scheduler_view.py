import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from modules.schedule import generate_discord_schedule, send_discord_webhook
from engine import WEEKLY_SCHEDULE_PATH, DISCORD_WEBHOOK_URL, safe_save_dataframe, load_local_schedule, log_dispatch_action
import os

LONG_RANGE_PTO_PATH = "data/long_range_pto.csv"

def load_long_range_pto():
    if os.path.exists(LONG_RANGE_PTO_PATH):
        try:
            return pd.read_csv(LONG_RANGE_PTO_PATH)
        except Exception:
            pass
    return pd.DataFrame(columns=["Driver Name", "Start Date", "End Date", "Category", "Reason / Notes"])

def render_scheduler_tab():
    st.subheader("📅 JNAL Operations: Scheduling & Long-Range Calendar")
    
    tab_weekly, tab_pto = st.tabs(["Weekly Shift Scheduler", "Long-Range PTO & Availability Calendar"])

    drivers_df = st.session_state.get('drivers_df')
    active_user = st.session_state.get('user_name', 'Admin')

    # ==========================================
    # TAB 1: WEEKLY SHIFT SCHEDULER
    # ==========================================
    with tab_weekly:
        c_date, c_routes = st.columns(2)
        with c_date:
            start_date = st.date_input("Schedule Start Date (Sunday)", key="sched_start_date")
            week_label = f"{start_date.strftime('%d-%b')} to {(start_date + timedelta(days=6)).strftime('%d-%b')}"
            st.caption(f"**Week Label:** {week_label}")
        with c_routes:
            expected_routes = st.number_input("Expected Daily Routes (Station Target)", min_value=0, value=25, key="sched_expected_routes")

        if 'schedule_df' not in st.session_state or st.session_state['schedule_df'] is None or st.session_state['schedule_df'].empty:
            loaded_sch = load_local_schedule()
            if loaded_sch.empty and drivers_df is not None and not drivers_df.empty:
                active_drivers = drivers_df[drivers_df['Status'] == 'ACTIVE'] if 'Status' in drivers_df.columns else drivers_df
                init_sch = []
                for _, row in active_drivers.iterrows():
                    full_name = str(row.get('Driver Name', ''))
                    parts = full_name.split(' ', 1)
                    last_name = parts[0] if len(parts) > 1 else full_name
                    first_name = parts[1] if len(parts) > 1 else ''
                    
                    init_sch.append({
                        "Last Name": last_name,
                        "First Name": first_name,
                        "Sun": "Off", "Mon": "Off", "Tue": "Off", 
                        "Wed": "Off", "Thu": "Off", "Fri": "Off", "Sat": "Off",
                        "Notes / Requests": ""
                    })
                sch_df = pd.DataFrame(init_sch)
                st.session_state['schedule_df'] = sch_df.sort_values(by=['Last Name', 'First Name'], ascending=[True, True]).reset_index(drop=True)
            else:
                st.session_state['schedule_df'] = loaded_sch.copy()

        def on_schedule_change():
            changes = st.session_state.get("weekly_schedule_editor_state")
            if changes and "schedule_df" in st.session_state:
                for row_idx, col_changes in changes.get("edited_rows", {}).items():
                    for col_name, new_val in col_changes.items():
                        if col_name in st.session_state['schedule_df'].columns:
                            st.session_state['schedule_df'].at[row_idx, col_name] = new_val

        st.markdown("### 📊 Daily Coverage vs. Station Targets")
        days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        metrics_cols = st.columns(7)
        
        for i, day in enumerate(days):
            driver_count = len(st.session_state['schedule_df'][st.session_state['schedule_df'][day] == "Driver"])
            delta = driver_count - expected_routes
            metrics_cols[i].metric(label=day, value=driver_count, delta=delta)

        df_display = st.session_state['schedule_df'].copy()
        work_shifts = ["Driver", "Helper", "OPS-AM", "OPS-PM"]
        df_display['Total Days'] = df_display[days].isin(work_shifts).sum(axis=1)

        st.caption("Assign shift options. Use the 'Notes / Requests' column to track driver PTO and availability constraints.")

        shift_options = ["Driver", "Helper", "On-Call", "Off", "OPS-AM", "OPS-PM", "Rqst Off"]
        
        sch_config = {
            "Last Name": st.column_config.TextColumn("Last Name", disabled=True),
            "First Name": st.column_config.TextColumn("First Name", disabled=True),
            "Sun": st.column_config.SelectboxColumn("Sun", options=shift_options, required=True),
            "Mon": st.column_config.SelectboxColumn("Mon", options=shift_options, required=True),
            "Tue": st.column_config.SelectboxColumn("Tue", options=shift_options, required=True),
            "Wed": st.column_config.SelectboxColumn("Wed", options=shift_options, required=True),
            "Thu": st.column_config.SelectboxColumn("Thu", options=shift_options, required=True),
            "Fri": st.column_config.SelectboxColumn("Fri", options=shift_options, required=True),
            "Sat": st.column_config.SelectboxColumn("Sat", options=shift_options, required=True),
            "Total Days": st.column_config.NumberColumn("Total Days", disabled=True, format="%d days"),
            "Notes / Requests": st.column_config.TextColumn("Notes / Requests", help="Record vacation dates or scheduling restrictions here.")
        }

        st.data_editor(
            df_display, 
            column_config=sch_config, 
            use_container_width=True, 
            num_rows="dynamic", 
            hide_index=True, 
            key="weekly_schedule_editor_state",
            on_change=on_schedule_change
        )

        c_s1, c_s2 = st.columns(2)
        with c_s1:
            if st.button("💾 Save Weekly Schedule to Disk", type="primary"):
                safe_save_dataframe(st.session_state['schedule_df'], WEEKLY_SCHEDULE_PATH)
                log_dispatch_action(f"Saved weekly schedule ({week_label}).", username=active_user)
                st.success("Weekly schedule saved permanently!")

        st.markdown("---")
        st.subheader("📢 Discord Announcement Generator (#weekly-schedule)")
        discord_text = generate_discord_schedule(st.session_state['schedule_df'], week_str=week_label)
        st.code(discord_text, language="markdown")

        with st.expander("🚀 Post Schedule Directly to Discord Channel"):
            webhook_input = st.text_input("Discord Webhook URL", value=DISCORD_WEBHOOK_URL, type="password", key="disc_webhook_weekly")
            if st.button("Broadcast Schedule to Discord Channel", type="primary", key="btn_disc_weekly"):
                if webhook_input.strip():
                    success, msg = send_discord_webhook(webhook_input.strip(), discord_text)
                    if success:
                        log_dispatch_action(f"Broadcast weekly schedule to Discord ({week_label}).", username=active_user)
                        st.success(msg)
                    else:
                        st.error(msg)
                else:
                    st.warning("Please provide a valid Discord Webhook URL.")

    # ==========================================
    # TAB 2: LONG-RANGE PTO & AVAILABILITY CALENDAR
    # ==========================================
    with tab_pto:
        st.markdown("### 🌴 Long-Range Driver PTO & Requests Tracker")
        st.caption("Log upcoming driver time-off, doctor appointments, or availability blocks well in advance to prevent weekly scheduling errors.")

        if 'pto_df' not in st.session_state:
            st.session_state['pto_df'] = load_long_range_pto()

        # Quick add form
        with st.form("pto_entry_form", clear_on_submit=True):
            st.markdown("#### Log New Request")
            f_col1, f_col2, f_col3, f_col4 = st.columns(4)
            
            # Get driver list names
            driver_names = []
            if drivers_df is not None and 'Driver Name' in drivers_df.columns:
                driver_names = sorted(drivers_df['Driver Name'].dropna().unique().tolist())
            elif 'schedule_df' in st.session_state and not st.session_state['schedule_df'].empty:
                driver_names = sorted((st.session_state['schedule_df']['Last Name'] + ", " + st.session_state['schedule_df']['First Name']).unique().tolist())
            else:
                driver_names = ["Manual Entry Required"]

            with f_col1:
                sel_driver = st.selectbox("Driver Name", options=driver_names)
            with f_col2:
                start_p_date = st.date_input("Start Date", value=datetime.today())
            with f_col3:
                end_p_date = st.date_input("End Date", value=datetime.today())
            with f_col4:
                category = st.selectbox("Category", options=["Approved PTO", "Unpaid Leave", "Appointment / Partial Off", "No Sundays", "Other Constraint"])
            
            reason_notes = st.text_input("Reason / Notes (e.g., Family vacation, Doctor visit)")
            
            submitted_pto = st.form_submit_button("➕ Add to Long-Range Calendar", type="primary")
            if submitted_pto:
                new_row = {
                    "Driver Name": sel_driver,
                    "Start Date": start_p_date.strftime("%Y-%m-%d"),
                    "End Date": end_p_date.strftime("%Y-%m-%d"),
                    "Category": category,
                    "Reason / Notes": reason_notes
                }
                st.session_state['pto_df'] = pd.concat([st.session_state['pto_df'], pd.DataFrame([new_row])], ignore_index=True)
                
                # Ensure directory exists and save
                os.makedirs(os.path.dirname(LONG_RANGE_PTO_PATH), exist_ok=True)
                st.session_state['pto_df'].to_csv(LONG_RANGE_PTO_PATH, index=False)
                log_dispatch_action(f"Added long-range PTO request for {sel_driver} ({start_p_date} to {end_p_date}).", username=active_user)
                st.success(f"Successfully recorded PTO request for {sel_driver}!")

        st.markdown("---")
        st.markdown("### 📋 Active Requests Log")
        
        def on_pto_change():
            changes = st.session_state.get("pto_editor_state")
            if changes and "pto_df" in st.session_state:
                for row_idx, col_changes in changes.get("edited_rows", {}).items():
                    for col_name, new_val in col_changes.items():
                        st.session_state['pto_df'].at[row_idx, col_name] = new_val

        pto_config = {
            "Driver Name": st.column_config.TextColumn("Driver Name"),
            "Start Date": st.column_config.TextColumn("Start Date"),
            "End Date": st.column_config.TextColumn("End Date"),
            "Category": st.column_config.SelectboxColumn("Category", options=["Approved PTO", "Unpaid Leave", "Appointment / Partial Off", "No Sundays", "Other Constraint"], required=True),
            "Reason / Notes": st.column_config.TextColumn("Reason / Notes")
        }

        edited_pto_df = st.data_editor(
            st.session_state['pto_df'],
            column_config=pto_config,
            use_container_width=True,
            num_rows="dynamic",
            hide_index=True,
            key="pto_editor_state",
            on_change=on_pto_change
        )

        c_p1, c_p2 = st.columns(2)
        with c_p1:
            if st.button("💾 Save Long-Range Calendar to Disk", type="primary", key="save_pto_disk"):
                os.makedirs(os.path.dirname(LONG_RANGE_PTO_PATH), exist_ok=True)
                edited_pto_df.to_csv(LONG_RANGE_PTO_PATH, index=False)
                st.session_state['pto_df'] = edited_pto_df.copy()
                log_dispatch_action("Updated long-range PTO calendar database.", username=active_user)
                st.success("Long-range calendar saved successfully!")
