import pandas as pd
import streamlit as st
from engine import (
    load_local_access_codes,
    log_dispatch_action,
    save_access_codes_storage,
)


def render_access_codes_tab(is_admin=False):
    access_df = st.session_state.get("access_df")
    if access_df is None or access_df.empty:
        access_df = load_local_access_codes()
        st.session_state["access_df"] = access_df

    hdr_l, hdr_r = st.columns([3, 1])
    with hdr_l:
        st.subheader("🔑 Gate, Locker & Building Access Codes")
        st.caption(
            "All profiles can add new locations and notes. Removing rows is restricted to Admin accounts."
        )
    with hdr_r:
        st.markdown("<div style='padding-top: 0.4rem;'></div>", unsafe_allow_html=True)
        save_codes_btn = st.button(
            "💾 Save Access Directory",
            type="primary",
            use_container_width=True,
            key="save_access_codes_top_btn",
        )

    search_term = st.text_input(
        "🔍 Search Location, Address, Code, or Instructions",
        placeholder="Type apartment complex, street name, or gate code...",
        key="access_code_search",
    ).strip()

    filtered_df = access_df.copy()
    if search_term and not filtered_df.empty:
        q = search_term.lower()
        mask = filtered_df.apply(
            lambda r: q in " ".join(r.astype(str).values).lower(), axis=1
        )
        filtered_df = filtered_df[mask]

    k1, k2 = st.columns(2)
    k1.metric("Total Saved Locations", len(access_df))
    k2.metric("Matching Locations", len(filtered_df))

    st.markdown("---")

    col_config = {
        "Location": st.column_config.TextColumn("Location / Complex Name", width="medium"),
        "Code": st.column_config.TextColumn("Gate / Door Code", width="small"),
        "Special Instructions": st.column_config.TextColumn("Special Instructions", width="large"),
    }

    allow_delete = bool(is_admin and not search_term)
    edited_codes = st.data_editor(
        filtered_df,
        column_config=col_config,
        num_rows="dynamic" if allow_delete else "fixed",
        use_container_width=True,
        hide_index=True,
        key="access_codes_data_editor",
    )

    if not is_admin:
        st.caption("ℹ️ Signed in as Dispatcher: row deletion is disabled. Use the form below to add a new location.")
        with st.expander("➕ Add New Gate / Building Code", expanded=False):
            with st.form("dispatcher_add_code_form", clear_on_submit=True):
                c1, c2 = st.columns([2, 1])
                with c1:
                    new_loc = st.text_input("Location / Complex Name")
                with c2:
                    new_code = st.text_input("Gate / Door Code")
                new_notes = st.text_input("Special Instructions")
                if st.form_submit_button("➕ Add Location", type="primary", use_container_width=True):
                    if not new_loc.strip():
                        st.error("Location name is required.")
                    else:
                        new_row = pd.DataFrame(
                            [
                                {
                                    "Location": new_loc.strip(),
                                    "Code": new_code.strip(),
                                    "Special Instructions": new_notes.strip(),
                                }
                            ]
                        )
                        combined = pd.concat([access_df, new_row], ignore_index=True)
                        save_access_codes_storage(combined)
                        log_dispatch_action(
                            f"Added access code for '{new_loc.strip()}'.",
                            username=st.session_state.get("user_name"),
                        )
                        st.toast(f"Added {new_loc.strip()} to Access Directory!", icon="🔑")
                        st.rerun()

    if save_codes_btn:
        if not search_term:
            final_codes = edited_codes.copy()
        else:
            final_codes = access_df.copy()
            for idx, row in edited_codes.iterrows():
                if idx in final_codes.index:
                    for col in ["Location", "Code", "Special Instructions"]:
                        final_codes.loc[idx, col] = row[col]

        save_access_codes_storage(final_codes)
        log_dispatch_action(
            "Updated Gate & Building Access Codes.",
            username=st.session_state.get("user_name"),
        )
        st.toast("Access codes saved to Cloud Storage!", icon="💾")
        st.rerun()
