import streamlit as st
import pandas as pd
from datetime import timedelta
from modules.schedule import generate_discord_schedule, send_discord_webhook
from engine import WEEKLY_SCHEDULE_PATH, DISCORD_WEBHOOK_URL, safe_save_dataframe, load_local_schedule, log_dispatch_action

def render_scheduler_tab():
    st.subheader("📅 Weekly Shift Scheduler & Discord Publisher")
    
    drivers_df = st.session_state.get('drivers_df')
    active_user = st.session_state.get('user_name', 'Admin')

    # 1. Dynamic Date & Route Target Controls
    c_date, c_routes = st.columns(2)
    with c_date:
        start_date = st.date_input("Schedule Start Date (Sunday)")
        week_label = f"{start_date.strftime('%d-%b')} to {(start_date + timedelta(days=6)).strftime('%d-%b')}"
        st.caption(f"**Week Label:** {week_label}")
    with c_routes:
        expected_routes = st.number_input("Expected Daily Routes (Station Target)", min_value=0, value=25)

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
            # Sort cleanly by Last Name, First Name
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

    # 2. Live Coverage Dashboard & Delta (+/-) Tracking
    st.markdown("### 📊 Daily Coverage vs. Station Targets")
    days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    metrics_cols = st.columns(7)
    
    for i, day in enumerate(days):
        driver_count = len(st.session_state['schedule_df'][st.session_state['schedule_df'][day] == "Driver"])
        delta = driver_count - expected_routes
        metrics_cols[i].metric(label=day, value=driver_count, delta=delta)

    # 3. Calculate Shift Totals for Overtime/Compliance Guardrails
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
        webhook_input = st.text_input("Discord Webhook URL", value=DISCORD_WEBHOOK_URL, type="password")
        if st.button("Broadcast Schedule to Discord Channel", type="primary"):
            if webhook_input.strip():
                success, msg = send_discord_webhook(webhook_input.strip(), discord_text)
                if success:
                    log_dispatch_action(f"Broadcast weekly schedule to Discord ({week_label}).", username=active_user)
                    st.success(msg)
                else:
                    st.error(msg)
            else:
                st.warning("Please provide a valid Discord Webhook URL.")
