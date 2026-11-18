import pandas as pd
import streamlit as st
from engine import (
    delete_driver_incident,
    load_local_incidents_log,
    load_local_scorecards,
    log_dispatch_action,
    save_driver_incident,
    update_driver_incident,
)
from modules.schedule import generate_discord_top_drivers, send_discord_webhook
from modules.scorecards import (
    append_to_master_scorecards_ledger,
    calculate_unified_scorecard,
    get_all_time_leaderboard,
    get_driver_historical_trend,
)

INCIDENT_SEVERITIES = [
    "Minor (-3 pts | 7-Day Recognition Hold)",
    "Moderate (-6 pts | 14-Day Recognition Hold)",
    "Severe (-10 pts | 30-Day Recognition Hold)",
    "Critical (-15 pts | Permanent Disqualification)",
]

INCIDENT_CATEGORIES = [
    "Pad / Parking Lot Safety",
    "Damage to Vehicle",
    "Property Damage",
    "Reckless Driving / Netradyne",
    "Customer Complaint / Escalation",
    "Route Refusal / Package Abandonment",
    "Uniform / Dress Code Violation",
    "Left Trash / Unclean Van",
    "Gross Insubordination / Policy",
    "Other",
]


def _get_prioritized_incident_drivers():
    drivers_df = st.session_state.get("drivers_df")
    current_roster = st.session_state.get("current_roster")

    on_road = []
    if current_roster is not None and not current_roster.empty:
        for col in ["Driver", "Helper"]:
            if col in current_roster.columns:
                for val in current_roster[col].dropna().unique():
                    v = str(val).strip()
                    if v and v.lower() not in ["nan", "none", "null", "unassigned"] and v not in on_road:
                        on_road.append(v)

    all_drivers = []
    if drivers_df is not None and not drivers_df.empty and "Driver Name" in drivers_df.columns:
        all_drivers = sorted(drivers_df["Driver Name"].dropna().astype(str).str.strip().unique().tolist())

    options = []
    label_map = {}
    seen = set()

    for name in sorted(on_road):
        lbl = f"🟢 {name} (On Road Today)"
        options.append(lbl)
        label_map[lbl] = name
        seen.add(name.lower())

    for name in all_drivers:
        if name and name.lower() not in seen:
            options.append(name)
            label_map[name] = name
            seen.add(name.lower())

    return options, label_map


def _get_fleet_van_options():
    fleet_df = st.session_state.get("fleet_df")
    vans = ["N/A"]
    if fleet_df is not None and not fleet_df.empty:
        bumper_col = next(
            (c for c in fleet_df.columns if c in ["Van Bumper", "vehicleName", "Bumper #"]),
            None,
        )
        if bumper_col:
            raw_vans = (
                fleet_df[bumper_col]
                .dropna()
                .astype(str)
                .str.strip()
                .str.replace(r"\.0$", "", regex=True)
                .unique()
                .tolist()
            )
            vans.extend(sorted([v for v in raw_vans if v and v.upper() != "UNNAMED"]))
    return vans


def render_scorecards_tab():
    st.subheader("📊 Driver Scorecards, Rankings & Incident Management")

    sub_nav = st.segmented_control(
        "Scorecard Section",
        options=[
            "📥 Weekly Upload & Calc",
            "🏆 Weekly Leaderboard",
            "🥇 All-Time Career Rankings",
            "📈 Driver Trend Analytics",
            "⚠️ Incident & Behavior Log",
            "📣 Discord Recognition",
        ],
        default="📥 Weekly Upload & Calc",
        label_visibility="collapsed",
        key="scorecards_sub_nav",
    )
    if not sub_nav:
        sub_nav = "📥 Weekly Upload & Calc"

    st.markdown("---")

    master_sc_df = st.session_state.get("scorecards_df")
    if master_sc_df is None or master_sc_df.empty:
        master_sc_df = load_local_scorecards()
        st.session_state["scorecards_df"] = master_sc_df

    # ---------------------------------------------------------
    # 1. WEEKLY UPLOAD & CALCULATION
    # ---------------------------------------------------------
    if sub_nav == "📥 Weekly Upload & Calc":
        st.markdown("#### Upload Weekly Amazon Scorecard Exports")
        st.caption(
            "Automatically merges CDF, Concessions, Quality RTS, DVIC Audit, Master Incidents, and Rescues into a volume-normalized Unified Composite DQI Score."
        )

        u1, u2 = st.columns(2)
        with u1:
            overview_file = st.file_uploader(
                "1. Primary Overview Scorecard (Required)",
                type=["csv", "xlsx"],
                key="sc_overview_up",
            )
            cdf_file = st.file_uploader(
                "2. Customer Delivery Feedback (CDF) Log",
                type=["csv", "xlsx"],
                key="sc_cdf_up",
            )
            concessions_file = st.file_uploader(
                "3. Delivery Concessions / DNRs",
                type=["csv", "xlsx"],
                key="sc_conc_up",
            )
        with u2:
            rts_file = st.file_uploader(
                "4. Quality RTS Log",
                type=["csv", "xlsx"],
                key="sc_rts_up",
            )
            dvic_file = st.file_uploader(
                "5. DVIC Pre-Trip Inspection Audit",
                type=["csv", "xlsx"],
                key="sc_dvic_up",
            )

        if st.button("⚡ Calculate & Save Weekly Scorecard", type="primary", use_container_width=True):
            if not overview_file:
                st.error("Please upload the Primary Overview Scorecard file first.")
            else:
                try:
                    with st.spinner("Computing Unified Composite DQI Scores..."):
                        calc_df = calculate_unified_scorecard(
                            overview_file=overview_file,
                            cdf_file=cdf_file,
                            concessions_file=concessions_file,
                            rts_file=rts_file,
                            dvic_file=dvic_file,
                        )
                        updated_master = append_to_master_scorecards_ledger(calc_df)
                        load_local_scorecards.clear()
                        st.session_state["scorecards_df"] = updated_master
                        st.session_state["latest_calc_scorecard"] = calc_df
                        log_dispatch_action(
                            f"Processed and saved weekly scorecard ({len(calc_df)} drivers).",
                            username=st.session_state.get("user_name"),
                        )
                        st.toast(f"Scorecard calculated for {len(calc_df)} drivers!", icon="📊")
                except Exception as e:
                    st.error(f"Error calculating scorecard: {e}")

        if "latest_calc_scorecard" in st.session_state and not st.session_state["latest_calc_scorecard"].empty:
            st.markdown("#### Latest Calculated Results")
            res_df = st.session_state["latest_calc_scorecard"].sort_values(
                by="Unified_Composite_Score", ascending=False
            )
            st.dataframe(res_df, use_container_width=True, hide_index=True)

    # ---------------------------------------------------------
    # 2. WEEKLY LEADERBOARD
    # ---------------------------------------------------------
    elif sub_nav == "🏆 Weekly Leaderboard":
        if master_sc_df is None or master_sc_df.empty or "Week" not in master_sc_df.columns:
            st.info("No historical scorecards uploaded yet.")
            return

        weeks = sorted(master_sc_df["Week"].dropna().unique().tolist(), reverse=True)
        sel_week = st.selectbox("Select Scorecard Week", options=weeks, key="weekly_lb_week_sel")

        week_df = master_sc_df[master_sc_df["Week"] == sel_week].copy()
        score_col = (
            "Unified_Composite_Score"
            if "Unified_Composite_Score" in week_df.columns
            else "Overall Score"
        )
        week_df[score_col] = pd.to_numeric(week_df[score_col], errors="coerce").fillna(0.0)
        week_df = week_df.sort_values(
            by=[score_col, "Packages Delivered"], ascending=[False, False]
        ).reset_index(drop=True)
        week_df.insert(0, "Rank", week_df.index + 1)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Drivers Evaluated", len(week_df))
        m2.metric("Team Avg Composite DQI", f"{week_df[score_col].mean():.2f}")
        m3.metric("Top Score", f"{week_df[score_col].max():.2f}")
        m4.metric("Total Packages", f"{int(week_df['Packages Delivered'].sum()):,}")

        st.dataframe(week_df, use_container_width=True, hide_index=True)

    # ---------------------------------------------------------
    # 3. ALL-TIME CAREER RANKINGS
    # ---------------------------------------------------------
    elif sub_nav == "🥇 All-Time Career Rankings":
        if master_sc_df is None or master_sc_df.empty:
            st.info("No historical scorecards uploaded yet.")
            return

        f1, f2 = st.columns([1, 2])
        with f1:
            active_only = st.checkbox("Active Drivers Only", value=True, key="career_active_only")
        with f2:
            min_pkgs = st.number_input(
                "Minimum Lifetime Deliveries for Official Rank",
                min_value=0,
                max_value=50000,
                value=1000,
                step=250,
            )

        leaderboard_df = get_all_time_leaderboard(
            master_scorecards_df=master_sc_df,
            min_lifetime_deliveries=min_pkgs,
            active_drivers_only=active_only,
            drivers_df=st.session_state.get("drivers_df"),
        )
        st.dataframe(leaderboard_df, use_container_width=True, hide_index=True)

    # ---------------------------------------------------------
    # 4. DRIVER TREND ANALYTICS
    # ---------------------------------------------------------
    elif sub_nav == "📈 Driver Trend Analytics":
        if master_sc_df is None or master_sc_df.empty or "Driver Name" not in master_sc_df.columns:
            st.info("No historical scorecards uploaded yet.")
            return

        driver_names = sorted(master_sc_df["Driver Name"].dropna().unique().tolist())
        sel_driver = st.selectbox("Select Driver", options=driver_names, key="trend_driver_sel")

        trend_df, summary, driver_incs = get_driver_historical_trend(master_sc_df, sel_driver)
        if trend_df.empty:
            st.warning("No scorecard trend records found for this driver.")
            return

        t1, t2, t3, t4, t5 = st.columns(5)
        t1.metric("Weeks Tracked", summary["weeks_tracked"])
        t2.metric("Career Avg DQI", f"{summary['avg_dqi']:.2f}")
        t3.metric("Latest DQI", f"{summary['recent_score']:.2f}", delta=f"{summary['trend_delta']:+.2f}")
        t4.metric("Lifetime Packages", f"{summary['lifetime_packages']:,}")
        t5.metric("Incidents on Record", summary["incident_count"])

        score_col = (
            "Unified_Composite_Score"
            if "Unified_Composite_Score" in trend_df.columns
            else "Overall Score"
        )
        chart_df = trend_df[["Week", score_col, "Overall Score"]].set_index("Week")
        st.line_chart(chart_df)

        st.markdown("#### Weekly Breakdown")
        st.dataframe(trend_df, use_container_width=True, hide_index=True)

        if not driver_incs.empty:
            st.markdown("#### Associated Incident History")
            st.dataframe(driver_incs, use_container_width=True, hide_index=True)

    # ---------------------------------------------------------
    # 5. INCIDENT & BEHAVIOR LOG
    # ---------------------------------------------------------
    elif sub_nav == "⚠️ Incident & Behavior Log":
        incidents_df = load_local_incidents_log()
        st.session_state["incidents_log_df"] = incidents_df

        total_inc = len(incidents_df) if incidents_df is not None else 0
        crit_cnt = (
            len(incidents_df[incidents_df["Severity"].astype(str).str.upper().str.contains("CRITICAL")])
            if total_inc > 0
            else 0
        )
        sev_cnt = (
            len(incidents_df[incidents_df["Severity"].astype(str).str.upper().str.contains("SEVERE")])
            if total_inc > 0
            else 0
        )

        ik1, ik2, ik3 = st.columns(3)
        ik1.metric("Total Incidents Logged", total_inc)
        ik2.metric("Severe Incidents", sev_cnt)
        ik3.metric("Critical Incidents", crit_cnt)

        st.markdown("---")

        driver_opts, driver_label_map = _get_prioritized_incident_drivers()
        van_opts = _get_fleet_van_options()

        with st.expander("➕ Log New Driver Incident / Infraction", expanded=False):
            with st.form("new_incident_form", clear_on_submit=True):
                ic1, ic2, ic3 = st.columns(3)
                with ic1:
                    if driver_opts:
                        d_sel = st.selectbox("Driver Name", options=driver_opts)
                        inc_driver = driver_label_map.get(d_sel, d_sel)
                    else:
                        inc_driver = st.text_input("Driver Name")
                with ic2:
                    inc_sev = st.selectbox("Severity Level", options=INCIDENT_SEVERITIES)
                with ic3:
                    inc_cat = st.selectbox("Incident Category", options=INCIDENT_CATEGORIES)

                ic4, ic5 = st.columns([1, 2])
                with ic4:
                    inc_van = st.selectbox("Van Bumper (If Applicable)", options=van_opts)
                with ic5:
                    inc_detail = st.text_input(
                        "Infraction / Event Summary",
                        placeholder="e.g., Backed into mailbox on Elm St; reported immediately",
                    )

                inc_notes = st.text_area("Supervisor Notes / Coaching Action", height=80)

                if st.form_submit_button("💾 Save Incident Record", type="primary", use_container_width=True):
                    if not str(inc_driver).strip():
                        st.error("Driver Name is required.")
                    else:
                        updated_inc = save_driver_incident(
                            driver_name=inc_driver,
                            severity=inc_sev,
                            category=inc_cat,
                            infraction_detail=inc_detail,
                            van_bumper=inc_van,
                            logged_by=st.session_state.get("user_name", "Admin"),
                            notes=inc_notes,
                        )
                        st.session_state["incidents_log_df"] = updated_inc
                        log_dispatch_action(
                            f"Logged {inc_sev} incident for {inc_driver} ({inc_cat}).",
                            username=st.session_state.get("user_name"),
                        )
                        st.toast("Incident logged to Master Ledger!", icon="⚠️")
                        st.rerun()

        st.markdown("### 📋 Master Incident Ledger")
        if incidents_df is None or incidents_df.empty:
            st.info("No driver incidents recorded.")
            return

        inc_search = st.text_input(
            "🔍 Filter Incidents by Driver, Category, Severity, or Van",
            placeholder="Search incidents...",
            key="incident_search_input",
        ).strip().lower()

        disp_inc = incidents_df.copy()
        if inc_search:
            mask = disp_inc.apply(
                lambda r: inc_search in " ".join(r.astype(str).values).lower(), axis=1
            )
            disp_inc = disp_inc[mask]

        st.dataframe(disp_inc.iloc[::-1].reset_index(drop=True), use_container_width=True, hide_index=True)

        with st.expander("✏️ Edit or Delete an Incident Record", expanded=False):
            inc_labels = [
                f"Row {idx} | {row.get('Date', '')} — {row.get('Driver Name', '')} [{row.get('Category', '')}]"
                for idx, row in incidents_df.iterrows()
            ]
            sel_inc_lbl = st.selectbox(
                "Select Incident to Modify",
                options=list(reversed(inc_labels)),
                key="edit_incident_selector",
            )
            inc_idx = int(sel_inc_lbl.split("|")[0].replace("Row", "").strip())
            inc_row = incidents_df.loc[inc_idx]

            with st.form("edit_incident_form"):
                e1, e2, e3 = st.columns(3)
                with e1:
                    e_driver = st.text_input("Driver Name", value=str(inc_row.get("Driver Name", "")))
                with e2:
                    curr_s = str(inc_row.get("Severity", INCIDENT_SEVERITIES[0]))
                    s_idx = INCIDENT_SEVERITIES.index(curr_s) if curr_s in INCIDENT_SEVERITIES else 0
                    e_sev = st.selectbox("Severity Level", options=INCIDENT_SEVERITIES, index=s_idx)
                with e3:
                    curr_c = str(inc_row.get("Category", INCIDENT_CATEGORIES[0]))
                    c_idx = INCIDENT_CATEGORIES.index(curr_c) if curr_c in INCIDENT_CATEGORIES else 0
                    e_cat = st.selectbox("Category", options=INCIDENT_CATEGORIES, index=c_idx)

                e4, e5 = st.columns([1, 2])
                with e4:
                    curr_v = str(inc_row.get("Van Bumper", "N/A"))
                    if curr_v not in van_opts:
                        van_opts = [curr_v] + van_opts
                    e_van = st.selectbox("Van Bumper", options=van_opts, index=van_opts.index(curr_v))
                with e5:
                    e_detail = st.text_input(
                        "Infraction / Detail", value=str(inc_row.get("Infraction / Detail", ""))
                    )

                e_notes = st.text_area("Notes", value=str(inc_row.get("Notes", "")), height=80)

                b1, b2 = st.columns(2)
                with b1:
                    upd_inc_btn = st.form_submit_button(
                        "💾 Update Incident", type="primary", use_container_width=True
                    )
                with b2:
                    del_inc_btn = st.form_submit_button(
                        "🗑️ Delete Incident", type="secondary", use_container_width=True
                    )

                if upd_inc_btn:
                    updated_df = update_driver_incident(
                        row_idx=inc_idx,
                        driver_name=e_driver,
                        severity=e_sev,
                        category=e_cat,
                        infraction_detail=e_detail,
                        van_bumper=e_van,
                        logged_by=st.session_state.get("user_name", "Admin"),
                        notes=e_notes,
                    )
                    st.session_state["incidents_log_df"] = updated_df
                    st.toast("Incident updated!", icon="💾")
                    st.rerun()

                if del_inc_btn:
                    updated_df = delete_driver_incident(inc_idx)
                    st.session_state["incidents_log_df"] = updated_df
                    st.toast("Incident deleted.", icon="🗑️")
                    st.rerun()

    # ---------------------------------------------------------
    # 6. DISCORD RECOGNITION ANNOUNCEMENT
    # ---------------------------------------------------------
    elif sub_nav == "📣 Discord Recognition":
        if master_sc_df is None or master_sc_df.empty or "Week" not in master_sc_df.columns:
            st.info("Upload a weekly scorecard first to generate Top Driver announcements.")
            return

        weeks = sorted(master_sc_df["Week"].dropna().unique().tolist(), reverse=True)
        c1, c2 = st.columns(2)
        with c1:
            rec_week = st.selectbox("Select Week", options=weeks, key="discord_rec_week")
        with c2:
            min_rec_pkgs = st.number_input(
                "Min Weekly Packages Delivered", min_value=0, max_value=2000, value=100, step=25
            )

        w_df = master_sc_df[master_sc_df["Week"] == rec_week].copy()
        if "Recognition_Eligible" in w_df.columns:
            w_df = w_df[w_df["Recognition_Eligible"].fillna(True).astype(bool)]

        msg_preview = generate_discord_top_drivers(
            w_df, week_str=str(rec_week), min_pkg_threshold=min_rec_pkgs
        )
        edited_msg = st.text_area("Discord Announcement Preview", value=msg_preview, height=260)

        from engine import DISCORD_WEBHOOK_URL

        webhook_input = st.text_input(
            "Discord Webhook URL", value=DISCORD_WEBHOOK_URL, type="password"
        )
        if st.button("🚀 Publish Top Drivers to Discord", type="primary"):
            ok, status_msg = send_discord_webhook(webhook_input, edited_msg)
            if ok:
                st.toast(status_msg, icon="🏆")
            else:
                st.error(status_msg)
