import datetime
import pandas as pd
import streamlit as st
from engine import (
    DISCORD_WEBHOOK_URL,
    load_local_drivers,
    load_local_schedule,
    load_long_range_pto_storage,
    load_standing_schedules_storage,
    load_weekly_targets_storage,
    log_dispatch_action,
    save_long_range_pto_storage,
    save_standing_schedules_storage,
    save_weekly_schedule_to_storage,
    save_weekly_targets_storage,
)
from modules.schedule import (
    apply_standing_schedules_to_df,
    auto_generate_pattern_weekly_schedule,
    generate_discord_schedule,
    send_discord_webhook,
)

SHIFT_OPTIONS = ["", "Driver", "Helper", "OPS-AM", "OPS-PM", "On-Call", "Off", "Rqst Off"]
DAY_PREFIXES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


def get_current_amazon_week_info(ref_date: datetime.date = None):
    """Calculates Amazon Sunday-Saturday week year, week number, date list, headers, and range label."""
    if ref_date is None:
        ref_date = datetime.date.today()
    elif isinstance(ref_date, pd.Timestamp):
        ref_date = ref_date.date()

    days_since_sunday = (ref_date.weekday() + 1) % 7
    week_start = ref_date - datetime.timedelta(days=days_since_sunday)
    week_end = week_start + datetime.timedelta(days=6)

    # Amazon week year is determined by the Sunday start of the week
    # (e.g., 2026 runs through Week 53 starting Sun Dec 27, 2026; 2027 Week 1 starts Sun Jan 3, 2027)
    amazon_year = week_start.year
    year_start = datetime.date(amazon_year, 1, 1)
    first_sun_offset = (6 - year_start.weekday()) % 7
    first_sunday = year_start + datetime.timedelta(days=first_sun_offset)

    if week_start < first_sunday:
        prev_year = amazon_year - 1
        prev_year_start = datetime.date(prev_year, 1, 1)
        prev_first_sun = prev_year_start + datetime.timedelta(
            days=(6 - prev_year_start.weekday()) % 7
        )
        amazon_year = prev_year
        week_num = ((week_start - prev_first_sun).days // 7) + 1
    else:
        week_num = ((week_start - first_sunday).days // 7) + 1

    day_dates = [week_start + datetime.timedelta(days=i) for i in range(7)]
    day_headers = [d.strftime("%a %d %b") for d in day_dates]
    range_str = f"{week_start.strftime('%d-%b')} to {week_end.strftime('%d-%b')}"
    return amazon_year, week_num, day_dates, day_headers, range_str


def render_scheduler_tab():
    st.subheader("📅 Weekly Shift Scheduler, Standing Rules & PTO")

    sub_nav = st.segmented_control(
        "Scheduling Section",
        options=["📆 Weekly Shift Builder", "🏖️ Long-Range PTO & Standing Schedules"],
        default="📆 Weekly Shift Builder",
        label_visibility="collapsed",
        key="scheduler_sub_nav",
    )
    if not sub_nav:
        sub_nav = "📆 Weekly Shift Builder"

    drivers_df = st.session_state.get("drivers_df")
    if drivers_df is None or drivers_df.empty:
        drivers_df = load_local_drivers()
        st.session_state["drivers_df"] = drivers_df

    pto_df = load_long_range_pto_storage()
    standing_rules = load_standing_schedules_storage()
    weekly_targets = load_weekly_targets_storage()

    # ---------------------------------------------------------
    # 1. WEEKLY SHIFT BUILDER
    # ---------------------------------------------------------
    if sub_nav == "📆 Weekly Shift Builder":
        nav_c1, nav_c2, nav_c3 = st.columns([1, 2, 1])
        if "sched_anchor_date" not in st.session_state:
            st.session_state["sched_anchor_date"] = datetime.date.today()

        with nav_c1:
            if st.button("⬅️ Previous Week", use_container_width=True):
                st.session_state["sched_anchor_date"] -= datetime.timedelta(days=7)
                st.rerun()
        with nav_c2:
            picked_date = st.date_input(
                "Week Anchor Date",
                value=st.session_state["sched_anchor_date"],
                label_visibility="collapsed",
            )
            if picked_date != st.session_state["sched_anchor_date"]:
                st.session_state["sched_anchor_date"] = picked_date
                st.rerun()
        with nav_c3:
            if st.button("Next Week ➡️", use_container_width=True):
                st.session_state["sched_anchor_date"] += datetime.timedelta(days=7)
                st.rerun()

        yr, wk_num, day_dates, day_headers, range_str = get_current_amazon_week_info(
            st.session_state["sched_anchor_date"]
        )
        week_key = f"{yr}_W{wk_num:02d}"

        st.markdown(f"### Amazon Week {wk_num} ({yr}) &bull; `{range_str}`")

        # Expected Daily Route Targets
        with st.expander("🎯 Expected Daily Route Targets (1-Week Forecast)", expanded=False):
            saved_wk_targets = weekly_targets.get(week_key, {})
            t_cols = st.columns(7)
            new_targets = {}
            for i, dh in enumerate(day_headers):
                with t_cols[i]:
                    default_val = int(
                        saved_wk_targets.get(dh, saved_wk_targets.get(DAY_PREFIXES[i], 20))
                    )
                    new_targets[dh] = st.number_input(
                        dh,
                        min_value=0,
                        max_value=100,
                        value=default_val,
                        step=1,
                        key=f"tgt_{week_key}_{i}",
                    )
            if st.button("💾 Save Route Targets", type="primary"):
                weekly_targets[week_key] = new_targets
                save_weekly_targets_storage(weekly_targets)
                st.toast("Weekly route targets saved!", icon="🎯")
                st.rerun()
        expected_routes_dict = weekly_targets.get(week_key, {dh: 20 for dh in day_headers})

        # Load or Initialize Week Schedule
        raw_sched = load_local_schedule(year=yr, week_num=wk_num)
        active_drivers = (
            drivers_df[drivers_df["Status"].astype(str).str.upper() != "INACTIVE"][
                "Driver Name"
            ]
            .dropna()
            .astype(str)
            .str.strip()
            .unique()
            .tolist()
            if drivers_df is not None and not drivers_df.empty
            else []
        )

        sched_rows = []
        existing_lookup = {}
        if raw_sched is not None and not raw_sched.empty and "Driver Name" in raw_sched.columns:
            for _, r in raw_sched.iterrows():
                existing_lookup[str(r["Driver Name"]).strip().lower()] = r

        all_names = sorted(
            set(active_drivers + [str(r["Driver Name"]).strip() for _, r in raw_sched.iterrows()])
            if raw_sched is not None and not raw_sched.empty
            else set(active_drivers),
            key=lambda n: n.split()[0].upper() if n else "",
        )

        for name in all_names:
            if not name:
                continue
            row_dict = {"Driver Name": name}
            src_row = existing_lookup.get(name.lower())
            for i, dh in enumerate(day_headers):
                prefix = DAY_PREFIXES[i]
                val = ""
                if src_row is not None:
                    if dh in src_row and pd.notna(src_row[dh]):
                        val = str(src_row[dh]).strip()
                    elif prefix in src_row and pd.notna(src_row[prefix]):
                        val = str(src_row[prefix]).strip()
                if val.lower() in ["nan", "none"]:
                    val = ""

                # Overlay approved Long-Range PTO
                if pto_df is not None and not pto_df.empty:
                    d_pto = pto_df[
                        pto_df["Driver Name"].astype(str).str.strip().str.lower() == name.lower()
                    ]
                    for _, p_row in d_pto.iterrows():
                        try:
                            s_dt = pd.to_datetime(p_row["Start Date"]).date()
                            e_dt = pd.to_datetime(p_row["End Date"]).date()
                            if s_dt <= day_dates[i] <= e_dt:
                                val = "Rqst Off"
                                break
                        except Exception:
                            continue

                row_dict[dh] = val
            sched_rows.append(row_dict)

        week_sched_df = pd.DataFrame(sched_rows)
        if not week_sched_df.empty:
            week_sched_df = apply_standing_schedules_to_df(
                week_sched_df, day_headers, standing_rules, overwrite_existing=False
            )

        # KPI Summary Bar
        work_codes = ["Driver", "Helper", "OPS-AM", "OPS-PM"]
        total_shifts = (
            sum(week_sched_df[dh].isin(work_codes).sum() for dh in day_headers)
            if not week_sched_df.empty
            else 0
        )
        ot_drivers = 0
        if not week_sched_df.empty:
            for _, r in week_sched_df.iterrows():
                if sum(str(r.get(dh, "")).strip() in work_codes for dh in day_headers) > 4:
                    ot_drivers += 1

        sk1, sk2, sk3 = st.columns(3)
        sk1.metric("Rostered Team Size", len(week_sched_df))
        sk2.metric("Total Scheduled Shifts", int(total_shifts))
        sk3.metric("Overtime Risk (>4 Shifts)", ot_drivers)

        # Action Bar
        act1, act2, act3 = st.columns([1.2, 1.2, 1])
        with act1:
            if st.button("⚡ Auto-Fill Schedule", use_container_width=True):
                prev_date = st.session_state["sched_anchor_date"] - datetime.timedelta(days=7)
                p_yr, p_wk, _, _, _ = get_current_amazon_week_info(prev_date)
                prev_df = load_local_schedule(year=p_yr, week_num=p_wk)

                auto_df = auto_generate_pattern_weekly_schedule(
                    schedule_df=week_sched_df,
                    day_headers=day_headers,
                    expected_routes_dict=expected_routes_dict,
                    drivers_df=drivers_df,
                    prev_week_schedule_df=prev_df,
                    standing_rules_dict=standing_rules,
                )
                save_weekly_schedule_to_storage(auto_df, year=yr, week_num=wk_num)
                st.toast("Auto-generated weekly schedule!", icon="⚡")
                st.rerun()
        with act2:
            if st.button("🧹 Clear Non-PTO Shifts", use_container_width=True):
                cleared = week_sched_df.copy()
                for dh in day_headers:
                    cleared[dh] = cleared[dh].apply(lambda v: v if v == "Rqst Off" else "")
                save_weekly_schedule_to_storage(cleared, year=yr, week_num=wk_num)
                st.toast("Cleared non-PTO shifts.", icon="🧹")
                st.rerun()
        with act3:
            save_sched_btn = st.button(
                "💾 Save Weekly Schedule", type="primary", use_container_width=True
            )

        if not week_sched_df.empty:
            week_sched_df["Total Shifts"] = week_sched_df.apply(
                lambda r: sum(str(r.get(dh, "")).strip() in work_codes for dh in day_headers),
                axis=1,
            )
            week_sched_df["OT Alert"] = week_sched_df["Total Shifts"].apply(
                lambda cnt: "⚠️ OT (>40h)" if cnt > 4 else ""
            )

            col_cfg = {
                "Driver Name": st.column_config.TextColumn("Driver Name", disabled=True, width="medium"),
                "Total Shifts": st.column_config.NumberColumn("Shifts", disabled=True, width="small"),
                "OT Alert": st.column_config.TextColumn("Status", disabled=True, width="small"),
            }
            for dh in day_headers:
                col_cfg[dh] = st.column_config.SelectboxColumn(dh, options=SHIFT_OPTIONS, width="small")

            edited_sched = st.data_editor(
                week_sched_df,
                column_config=col_cfg,
                use_container_width=True,
                hide_index=True,
                key=f"sched_editor_{week_key}",
            )

            if save_sched_btn:
                save_cols = ["Driver Name"] + day_headers
                save_weekly_schedule_to_storage(edited_sched[save_cols], year=yr, week_num=wk_num)
                log_dispatch_action(
                    f"Saved weekly schedule for {week_key}.",
                    username=st.session_state.get("user_name"),
                )
                st.toast(f"Schedule for Week {wk_num} saved!", icon="💾")
                st.rerun()

            with st.expander("📣 Discord Schedule Announcement Generator", expanded=False):
                discord_txt = generate_discord_schedule(edited_sched, week_str=range_str)
                edited_discord = st.text_area("Discord Message Preview", value=discord_txt, height=260)
                wh_url = st.text_input("Discord Webhook URL", value=DISCORD_WEBHOOK_URL, type="password")
                if st.button("🚀 Publish Schedule to Discord", type="primary"):
                    ok, msg = send_discord_webhook(wh_url, edited_discord)
                    if ok:
                        st.toast(msg, icon="📅")
                    else:
                        st.error(msg)

    # ---------------------------------------------------------
    # 2. LONG-RANGE PTO & STANDING SCHEDULES
    # ---------------------------------------------------------
    elif sub_nav == "🏖️ Long-Range PTO & Standing Schedules":
        c_left, c_right = st.columns(2)

        with c_left:
            st.markdown("### 🏖️ Long-Range Time-Off / PTO Tracker")
            with st.form("add_pto_form", clear_on_submit=True):
                driver_names = (
                    sorted(drivers_df["Driver Name"].dropna().unique().tolist())
                    if drivers_df is not None and not drivers_df.empty
                    else []
                )
                pto_driver = (
                    st.selectbox("Driver Name", options=driver_names)
                    if driver_names
                    else st.text_input("Driver Name")
                )
                d1, d2 = st.columns(2)
                with d1:
                    s_date = st.date_input("Start Date", value=datetime.date.today())
                with d2:
                    e_date = st.date_input("End Date", value=datetime.date.today())
                pto_cat = st.selectbox(
                    "Category",
                    options=["PTO / Vacation", "Unpaid Time Off", "Medical Leave", "Military"],
                )
                pto_notes = st.text_input("Notes")

                if st.form_submit_button("➕ Add Time-Off Request", type="primary", use_container_width=True):
                    if e_date < s_date:
                        st.error("End Date cannot be earlier than Start Date.")
                    else:
                        new_pto = pd.DataFrame(
                            [
                                {
                                    "Driver Name": str(pto_driver).strip(),
                                    "Start Date": str(s_date),
                                    "End Date": str(e_date),
                                    "Category": pto_cat,
                                    "Reason / Notes": pto_notes,
                                }
                            ]
                        )
                        updated_pto = pd.concat([pto_df, new_pto], ignore_index=True)
                        save_long_range_pto_storage(updated_pto)
                        st.toast("Time-off request saved!", icon="🏖️")
                        st.rerun()

            edited_pto = st.data_editor(
                pto_df,
                num_rows="dynamic",
                use_container_width=True,
                hide_index=True,
                key="pto_table_editor",
            )
            if st.button("💾 Save PTO Table Edits", use_container_width=True):
                save_long_range_pto_storage(edited_pto)
                st.toast("PTO log updated!", icon="💾")
                st.rerun()

        with c_right:
            st.markdown("### 🔒 Standing / Fixed Weekly Schedule Rules")
            st.caption(
                "Force-assign recurring shifts (e.g., OPS Manager, Dispatchers, or fixed-day drivers) before auto-scheduling."
            )
            with st.form("standing_rule_form"):
                driver_names = (
                    sorted(drivers_df["Driver Name"].dropna().unique().tolist())
                    if drivers_df is not None and not drivers_df.empty
                    else []
                )
                rule_driver = (
                    st.selectbox("Select Team Member", options=driver_names, key="rule_driver_sel")
                    if driver_names
                    else st.text_input("Team Member Name")
                )
                rule_days = st.multiselect("Fixed Working Days", options=DAY_PREFIXES)
                rule_shift = st.selectbox(
                    "Assigned Shift Code", options=["Driver", "Helper", "OPS-AM", "OPS-PM", "On-Call"]
                )
                lock_only = st.checkbox(
                    "Lock strictly to these fixed days (do not auto-schedule extra days)",
                    value=True,
                )

                if st.form_submit_button("💾 Save Standing Rule", type="primary", use_container_width=True):
                    if rule_driver and rule_days:
                        standing_rules[str(rule_driver).strip().lower()] = {
                            "display_name": str(rule_driver).strip(),
                            "days": rule_days,
                            "shift": rule_shift,
                            "lock_only_fixed_days": lock_only,
                        }
                        save_standing_schedules_storage(standing_rules)
                        st.toast(f"Saved standing schedule for {rule_driver}!", icon="🔒")
                        st.rerun()
                    else:
                        st.error("Select a team member and at least one day.")

            if standing_rules:
                rules_list = [
                    {
                        "Team Member": v.get("display_name", k.title()),
                        "Days": ", ".join(v.get("days", [])),
                        "Shift": v.get("shift", ""),
                        "Locked Only": "Yes" if v.get("lock_only_fixed_days", True) else "No",
                        "_key": k,
                    }
                    for k, v in standing_rules.items()
                ]
                rules_df = pd.DataFrame(rules_list)
                st.dataframe(
                    rules_df[["Team Member", "Days", "Shift", "Locked Only"]],
                    use_container_width=True,
                    hide_index=True,
                )

                del_rule_key = st.selectbox(
                    "Remove Standing Rule",
                    options=["Select..."] + [r["_key"] for r in rules_list],
                    format_func=lambda k: standing_rules[k].get("display_name", k) if k in standing_rules else k,
                )
                if del_rule_key != "Select..." and st.button("🗑️ Delete Selected Rule"):
                    standing_rules.pop(del_rule_key, None)
                    save_standing_schedules_storage(standing_rules)
                    st.toast("Standing rule removed.", icon="🗑️")
                    st.rerun()
