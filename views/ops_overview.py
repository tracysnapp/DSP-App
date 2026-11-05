import streamlit as st
import pandas as pd
from modules.roster import calculate_ops_metrics, update_closing_checklist_assignments
from engine import save_snapshot_file

def render_ops_overview_tab():
    st.subheader("📊 Daily Operations High-Level Summary")

    if 'current_roster' in st.session_state and not st.session_state['current_roster'].empty:
        roster_df = st.session_state['current_roster'].copy()
        fleet_df = st.session_state.get('fleet_df', None)

        metrics = calculate_ops_metrics(roster_df, fleet_df)

        m_col1, m_col2, m_col3, m_col4, m_col5 = st.columns(5)
        m_col1.metric("Today's Total Routes", metrics.get("total_routes", 0))
        m_col2.metric("Active Vans (UP)", metrics.get("active_fleet", 0))
        m_col3.metric("Size Fallbacks Used", metrics.get("fallback_count", 0), delta="-Fallbacks" if metrics.get("fallback_count", 0) > 0 else "Optimal", delta_color="inverse")
        m_col4.metric("Active Sweepers", metrics.get("sweeper_count", 0))
        m_col5.metric("Grounded Vans", metrics.get("grounded_fleet", 0), delta_color="inverse")

        st.markdown("---")
        st.markdown("#### 📱 Live On-Road Operations & Shift Reference Log")
        st.caption("Quick reference view for dispatchers to monitor assigned vans, device info, and shift timing.")

        ref_display_cols = ['Route', 'Driver', 'Van Bumper', 'Phone ID', 'Phone Number', 'Show Time', 'Shift End', 'Remarks']
        for col in ref_display_cols:
            if col not in roster_df.columns:
                roster_df[col] = ""

        ref_df = roster_df[ref_display_cols].copy()

        def on_ops_ref_change():
            changes = st.session_state.get("ops_ref_dashboard_editor_state")
            if changes and "current_roster" in st.session_state:
                for row_idx, col_changes in changes.get("edited_rows", {}).items():
                    if "Remarks" in col_changes:
                        st.session_state['current_roster'].at[row_idx, 'Remarks'] = col_changes["Remarks"]
                
                update_closing_checklist_assignments(st.session_state['current_roster'], st.session_state)
                now_filename = f"roster_{pd.Timestamp.now().strftime('%Y-%m-%d_%H%M')}.xlsx"
                save_snapshot_file(st.session_state['current_roster'], now_filename)

        ref_config = {
            "Route": st.column_config.TextColumn("Route", disabled=True, width="small"),
            "Driver": st.column_config.TextColumn("Driver", disabled=True, width="medium"),
            "Van Bumper": st.column_config.TextColumn("Van Bumper", disabled=True, width="small"),
            "Phone ID": st.column_config.TextColumn("Phone ID", disabled=True, width="small"),
            "Phone Number": st.column_config.TextColumn("Phone Number", disabled=True, width="medium"),
            "Show Time": st.column_config.TextColumn("Show Time", disabled=True, width="small"),
            "Shift End": st.column_config.TextColumn("Shift End", disabled=True, width="small"),
            "Remarks": st.column_config.TextColumn("Dispatcher Remarks / Notes", width="large")
        }

        st.data_editor(
            ref_df,
            column_config=ref_config,
            use_container_width=True,
            num_rows="fixed",
            hide_index=True,
            key="ops_ref_dashboard_editor_state",
            on_change=on_ops_ref_change
        )

        st.markdown("---")
        c_left, c_right = st.columns([2, 1])

        with c_left:
            st.markdown("#### 🌊 Launch Wave & Pad Distribution")
            if 'Wave' in roster_df.columns and 'Pad' in roster_df.columns:
                # FIXED: Filtered out blank or N/A wave strings before unstacking
                valid_waves_df = roster_df[roster_df['Wave'].astype(str).str.strip().str.upper().isin(['', 'N/A', 'NAN', 'NONE']) == False]
                if not valid_waves_df.empty:
                    wave_summary = valid_waves_df.groupby(['Wave', 'Pad']).size().unstack(fill_value=0)
                    st.dataframe(wave_summary, use_container_width=True)
                else:
                    st.info("Wave and Pad information will populate once routes are assigned.")
            else:
                st.info("Wave and Pad information will populate once routes are assigned.")

        with c_right:
            st.markdown("#### 📦 Route Service Type Breakdown")
            size_counts = metrics.get("size_counts", {})
            if size_counts:
                size_df = pd.DataFrame(list(size_counts.items()), columns=["Service Type", "Count"])
                st.dataframe(size_df, use_container_width=True, hide_index=True)

    else:
        st.info("Upload today's Cortex route export or load a historical roster from the sidebar to populate Ops Overview metrics.")