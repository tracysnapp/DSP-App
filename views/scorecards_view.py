import streamlit as st
import pandas as pd
from modules.scorecards import (
    calculate_unified_scorecard,
    append_to_master_scorecards_ledger,
    get_all_time_leaderboard,
    get_driver_historical_trend
)
from modules.schedule import send_discord_webhook, generate_discord_top_drivers
from engine import (
    DISCORD_WEBHOOK_URL, 
    safe_save_dataframe, 
    SCORECARDS_PATH, 
    log_dispatch_action, 
    load_local_incidents_log, 
    save_driver_incident
)

def render_scorecards_tab():
    st.subheader("🏆 Driver Quality Index (DQI) Scorecards & Analytics")
    
    scorecards_df = st.session_state.get('scorecards_df')
    drivers_df = st.session_state.get('drivers_df')
    fleet_df = st.session_state.get('fleet_df')
    active_user = st.session_state.get('user_name', 'Admin')

    tab_calc, tab_weekly, tab_driver_trend, tab_incidents, tab_ledger, tab_career = st.tabs([
        "📥 Batch Weekly Ingestion & DQI Calculator",
        "📊 Weekly Performance Leaderboard",
        "📈 Individual Driver Scorecard & Trends",
        "🚨 Driver Incident & Behavior Tracker",
        "📜 Master Scorecards Ledger",
        "🥇 All-Time Career Leaderboard"
    ])

    # ---------------------------------------------------------
    # TAB 1: BATCH INGESTION & CALCULATOR
    # ---------------------------------------------------------
    with tab_calc:
        st.markdown("#### 📥 Batch Weekly Cortex Scorecard Import")
        st.caption("Upload the 5 weekly Cortex report files to execute the Volume-Normalized DQI engine.")

        col_u1, col_u2 = st.columns(2)
        with col_u1:
            overview_file = st.file_uploader("1. Primary Overview Scorecard (.csv or .xlsx)*", type=["csv", "xlsx"], key="sc_ov")
            cdf_file = st.file_uploader("2. Customer Delivery Feedback (CDF) Log (.csv or .xlsx)", type=["csv", "xlsx"], key="sc_cdf")
            concessions_file = st.file_uploader("3. Delivery Concessions / DNRs (.csv or .xlsx)", type=["csv", "xlsx"], key="sc_conc")
        
        with col_u2:
            rts_file = st.file_uploader("4. Quality RTS Log (.csv or .xlsx)", type=["csv", "xlsx"], key="sc_rts")
            dvic_file = st.file_uploader("5. DVIC Pre-Trip Audit Log (.csv or .xlsx)", type=["csv", "xlsx"], key="sc_dvic")

        if overview_file:
            if st.button("⚡ Calculate Volume-Normalized DQI Scorecard", type="primary", use_container_width=True):
                try:
                    calculated_df = calculate_unified_scorecard(
                        overview_file=overview_file,
                        cdf_file=cdf_file,
                        concessions_file=concessions_file,
                        rts_file=rts_file,
                        dvic_file=dvic_file
                    )
                    st.session_state['pending_scorecard_df'] = calculated_df
                    st.toast("DQI calculation complete!", icon="✅")
                except Exception as e:
                    st.error(f"Error calculating scorecard: {str(e)}")

        if 'pending_scorecard_df' in st.session_state and not st.session_state['pending_scorecard_df'].empty:
            st.markdown("---")
            st.markdown("#### 📊 Calculated Weekly DQI Preview")
            pending_df = st.session_state['pending_scorecard_df']
            
            st.dataframe(pending_df, use_container_width=True, hide_index=True)

            c_sc1, c_sc2 = st.columns(2)
            with c_sc1:
                if st.button("💾 Append & Commit to Master Scorecards Ledger", type="primary", use_container_width=True):
                    updated_ledger = append_to_master_scorecards_ledger(pending_df)
                    st.session_state['scorecards_df'] = updated_ledger
                    
                    week_val = pending_df['Week'].iloc[0] if 'Week' in pending_df.columns else "Current Week"
                    log_dispatch_action(f"Committed weekly DQI scorecard for {week_val} ({len(pending_df)} drivers).", username=active_user)
                    
                    del st.session_state['pending_scorecard_df']
                    st.success(f"Appended scorecard for {week_val} to Master Ledger!")
                    st.rerun()

            with c_sc2:
                if st.button("🗑️ Discard Preview", type="secondary", use_container_width=True):
                    del st.session_state['pending_scorecard_df']
                    st.rerun()

    # ---------------------------------------------------------
    # TAB 2: WEEKLY PERFORMANCE LEADERBOARD
    # ---------------------------------------------------------
    with tab_weekly:
        st.markdown("#### 📊 Weekly Performance Leaderboard")
        if scorecards_df is not None and not scorecards_df.empty:
            weeks_list = list(scorecards_df['Week'].astype(str).unique()) if 'Week' in scorecards_df.columns else []
            selected_week = st.selectbox("Select Week for Performance Leaderboard", options=weeks_list, index=len(weeks_list)-1 if weeks_list else 0)

            weekly_df = scorecards_df[scorecards_df['Week'].astype(str) == selected_week].copy()
            score_col = 'Unified_Composite_Score' if 'Unified_Composite_Score' in weekly_df.columns else 'Overall Score'

            # FIXED: Added explicit non-empty guard to prevent IndexError on zero-route weeks
            if not weekly_df.empty:
                weekly_df[score_col] = pd.to_numeric(weekly_df[score_col].astype(str).str.replace('%', ''), errors='coerce').fillna(0)
                weekly_df = weekly_df.sort_values(by=[score_col, 'Packages Delivered'], ascending=[False, False]).reset_index(drop=True)

                medals = ["🥇 1st", "🥈 2nd", "🥉 3rd"]
                weekly_df['Rank'] = [medals[i] if i < len(medals) else f"#{i+1}" for i in range(len(weekly_df))]

                disp_cols = ['Rank', 'Driver Name', score_col, 'Overall Standing', 'Packages Delivered', 'FICO']
                valid_cols = [c for c in disp_cols if c in weekly_df.columns]

                st.dataframe(weekly_df[valid_cols], use_container_width=True, hide_index=True)

                st.markdown("---")
                with st.expander("📢 Broadcast Week Leaderboard to Discord"):
                    top_msg = generate_discord_top_drivers(weekly_df, week_str=selected_week)
                    st.code(top_msg, language="markdown")
                    
                    webhook_url = st.text_input("Discord Webhook URL", value=DISCORD_WEBHOOK_URL, type="password", key="sc_weekly_webhook")
                    if st.button("Publish Top Drivers to Discord Channel", type="primary"):
                        if webhook_url.strip():
                            success, msg = send_discord_webhook(webhook_url.strip(), top_msg)
                            if success:
                                st.success(msg)
                            else:
                                st.error(msg)
            else:
                st.info(f"No driver scorecard data found for week `{selected_week}`.")
        else:
            st.info("No scorecards available. Import weekly Cortex files in Tab 1.")

    # ---------------------------------------------------------
    # TAB 3: INDIVIDUAL DRIVER SCORECARD & TRENDS
    # ---------------------------------------------------------
    with tab_driver_trend:
        st.markdown("#### 📈 Individual Driver Scorecard & Trend Lines")
        
        if scorecards_df is not None and not scorecards_df.empty and 'Driver Name' in scorecards_df.columns:
            available_drivers = sorted(scorecards_df['Driver Name'].dropna().unique())
            selected_driver = st.selectbox("Select Driver Associate to Analyze", options=available_drivers, key="driver_trend_sel")

            if selected_driver:
                driver_history_df, metrics, driver_incidents_df = get_driver_historical_trend(scorecards_df, selected_driver)

                if not driver_history_df.empty:
                    st.markdown(f"### Scorecard Performance: **{metrics['matched_name']}**")
                    
                    m_col1, m_col2, m_col3, m_col4, m_col5 = st.columns(5)
                    m_col1.metric("Career Avg DQI", f"{metrics['avg_dqi']}")
                    m_col2.metric("Most Recent DQI", f"{metrics['recent_score']}", delta=f"{metrics['trend_delta']} vs prev week")
                    m_col3.metric("Peak DQI Score", f"{metrics['max_dqi']}")
                    m_col4.metric("Lifetime Packages", f"{metrics['lifetime_packages']:,}")
                    m_col5.metric("Safety/Behavior Incidents", f"{metrics['incident_count']}")

                    st.markdown("#### 📉 Week-Over-Week DQI Trend Line")
                    score_col = 'Unified_Composite_Score' if 'Unified_Composite_Score' in driver_history_df.columns else 'Overall Score'
                    
                    chart_data = driver_history_df.set_index('Week')[[score_col]].rename(columns={score_col: "DQI Score"})
                    st.line_chart(chart_data)

                    st.markdown("#### 🚨 Safety & Driving Behavior Incidents Log")
                    if not driver_incidents_df.empty:
                        st.dataframe(driver_incidents_df, use_container_width=True, hide_index=True)
                    else:
                        st.success("Clean safety record! No driving or behavior incidents logged for this driver.")

                    st.markdown("#### 📜 Historical Weekly Breakdown")
                    st.dataframe(driver_history_df, use_container_width=True, hide_index=True)
                else:
                    st.warning("No historical scorecard data found for this driver.")
        else:
            st.info("No historical scorecard records found in `master_scorecards.xlsx`.")

    # ---------------------------------------------------------
    # TAB 4: DRIVER INCIDENT & BEHAVIOR TRACKER
    # ---------------------------------------------------------
    with tab_incidents:
        st.markdown("#### 🚨 Driver Incident & Behavior Log")
        st.caption("Record on-pad or on-road safety violations, vehicle damage, unprofessional behavior, or customer/warehouse complaints.")

        incidents_df = load_local_incidents_log()

        with st.expander("➕ Log New Driving or Behavior Incident", expanded=True):
            col_in1, col_in2, col_in3 = st.columns(3)
            
            driver_options = []
            if drivers_df is not None and not drivers_df.empty and 'Driver Name' in drivers_df.columns:
                driver_options = sorted(drivers_df['Driver Name'].dropna().unique())
            elif scorecards_df is not None and not scorecards_df.empty and 'Driver Name' in scorecards_df.columns:
                driver_options = sorted(scorecards_df['Driver Name'].dropna().unique())

            inc_driver = col_in1.selectbox("Driver Associate*", options=driver_options if driver_options else ["Select Driver..."], key="inc_d_name")
            inc_severity = col_in2.selectbox("Severity Level*", options=["Minor (Coaching Required)", "Moderate (Written Warning)", "Severe (Final Warning)", "Critical (Suspension / Termination)"], key="inc_sev")
            
            inc_category = col_in3.selectbox("Incident Category*", options=[
                "Pad/Parking Lot Safety",
                "Reckless Driving",
                "Damage to Vehicle",
                "Left Trash In Van",
                "Unprofessional Behavior / Attitude",
                "Customer Complaint",
                "Property Damage",
                "Uniform Violation",
                "Route Refusal/Package Abandonment",
                "Gross Insubordination",
                "Other"
            ], key="inc_cat")

            col_in4, col_in5 = st.columns(2)
            
            van_list = ["N/A"]
            if fleet_df is not None and not fleet_df.empty and 'vehicleName' in fleet_df.columns:
                van_list += sorted(fleet_df['vehicleName'].astype(str).str.strip().unique())

            inc_van = col_in4.selectbox("Associated Van Bumper (Optional)", options=van_list, key="inc_van_sel")
            inc_detail = col_in5.text_input("Short Infraction Summary*", placeholder="e.g. Copped an attitude with dispatcher over dispatch phone and hung up multiple times", key="inc_detail_input")
            
            inc_notes = st.text_area("Detailed Action Taken / Management Notes", placeholder="e.g. Addressed attitude on dispatch line during debrief; issued formal warning regarding professional communication.", key="inc_notes_input")

            if st.button("🚨 Record Incident to Master Log", type="primary"):
                if not inc_driver or inc_driver == "Select Driver..." or not inc_detail.strip():
                    st.warning("Please select a valid driver and enter an infraction summary.")
                else:
                    save_driver_incident(
                        driver_name=inc_driver,
                        severity=inc_severity,
                        category=inc_category,
                        infraction_detail=inc_detail,
                        van_bumper=inc_van,
                        logged_by=active_user,
                        notes=inc_notes
                    )
                    log_dispatch_action(f"Logged safety incident for driver '{inc_driver}' ({inc_category} - {inc_severity}).", username=active_user)
                    st.toast(f"Logged incident for {inc_driver}!", icon="🚨")
                    st.rerun()

        st.markdown("---")
        st.markdown("#### 📜 Master Incident & Behavior Log Ledger")
        if incidents_df is not None and not incidents_df.empty:
            st.dataframe(incidents_df, use_container_width=True, hide_index=True)
        else:
            st.info("No driving or behavior incidents currently recorded.")

    # ---------------------------------------------------------
    # TAB 5: MASTER SCORECARDS LEDGER
    # ---------------------------------------------------------
    with tab_ledger:
        st.markdown("#### 📜 Historical Master Scorecards Ledger")
        if scorecards_df is not None and not scorecards_df.empty:
            weeks_list = ["ALL WEEKS"] + list(scorecards_df['Week'].astype(str).unique()) if 'Week' in scorecards_df.columns else ["ALL WEEKS"]
            sel_week = st.selectbox("Filter Ledger by Week", options=weeks_list, key="ledger_filter_week")

            filtered_ledger = scorecards_df if sel_week == "ALL WEEKS" else scorecards_df[scorecards_df['Week'].astype(str) == sel_week]
            st.dataframe(filtered_ledger, use_container_width=True, hide_index=True)
        else:
            st.info("No historical scorecards loaded. Use Tab 1 to import weekly scorecards.")

    # ---------------------------------------------------------
    # TAB 6: CAREER LEADERBOARD
    # ---------------------------------------------------------
    with tab_career:
        st.markdown("#### 🥇 All-Time Package-Weighted Career Leaderboard")
        if scorecards_df is not None and not scorecards_df.empty:
            active_only = st.checkbox("Show Active Drivers Only", value=True)
            min_pkgs = st.number_input("Minimum Lifetime Deliveries Threshold", value=1000, step=250)

            leaderboard_df = get_all_time_leaderboard(
                scorecards_df, 
                min_lifetime_deliveries=min_pkgs, 
                active_drivers_only=active_only, 
                drivers_df=drivers_df
            )
            st.dataframe(leaderboard_df, use_container_width=True, hide_index=True)
        else:
            st.info("Leaderboard will populate once scorecards are committed to the master ledger.")