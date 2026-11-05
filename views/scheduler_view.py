import streamlit as st
import pandas as pd
from modules.schedule import generate_discord_schedule, send_discord_webhook
from engine import WEEKLY_SCHEDULE_PATH, DISCORD_WEBHOOK_URL, safe_save_dataframe, load_local_schedule, log_dispatch_action

def render_scheduler_tab():
    st.subheader("📅 Weekly Shift Scheduler & Discord Publisher")
    
    drivers_df = st.session_state.get('drivers_df')
    active_user = st.session_state.get('user_name', 'Admin')

    if 'schedule_df' not in st.session_state or st.session_state['schedule_df'] is None or st.session_state['schedule_df'].empty:
        loaded_sch = load_local_schedule()
        if loaded_sch.empty and drivers_df is not None and not drivers_df.empty:
            active_drivers = drivers_df[drivers_df['Status'] == 'ACTIVE']['Driver Name'].tolist() if 'Status' in drivers_df.columns else []
            init_sch = []
            for d in active_drivers:
                init_sch.append({
                    "Driver Name": d, 
                    "Sun": "Off", "Mon": "Off", "Tue": "Off", 
                    "Wed": "Off", "Thu": "Off", "Fri": "Off", "Sat": "Off"
                })
            
            sch_df = pd.DataFrame(init_sch)
            sch_df['first_name'] = sch_df['Driver Name'].astype(str).str.strip().str.split().str[0].str.upper()
            st.session_state['schedule_df'] = sch_df.sort_values(by=['first_name', 'Driver Name'], ascending=[True, True]).drop(columns=['first_name']).reset_index(drop=True)
        else:
            # Explicit .copy() to prevent mutating Streamlit cached objects
            st.session_state['schedule_df'] = loaded_sch.copy()

    def on_schedule_change():
        changes = st.session_state.get("weekly_schedule_editor_state")
        if changes and "schedule_df" in st.session_state:
            for row_idx, col_changes in changes.get("edited_rows", {}).items():
                for col_name, new_val in col_changes.items():
                    st.session_state['schedule_df'].at[row_idx, col_name] = new_val

    week_label = st.text_input("Week Label / Date Range", value="18-Oct to 24-Oct")
    st.caption("Assign daily shift options: Driver, Helper, On-Call, Off, OPS-AM, OPS-PM, or Rqst Off.")

    shift_options = ["Driver", "Helper", "On-Call", "Off", "OPS-AM", "OPS-PM", "Rqst Off"]
    
    sch_config = {
        "Driver Name": st.column_config.TextColumn("Driver Name", disabled=True),
        "Sun": st.column_config.SelectboxColumn("Sun", options=shift_options, required=True),
        "Mon": st.column_config.SelectboxColumn("Mon", options=shift_options, required=True),
        "Tue": st.column_config.SelectboxColumn("Tue", options=shift_options, required=True),
        "Wed": st.column_config.SelectboxColumn("Wed", options=shift_options, required=True),
        "Thu": st.column_config.SelectboxColumn("Thu", options=shift_options, required=True),
        "Fri": st.column_config.SelectboxColumn("Fri", options=shift_options, required=True),
        "Sat": st.column_config.SelectboxColumn("Sat", options=shift_options, required=True),
    }

    st.data_editor(
        st.session_state['schedule_df'], 
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
        webhook_input = st.text_input("Discord Webhook URL", value=DISCORD_WEBHOOK_URL, type="password", placeholder="https://discord.com/api/webhooks/...")
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