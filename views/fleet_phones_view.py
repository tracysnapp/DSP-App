import pandas as pd
import streamlit as st
from engine import (
    MASTER_FLEET_PATH,
    MASTER_PHONES_PATH,
    load_local_fleet,
    load_local_phones,
    log_dispatch_action,
    safe_save_dataframe,
)
from modules.fleet import process_fleet_data, process_phone_data, sync_live_roster_phones


def render_fleet_tab():
    st.subheader("🚐 Fleet & Mobile Device Management")

    fleet_df = st.session_state.get("fleet_df")
    if fleet_df is None or fleet_df.empty:
        fleet_df = load_local_fleet()
        if fleet_df is None:
            fleet_df = pd.DataFrame(
                columns=["Van Bumper", "VIN", "Size Bracket", "Status", "Last Driven", "Remarks"]
            )
        st.session_state["fleet_df"] = fleet_df

    phones_df = st.session_state.get("phones_df")
    if phones_df is None or phones_df.empty:
        phones_df = load_local_phones()
        if phones_df is None:
            phones_df = pd.DataFrame(columns=["device_clean", "number_clean", "status_clean"])
        st.session_state["phones_df"] = phones_df

    # Top KPI Bar
    total_vans = len(fleet_df)
    up_vans = len(fleet_df[fleet_df["Status"].astype(str).str.upper() == "UP"]) if total_vans > 0 else 0
    down_vans = total_vans - up_vans
    active_phones = (
        len(phones_df[phones_df["status_clean"].astype(str).str.upper() == "ACTIVE"])
        if not phones_df.empty and "status_clean" in phones_df.columns
        else len(phones_df)
    )

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Fleet Vans", total_vans)
    k2.metric("Operational (UP)", up_vans)
    k3.metric("Grounded (DOWN)", down_vans)
    k4.metric("Active Devices", active_phones)

    st.markdown("---")

    sub_view = st.segmented_control(
        "Fleet & Device Section",
        options=["🚐 Vehicle Fleet Tracker", "📱 Device & Phone Roster"],
        default="🚐 Vehicle Fleet Tracker",
        label_visibility="collapsed",
        key="fleet_phones_sub_nav",
    )
    if not sub_view:
        sub_view = "🚐 Vehicle Fleet Tracker"

    # ---------------------------------------------------------
    # 1. VEHICLE FLEET TRACKER
    # ---------------------------------------------------------
    if sub_view == "🚐 Vehicle Fleet Tracker":
        hdr_l, hdr_r = st.columns([3, 1])
        with hdr_l:
            status_filter = st.radio(
                "Filter Fleet Status",
                options=["All", "UP", "DOWN"],
                horizontal=True,
                key="fleet_status_filter",
            )
        with hdr_r:
            st.markdown("<div style='padding-top: 0.4rem;'></div>", unsafe_allow_html=True)
            save_fleet_btn = st.button(
                "💾 Save Fleet Changes",
                type="primary",
                use_container_width=True,
                key="save_fleet_top_btn",
            )

        with st.expander("📤 Import / Replace Fleet Spreadsheet", expanded=False):
            up_fleet = st.file_uploader(
                "Upload Master Fleet Excel/CSV", type=["xlsx", "xls", "csv"], key="fleet_file_up"
            )
            if up_fleet and st.button("Apply Imported Fleet File", type="primary"):
                raw_f = (
                    pd.read_csv(up_fleet)
                    if up_fleet.name.endswith(".csv")
                    else pd.read_excel(up_fleet)
                )
                clean_f = process_fleet_data(raw_f)
                safe_save_dataframe(clean_f, MASTER_FLEET_PATH)
                load_local_fleet.clear()
                st.session_state["fleet_df"] = clean_f
                st.toast(f"Imported {len(clean_f)} vehicles!", icon="🚐")
                st.rerun()

        display_fleet = fleet_df.copy()
        if status_filter != "All" and not display_fleet.empty:
            display_fleet = display_fleet[
                display_fleet["Status"].astype(str).str.upper() == status_filter
            ]

        fleet_col_config = {
            "Van Bumper": st.column_config.TextColumn("Van Bumper", width="small"),
            "VIN": st.column_config.TextColumn("VIN", width="medium"),
            "Size Bracket": st.column_config.SelectboxColumn(
                "Size Bracket", options=["M", "L", "XL"], width="small"
            ),
            "Status": st.column_config.SelectboxColumn(
                "Status", options=["UP", "DOWN"], width="small"
            ),
            "Last Driven": st.column_config.TextColumn("Last Driven", width="small"),
            "Remarks": st.column_config.TextColumn("Remarks", width="large"),
        }
        if "priority_rank" in display_fleet.columns:
            fleet_col_config["priority_rank"] = st.column_config.NumberColumn(
                "Priority (1=Lock)", min_value=1, max_value=99, step=1, width="small"
            )

        edited_fleet = st.data_editor(
            display_fleet,
            column_config=fleet_col_config,
            num_rows="dynamic" if status_filter == "All" else "fixed",
            use_container_width=True,
            hide_index=True,
            key="fleet_data_editor",
        )

        if save_fleet_btn:
            if status_filter == "All":
                updated_full_fleet = edited_fleet.copy()
            else:
                updated_full_fleet = fleet_df.copy()
                for _, row in edited_fleet.iterrows():
                    vin_val = str(row.get("VIN", "")).strip()
                    bumper_val = str(row.get("Van Bumper", "")).strip()
                    match_mask = (
                        (updated_full_fleet["VIN"].astype(str).str.strip() == vin_val)
                        if vin_val
                        else (updated_full_fleet["Van Bumper"].astype(str).str.strip() == bumper_val)
                    )
                    if match_mask.any():
                        for col in edited_fleet.columns:
                            updated_full_fleet.loc[match_mask, col] = row[col]

            safe_save_dataframe(updated_full_fleet, MASTER_FLEET_PATH)
            load_local_fleet.clear()
            st.session_state["fleet_df"] = updated_full_fleet
            log_dispatch_action(
                "Updated Master Fleet Tracker.",
                username=st.session_state.get("user_name"),
            )
            st.toast("Fleet directory saved to Cloud Storage!", icon="💾")
            st.rerun()

    # ---------------------------------------------------------
    # 2. DEVICE & PHONE ROSTER
    # ---------------------------------------------------------
    elif sub_view == "📱 Device & Phone Roster":
        hdr_l, hdr_r = st.columns([3, 1])
        with hdr_l:
            phone_filter = st.radio(
                "Filter Device Status",
                options=["All", "ACTIVE", "INACTIVE"],
                horizontal=True,
                key="phone_status_filter",
            )
        with hdr_r:
            st.markdown("<div style='padding-top: 0.4rem;'></div>", unsafe_allow_html=True)
            save_phones_btn = st.button(
                "💾 Save Device Roster",
                type="primary",
                use_container_width=True,
                key="save_phones_top_btn",
            )

        with st.expander("📤 Import / Replace Phone Directory", expanded=False):
            up_phones = st.file_uploader(
                "Upload Master Phones Excel/CSV", type=["xlsx", "xls", "csv"], key="phones_file_up"
            )
            if up_phones and st.button("Apply Imported Phone File", type="primary"):
                raw_p = (
                    pd.read_csv(up_phones)
                    if up_phones.name.endswith(".csv")
                    else pd.read_excel(up_phones)
                )
                clean_p = process_phone_data(raw_p)
                safe_save_dataframe(clean_p, MASTER_PHONES_PATH)
                load_local_phones.clear()
                st.session_state["phones_df"] = clean_p
                st.toast(f"Imported {len(clean_p)} devices!", icon="📱")
                st.rerun()

        display_phones = phones_df[["device_clean", "number_clean", "status_clean"]].copy()
        display_phones.columns = ["Device / Van ID", "Phone Number", "Status"]

        if phone_filter != "All" and not display_phones.empty:
            display_phones = display_phones[
                display_phones["Status"].astype(str).str.upper() == phone_filter
            ]

        phone_col_config = {
            "Device / Van ID": st.column_config.TextColumn("Device / Van ID", width="medium"),
            "Phone Number": st.column_config.TextColumn("Phone Number", width="medium"),
            "Status": st.column_config.SelectboxColumn(
                "Status", options=["ACTIVE", "INACTIVE", "REPAIR"], width="small"
            ),
        }

        edited_phones = st.data_editor(
            display_phones,
            column_config=phone_col_config,
            num_rows="dynamic" if phone_filter == "All" else "fixed",
            use_container_width=True,
            hide_index=True,
            key="phones_data_editor",
        )

        if save_phones_btn:
            save_ready = edited_phones.rename(
                columns={
                    "Device / Van ID": "device_clean",
                    "Phone Number": "number_clean",
                    "Status": "status_clean",
                }
            )
            if phone_filter != "All":
                full_p = phones_df[["device_clean", "number_clean", "status_clean"]].copy()
                for _, row in save_ready.iterrows():
                    dev_id = str(row["device_clean"]).strip()
                    m = full_p["device_clean"].astype(str).str.strip() == dev_id
                    if m.any():
                        full_p.loc[m, "number_clean"] = row["number_clean"]
                        full_p.loc[m, "status_clean"] = row["status_clean"]
                save_ready = full_p

            safe_save_dataframe(save_ready, MASTER_PHONES_PATH)
            load_local_phones.clear()
            st.session_state["phones_df"] = save_ready

            if st.session_state.get("current_roster") is not None:
                st.session_state["current_roster"] = sync_live_roster_phones(
                    st.session_state["current_roster"], save_ready
                )

            log_dispatch_action(
                "Updated Master Phone Directory.",
                username=st.session_state.get("user_name"),
            )
            st.toast("Device roster saved and synced!", icon="💾")
            st.rerun()
