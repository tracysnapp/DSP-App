import streamlit as st
import pandas as pd
import streamlit.components.v1 as components
from engine import save_daily_closing_checklist, HISTORY_DIR, log_dispatch_action
from modules.roster import update_closing_checklist_assignments, generate_printable_closing_html

def render_closing_checklist_tab():
    st.subheader("📝 End of Day Driver Closing & Debrief Checklist")
    
    if 'current_roster' in st.session_state and not st.session_state['current_roster'].empty:
        roster_df = st.session_state['current_roster'].copy().reset_index(drop=True)
        active_user = st.session_state.get('user_name', 'Dispatcher')
        
        # FIXED: Reference 'Van' instead of 'Van Number' to avoid wiping live debrief data
        if 'closing_df' not in st.session_state or st.session_state['closing_df'] is None or st.session_state['closing_df'].empty or "Van" not in st.session_state['closing_df'].columns:
            update_closing_checklist_assignments(roster_df, st.session_state)

        closing_data = st.session_state['closing_df'].copy()

        # DEBRIEF UNRETURNED EQUIPMENT AUDIT BANNER
        unreturned_keys = len(closing_data[closing_data['Keys Returned'].astype(str).str.strip().str.upper().isin(['NO', 'FALSE', 'N'])])
        unreturned_phones = len(closing_data[closing_data['Phone Returned'].astype(str).str.strip().str.upper().isin(['NO', 'FALSE', 'N'])])

        if unreturned_keys > 0 or unreturned_phones > 0:
            st.warning(f"⚠️ **Debrief Equipment Audit Alert:** `{unreturned_keys}` Unreturned Key Set(s) | `{unreturned_phones}` Unreturned Device(s) logged!")

        def on_closing_change():
            changes = st.session_state.get("closing_checklist_editor_state")
            if changes and "closing_df" in st.session_state:
                for row_idx, col_changes in changes.get("edited_rows", {}).items():
                    for col_name, new_val in col_changes.items():
                        st.session_state['closing_df'].at[row_idx, col_name] = new_val

        # FIXED: Updated 'Van Number' column config key to 'Van'
        closing_config = {
            "Driver Name": st.column_config.TextColumn("Driver Name", width="medium", disabled=True),
            "Van": st.column_config.TextColumn("Van", width="small", disabled=True),
            "Clock out time": st.column_config.TextColumn("Clock out time", width="small"),
            "DVIC Complete": st.column_config.SelectboxColumn("DVIC Complete", options=["YES", "NO"], width="small"),
            "Damage?": st.column_config.SelectboxColumn("Damage?", options=["NO", "YES - NEW", "PRE-EXISTING"], width="small"),
            "Cleaned?": st.column_config.SelectboxColumn("Cleaned?", options=["YES", "NO"], width="small"),
            "Keys Returned": st.column_config.SelectboxColumn("Keys Returned", options=["YES", "NO"], width="small"),
            "Phone Returned": st.column_config.SelectboxColumn("Phone Returned", options=["YES", "NO"], width="small"),
            "Portable Charger": st.column_config.SelectboxColumn("Portable Charger", options=["YES", "NO", "N/A"], width="small"),
            "Fuel Card Returned": st.column_config.SelectboxColumn("Fuel Card Returned", options=["YES", "NO"], width="small"),
            "Fuel Level": st.column_config.SelectboxColumn("Fuel Level", options=["100%", "75%", "50%", "25%", "LOW"], width="small"),
            "Packages/Returns Handled": st.column_config.TextColumn("Packages/Returns Handled", width="medium"),
            "Remarks": st.column_config.TextColumn("Remarks", width="medium"),
            "DA Signature": st.column_config.TextColumn("DA Signature", width="medium")
        }

        st.data_editor(
            st.session_state['closing_df'],
            column_config=closing_config,
            use_container_width=True,
            num_rows="fixed",
            hide_index=True,
            key="closing_checklist_editor_state",
            on_change=on_closing_change
        )
        
        c_btn1, c_btn2 = st.columns(2)
        with c_btn1:
            if st.button("💾 Save Closing Checklist Log to Disk", type="primary"):
                save_daily_closing_checklist(st.session_state['closing_df'])
                log_dispatch_action(f"Saved EOD debrief closing checklist log ({len(st.session_state['closing_df'])} drivers).", username=active_user)
                st.success(f"Saved EOD debrief log and created snapshot in {HISTORY_DIR}/!")
        with c_btn2:
            closing_csv = st.session_state['closing_df'].to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download Closing Checklist CSV",
                data=closing_csv,
                file_name="daily_closing_checklist.csv",
                mime="text/csv"
            )

        st.markdown("---")
        st.subheader("🖨️ Printable Handwritten Closing Checklist (Sorted Numerically by Van Number)")
        
        closing_html_view = generate_printable_closing_html(st.session_state['closing_df'])
        components.html(closing_html_view, height=500, scrolling=True)

    else:
        st.info("Run auto-assignment on Tab 1 to populate today's driver and van assignments into the Closing Checklist.")