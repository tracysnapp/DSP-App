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
            st.caption("Click any van's **Status** cell to toggle between **UP** and **DOWN**. Save changes when finished.")
            
            # Interactive UP/DOWN dropdown options for all users
            status_options = ["UP", "DOWN"]
            
            # Map column configuration dynamically matching clean or raw column names
            status_col = 'status_clean' if 'status_clean' in fleet_df.columns else ('Status' if 'Status' in fleet_df.columns else fleet_df.columns[0])
            name_col = 'vehicleName' if 'vehicleName' in fleet_df.columns else fleet_df.columns[0]
            vin_col = 'vin_clean' if 'vin_clean' in fleet_df.columns else ('VIN' if 'VIN' in fleet_df.columns else fleet_df.columns[0])
            st_col = 'serviceType_clean' if 'serviceType_clean' in fleet_df.columns else ('Service Type' if 'Service Type' in fleet_df.columns else fleet_df.columns[0])
            driven_col = 'last_driven_clean' if 'last_driven_clean' in fleet_df.columns else ('Last Driven' if 'Last Driven' in fleet_df.columns else fleet_df.columns[0])
            remarks_col = 'remarks_clean' if 'remarks_clean' in fleet_df.columns else ('Remarks' if 'Remarks' in fleet_df.columns else fleet_df.columns[-1])

            fleet_config = {
                name_col: st.column_config.TextColumn("Van Bumper", disabled=True),
                vin_col: st.column_config.TextColumn("VIN", disabled=True),
                st_col: st.column_config.TextColumn("Size Bracket", disabled=True),
                status_col: st.column_config.SelectboxColumn("Status (UP/DOWN)", options=status_options, required=True),
                driven_col: st.column_config.TextColumn("Last Driven", disabled=True),
                remarks_col: st.column_config.TextColumn("Remarks / Maintenance Notes")
            }

            edited_fleet = st.data_editor(
                fleet_df,
                column_config=fleet_config,
                use_container_width=True,
                hide_index=True,
                key="fleet_editor_key"
            )

            if st.button("💾 Save Fleet Vehicle Changes", type="primary", use_container_width=True):
                updated_fleet = process_fleet_data(edited_fleet)
                st.session_state['fleet_df'] = updated_fleet
                safe_save_dataframe(updated_fleet, MASTER_FLEET_PATH)
                load_local_fleet.clear()
                log_dispatch_action("Updated Fleet Vehicle Status master record.", username=active_user)
                st.toast("Fleet vehicle status saved!", icon="🚐")
                st.rerun()
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
