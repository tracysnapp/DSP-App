import streamlit as st
import pandas as pd
from engine import ACCESS_CODES_PATH, safe_save_dataframe, process_access_data, log_dispatch_action

def render_access_codes_tab(is_admin):
    st.subheader("🔑 Gate & Building Access Codes Directory")
    
    access_df = st.session_state.get('access_df')
    active_user = st.session_state.get('user_name', 'Dispatcher')

    if access_df is not None:
        access_data = access_df.copy()

        # ---------------------------------------------------------
        # 1. ADD NEW ACCESS CODE (AVAILABLE TO ALL PROFILES)
        # ---------------------------------------------------------
        with st.expander("➕ Add New Gate / Access Code", expanded=False):
            with st.form("add_access_code_form", clear_on_submit=True):
                col_ac1, col_ac2 = st.columns([1, 1])
                new_loc = col_ac1.text_input("Location / Address*", placeholder="e.g. Oakwood Apartments / 123 Main St")
                new_code = col_ac2.text_input("Gate / Keypad Code*", placeholder="e.g. #1234 or Call Box 042")
                new_instructions = st.text_area("Special Instructions & Delivery Notes", placeholder="e.g. Pull up close to sensor, ring #1234 if gate remains closed.")

                submit_add_code = st.form_submit_button("Add Access Code", type="primary", use_container_width=True)

                if submit_add_code:
                    if new_loc.strip() and new_code.strip():
                        existing_locs = [str(loc).strip().lower() for loc in access_data['Location'].dropna().unique()]
                        if new_loc.strip().lower() in existing_locs:
                            st.error(f"Location '{new_loc.strip()}' already exists in the access directory!")
                        else:
                            new_code_row = {
                                "Location": new_loc.strip(),
                                "Code": new_code.strip(),
                                "Special Instructions": new_instructions.strip()
                            }
                            updated_access = pd.concat([access_data, pd.DataFrame([new_code_row])], ignore_index=True)
                            st.session_state['access_df'] = process_access_data(updated_access)
                            safe_save_dataframe(st.session_state['access_df'], ACCESS_CODES_PATH)
                            log_dispatch_action(f"Added access code entry for '{new_loc.strip()}'.", username=active_user)
                            st.success(f"Added access code for '{new_loc.strip()}'!")
                            st.rerun()
                    else:
                        st.warning("Both Location and Code are required.")

        # ---------------------------------------------------------
        # 2. REMOVE ACCESS CODE (ADMIN PROFILE ONLY)
        # ---------------------------------------------------------
        if is_admin:
            with st.expander("🗑️ Remove Access Code (Admin Only)", expanded=False):
                st.caption("🔒 Admin Access: Permanently delete an outdated location or access code from the directory.")
                existing_locations = sorted(access_data['Location'].dropna().astype(str).str.strip().unique().tolist()) if not access_data.empty else []

                if existing_locations:
                    col_r1, col_r2 = st.columns([3, 1])
                    target_loc_to_remove = col_r1.selectbox("Select Location to Remove", options=["Select Location..."] + existing_locations, key="rem_code_loc_sel")

                    if col_r2.button("❌ Remove Code", type="primary", use_container_width=True):
                        if target_loc_to_remove != "Select Location...":
                            updated_access = access_data[access_data['Location'].astype(str).str.strip() != target_loc_to_remove].reset_index(drop=True)
                            st.session_state['access_df'] = updated_access
                            safe_save_dataframe(updated_access, ACCESS_CODES_PATH)
                            log_dispatch_action(f"Deleted access code entry for location '{target_loc_to_remove}'.", username=active_user)
                            st.toast(f"Removed '{target_loc_to_remove}' from access directory!", icon="🗑️")
                            st.rerun()
                        else:
                            st.warning("Please select a location to remove.")
                else:
                    st.info("No locations currently stored in access directory.")

        st.markdown("---")

        # ---------------------------------------------------------
        # 3. SEARCH & DIRECTORY DATA EDITOR
        # ---------------------------------------------------------
        search_term = st.text_input("🔍 Search Location, Address, or Code", placeholder="Type location name, street address, or gate code...")
        
        if search_term.strip():
            st_clean = search_term.strip().lower()
            filtered_df = access_data[
                access_data['Location'].astype(str).str.lower().str.contains(st_clean) |
                access_data['Code'].astype(str).str.lower().str.contains(st_clean) |
                access_data['Special Instructions'].astype(str).str.lower().str.contains(st_clean)
            ]
        else:
            filtered_df = access_data

        st.caption(f"Showing {len(filtered_df)} location records.")

        def on_access_change():
            changes = st.session_state.get("access_codes_editor_state")
            if changes and "access_df" in st.session_state:
                for row_idx, col_changes in changes.get("edited_rows", {}).items():
                    for col_name, new_val in col_changes.items():
                        st.session_state['access_df'].at[row_idx, col_name] = new_val
                
                deleted_rows = changes.get("deleted_rows", [])
                if deleted_rows:
                    if is_admin:
                        st.session_state['access_df'] = st.session_state['access_df'].drop(deleted_rows).reset_index(drop=True)
                        safe_save_dataframe(st.session_state['access_df'], ACCESS_CODES_PATH)
                        log_dispatch_action(f"Deleted {len(deleted_rows)} entry/entries from Gate Access Directory via table row deletion.", username=active_user)
                        st.toast("Access code entry deleted successfully!", icon="🗑️")
                    else:
                        st.toast("⚠️ Deletion restricted: Only Admin accounts can delete access codes.", icon="🔒")

        access_config = {
            "Location": st.column_config.TextColumn("Location / Address", width="large", disabled=not is_admin, required=True),
            "Code": st.column_config.TextColumn("Gate / Keypad Code", width="medium", disabled=not is_admin, required=True),
            "Special Instructions": st.column_config.TextColumn("Special Instructions & Delivery Notes", width="large", disabled=not is_admin)
        }

        st.data_editor(
            filtered_df,
            column_config=access_config,
            use_container_width=True,
            num_rows="dynamic" if is_admin else "fixed",
            hide_index=True,
            key="access_codes_editor_state",
            on_change=on_access_change
        )

        st.write("")
        if is_admin:
            if st.button("💾 Save Gate Access Directory to Disk", type="primary"):
                save_df = st.session_state['access_df']
                safe_save_dataframe(save_df, ACCESS_CODES_PATH)
                log_dispatch_action("Saved manual edits to Gate Access Directory to disk.", username=active_user)
                st.success("Gate access codes and instructions saved permanently!")
        else:
            st.caption("🔒 *Read-Only Table Editing for Dispatch Desk.*")
    else:
        st.info(f"Place `{ACCESS_CODES_PATH}` in your project folder.")