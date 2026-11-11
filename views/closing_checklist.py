import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from engine import log_dispatch_action, save_daily_closing_checklist, update_van_last_driven
from modules.roster import update_closing_checklist_assignments, get_sorted_roster


def render_closing_checklist_tab():
    st.subheader("📝 Daily Closing & Debrief Checklist")

    active_user = st.session_state.get("user_name", "Dispatcher")

    # Button / Action to Generate/Initialize Closing Checklist from Current Roster
    if "current_roster" in st.session_state and not st.session_state["current_roster"].empty:
        col_gen1, col_gen2 = st.columns([2, 2])
        with col_gen1:
            if st.button("🚀 Generate Closing Checklist from Roster", type="primary", use_container_width=True):
                update_closing_checklist_assignments(
                    st.session_state["current_roster"], st.session_state
                )
                
                # Automatically record last driven date for all vans assigned on the roster
                roster_df = st.session_state["current_roster"]
                if "Van Bumper" in roster_df.columns:
                    van_bumpers = roster_df["Van Bumper"].dropna().unique()
                    today_str = pd.Timestamp.now().strftime("%Y-%m-%d")
                    for v in van_bumpers:
                        v_str = str(v).strip()
                        if v_str and v_str.upper() not in ["UNASSIGNED", "NAN", "NONE", "N/A", ""]:
                            update_van_last_driven(v_str, activity_date=today_str)
                            
                log_dispatch_action(
                    "Generated Daily Closing Checklist and updated van last driven records.",
                    username=active_user,
                )
                st.toast("Closing checklist generated and van last driven dates updated!", icon="🚐")
                st.rerun()

    if (
        "closing_df" not in st.session_state
        or st.session_state["closing_df"] is None
        or st.session_state["closing_df"].empty
    ):
        if (
            "current_roster" in st.session_state
            and not st.session_state["current_roster"].empty
        ):
            update_closing_checklist_assignments(
                st.session_state["current_roster"], st.session_state
            )
        else:
            st.session_state["closing_df"] = pd.DataFrame(
                columns=[
                    "Van",
                    "Driver",
                    "Route",
                    "Phone ID",
                    "Bag Returned",
                    "Key Returned",
                    "Phone Returned",
                    "Gas Level",
                    "Miles",
                    "Debrief Notes",
                    "Status",
                ]
            )

    closing_df = st.session_state["closing_df"]

    if not closing_df.empty:
        c1, c2, c3 = st.columns([2, 1, 1])
        with c1:
            st.caption("Track return of equipment, gas level, and route debrief status.")
        with c2:
            pass
        with c3:
            if st.button(
                "💾 Save Debrief Updates", type="primary", use_container_width=True
            ):
                save_daily_closing_checklist(st.session_state["closing_df"])
                
                # Also ensure last driven dates are recorded upon saving debriefs
                for _, row in st.session_state["closing_df"].iterrows():
                    v_num = str(row.get("Van", "")).strip()
                    if v_num and v_num.upper() not in ["UNASSIGNED", "NAN", "NONE", "N/A", ""]:
                        update_van_last_driven(v_num)

                log_dispatch_action(
                    "Saved Daily Closing & Debrief Checklist state & updated fleet last driven.",
                    username=active_user,
                )
                st.toast("Closing checklist saved and fleet recency updated!", icon="📝")
                st.rerun()

        closing_config = {
            "Van": st.column_config.TextColumn("Van", disabled=True, width="small"),
            "Driver": st.column_config.TextColumn(
                "Driver", disabled=True, width="medium"
            ),
            "Route": st.column_config.TextColumn(
                "Route", disabled=True, width="small"
            ),
            "Phone ID": st.column_config.TextColumn(
                "Phone ID", disabled=True, width="small"
            ),
            "Bag Returned": st.column_config.CheckboxColumn(
                "Bag Ret.", default=False, width="small"
            ),
            "Key Returned": st.column_config.CheckboxColumn(
                "Key Ret.", default=False, width="small"
            ),
            "Phone Returned": st.column_config.CheckboxColumn(
                "Phone Ret.", default=False, width="small"
            ),
            "Gas Level": st.column_config.SelectboxColumn(
                "Gas Level",
                options=["Full", "3/4", "1/2", "1/4", "Empty"],
                required=True,
                width="small",
            ),
            "Miles": st.column_config.NumberColumn(
                "End Miles", min_value=0, step=1, width="small"
            ),
            "Debrief Notes": st.column_config.TextColumn(
                "Debrief Notes / Issues", width="large"
            ),
            "Status": st.column_config.SelectboxColumn(
                "Status",
                options=["PENDING", "DEBRIEFED", "FLAGGED"],
                required=True,
                width="small",
            ),
        }

        def on_closing_change():
            changes = st.session_state.get("closing_checklist_editor_state")
            if changes and "closing_df" in st.session_state:
                for row_idx, col_changes in changes.get("edited_rows", {}).items():
                    for col_name, new_val in col_changes.items():
                        st.session_state["closing_df"].at[row_idx, col_name] = new_val
                save_daily_closing_checklist(st.session_state["closing_df"])

        st.data_editor(
            st.session_state["closing_df"],
            column_config=closing_config,
            use_container_width=True,
            hide_index=True,
            key="closing_checklist_editor_state",
            on_change=on_closing_change,
        )

        printable_closing_df = get_sorted_roster(st.session_state["closing_df"]) if 'Route' in st.session_state["closing_df"].columns else st.session_state["closing_df"]

        st.markdown("---")
        st.subheader("🖨️ Clipboard Print Preview (Closing & Debrief Checklist)")

        html_closing_view = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                    color: #111;
                    padding: 10px;
                }}
                table {{
                    width: 100%;
                    border-collapse: collapse;
                    margin-top: 10px;
                    font-size: 12px;
                }}
                th, td {{
                    border: 1px solid #ddd;
                    padding: 6px 8px;
                    text-align: left;
                }}
                th {{
                    background-color: #f4f4f4;
                    font-weight: bold;
                }}
                h3 {{
                    margin-bottom: 5px;
                }}
                .print-btn-container {{
                    margin-bottom: 15px;
                }}
                .print-btn {{
                    background-color: #007bff;
                    color: white;
                    padding: 8px 16px;
                    border: none;
                    border-radius: 4px;
                    cursor: pointer;
                    font-size: 14px;
                    font-weight: 500;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.12);
                }}
                .print-btn:hover {{
                    background-color: #0056b3;
                }}
                @media print {{
                    .print-btn-container {{
                        display: none;
                    }}
                }}
            </style>
        </head>
        <body>
            <div class="print-btn-container">
                <button class="print-btn" onclick="window.print()">🖨️ Print Checklist</button>
            </div>
            <h3>Daily Closing & Debrief Clipboard View</h3>
            {printable_closing_df.to_html(index=False, classes='closing-table', border=0)}
        </body>
        </html>
        """

        components.html(html_closing_view, height=500, scrolling=True)

        csv = printable_closing_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Export Closing Checklist CSV (For Records/Archiving)",
            data=csv,
            file_name="daily_closing_checklist.csv",
            mime="text/csv",
        )
    else:
        st.info(
            "No active roster loaded yet. Run auto-assignment or load a roster"
            " snapshot in Tab 1 to populate the closing checklist."
        )
