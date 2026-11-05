import streamlit as st
import pandas as pd
from engine import (
    save_daily_closing_checklist, 
    log_dispatch_action,
    load_local_access_codes,
    safe_save_dataframe,
    ACCESS_CODES_PATH
)
from modules.roster import update_closing_checklist_assignments

def render_closing_checklist_tab():
    st.subheader("📝 Daily Closing & Debrief Checklist")
    
    active_user = st.session_state.get('user_name', 'Dispatcher')

    if 'closing_df' not in st.session_state or st.session_state['closing_df'] is None or st.session_state['closing_df'].empty:
        if 'current_roster' in st.session_state and not st.session_state['current_roster'].empty:
            update_closing_checklist_assignments(st.session_state['current_roster'], st.session_state)
        else:
            st.session_state['closing_df'] = pd.DataFrame(columns=[
                "Van", "Driver", "Route", "Phone ID", "Bag Returned", 
                "Key Returned", "Phone Returned", "Gas Level", "Miles", "Debrief Notes", "Status"
            ])

    closing_df = st.session_state['closing_df']

    if not closing_df.empty:
        c1, c2 = st.columns([3, 1])
        with c1:
            st.caption("Track return of equipment, gas level, and route debrief status.")
        with c2:
            if st.button("💾 Save Debrief Updates", type="primary", use_container_width=True):
                save_daily_closing_checklist(st.session_state['closing_df'])
                log_dispatch_action("Saved Daily Closing & Debrief Checklist state.", username=active_user)
                st.toast("Closing checklist saved to disk & GCS!", icon="📝")
                st.rerun()

        closing_config = {
            "Van": st.column_config.TextColumn("Van", disabled=True, width="small"),
            "Driver": st.column_config.TextColumn("Driver", disabled=True, width="medium"),
            "Route": st.column_config.TextColumn("Route", disabled=True, width="small"),
            "Phone ID": st.column_config.TextColumn("Phone ID", disabled=True, width="small"),
            "Bag Returned": st.column_config.CheckboxColumn("Bag Ret.", default=False, width="small"),
            "Key Returned": st.column_config.CheckboxColumn("Key Ret.", default=False, width="small"),
            "Phone Returned": st.column_config.CheckboxColumn("Phone Ret.", default=False, width="small"),
            "Gas Level": st.column_config.SelectboxColumn("Gas Level", options=["Full", "3/4", "1/2", "1/4", "Empty"], required=True, width="small"),
            "Miles": st.column_config.NumberColumn("End Miles", min_value=0, step=1, width="small"),
            "Debrief Notes": st.column_config.TextColumn("Debrief Notes / Issues", width="large"),
            "Status": st.column_config.SelectboxColumn("Status", options=["PENDING", "DEBRIEFED", "FLAGGED"], required=True, width="small")
        }

        def on_closing_change():
            changes = st.session_state.get("closing_checklist_editor_state")
            if changes and "closing_df" in st.session_state:
                for row_idx, col_changes in changes.get("edited_rows", {}).items():
                    for col_name, new_val in col_changes.items():
                        st.session_state['closing_df'].at[row_idx, col_name] = new_val
                save_daily_closing_checklist(st.session_state['closing_df'])

        st.data_editor(
            st.session_state['closing_df'],
            column_config=closing_config,
            use_container_width=True,
            hide_index=True,
            key="closing_checklist_editor_state",
            on_change=on_closing_change
        )
    else:
        st.info("No active roster loaded yet. Run auto-assignment or load a roster snapshot in Tab 1 to populate the closing checklist.")

    st.markdown("---")
    st.subheader("🔑 Station & Delivery Access Codes")
    
    access_df = st.session_state.get('access_codes_df')
    if access_df is not None:
        user_role = st.session_state.get('user_role', 'Dispatcher')
        is_admin = (user_role == 'Admin')

        if is_admin:
            st.caption("Manage station gate codes, door access, and locker codes (Admin Edit Mode).")
            edited_access = st.data_editor(
                access_df,
                use_container_width=True,
                hide_index=True,
                num_rows="dynamic",
                key="access_codes_editor_key"
            )
            if st.button("💾 Save Access Codes", type="primary"):
                st.session_state['access_codes_df'] = edited_access.copy()
                safe_save_dataframe(edited_access, ACCESS_CODES_PATH)
                load_local_access_codes.clear()
                log_dispatch_action("Updated Station Access & Gate Codes.", username=active_user)
                st.toast("Access codes saved!", icon="🔑")
                st.rerun()
        else:
            st.caption("Read-Only View for Dispatch Desk.")
            st.dataframe(access_df, use_container_width=True, hide_index=True)
