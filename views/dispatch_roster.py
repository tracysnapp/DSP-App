import datetime
from difflib import SequenceMatcher
import re
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from engine import (
    MASTER_DRIVERS_PATH,
    MASTER_FLEET_PATH,
    get_van_last_driven_dict,
    load_local_drivers,
    log_dispatch_action,
    safe_save_dataframe,
    save_snapshot_file,
)
from modules.fleet import find_matching_phone, process_driver_data
from modules.roster import (
    condense_service_type,
    generate_printable_html,
    get_prioritized_reserve_drivers,
    get_sorted_roster,
    run_auto_assignment,
    update_closing_checklist_assignments,
)


def normalize_name(name_str):
  if pd.isna(name_str) or not str(name_str).strip():
    return ""

  s = str(name_str).strip().lower()

  if "," in s:
    parts = [p.strip() for p in s.split(",", 1)]
    if len(parts) == 2:
      s = f"{parts[1]} {parts[0]}"

  s = re.sub(r"[^a-z\s]", "", s)
  tokens = s.split()

  if not tokens:
    return ""
  if len(tokens) == 1:
    return tokens[0]

  return f"{tokens[0]} {tokens[-1]}"


def is_driver_in_directory(
    cortex_name, known_drivers_list, similarity_threshold=0.85
):
  cortex_norm = normalize_name(cortex_name)
  if not cortex_norm:
    return True

  for known in known_drivers_list:
    known_norm = normalize_name(known)

    if cortex_norm == known_norm:
      return True

    if (
        SequenceMatcher(None, cortex_norm, known_norm).ratio()
        >= similarity_threshold
    ):
      return True

  return False


def format_van_with_recency_and_size(van_bumper, fleet_df, last_driven_map):
  bmp = str(van_bumper).strip()
  st_val = "M"
  v_type = ""

  if fleet_df is not None and not fleet_df.empty and "vehicleName" in fleet_df.columns:
    match = fleet_df[fleet_df["vehicleName"].astype(str).str.strip() == bmp]
    if not match.empty:
      st_val = str(match.iloc[0].get("ST", "M")).strip()
      v_type = str(match.iloc[0].get("type_clean", "")).strip()

  recency_str = "Never driven / No history"
  if bmp in last_driven_map:
    last_date = last_driven_map[bmp]
    days_ago = (datetime.date.today() - last_date).days
    if days_ago == 0:
      recency_str = "Driven today"
    elif days_ago == 1:
      recency_str = "Last driven yesterday (1 day ago)"
    else:
      recency_str = f"Last driven {days_ago} days ago"

  type_part = f" ({v_type} - {st_val})" if v_type else f" ({st_val})"
  return f"{bmp}{type_part} | {recency_str}"


def render_dispatch_roster_tab(cortex_file, update_live_roster_fn):
  st.subheader("Daily Route Assignment & Roster")

  fleet = st.session_state.get("fleet_df")
  phones = st.session_state.get("phones_df")
  drivers_df = st.session_state.get("drivers_df")
  active_user = st.session_state.get("user_name", "Dispatcher")

  # Load van recency map ONCE at the start of the tab render
  last_driven_map = get_van_last_driven_dict()

  if fleet is not None:
    active_mask = (
        fleet["status_clean"].isin(
            ["UP", "ACTIVE", "OPERATIONAL", "WORKABLE", "AVAILABLE"]
        )
        if "status_clean" in fleet.columns
        else [True] * len(fleet)
    )
    active_fleet_df = (
        fleet[active_mask].copy()
        if "status_clean" in fleet.columns
        else fleet.copy()
    )
    active_count = len(active_fleet_df)

    if (
        "current_roster" in st.session_state
        and not st.session_state["current_roster"].empty
    ):
      r_col1, r_col2, r_col3 = st.columns([3, 1, 1])

      with r_col2:
        if st.button("💾 Save Updates", type="primary", use_container_width=True):
          update_live_roster_fn(
              st.session_state["current_roster"],
              toast_msg="Roster and snapshot saved to Cloud Storage!",
          )
          log_dispatch_action(
              "Manually saved active roster updates and GCS snapshot.",
              username=active_user,
          )
          st.rerun()

      with r_col3:
        if st.button(
            "⚠️ Reset Today's Roster", type="secondary", use_container_width=True
        ):
          st.session_state["current_roster"] = pd.DataFrame()
          st.session_state["closing_df"] = pd.DataFrame()
          log_dispatch_action(
              "Reset today's active roster and closing checklist.",
              username=active_user,
          )
          st.toast("Cleared active roster and closing checklist!", icon="🧹")
          st.rerun()

    if cortex_file or (
        "current_roster" in st.session_state
        and not st.session_state["current_roster"].empty
    ):
      if cortex_file:
        routes_df = (
            pd.read_excel(cortex_file)
            if cortex_file.name.endswith((".xlsx", ".xls"))
            else pd.read_csv(cortex_file)
        )

        driver_col = next(
            (
                c
                for c in routes_df.columns
                if "driver" in str(c).lower() and "name" in str(c).lower()
            ),
            None,
        )
        if driver_col and drivers_df is not None and not drivers_df.empty:
          cortex_drivers = [
              str(d).strip()
              for d in routes_df[driver_col].dropna().unique()
              if str(d).strip()
              and str(d).strip().lower()
              not in ["nan", "none", "null", "unassigned"]
          ]
          known_drivers = list(
              drivers_df["Driver Name"].dropna().astype(str).str.strip().unique()
          )

          new_drivers = [
              d for d in cortex_drivers if not is_driver_in_directory(d, known_drivers)
          ]

          if new_drivers:
            st.info(
                f"💡 **New Driver Associate(s) Detected in Cortex Export:**"
                f" {', '.join(new_drivers)}"
            )
            if st.button(
                "➕ Append New Driver(s) to Master Directory", type="secondary"
            ):
              new_rows = []
              for nd in new_drivers:
                new_rows.append({
                    "Driver Name": nd,
                    "Transporter ID": "",
                    "Phone Number": "",
                    "Status": "ACTIVE",
                    "Role": "Driver Associate",
                    "Hire Date": str(pd.Timestamp.now().strftime("%Y-%m-%d")),
                    "Preferred Shifts": "Mon,Tue,Wed,Thu,Fri,Sat,Sun",
                    "Overall Score": 100.0,
                    "Standing": "Fantastic",
                })
              updated_drivers = pd.concat(
                  [drivers_df, pd.DataFrame(new_rows)], ignore_index=True
              )
              st.session_state["drivers_df"] = process_driver_data(
                  updated_drivers
              )
              safe_save_dataframe(
                  st.session_state["drivers_df"], MASTER_DRIVERS_PATH
              )
              load_local_drivers.clear()
              log_dispatch_action(
                  f"Added new drivers {new_drivers} to Master Directory from"
                  " Cortex.",
                  username=active_user,
              )
              st.success(f"Added {len(new_drivers)} driver(s) to Master Directory!")
              st.rerun()

        c1, c2 = st.columns(2)
        c1.metric("Today's Cortex Routes", len(routes_df))
        c2.metric("Active Vans (Status: UP)", active_count)

        # PRIORITY VAN PRE-ASSIGNMENT SELECTION
        with st.expander(
            "⭐ Priority Van Pre-Assignments (Force Vans on Road / Rotate Stale"
            " Fleet)",
            expanded=False,
        ):
          st.caption(
              "Vans are automatically tracked by their last driven date from"
              " historical snapshots. Select vans that MUST be prioritized or"
              " use the auto-select button below to rotate vehicles sitting over"
              " a week."
          )

          active_van_bumpers = (
              active_fleet_df["vehicleName"].astype(str).str.strip().tolist()
              if "vehicleName" in active_fleet_df.columns
              else []
          )

          stale_vans_list = []
          today_date = datetime.date.today()
          for v in active_van_bumpers:
            if v not in last_driven_map:
              stale_vans_list.append(v)
            else:
              d_ago = (today_date - last_driven_map[v]).days
              if d_ago >= 7:
                stale_vans_list.append(v)

          # --- STALE VAN BANNER MESSAGE ---
          if stale_vans_list:
            st.warning(
                f"⚠️ **Stale Fleet Alert:** Found **{len(stale_vans_list)}** active"
                f" operational van(s) that haven't been driven in 7+ days or have no"
                f" recorded history: **{', '.join(stale_vans_list)}**. Use the"
                " button below to quickly queue them for rotation!"
            )

          if st.button(
              f"⚡ Auto-Select Stale Vans (Sitting > 7 Days: {len(stale_vans_list)}"
              " Found)",
              type="secondary",
          ):
            st.session_state["priority_vans_multiselect"] = stale_vans_list
            st.rerun()

          van_display_map = {
              v: format_van_with_recency_and_size(v, active_fleet_df, last_driven_map)
              for v in active_van_bumpers
          }

          prio_vans_selected = st.multiselect(
              "Priority Vans for Today's Auto-Assignment",
              options=active_van_bumpers,
              format_func=lambda x: van_display_map.get(x, x),
              key="priority_vans_multiselect",
          )

        if st.button("🚀 Run Auto-Assignment Engine", type="primary"):
          if prio_vans_selected:
            prio_fleet_df = active_fleet_df.copy()
            if "priority_rank" not in prio_fleet_df.columns:
              prio_fleet_df["priority_rank"] = 10
            prio_fleet_df.loc[
                prio_fleet_df["vehicleName"]
                .astype(str)
                .str.strip()
                .isin(prio_vans_selected),
                "priority_rank",
            ] = 1
            results_df = run_auto_assignment(routes_df, prio_fleet_df, phones)
          else:
            results_df = run_auto_assignment(routes_df, fleet, phones)

          if "Remarks" in results_df.columns:
            results_df["Remarks"] = results_df["Remarks"].replace(
                ["EXACT", "EXACT MATCH"], ""
            )

          if "closing_df" in st.session_state:
            del st.session_state["closing_df"]

          log_dispatch_action(
              f"Executed auto-assignment engine for {len(results_df)} routes."
              f" Priority vans: {prio_vans_selected}",
              username=active_user,
          )
          update_live_roster_fn(
              results_df, toast_msg="Auto-assignment engine complete!"
          )
          st.rerun()

      if (
          "current_roster" in st.session_state
          and not st.session_state["current_roster"].empty
      ):
        st.markdown("---")

        with st.expander(
            "🛠️ Live Dispatch Actions (Driver Swap / Reassign Van / Add Sweeper"
            " / Remove Driver/Route)",
            expanded=True,
        ):
          col_sw1, col_sw2, col_sw3, col_sw4 = st.columns(4)
          roster_df = st.session_state["current_roster"].copy().reset_index(drop=True)

          phone_map = {}
          if phones is not None and not phones.empty:
            p_active = (
                phones[~phones["status_clean"].isin(["INACTIVE", "RETIRED", "DELETED"])]
                if "status_clean" in phones.columns
                else phones
            )
            phone_map = dict(zip(p_active["device_clean"], p_active["number_clean"]))

          driver_option_map = {}
          assigned_driver_options = []
          for idx, row in roster_df.iterrows():
            drv = str(row.get("Driver", "")).strip()
            rt = str(row.get("Route", "")).strip()
            bmp = str(row.get("Van Bumper", "")).strip()
            van_lbl = format_van_with_recency_and_size(
                bmp, active_fleet_df, last_driven_map
            )
            display_label = f"[{idx}] {drv} (Route: {rt} | Van: {van_lbl})"
            assigned_driver_options.append(display_label)
            driver_option_map[display_label] = idx

          used_vans = roster_df["Van Bumper"].astype(str).str.strip().tolist()
          active_van_names = (
              active_fleet_df["vehicleName"].astype(str).str.strip().tolist()
              if "vehicleName" in active_fleet_df.columns
              else []
          )
          unassigned_vans = [v for v in active_van_names if v not in used_vans]

          # 1. REPLACE DRIVER
          with col_sw1:
            st.markdown("#### 🔄 Replace Driver")
            if assigned_driver_options:
              driver_sel = st.selectbox(
                  "Assigned Driver to Replace",
                  options=assigned_driver_options,
                  key="rep_d1",
              )

              day_name = pd.Timestamp.now().strftime("%a")
              prioritized_reserves = get_prioritized_reserve_drivers(
                  roster_df,
                  st.session_state.get("schedule_df", None),
                  st.session_state.get("drivers_df", None),
                  day_of_week=day_name,
              )

              reserve_labels = [p[0] for p in prioritized_reserves] + [
                  "Other (Type Manual Name)"
              ]
              selected_res_label = st.selectbox(
                  "Select Reserve Replacement",
                  options=reserve_labels,
                  key="res_prio_sel",
              )

              if selected_res_label == "Other (Type Manual Name)":
                manual_res_name = st.text_input(
                    "Type Driver Name", key="manual_res_name"
                )
                chosen_reserve = manual_res_name.strip()
              else:
                chosen_reserve = next(
                    (p[1] for p in prioritized_reserves if p[0] == selected_res_label),
                    "",
                )

              if st.button("Confirm Driver Swap"):
                if chosen_reserve:
                  target_idx = driver_option_map[driver_sel]
                  old_driver = roster_df.at[target_idx, "Driver"]
                  roster_df.at[target_idx, "Driver"] = chosen_reserve

                  log_dispatch_action(
                      f"Swapped driver '{old_driver}' with '{chosen_reserve}' on row"
                      f" index {target_idx}.",
                      username=active_user,
                  )
                  update_live_roster_fn(
                      roster_df,
                      toast_msg=f"Replaced {old_driver} with {chosen_reserve}!",
                  )
                  st.rerun()
                else:
                  st.warning("Please select or type a reserve driver name.")
            else:
              st.info("No drivers available.")

          # 2. REASSIGN VAN
          with col_sw2:
            st.markdown("#### 🚐 Reassign Van")
            if assigned_driver_options and unassigned_vans:
              van_target_sel = st.selectbox(
                  "Select Route / Driver",
                  options=assigned_driver_options,
                  key="sw_v1",
              )

              van_label_map = {
                  v: format_van_with_recency_and_size(
                      v, active_fleet_df, last_driven_map
                  )
                  for v in unassigned_vans
              }
              new_van_sel = st.selectbox(
                  "Select Unassigned Van",
                  options=unassigned_vans,
                  format_func=lambda x: van_label_map.get(x, x),
                  key="sw_v2",
              )

              if st.button("Confirm Van Reassignment"):
                target_idx = driver_option_map[van_target_sel]
                old_van = roster_df.at[target_idx, "Van Bumper"]

                van_matches = (
                    fleet[
                        fleet["vehicleName"].astype(str).str.strip()
                        == str(new_van_sel).strip()
                    ]
                    if "vehicleName" in fleet.columns
                    else pd.DataFrame()
                )
                sel_st = (
                    str(van_matches.iloc[0].get("ST", "M")).strip()
                    if not van_matches.empty
                    else "M"
                )

                if str(new_van_sel).strip() != "UNASSIGNED":
                  pid, pnum = find_matching_phone(new_van_sel, phone_map)
                else:
                  pid, pnum = "", ""

                roster_df.at[target_idx, "Van Bumper"] = str(new_van_sel)
                roster_df.at[target_idx, "Sel Size"] = str(sel_st)
                roster_df.at[target_idx, "Phone ID"] = str(pid)
                roster_df.at[target_idx, "Phone Number"] = str(pnum)

                log_dispatch_action(
                    f"Reassigned route from Van #{old_van} to Van #{new_van_sel}.",
                    username=active_user,
                )
                update_live_roster_fn(
                    roster_df,
                    toast_msg=f"Reassigned route from Van #{old_van} to Van #{new_van_sel}!",
                )
                st.rerun()
            elif not unassigned_vans:
              st.info("No unassigned active ('UP') vans available in fleet.")

          # 3. ADD SWEEPER
          with col_sw3:
            st.markdown("#### 🧹 Add Sweeper")
            sweeper_driver = st.text_input(
                "Sweeper Driver Name", value="Unassigned Sweeper", key="swp_name"
            )

            if unassigned_vans:
              van_label_map = {
                  v: format_van_with_recency_and_size(
                      v, active_fleet_df, last_driven_map
                  )
                  for v in unassigned_vans
              }
              selected_swp_van = st.selectbox(
                  "Assign Unassigned Van",
                  options=unassigned_vans,
                  format_func=lambda x: van_label_map.get(x, x),
                  key="swp_van",
              )

              if st.button("Add Sweeper to Roster"):
                van_matches = (
                    fleet[
                        fleet["vehicleName"].astype(str).str.strip()
                        == str(selected_swp_van).strip()
                    ]
                    if "vehicleName" in fleet.columns
                    else pd.DataFrame()
                )
                sel_st = (
                    str(van_matches.iloc[0].get("ST", "M")).strip()
                    if not van_matches.empty
                    else "M"
                )

                if str(selected_swp_van).strip() != "UNASSIGNED":
                  pid, pnum = find_matching_phone(selected_swp_van, phone_map)
                else:
                  pid, pnum = "", ""

                sw_count = (
                    len([
                        r
                        for r in roster_df["Route"]
                        if str(r).upper().startswith("S-")
                        or "SWEEPER" in str(r).upper()
                    ])
                    + 1
                )
                new_row = {
                    "Route": f"S-{sw_count}",
                    "Req Size": "N/A",
                    "Van Bumper": str(selected_swp_van),
                    "Sel Size": str(sel_st),
                    "Driver": str(sweeper_driver),
                    "Helper": "",
                    "Wave": "",
                    "Pad": "",
                    "Departure": "",
                    "Phone ID": str(pid),
                    "Phone Number": str(pnum),
                    "Show Time": "",
                    "Shift End": "",
                    "Remarks": "",
                }

                updated_roster = pd.concat(
                    [roster_df, pd.DataFrame([new_row])], ignore_index=True
                )
                log_dispatch_action(
                    f"Added Sweeper '{sweeper_driver}' in Van #{selected_swp_van}.",
                    username=active_user,
                )
                update_live_roster_fn(
                    updated_roster,
                    toast_msg=(
                        f"Added Sweeper {sweeper_driver} in Van #{selected_swp_van}!"
                    ),
                )
                st.rerun()
            else:
              st.warning("No unassigned active ('UP') vans available in fleet tracker.")

          # 4. REMOVE DRIVER / ROUTE ACTION
          with col_sw4:
            st.markdown("#### ❌ Remove Driver / Route")
            if assigned_driver_options:
              remove_target_sel = st.selectbox(
                  "Select Route / Driver to Remove",
                  options=assigned_driver_options,
                  key="rem_d_sel",
              )
              remove_action_mode = st.radio(
                  "Action Type",
                  options=[
                      "Remove Driver Only (Mark Unassigned)",
                      "Drop Route Completely",
                  ],
                  key="rem_mode_rad",
              )

              if st.button("Confirm Removal", type="primary"):
                target_idx = driver_option_map[remove_target_sel]
                target_route = roster_df.at[target_idx, "Route"]
                target_driver = roster_df.at[target_idx, "Driver"]

                if remove_action_mode == "Remove Driver Only (Mark Unassigned)":
                  roster_df.at[target_idx, "Driver"] = "UNASSIGNED"
                  log_dispatch_action(
                      f"Removed driver '{target_driver}' from Route {target_route}"
                      " (Set to UNASSIGNED).",
                      username=active_user,
                  )
                  update_live_roster_fn(
                      roster_df,
                      toast_msg=(
                          f"Removed {target_driver} from Route {target_route}!"
                      ),
                  )
                else:
                  roster_df = roster_df.drop(index=target_idx).reset_index(drop=True)
                  log_dispatch_action(
                      f"Dropped Route {target_route} (Driver: {target_driver})"
                      " completely from active roster.",
                      username=active_user,
                  )
                  update_live_roster_fn(
                      roster_df, toast_msg=f"Dropped Route {target_route} completely!"
                  )
                st.rerun()
            else:
              st.info("No active routes to remove.")

          st.markdown("---")

          # 5. ADD EXTRA ROUTE / LATE ROUTE ASSIGNMENT
          st.markdown("#### ➕ Add Extra Route / Late Route Assignment")
          st.caption(
              "Manually append late Cortex routes or Extra Route Offers (EROs)"
              " directly to active roster."
          )

          ex_col1, ex_col2, ex_col3, ex_col4 = st.columns(4)

          extra_route_code = ex_col1.text_input(
              "Route Code*", placeholder="e.g. CX102 or ERO-1", key="ext_rt_code"
          )
          extra_req_size = ex_col2.selectbox(
              "Required Size*",
              options=[
                  "Standard Parcel - Medium",
                  "Standard Parcel - Large",
                  "Standard Parcel - Extra Large",
                  "On-Road Experience",
                  "Nursery 1",
                  "Nursery 2",
              ],
              index=0,
              key="ext_rt_size",
          )
          extra_dep_time = ex_col3.text_input(
              "Departure Time*", value="10:00 AM", placeholder="e.g. 10:15 AM", key="ext_rt_dep"
          )

          day_name = pd.Timestamp.now().strftime("%a")
          extra_prio_reserves = get_prioritized_reserve_drivers(
              roster_df,
              st.session_state.get("schedule_df", None),
              st.session_state.get("drivers_df", None),
              day_of_week=day_name,
          )
          extra_res_labels = [p[0] for p in extra_prio_reserves] + [
              "Unassigned / Open",
              "Other (Type Manual Name)",
          ]
          extra_driver_sel = ex_col4.selectbox(
              "Assigned Driver", options=extra_res_labels, key="ext_drv_sel"
          )

          ex_col5, ex_col6, ex_col7 = st.columns([1, 1, 2])

          if extra_driver_sel == "Other (Type Manual Name)":
            extra_manual_driver = ex_col5.text_input(
                "Type Driver Name", key="ext_manual_drv"
            )
            final_extra_driver = extra_manual_driver.strip()
          elif extra_driver_sel == "Unassigned / Open":
            final_extra_driver = "UNASSIGNED"
          else:
            final_extra_driver = next(
                (p[1] for p in extra_prio_reserves if p[0] == extra_driver_sel), ""
            )

          extra_helper = ex_col6.text_input(
              "Assigned Helper (Optional)", value="", key="ext_hlp_name"
          )

          if unassigned_vans:
            van_label_map = {
                v: format_van_with_recency_and_size(
                    v, active_fleet_df, last_driven_map
                )
                for v in unassigned_vans
            }
            van_options_ext = ["AUTO-MATCH BEST FIT"] + unassigned_vans
            extra_van_sel = ex_col7.selectbox(
                "Assign Van*",
                options=van_options_ext,
                format_func=lambda x: (
                    van_label_map.get(x, x)
                    if x != "AUTO-MATCH BEST FIT"
                    else "AUTO-MATCH BEST FIT"
                ),
                key="ext_van_sel",
            )
          else:
            extra_van_sel = "NO VANS AVAILABLE"
            ex_col7.warning("No active unassigned vans!")

          if st.button("➕ Append Extra Route to Roster", type="primary"):
            if not extra_route_code.strip():
              st.warning("Please enter a valid Route Code.")
            else:
              short_req = condense_service_type(extra_req_size)

              if extra_van_sel == "AUTO-MATCH BEST FIT" and unassigned_vans:
                chosen_van = unassigned_vans[0]
              elif extra_van_sel in unassigned_vans:
                chosen_van = extra_van_sel
              else:
                chosen_van = "UNASSIGNED"

              if chosen_van != "UNASSIGNED" and chosen_van != "NO VANS AVAILABLE":
                van_matches = (
                    fleet[
                        fleet["vehicleName"].astype(str).str.strip()
                        == str(chosen_van).strip()
                    ]
                    if "vehicleName" in fleet.columns
                    else pd.DataFrame()
                )
                sel_st = (
                    str(van_matches.iloc[0].get("ST", "M")).strip()
                    if not van_matches.empty
                    else "M"
                )
                pid, pnum = find_matching_phone(chosen_van, phone_map)
              else:
                sel_st = "N/A"
                pid, pnum = "", ""

              try:
                dep_dt = pd.to_datetime(
                    extra_dep_time.strip(), format="mixed", errors="coerce"
                )
                if pd.isna(dep_dt):
                  dep_dt = pd.to_datetime(
                      f"{pd.Timestamp.now().strftime('%Y-%m-%d')}"
                      f" {extra_dep_time.strip()}"
                  )

                wave_dt = dep_dt - pd.Timedelta(minutes=20)
                show_dt = wave_dt - pd.Timedelta(minutes=30)
                end_dt = show_dt + pd.Timedelta(hours=10)

                dep_str = dep_dt.strftime("%I:%M %p").lstrip("0")
                wave_str = wave_dt.strftime("%I:%M %p").lstrip("0")
                show_str = show_dt.strftime("%I:%M %p").lstrip("0")
                end_str = end_dt.strftime("%I:%M %p").lstrip("0")
              except Exception:
                dep_str = extra_dep_time.strip()
                wave_str, show_str, end_str = "N/A", "N/A", "N/A"

              new_extra_row = {
                  "Route": str(extra_route_code.strip()),
                  "Req Size": str(short_req),
                  "Van Bumper": str(chosen_van),
                  "Sel Size": str(sel_st),
                  "Driver": str(final_extra_driver),
                  "Helper": str(extra_helper.strip()),
                  "Wave": str(wave_str),
                  "Pad": "Pad A",
                  "Departure": str(dep_str),
                  "Phone ID": str(pid),
                  "Phone Number": str(pnum),
                  "Show Time": str(show_str),
                  "Shift End": str(end_str),
                  "Remarks": "EXTRA ROUTE / LATE ROUTE",
              }

              updated_roster = pd.concat(
                  [roster_df, pd.DataFrame([new_extra_row])], ignore_index=True
              )
              log_dispatch_action(
                  "Appended Extra Route Offer"
                  f" '{extra_route_code.strip()}' (Driver:"
                  f" {final_extra_driver}, Van: {chosen_van}).",
                  username=active_user,
              )
              update_live_roster_fn(
                  updated_roster,
                  toast_msg=f"Appended Extra Route '{extra_route_code.strip()}'!",
              )
              st.rerun()

        with st.expander(
            "📍 Wave Pad Assignments (Assign Loading Pads by Wave Time)",
            expanded=True,
        ):
          roster_df = st.session_state["current_roster"].copy()

          raw_waves = [
              w
              for w in roster_df["Wave"].unique()
              if str(w).strip() and str(w).strip().upper() != "N/A"
          ]
          unique_waves = sorted(
              raw_waves,
              key=lambda x: pd.to_datetime(x, format="%I:%M %p", errors="coerce"),
          )

          if unique_waves:
            st.caption(
                "Assign today's loading pad (Pad A or Pad B) for each wave time"
                " received from warehouse stage workers."
            )

            wave_cols = st.columns(min(len(unique_waves), 4))
            pad_selections = {}

            for i, wave_time in enumerate(unique_waves):
              col_target = wave_cols[i % 4]
              with col_target:
                current_pad = (
                    roster_df[roster_df["Wave"] == wave_time]["Pad"].iloc[0]
                    if not roster_df[roster_df["Wave"] == wave_time].empty
                    else "Pad A"
                )
                default_idx = 0 if "A" in str(current_pad) else 1

                pad_selections[wave_time] = st.selectbox(
                    f"Wave {wave_time}",
                    options=["Pad A", "Pad B"],
                    index=default_idx,
                    key=f"pad_sel_{wave_time}",
                )

            if st.button("Apply Pad Assignments"):
              for wave_time, chosen_pad in pad_selections.items():
                roster_df.loc[roster_df["Wave"] == wave_time, "Pad"] = chosen_pad

              log_dispatch_action(
                  "Updated Wave Pad assignments across active roster.",
                  username=active_user,
              )
              update_live_roster_fn(
                  roster_df, toast_msg="Loading pad assignments updated across roster!"
              )
              st.rerun()
          else:
            st.info("No active wave times available to assign pads.")

        st.markdown("---")
        st.subheader("Interactive Dispatch Roster")

        if "Remarks" in st.session_state["current_roster"].columns:
          st.session_state["current_roster"]["Remarks"] = st.session_state[
              "current_roster"
          ]["Remarks"].replace(["EXACT", "EXACT MATCH"], "")

        if "Helper" not in st.session_state["current_roster"].columns:
          driver_idx = st.session_state["current_roster"].columns.get_loc("Driver")
          st.session_state["current_roster"].insert(driver_idx + 1, "Helper", "")

        active_phones = []
        phone_number_lookup = {}
        if phones is not None and not phones.empty:
          p_active = (
              phones[~phones["status_clean"].isin(["INACTIVE", "RETIRED", "DELETED"])]
              if "status_clean" in phones.columns
              else phones
          )
          active_phones = list(p_active["device_clean"].unique())
          phone_number_lookup = dict(
              zip(p_active["device_clean"], p_active["number_clean"])
          )

        assigned_phones = [
            str(p).strip()
            for p in st.session_state["current_roster"]["Phone ID"]
            .dropna()
            .unique()
            if str(p).strip()
        ]

        def try_int_sort(val):
          try:
            return int("".join(filter(str.isdigit, str(val))))
          except ValueError:
            return str(val)

        unassigned_phones = [p for p in active_phones if p not in assigned_phones]
        sorted_unassigned_phones = sorted(unassigned_phones, key=try_int_sort)

        with st.expander(
            "📱 Manage Route Phone Assignments (Unassigned Pool Only)", expanded=False
        ):
          st.caption(
              "Select a route below to assign or change its phone ID using only"
              " available unassigned phones."
          )
          for idx, row in st.session_state["current_roster"].iterrows():
            rt_code = row.get("Route", "N/A")
            drv_name = row.get("Driver", "Unassigned")
            curr_phone = str(row.get("Phone ID", "")).strip()

            row_phone_options = [""]
            if curr_phone and curr_phone not in row_phone_options:
              row_phone_options.append(curr_phone)
            for up in sorted_unassigned_phones:
              if up not in row_phone_options:
                row_phone_options.append(up)

            default_index = (
                row_phone_options.index(curr_phone)
                if curr_phone in row_phone_options
                else 0
            )

            p_col1, p_col2, p_col3 = st.columns([2, 2, 1])
            p_col1.markdown(f"**Route:** {rt_code} | **Driver:** {drv_name}")

            selected_new_phone = p_col2.selectbox(
                f"Phone for {rt_code}",
                options=row_phone_options,
                index=default_index,
                key=f"phone_assign_row_{idx}",
                label_visibility="collapsed",
            )

            if selected_new_phone != curr_phone:
              st.session_state["current_roster"].at[idx, "Phone ID"] = (
                  selected_new_phone
              )
              st.session_state["current_roster"].at[idx, "Phone Number"] = (
                  phone_number_lookup.get(selected_new_phone, "")
              )
              update_closing_checklist_assignments(
                  st.session_state["current_roster"], st.session_state
              )
              now_filename = (
                  f"roster_{pd.Timestamp.now().strftime('%Y-%m-%d_%H%M')}.xlsx"
              )
              save_snapshot_file(st.session_state["current_roster"], now_filename)
              st.rerun()

        def on_roster_change():
          changes = st.session_state.get("daily_roster_editor_state")
          if changes and "current_roster" in st.session_state:
            for row_idx, col_changes in changes.get("edited_rows", {}).items():
              for col_name, new_val in col_changes.items():
                st.session_state["current_roster"].at[row_idx, col_name] = new_val

            for row_idx, col_changes in changes.get("edited_rows", {}).items():
              if "Phone ID" in col_changes:
                dev_id = str(col_changes["Phone ID"]).strip()
                st.session_state["current_roster"].at[row_idx, "Phone Number"] = (
                    phone_number_lookup.get(dev_id, "")
                )

            update_closing_checklist_assignments(
                st.session_state["current_roster"], st.session_state
            )
            now_filename = (
                f"roster_{pd.Timestamp.now().strftime('%Y-%m-%d_%H%M')}.xlsx"
            )
            save_snapshot_file(st.session_state["current_roster"], now_filename)

        roster_config = {
            "Route": st.column_config.TextColumn("Route", width="small"),
            "Req Size": st.column_config.TextColumn("Req Size", width="small"),
            "Van Bumper": st.column_config.TextColumn("Van Bumper", width="small"),
            "Sel Size": st.column_config.TextColumn("Sel Size", width="small"),
            "Driver": st.column_config.TextColumn("Driver", width="medium"),
            "Helper": st.column_config.TextColumn("Helper", width="medium"),
            "Wave": st.column_config.TextColumn("Wave", width="small"),
            "Pad": st.column_config.TextColumn("Pad", width="small"),
            "Departure": st.column_config.TextColumn("Departure", width="small"),
            "Phone ID": st.column_config.TextColumn("Phone ID", width="small"),
            "Phone Number": st.column_config.TextColumn(
                "Phone Number", width="medium"
            ),
            "Show Time": st.column_config.TextColumn("Show Time", width="small"),
            "Shift End": st.column_config.TextColumn("Shift End", width="small"),
            "Remarks": st.column_config.TextColumn("Remarks", width="medium"),
        }

        st.data_editor(
            st.session_state["current_roster"],
            column_config=roster_config,
            use_container_width=True,
            num_rows="fixed",
            hide_index=True,
            key="daily_roster_editor_state",
            on_change=on_roster_change,
        )

        printable_roster = get_sorted_roster(st.session_state["current_roster"])

        st.markdown("---")
        st.subheader("🖨️ Clipboard Print Preview (Sorted by Wave & First Name)")

        html_view = generate_printable_html(printable_roster)
        components.html(html_view, height=500, scrolling=True)

        csv = printable_roster.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Export Roster CSV (For Records/Archiving)",
            data=csv,
            file_name="daily_dispatch_roster.csv",
            mime="text/csv",
        )
    else:
      st.info(
          "Upload today's Cortex route export in the sidebar to run"
          " auto-assignments or load a historical roster."
      )
  else:
    st.warning(f"No local `{MASTER_FLEET_PATH}` file found in your project folder.")
