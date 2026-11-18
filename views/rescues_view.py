import datetime
import pandas as pd
import streamlit as st
from engine import (
    delete_driver_rescue,
    load_local_rescues_log,
    log_dispatch_action,
    save_driver_rescue,
    update_driver_rescue,
)

RESCUE_REASONS = [
    "Behind on Route",
    "Slow Pace",
    "Route Overload / High Stop Count",
    "Van Breakdown / Mechanical",
    "Medical / Personal Emergency",
    "Weather / Traffic Delay",
    "Other",
]

RESCUER_TYPES = [
    "Route Driver (Completed Route)",
    "Sweeper / Helper (No Bonus)",
]


def _get_prioritized_driver_list():
    drivers_df = st.session_state.get("drivers_df")
    current_roster = st.session_state.get("current_roster")

    on_road_names = []
    if current_roster is not None and not current_roster.empty:
        for col in ["Driver", "Helper"]:
            if col in current_roster.columns:
                for val in current_roster[col].dropna().unique():
                    clean_v = str(val).strip()
                    if clean_v and clean_v.lower() not in ["nan", "none", "null", "unassigned"]:
                        if clean_v not in on_road_names:
                            on_road_names.append(clean_v)

    all_active = []
    if drivers_df is not None and not drivers_df.empty and "Driver Name" in drivers_df.columns:
        if "Status" in drivers_df.columns:
            active_df = drivers_df[drivers_df["Status"].astype(str).str.upper() != "INACTIVE"]
        else:
            active_df = drivers_df
        all_active = sorted(active_df["Driver Name"].dropna().astype(str).str.strip().unique().tolist())

    options = []
    label_to_name = {}
    seen = set()

    for name in sorted(on_road_names):
        lbl = f"🟢 {name} (On Road Today)"
        options.append(lbl)
        label_to_name[lbl] = name
        seen.add(name.lower())

    for name in all_active:
        if name and name.lower() not in seen:
            options.append(name)
            label_to_name[name] = name
            seen.add(name.lower())

    return options, label_to_name


def render_rescues_tab():
    st.subheader("🚚 Daily Rescues & Sweeps Log")
    st.caption(
        "Log mid-day rescues and sweeps. Penalized rescues deduct 5 pts from the rescued driver; route drivers who complete their route and perform a rescue earn +5 pts."
    )

    rescues_df = load_local_rescues_log()

    # Top KPI Bar
    total_rescues = len(rescues_df) if rescues_df is not None else 0
    penalized_cnt = (
        int(rescues_df["Penalize Rescued"].fillna(False).astype(bool).sum())
        if total_rescues > 0 and "Penalize Rescued" in rescues_df.columns
        else 0
    )
    bonus_cnt = (
        len(
            rescues_df[
                ~rescues_df["Rescuer Type"].astype(str).str.lower().str.contains("sweeper", na=False)
            ]
        )
        if total_rescues > 0 and "Rescuer Type" in rescues_df.columns
        else 0
    )
    sweeper_cnt = max(total_rescues - bonus_cnt, 0)

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Rescues Logged", total_rescues)
    k2.metric("Penalized Rescues (-5 pts)", penalized_cnt)
    k3.metric("Route Driver Assists (+5 pts)", bonus_cnt)
    k4.metric("Designated Sweeps", sweeper_cnt)

    st.markdown("---")

    driver_options, label_to_name = _get_prioritized_driver_list()

    # Log New Rescue Expander
    with st.expander("➕ Log New Rescue / Sweep", expanded=True):
        with st.form("log_rescue_form", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            with c1:
                if driver_options:
                    rescued_sel = st.selectbox("Rescued Driver (Needed Help)", options=driver_options)
                    rescued_name = label_to_name.get(rescued_sel, rescued_sel)
                else:
                    rescued_name = st.text_input("Rescued Driver Name")
            with c2:
                if driver_options:
                    rescuer_sel = st.selectbox("Rescuer Driver (Provided Help)", options=driver_options)
                    rescuer_name = label_to_name.get(rescuer_sel, rescuer_sel)
                else:
                    rescuer_name = st.text_input("Rescuer Driver Name")
            with c3:
                rescuer_type = st.selectbox("Rescuer Role / Type", options=RESCUER_TYPES)

            c4, c5 = st.columns([2, 1])
            with c4:
                reason = st.selectbox("Rescue Reason", options=RESCUE_REASONS)
            with c5:
                st.markdown("<div style='padding-top: 1.7rem;'></div>", unsafe_allow_html=True)
                penalize_flag = st.checkbox(
                    "Deduct 5 pts from Rescued Driver",
                    value=True,
                    help="Check if the driver fell behind due to pace/performance. Uncheck for van breakdowns or route overload.",
                )

            notes = st.text_input(
                "Notes (Totes / Stops Taken, Time, Location)",
                placeholder="e.g., Took 2 totes (28 stops) at 4:15 PM",
            )

            submitted = st.form_submit_button(
                "💾 Log Rescue Record", type="primary", use_container_width=True
            )
            if submitted:
                if not str(rescued_name).strip() or not str(rescuer_name).strip():
                    st.error("Both Rescued Driver and Rescuer Driver are required.")
                elif str(rescued_name).strip().lower() == str(rescuer_name).strip().lower():
                    st.error("Rescued Driver and Rescuer Driver cannot be the same person.")
                else:
                    save_driver_rescue(
                        rescued_driver=rescued_name,
                        rescuer_driver=rescuer_name,
                        rescuer_type=rescuer_type,
                        reason=reason,
                        logged_by=st.session_state.get("user_name", "Dispatch"),
                        notes=notes,
                        penalize_rescued=penalize_flag,
                    )
                    log_dispatch_action(
                        f"Logged rescue: {rescuer_name} rescued {rescued_name} ({reason}).",
                        username=st.session_state.get("user_name"),
                    )
                    st.toast("Rescue logged successfully!", icon="🚚")
                    st.rerun()

    st.markdown("---")
    st.markdown("### 📋 Master Rescues Ledger")

    if rescues_df is None or rescues_df.empty:
        st.info("No rescue records logged yet.")
        return

    # Quick Search Filter
    search_q = st.text_input(
        "🔍 Filter Rescues by Driver, Reason, or Notes",
        placeholder="Type driver name or reason...",
        key="rescues_search_filter",
    ).strip().lower()

    display_df = rescues_df.copy()
    if search_q:
        mask = display_df.apply(
            lambda r: search_q in " ".join(r.astype(str).values).lower(), axis=1
        )
        display_df = display_df[mask]

    display_df = display_df.iloc[::-1].reset_index(drop=True)
    st.dataframe(display_df, use_container_width=True, hide_index=True)

    # Current Week Net Rescue Point Impact Summary
    with st.expander("📊 Current Week Net Rescue Point Impact (Last 7 Days)", expanded=False):
        temp_df = rescues_df.copy()
        temp_df["Parsed_Date"] = pd.to_datetime(temp_df["Date"], errors="coerce")
        cutoff = pd.Timestamp.now() - pd.Timedelta(days=7)
        recent_df = temp_df[temp_df["Parsed_Date"].isna() | (temp_df["Parsed_Date"] >= cutoff)]

        if recent_df.empty:
            st.caption("No rescues logged in the past 7 days.")
        else:
            impact_map = {}
            for _, r in recent_df.iterrows():
                r_driver = str(r.get("Rescued Driver", "")).strip()
                p_driver = str(r.get("Rescuer Driver", "")).strip()
                is_pen = bool(r.get("Penalize Rescued", False))
                is_sweeper = "sweeper" in str(r.get("Rescuer Type", "")).lower()

                if r_driver:
                    impact_map.setdefault(r_driver, {"Times Rescued (Penalized)": 0, "Route Assists (+5)": 0, "Net Points": 0})
                    if is_pen:
                        impact_map[r_driver]["Times Rescued (Penalized)"] += 1
                        impact_map[r_driver]["Net Points"] -= 5

                if p_driver:
                    impact_map.setdefault(p_driver, {"Times Rescued (Penalized)": 0, "Route Assists (+5)": 0, "Net Points": 0})
                    if not is_sweeper:
                        impact_map[p_driver]["Route Assists (+5)"] += 1
                        impact_map[p_driver]["Net Points"] += 5

            impact_rows = [{"Driver Name": k, **v} for k, v in impact_map.items()]
            impact_summary_df = pd.DataFrame(impact_rows).sort_values(
                by=["Net Points", "Driver Name"], ascending=[False, True]
            )
            st.dataframe(impact_summary_df, use_container_width=True, hide_index=True)

    # Edit / Delete Selected Record
    with st.expander("✏️ Edit or Delete a Rescue Record", expanded=False):
        record_labels = [
            f"Row {idx} | {row.get('Date', '')} — {row.get('Rescuer Driver', '')} rescued {row.get('Rescued Driver', '')} ({row.get('Reason', '')})"
            for idx, row in rescues_df.iterrows()
        ]
        selected_label = st.selectbox(
            "Select Record to Modify",
            options=list(reversed(record_labels)),
            key="edit_rescue_selector",
        )
        sel_idx = int(selected_label.split("|")[0].replace("Row", "").strip())
        sel_row = rescues_df.loc[sel_idx]

        with st.form("edit_rescue_form"):
            ec1, ec2, ec3 = st.columns(3)
            with ec1:
                edit_rescued = st.text_input(
                    "Rescued Driver", value=str(sel_row.get("Rescued Driver", ""))
                )
            with ec2:
                edit_rescuer = st.text_input(
                    "Rescuer Driver", value=str(sel_row.get("Rescuer Driver", ""))
                )
            with ec3:
                curr_type = str(sel_row.get("Rescuer Type", RESCUER_TYPES[0]))
                type_idx = RESCUER_TYPES.index(curr_type) if curr_type in RESCUER_TYPES else 0
                edit_type = st.selectbox("Rescuer Type", options=RESCUER_TYPES, index=type_idx)

            ec4, ec5 = st.columns([2, 1])
            with ec4:
                curr_reason = str(sel_row.get("Reason", RESCUE_REASONS[0]))
                reason_idx = RESCUE_REASONS.index(curr_reason) if curr_reason in RESCUE_REASONS else 0
                edit_reason = st.selectbox("Rescue Reason", options=RESCUE_REASONS, index=reason_idx)
            with ec5:
                st.markdown("<div style='padding-top: 1.7rem;'></div>", unsafe_allow_html=True)
                edit_penalize = st.checkbox(
                    "Deduct 5 pts from Rescued",
                    value=bool(sel_row.get("Penalize Rescued", False)),
                )

            edit_notes = st.text_input("Notes", value=str(sel_row.get("Notes", "")))

            btn_col1, btn_col2 = st.columns(2)
            with btn_col1:
                update_btn = st.form_submit_button(
                    "💾 Update Record", type="primary", use_container_width=True
                )
            with btn_col2:
                delete_btn = st.form_submit_button(
                    "🗑️ Delete Record", type="secondary", use_container_width=True
                )

            if update_btn:
                update_driver_rescue(
                    row_idx=sel_idx,
                    rescued_driver=edit_rescued,
                    rescuer_driver=edit_rescuer,
                    rescuer_type=edit_type,
                    reason=edit_reason,
                    logged_by=st.session_state.get("user_name", "Dispatch"),
                    notes=edit_notes,
                    penalize_rescued=edit_penalize,
                )
                st.toast("Rescue record updated!", icon="💾")
                st.rerun()

            if delete_btn:
                delete_driver_rescue(sel_idx)
                st.toast("Rescue record deleted.", icon="🗑️")
                st.rerun()
