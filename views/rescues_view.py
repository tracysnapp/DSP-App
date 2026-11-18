import streamlit as st
from engine import (
    delete_driver_rescue,
    load_local_rescues_log,
    log_dispatch_action,
    save_driver_rescue,
    update_driver_rescue,
)


def render_rescues_tab():
    st.subheader("🚚 Rescue & Sweep Dispatch Tracker")
    st.caption(
        "Log rescues. Rescues due to being behind on route deduct 5 pts. Route"
        " drivers who complete their route and perform a rescue earn +5 pts"
        " bonus (Designated Sweepers do not earn bonus points)."
    )

    drivers_df = st.session_state.get("drivers_df")
    scorecards_df = st.session_state.get("scorecards_df")
    active_user = st.session_state.get("user_name", "Dispatch Desk")

    rescues_df = load_local_rescues_log()

    with st.expander("➕ Log New Rescue Dispatch", expanded=True):
        col_r1, col_r2 = st.columns(2)

        driver_options = []
        if (
            drivers_df is not None
            and not drivers_df.empty
            and "Driver Name" in drivers_df.columns
        ):
            driver_options = sorted(drivers_df["Driver Name"].dropna().unique())
        elif (
            scorecards_df is not None
            and not scorecards_df.empty
            and "Driver Name" in scorecards_df.columns
        ):
            driver_options = sorted(
                scorecards_df["Driver Name"].dropna().unique()
            )

        r_driver = col_r1.selectbox(
            "Driver Rescued*",
            options=driver_options if driver_options else ["Select Driver..."],
            key="res_rescued_sel",
        )
        r_rescuer = col_r2.selectbox(
            "Rescuer / Sweeper Driver*",
            options=driver_options if driver_options else ["Select Driver..."],
            key="res_rescuer_sel",
        )

        col_r3, col_r4 = st.columns(2)
        r_type = col_r3.selectbox(
            "Rescuer Role / Status*",
            options=[
                "Route Driver (Completed Route)",
                "Designated Sweeper",
            ],
            key="res_type_sel",
        )

        r_reason = col_r4.selectbox(
            "Rescue Reason*",
            options=[
                "Behind on Route / Slow Pace",
                "Vehicle Breakdown / Swap",
                "App / Navigation Glitch",
                "Safety / Medical / Personal",
                "Other",
            ],
            key="res_reason_sel",
        )

        r_notes = st.text_input(
            "Dispatch Notes / Package Count",
            placeholder="e.g. Swiped 35 stops to help catch up",
            key="res_notes_input",
        )

        if st.button("🚚 Record Rescue Dispatch", type="primary"):
            if (
                not r_driver
                or r_driver == "Select Driver..."
                or not r_rescuer
                or r_rescuer == "Select Driver..."
            ):
                st.warning(
                    "Please select both the rescued driver and the rescuer."
                )
            elif r_driver == r_rescuer:
                st.warning("A driver cannot rescue themselves.")
            else:
                save_driver_rescue(
                    rescued_driver=r_driver,
                    rescuer_driver=r_rescuer,
                    rescuer_type=r_type,
                    reason=r_reason,
                    logged_by=active_user,
                    notes=r_notes,
                )
                log_dispatch_action(
                    f"Logged rescue: '{r_rescuer}' ({r_type}) rescued"
                    f" '{r_driver}' ({r_reason}).",
                    username=active_user,
                )
                st.toast(f"Logged rescue for {r_driver}!", icon="🚚")
                st.rerun()

    st.markdown("---")
    st.markdown("#### ✏️ Edit or Delete Existing Rescue Records")
    if rescues_df is not None and not rescues_df.empty:
        rescues_df["Display_Label"] = [
            f"[{row.get('Date', '')}] Rescued: {row.get('Rescued Driver', '')}"
            f" | Rescuer: {row.get('Rescuer Driver', '')}"
            f" [{row.get('Rescuer Type', 'Route Driver')}]"
            f" ({row.get('Reason', '')})"
            for _, row in rescues_df.iterrows()
        ]
        selected_rescue_label = st.selectbox(
            "Select Rescue Record to Modify",
            options=["Select Record..."] + list(rescues_df["Display_Label"]),
        )

        if selected_rescue_label != "Select Record...":
            match_r_idx = rescues_df[
                rescues_df["Display_Label"] == selected_rescue_label
            ].index[0]
            r_row_data = rescues_df.loc[match_r_idx]

            with st.form("edit_rescue_form"):
                st.markdown(
                    f"**Editing Rescue Index #{match_r_idx}** (Logged:"
                    f" {r_row_data.get('Date', '')})"
                )

                er_col1, er_col2 = st.columns(2)
                er_rescued = er_col1.text_input(
                    "Rescued Driver",
                    value=str(r_row_data.get("Rescued Driver", "")),
                )
                er_rescuer = er_col2.text_input(
                    "Rescuer Driver",
                    value=str(r_row_data.get("Rescuer Driver", "")),
                )

                er_col3, er_col4 = st.columns(2)
                type_opts = [
                    "Route Driver (Completed Route)",
                    "Designated Sweeper",
                ]
                cur_type = str(
                    r_row_data.get(
                        "Rescuer Type", "Route Driver (Completed Route)"
                    )
                )
                er_type = er_col3.selectbox(
                    "Rescuer Role / Status",
                    options=type_opts,
                    index=type_opts.index(cur_type)
                    if cur_type in type_opts
                    else 0,
                )

                reason_opts = [
                    "Behind on Route / Slow Pace",
                    "Vehicle Breakdown / Swap",
                    "App / Navigation Glitch",
                    "Safety / Medical / Personal",
                    "Other",
                ]
                cur_reason = str(r_row_data.get("Reason", ""))
                er_reason = er_col4.selectbox(
                    "Reason",
                    options=reason_opts,
                    index=reason_opts.index(cur_reason)
                    if cur_reason in reason_opts
                    else 0,
                )

                er_notes = st.text_area(
                    "Notes", value=str(r_row_data.get("Notes", ""))
                )

                col_rbtn1, col_rbtn2 = st.columns(2)
                if col_rbtn1.form_submit_button(
                    "💾 Save Rescue Changes",
                    type="primary",
                    use_container_width=True,
                ):
                    update_driver_rescue(
                        match_r_idx,
                        er_rescued,
                        er_rescuer,
                        er_type,
                        er_reason,
                        active_user,
                        er_notes,
                    )
                    st.success("Rescue record updated successfully!")
                    st.rerun()
                if col_rbtn2.form_submit_button(
                    "🗑️ Delete Rescue Record",
                    type="secondary",
                    use_container_width=True,
                ):
                    delete_driver_rescue(match_r_idx)
                    st.success("Rescue record deleted successfully!")
                    st.rerun()

    st.markdown("---")
    st.markdown("#### 📜 Master Rescue Dispatch Ledger")
    if rescues_df is not None and not rescues_df.empty:
        st.dataframe(
            rescues_df.drop(columns=["Display_Label"], errors="ignore"),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No rescue dispatches currently recorded.")
