import streamlit as st
import pandas as pd
from modules.fleet import process_fleet_data, process_phone_data, sync_live_roster_phones
from engine import MASTER_FLEET_PATH, MASTER_PHONES_PATH, safe_save_dataframe

def render_fleet_tab(is_admin=True):
    st.subheader("Live Vehicle Fleet Tracker & Grounded Log")
    fleet = st.session_state.get('fleet_df')
    
    if fleet is not None:
        m1, m2, m3 = st.columns(3)
        total_vans = len(fleet)
        active_vans = len(fleet[fleet['status_clean'].isin(['UP', 'ACTIVE', 'OPERATIONAL', 'WORKABLE', 'AVAILABLE'])]) if 'status_clean' in fleet.columns else len(fleet)
        grounded_vans = len(fleet[fleet['status_clean'] == 'DOWN']) if 'status_clean' in fleet.columns else 0
        
        m1.metric("Total Fleet Count", total_vans)
        m2.metric("Active Vans (UP)", active_vans)
        m3.metric("Down / Grounded", grounded_vans, delta_color="inverse")
        
        st.markdown("---")

        # ADMIN ONLY: Add Vehicle & Archive Forms
        if is_admin:
            with st.expander("➕ / 📦 Add New Vehicle or Archive/Retire Rental Van", expanded=False):
                col_add_v, col_rem_v = st.columns(2)

                with col_add_v:
                    st.markdown("#### ➕ Add New Vehicle")
                    with st.form("add_vehicle_form", clear_on_submit=True):
                        new_bumper = st.text_input("Bumper # / Vehicle ID*", placeholder="e.g. 105 or rental ID")
                        new_st = st.selectbox("Service Type (ST)*", options=["M", "L", "XL", "ORE"], index=0)
                        new_status = st.selectbox("Initial Status*", options=["UP", "DOWN"], index=0)
                        new_make = st.text_input("Make / Model", placeholder="e.g. RAM ProMaster 3500")
                        new_vin = st.text_input("VIN", placeholder="17-character VIN")
                        new_plate = st.text_input("License Plate", placeholder="e.g. ABC1234")
                        new_state = st.text_input("State", value="FL")
                        new_remarks = st.text_input("Remarks / Notes", placeholder="e.g. Rental addition")

                        submit_add_v = st.form_submit_button("Add Vehicle to Fleet", type="primary", use_container_width=True)

                        if submit_add_v:
                            if new_bumper.strip():
                                existing_bumpers = fleet['vehicleName'].astype(str).str.strip().tolist() if 'vehicleName' in fleet.columns else []
                                if new_bumper.strip() in existing_bumpers:
                                    st.error(f"Vehicle #{new_bumper.strip()} already exists in fleet!")
                                else:
                                    new_v_row = {
                                        'Bumper #': new_bumper.strip(),
                                        'ST': new_st,
                                        'Status': new_status,
                                        'Make': new_make.strip(),
                                        'VIN': new_vin.strip(),
                                        'Plate': new_plate.strip(),
                                        'State': new_state.strip(),
                                        'Remarks': new_remarks.strip()
                                    }
                                    updated_fleet = pd.concat([fleet, pd.DataFrame([new_v_row])], ignore_index=True)
                                    st.session_state['fleet_df'] = process_fleet_data(updated_fleet)
                                    safe_save_dataframe(st.session_state['fleet_df'], MASTER_FLEET_PATH)
                                    
                                    if 'current_roster' in st.session_state and not st.session_state['current_roster'].empty:
                                        st.session_state['current_roster'] = sync_live_roster_phones(st.session_state['current_roster'], st.session_state['phones_df'])

                                    st.success(f"Added Vehicle #{new_bumper.strip()} to master fleet!")
                                    st.rerun()
                            else:
                                st.warning("Bumper # is required.")

                with col_rem_v:
                    st.markdown("#### 📦 Archive / Retire Vehicle")
                    st.caption("Marks van status as RETIRED or RETURNED instead of deleting historical data.")
                    all_fleet_bumpers = sorted(fleet['vehicleName'].astype(str).str.strip().unique().tolist()) if 'vehicleName' in fleet.columns else []
                    if all_fleet_bumpers:
                        archive_v_sel = st.selectbox("Select Vehicle to Archive", options=["Select vehicle..."] + all_fleet_bumpers)
                        archive_reason = st.selectbox("Archival Status Reason", options=["RETIRED", "RETURNED (RENTAL)", "DELETED"], index=0)

                        if st.button("Confirm Soft Delete / Retire", type="secondary", use_container_width=True):
                            if archive_v_sel != "Select vehicle...":
                                updated_fleet = fleet.copy()
                                target_idx = updated_fleet[updated_fleet['vehicleName'].astype(str).str.strip() == archive_v_sel].index
                                updated_fleet.loc[target_idx, 'Status'] = archive_reason
                                
                                st.session_state['fleet_df'] = process_fleet_data(updated_fleet)
                                safe_save_dataframe(st.session_state['fleet_df'], MASTER_FLEET_PATH)
                                
                                if 'current_roster' in st.session_state and not st.session_state['current_roster'].empty:
                                    st.session_state['current_roster'] = sync_live_roster_phones(st.session_state['current_roster'], st.session_state['phones_df'])

                                st.success(f"Archived Vehicle #{archive_v_sel} as {archive_reason}!")
                                st.rerun()
                            else:
                                st.warning("Select a vehicle to archive.")
                    else:
                        st.info("No vehicles available in fleet directory.")

            st.markdown("---")

        st.write("### Manage Fleet Statuses")
        if not is_admin:
            st.caption("🔒 Dispatch Desk Access: Edit Status (UP / DOWN) and Remarks only.")

        display_cols = [c for c in ['Bumper #', 'ST', 'Status', 'Make', 'VIN', 'Plate', 'State', 'Remarks'] if c in fleet.columns]
        
        editor_key = f"fleet_tracker_editor_{'admin' if is_admin else 'dispatch'}"

        def on_fleet_change():
            changes = st.session_state.get(editor_key)
            if changes and "fleet_df" in st.session_state:
                for row_idx, col_changes in changes.get("edited_rows", {}).items():
                    for col_name, new_val in col_changes.items():
                        st.session_state['fleet_df'].at[row_idx, col_name] = new_val

        column_configurations = {
            "Bumper #": st.column_config.Column(disabled=True),
            "ST": st.column_config.Column(disabled=not is_admin),
            "Make": st.column_config.Column(disabled=not is_admin),
            "VIN": st.column_config.Column(disabled=not is_admin),
            "Plate": st.column_config.Column(disabled=not is_admin),
            "State": st.column_config.Column(disabled=not is_admin),
            "Status": st.column_config.SelectboxColumn("Status", options=["UP", "DOWN", "RETIRED", "RETURNED"], required=True),
            "Remarks": st.column_config.TextColumn("Remarks")
        }

        st.data_editor(
            fleet[display_cols], 
            column_config=column_configurations, 
            use_container_width=True, 
            hide_index=True,
            key=editor_key,
            on_change=on_fleet_change
        )
        
        st.write("")
        if st.button("💾 Save Fleet Status Overrides to Disk"):
            st.session_state['fleet_df'] = process_fleet_data(st.session_state['fleet_df'])
            safe_save_dataframe(st.session_state['fleet_df'], MASTER_FLEET_PATH)
            
            if 'current_roster' in st.session_state and not st.session_state['current_roster'].empty:
                st.session_state['current_roster'] = sync_live_roster_phones(st.session_state['current_roster'], st.session_state['phones_df'])

            st.success("Fleet statuses and remarks saved permanently!")
    else:
        st.info(f"Place `{MASTER_FLEET_PATH}` in your project folder.")

def render_phones_tab():
    st.subheader("Phone & Device Roster Management")
    phones = st.session_state.get('phones_df')
    
    if phones is not None:
        st.caption("Manage device names and corresponding numbers. Click **Save Phone Directory to Disk** to update permanently.")
        
        with st.expander("➕ / 📦 Add New Device or Archive/Deactivate Phone", expanded=False):
            col_add_p, col_rem_p = st.columns(2)

            with col_add_p:
                st.markdown("#### ➕ Add New Device")
                with st.form("add_phone_form", clear_on_submit=True):
                    new_dev_name = st.text_input("Device Name / Phone ID*", placeholder="e.g. 105 or Phone 25")
                    new_dev_num = st.text_input("Phone Number*", placeholder="e.g. 850-555-0199")

                    submit_add_p = st.form_submit_button("Add Phone Device", type="primary", use_container_width=True)

                    if submit_add_p:
                        if new_dev_name.strip() and new_dev_num.strip():
                            existing_devices = phones['device_clean'].astype(str).str.strip().tolist() if 'device_clean' in phones.columns else []
                            if new_dev_name.strip() in existing_devices:
                                st.error(f"Device '{new_dev_name.strip()}' already exists!")
                            else:
                                new_p_row = {
                                    'Device Name': new_dev_name.strip(),
                                    'Phone Number': new_dev_num.strip(),
                                    'Status': 'ACTIVE'
                                }
                                updated_phones = pd.concat([phones, pd.DataFrame([new_p_row])], ignore_index=True)
                                st.session_state['phones_df'] = process_phone_data(updated_phones)
                                safe_save_dataframe(st.session_state['phones_df'], MASTER_PHONES_PATH)
                                
                                if 'current_roster' in st.session_state and not st.session_state['current_roster'].empty:
                                    st.session_state['current_roster'] = sync_live_roster_phones(st.session_state['current_roster'], st.session_state['phones_df'])

                                st.success(f"Added device '{new_dev_name.strip()}' to phone directory!")
                                st.rerun()
                        else:
                            st.warning("Both Device Name and Phone Number are required.")

            with col_rem_p:
                st.markdown("#### 📦 Archive / Deactivate Device")
                st.caption("Marks phone as INACTIVE or RETIRED without deleting record history.")
                all_devices = sorted(phones['device_clean'].astype(str).str.strip().unique().tolist()) if 'device_clean' in phones.columns else []
                if all_devices:
                    archive_p_sel = st.selectbox("Select Device to Archive", options=["Select device..."] + all_devices)
                    p_archive_status = st.selectbox("Archival Reason", options=["INACTIVE", "RETIRED", "DAMAGED"], index=0)

                    if st.button("Confirm Soft Delete / Archive Device", type="secondary", use_container_width=True):
                        if archive_p_sel != "Select device...":
                            # FIXED: Run process_phone_data to guarantee clean device_clean string matching
                            updated_phones = process_phone_data(phones.copy())
                            target_p_idx = updated_phones[updated_phones['device_clean'].astype(str).str.strip() == archive_p_sel].index
                            
                            if 'Status' not in updated_phones.columns:
                                updated_phones['Status'] = 'ACTIVE'
                            updated_phones.loc[target_p_idx, 'Status'] = p_archive_status

                            st.session_state['phones_df'] = process_phone_data(updated_phones)
                            safe_save_dataframe(st.session_state['phones_df'], MASTER_PHONES_PATH)
                            
                            if 'current_roster' in st.session_state and not st.session_state['current_roster'].empty:
                                st.session_state['current_roster'] = sync_live_roster_phones(st.session_state['current_roster'], st.session_state['phones_df'])

                            st.success(f"Archived device '{archive_p_sel}' as {p_archive_status}!")
                            st.rerun()
                        else:
                            st.warning("Select a device to archive.")
                else:
                    st.info("No phone devices available in directory.")

        st.markdown("---")
        display_phone_cols = [c for c in ['device_clean', 'number_clean', 'status_clean'] if c in phones.columns]

        def on_phones_change():
            changes = st.session_state.get("phone_directory_editor_state")
            if changes and "phones_df" in st.session_state:
                for row_idx, col_changes in changes.get("edited_rows", {}).items():
                    for col_name, new_val in col_changes.items():
                        st.session_state['phones_df'].at[row_idx, col_name] = new_val

        st.data_editor(
            phones[display_phone_cols],
            column_config={
                "device_clean": st.column_config.TextColumn("Device Name / Phone ID", required=True),
                "number_clean": st.column_config.TextColumn("Phone Number", required=True),
                "status_clean": st.column_config.SelectboxColumn("Status", options=["ACTIVE", "INACTIVE", "RETIRED", "DAMAGED"], required=True)
            },
            use_container_width=True,
            num_rows="dynamic",
            hide_index=True,
            key="phone_directory_editor_state",
            on_change=on_phones_change
        )
        
        st.write("")
        if st.button("💾 Save Phone Directory to Disk"):
            st.session_state['phones_df'] = process_phone_data(st.session_state['phones_df'])
            safe_save_dataframe(st.session_state['phones_df'], MASTER_PHONES_PATH)
            
            if 'current_roster' in st.session_state and not st.session_state['current_roster'].empty:
                st.session_state['current_roster'] = sync_live_roster_phones(st.session_state['current_roster'], st.session_state['phones_df'])

            st.success("Phone directory saved permanently and live roster synced!")
    else:
        st.info(f"Place `{MASTER_PHONES_PATH}` in your project folder.")