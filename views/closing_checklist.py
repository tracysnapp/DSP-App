import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from engine import log_dispatch_action, save_daily_closing_checklist
from modules.roster import generate_printable_closing_html

CLOSING_COLUMNS = [
    "Driver Name",
    "Van",
    "Clock out time",
    "DVIC Complete",
    "Damage?",
    "Cleaned?",
    "Keys Returned",
    "Phone Returned",
    "Portable Charger",
    "Fuel Card Returned",
    "Fuel Level",
    "Packages/Returns Handled",
    "Remarks",
    "DA Signature",
]


def render_closing_checklist_tab():
    hdr_left, hdr_right = st.columns([3, 1])
    with hdr_left:
        st.subheader("📝 End-of-Day Driver Closing & Debrief Checklist")
        st.caption(
            "Auto-populated from today's active Dispatch Roster. Track van returns, equipment check-in, and debrief remarks."
        )
    with hdr_right:
        st.markdown("<div style='padding-top: 0.4rem;'></div>", unsafe_allow_html=True)
        save_top_clicked = st.button(
            "💾 Save Debrief Log",
            type="primary",
            use_container_width=True,
            key="save_closing_top_btn",
        )

    closing_df = st.session_state.get("closing_df")
    if closing_df is None or closing_df.empty:
        closing_df = pd.DataFrame(columns=CLOSING_COLUMNS)
    else:
        closing_df = closing_df.copy()
        if "Van Number" in closing_df.columns and "Van" not in closing_df.columns:
            closing_df = closing_df.rename(columns={"Van Number": "Van"})
        for col in CLOSING_COLUMNS:
            if col not in closing_df.columns:
                closing_df[col] = ""
        closing_df = closing_df[CLOSING_COLUMNS].fillna("").astype(str)

    # Top KPI Summary Bar
    total_out = len(closing_df)
    debriefed_cnt = (
        len(
            closing_df[
                (closing_df["Clock out time"].str.strip() != "")
                | (closing_df["Keys Returned"].str.strip().str.upper() == "YES")
            ]
        )
        if total_out > 0
        else 0
    )
    pending_cnt = max(total_out - debriefed_cnt, 0)
    flagged_cnt = (
        len(
            closing_df[
                (closing_df["Damage?"].str.strip().str.upper() == "YES")
                | (closing_df["Cleaned?"].str.strip().str.upper() == "NO")
                | (closing_df["DVIC Complete"].str.strip().str.upper() == "NO")
            ]
        )
        if total_out > 0
        else 0
    )

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Vans / Drivers Out", total_out)
    k2.metric("Debriefed", debriefed_cnt)
    k3.metric("Pending Return", pending_cnt)
    k4.metric("Flagged Issues", flagged_cnt)

    st.markdown("---")

    if closing_df.empty:
        st.info(
            "No active routes loaded yet. Upload a Cortex export or restore a snapshot in the sidebar to populate the debrief checklist."
        )
        return

    closing_config = {
        "Driver Name": st.column_config.TextColumn("Driver Name", width="medium"),
        "Van": st.column_config.TextColumn("Van", width="small"),
        "Clock out time": st.column_config.TextColumn("Clock Out", width="small"),
        "DVIC Complete": st.column_config.SelectboxColumn(
            "DVIC", options=["", "Yes", "No"], width="small"
        ),
        "Damage?": st.column_config.SelectboxColumn(
            "Damage?", options=["", "No", "Yes"], width="small"
        ),
        "Cleaned?": st.column_config.SelectboxColumn(
            "Cleaned?", options=["", "Yes", "No"], width="small"
        ),
        "Keys Returned": st.column_config.SelectboxColumn(
            "Keys", options=["", "Yes", "No"], width="small"
        ),
        "Phone Returned": st.column_config.SelectboxColumn(
            "Phone", options=["", "Yes", "No"], width="small"
        ),
        "Portable Charger": st.column_config.SelectboxColumn(
            "Charger", options=["", "Yes", "No"], width="small"
        ),
        "Fuel Card Returned": st.column_config.SelectboxColumn(
            "Fuel Card", options=["", "Yes", "No"], width="small"
        ),
        "Fuel Level": st.column_config.SelectboxColumn(
            "Fuel",
            options=["", "Full", "3/4", "1/2", "1/4", "Low"],
            width="small",
        ),
        "Packages/Returns Handled": st.column_config.SelectboxColumn(
            "RTS Handled", options=["", "Yes", "No", "N/A"], width="small"
        ),
        "Remarks": st.column_config.TextColumn("Remarks", width="large"),
        "DA Signature": st.column_config.TextColumn("DA Signature", width="medium"),
    }

    edited_closing = st.data_editor(
        closing_df,
        column_config=closing_config,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key="closing_checklist_editor",
    )

    if save_top_clicked:
        cleaned_save = edited_closing.fillna("").astype(str)
        st.session_state["closing_df"] = cleaned_save
        save_daily_closing_checklist(cleaned_save)
        log_dispatch_action(
            "Updated and saved End-of-Day Closing Checklist.",
            username=st.session_state.get("user_name"),
        )
        st.toast("Closing checklist saved to Cloud Storage!", icon="💾")
        st.rerun()

    st.markdown("---")
    with st.expander("🖨️ Printable Landscape Debrief Sheet (Clipboard Ready)", expanded=False):
        st.caption(
            "Generates a clean landscape print sheet with blank check-in boxes and wide signature fields."
        )
        printable_html = generate_printable_closing_html(edited_closing)
        components.html(printable_html, height=520, scrolling=True)
