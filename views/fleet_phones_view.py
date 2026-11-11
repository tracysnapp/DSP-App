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

        # --- QUICK SUMMARY COUNT METRICS (XL, L, M) ---
        if fleet_df is not None and not fleet_df.empty and "Size Bracket" in fleet_df.columns:
            size_counts = fleet_df["Size Bracket"].str.strip().str.upper().value_counts()
            xl_count = int(size_counts.get("XL", 0))
            l_count = int(size_counts.get("L", 0))
            m_count = int(size_counts.get("M", 0))

            m_col1, m_col2, m_col3 = st.columns(3)
            m_col1.metric("XL Vans", xl_count)
            m_col2.metric("L Vans", l_count)
            m_col3.metric("M Vans", m_count)
            st.markdown("---")

        # --- ADD / REMOVE VEHICLE EXPANDER ---
        with st.expander("➕ / 🗑️ Add or Remove Fleet Vehicle", expanded=False):
            col_add_v, col_rem_v = st.columns(2)
            
            with col_add_v:
                st.markdown("#### Add New Vehicle")
                with st.form("add_vehicle_form"):
                    new_bumper = st.text_input("Van Bumper #*", placeholder="e.g. 1234 or V-20")
                    new_vin = st.text_input("VIN (Optional)", placeholder="Full 17-character VIN")
                    new_size = st.selectbox("Size Bracket*", options=["M", "L", "XL", "ORE"], index=0)
                    new_status = st.selectbox("Initial Status*", options=["UP", "DOWN"], index=0)
                    new_remarks = st.text_input("Remarks / Notes", placeholder="Optional notes")
                    
                    submit_add_van = st.form_submit_button("Add Vehicle to Fleet", type="primary")
                    if submit_add_van:
                        if not new_bumper.strip():
                            st.error("Van Bumper number is required.")
                        else:
                            current_fleet = fleet_df.copy() if fleet_df is not None else pd.DataFrame()
                            existing_bumpers = [str(x).strip().upper() for x in current_fleet.get("Van Bumper", [])]
                            if new_bumper.strip().upper() in existing_bumpers:
                                st.error(f"Van Bumper '{new_bumper.strip()}' already exists in the fleet master list.")
                            else:
                                new_row = {
                                    "Van Bumper": new_bumper.strip(),
                                    "VIN": new_vin.strip() if new_vin.strip() else new_bumper.strip(),
                                    "Size Bracket": new_size,
                                    "Status": new_status,
                                    "Last Driven": "",
                                    "Remarks": new_remarks.strip()
                                }
                                updated_fleet = pd.concat([current_fleet, pd.DataFrame([new_row])], ignore_index=True)
                                processed_updated = process_fleet_data(updated_fleet)
                                st.session_state['fleet_df'] = processed_updated
                                safe_save_dataframe(processed_updated, MASTER_FLEET_PATH)
                                load_local_fleet.clear()
                                log_dispatch_action(f"Added new vehicle Van #{new_bumper.strip()} to fleet.", username=active_user)
                                st.toast(f"Added Van #{new_bumper.strip()} successfully!", icon="🚐")
                                st.rerun()

            with col_rem_v:
                st.markdown("#### Remove Vehicle")
                if fleet_df is not None and not fleet_df.empty:
                    van_list_options = fleet_df["Van Bumper"].astype(str).tolist() if "Van Bumper" in fleet_df.columns else []
                    van_to_remove = st.selectbox("Select Vehicle to Remove", options=["Select Vehicle..."] + van_list_options, key="rem_van_sel")
                    
                    if st.button("🗑️ Permanently Remove Vehicle", type="secondary"):
                        if van_to_remove == "Select Vehicle...":
                            st.warning("Please select a valid vehicle to remove.")
                        else:
                            updated_fleet = fleet_df[fleet_df["Van Bumper"].astype(str).str.strip() != van_to_remove.strip()].copy()
                            processed_updated = process_fleet_data(updated_fleet)
                            st.session_state['fleet_df'] = processed_updated
                            safe_save_dataframe(processed_updated, MASTER_FLEET_PATH)
                            load_local_fleet.clear()
                            log_dispatch_action(f"Removed vehicle Van #{van_to_remove} from fleet master list.", username=active_user)
                            st.toast(f"Removed Van #{van_to_remove} successfully!", icon="🗑️")
                            st.rerun()
                else:
                    st.info("No vehicles available to remove.")

        st.markdown("---")
        if fleet_df is not None and not fleet_df.empty:
            st.caption("Click any van's **Status** cell to select **UP** or **DOWN** from the dropdown. Click **Save** when finished.")
            
            fleet_config = {
                "Van Bumper": st.column_config.TextColumn("Van Bumper", disabled=True),
                "VIN": st.column_config.TextColumn("VIN", disabled=True),
                "Size Bracket": st.column_config.TextColumn("Size Bracket", disabled=True),
                "Status": st.column_config.SelectboxColumn("Status", options=["UP", "DOWN"], required=True),
                "Last Driven": st.column_config.TextColumn("Last Driven", disabled=True),
                "Remarks": st.column_config.TextColumn("Remarks / Maintenance Notes")
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

        with st.expander("➕ / 🗑️ Add or Remove Mobile Device / Phone", expanded=False):
            col_add_p, col_rem_p = st.columns(2)
            
            with col_add_p:
                st.markdown("#### Add New Phone / Device")
                with st.form("add_phone_form"):
                    new_device_id = st.text_input("Device ID / Phone Name*", placeholder="e.g. DDK6-01 or Phone 15")
                    new_phone_num = st.text_input("Phone Number (Optional)", placeholder="e.g. 555-0199")
                    new_phone_status = st.selectbox("Initial Device Status*", options=["ACTIVE", "SPARE", "REPAIR", "INACTIVE"], index=0)
                    new_phone_notes = st.text_input("Notes / Condition", placeholder="Optional condition notes")
                    
                    submit_add_phone = st.form_submit_button("Add Device to Roster", type="primary")
                    if submit_add_phone:
                        if not new_device_id.strip():
                            st.error("Device ID / Phone Name is required.")
                        else:
                            current_phones = phones_df.copy() if phones_df is not None else pd.DataFrame()
                            device_col_name = next((c for c in current_phones.columns if 'device' in str(c).lower() or 'name' in str(c).lower()), current_phones.columns[0] if not current_phones.empty else 'device_clean')
                            
                            existing_devices = [str(x).strip().upper() for x in current_phones.get(device_col_name, [])]
                            if new_device_id.strip().upper() in existing_devices:
                                st.error(f"Device ID '{new_device_id.strip()}' already exists in the phone directory.")
                            else:
                                new_phone_row = {
                                    "device_clean": new_device_id.strip(),
                                    "number_clean": new_phone_num.strip(),
                                    "van_assignment": "",
                                    "status_clean": new_phone_status,
                                    "notes": new_phone_notes.strip()
                                }
                                updated_phones = pd.concat([current_phones, pd.DataFrame([new_phone_row])], ignore_index=True)
                                processed_phones_updated = process_phone_data(updated_phones)
                                st.session_state['phones_df'] = processed_phones_updated
                                safe_save_dataframe(processed_phones_updated, MASTER_PHONES_PATH)
                                load_local_phones.clear()
                                log_dispatch_action(f"Added new phone device '{new_device_id.strip()}' to inventory.", username=active_user)
                                st.toast(f"Added device {new_device_id.strip()} successfully!", icon="📱")
                                st.rerun()

            with col_rem_p:
                st.markdown("#### Remove Phone / Device")
                if phones_df is not None and not phones_df.empty:
                    dev_col = next((c for c in phones_df.columns if 'device' in str(c).lower() or 'name' in str(c).lower()), phones_df.columns[0])
                    phone_list_options = phones_df[dev_col].astype(str).tolist()
                    phone_to_remove = st.selectbox("Select Device to Remove", options=["Select Device..."] + phone_list_options, key="rem_phone_sel")
                    
                    if st.button("🗑️ Permanently Remove Device", type="secondary"):
                        if phone_to_remove == "Select Device...":
                            st.warning("Please select a valid device to remove.")
                        else:
                            updated_phones = phones_df[phones_df[dev_col].astype(str).str.strip() != phone_to_remove.strip()].copy()
                            processed_phones_updated = process_phone_data(updated_phones)
                            st.session_state['phones_df'] = processed_phones_updated
                            safe_save_dataframe(processed_phones_updated, MASTER_PHONES_PATH)
                            load_local_phones.clear()
                            log_dispatch_action(f"Removed phone device '{phone_to_remove}' from master inventory.", username=active_user)
                            st.toast(f"Removed device {phone_to_remove} successfully!", icon="🗑️")
                            st.rerun()
                else:
                    st.info("No phone devices available to remove.")

        st.markdown("---")
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
