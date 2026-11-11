import streamlit as st
import pandas as pd
from engine import (
    MASTER_FLEET_PATH, 
    MASTER_PHONES_PATH, 
    safe_save_dataframe, 
    log_dispatch_action, 
    load_local_fleet, 
    load_local_phones
)
from modules.fleet import process_fleet_data, process_phone_data

def render_fleet_tab():
    st.subheader("🚐 Fleet & Phone Roster Management")
    
    user_role = st.session_state.get('user_role', 'Dispatcher')
    active_user = st.session_state.get('user_name', 'User')
    is_admin = (user_role == 'Admin')

    fleet_df = st.session_state.get('fleet_df')
    phones_df = st.session_state.get('phones_df')

    tab_fleet_view, tab_phones_view = st.tabs(["🚐 Fleet Vehicle Status", "📱 Phone & Device Roster"])

    # ---------------------------------------------------------
    # TAB 1: FLEET VEHICLE STATUS
    # ---------------------------------------------------------
    with tab_fleet_view:
        st.markdown("### Fleet Vehicle Master List")
        if fleet_df is not None and not fleet_df.empty:
            if is_admin:
                st.caption("Editable view (Admin Mode). Changes update local and cloud storage.")
                
                # Restricted to UP or DOWN dropdown options per user requirement
                status_options = ["UP", "DOWN"]
                fleet_config = {
                    "vehicleName": st.column_config.TextColumn("Van Bumper", disabled=True),
                    "vin_clean": st.column_config.TextColumn("VIN", disabled=True),
                    "serviceType_clean": st.column_config.TextColumn("Size Bracket", disabled=True),
                    "status_clean": st.column_config.SelectboxColumn("Status", options=status_options, required=True),
                    "last_driven_clean": st.column_config.TextColumn("Last Driven", disabled=True),
                    "remarks_clean": st.column_config.TextColumn("Remarks / Notes")
                }

                edited_fleet = st.data_editor(
                    fleet_df,
                    column_config=fleet_config,
                    use_container_width=True,
                    hide_index=True,
                    key="fleet_editor_key"
                )

                if st.button("💾 Save Fleet Vehicle Changes", type="primary"):
                    st.session_state['fleet_df'] = process_fleet_data(edited_fleet)
                    safe_save_dataframe(st.session_state['fleet_df'], MASTER_FLEET_PATH)
                    load_local_fleet.clear()
                    log_dispatch_action("Updated Fleet Vehicle Status master record.", username=active_user)
                    st.toast("Fleet vehicle status saved!", icon="🚐")
                    st.rerun()
            else:
                st.caption("Read-Only Dispatch View.")
                st.dataframe(fleet_df, use_container_width=True, hide_index=True)
        else:
            st.warning("No fleet data available. Please verify master_fleet.xlsx file exists.")

    # ---------------------------------------------------------
    # TAB 2: PHONE & DEVICE ROSTER
    # ---------------------------------------------------------
    with tab_phones_view:
        st.markdown("### Dispatch Phone & Device Inventory")
        if phones_df is not None and not phones_df.empty:
            if is_admin:
                st.caption("Editable view (Admin Mode). Manage phone assignments and device statuses.")
                
                phone_status_options = ["ACTIVE", "SPARE", "REPAIR", "INACTIVE", "DELETED"]
                phones_config = {
                    "device_clean": st.column_config.TextColumn("Device ID / Phone Name", required=True),
                    "number_clean": st.column_config.TextColumn("Phone Number"),
                    "van_assignment": st.column_config.TextColumn("Assigned Van Bumper"),
                    "status_clean": st.column_config.SelectboxColumn("Device Status", options=phone_status_options, required=True),
                    "notes": st.column_config.TextColumn("Notes / Condition")
                }

                edited_phones = st.data_editor(
                    phones_df,
                    column_config=phones_config,
                    use_container_width=True,
                    hide_index=True,
                    num_rows="dynamic",
                    key="phones_editor_key"
                )

                if st.button("💾 Save Phone Roster Changes", type="primary"):
                    st.session_state['phones_df'] = process_phone_data(edited_phones)
                    safe_save_dataframe(st.session_state['phones_df'], MASTER_PHONES_PATH)
                    load_local_phones.clear()
                    log_dispatch_action("Updated Phone & Device Roster master record.", username=active_user)
                    st.toast("Phone roster saved!", icon="📱")
                    st.rerun()
            else:
                st.caption("Read-Only Dispatch View.")
                st.dataframe(phones_df, use_container_width=True, hide_index=True)
        else:
            st.warning("No phone roster data available. Please verify master_phones.xlsx file exists.")
