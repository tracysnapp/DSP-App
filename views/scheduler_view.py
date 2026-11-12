from datetime import datetime, timedelta
import pandas as pd
import streamlit as st
from engine import (
    DISCORD_WEBHOOK_URL,
    load_local_schedule,
    load_long_range_pto_storage,
    load_weekly_targets_storage,
    log_dispatch_action,
    save_long_range_pto_storage,
    save_weekly_schedule_to_storage,
    save_weekly_targets_storage,
)
from modules.schedule import (
    auto_generate_pattern_weekly_schedule,
    generate_discord_schedule,
    send_discord_webhook,
)


def get_amazon_week_1_start(year: int) -> datetime:
  if year == 2027:
    return datetime(2027, 1, 3)
  elif year == 2026:
    return datetime(2025, 12, 28)

  jan_4 = datetime(year, 1, 4)
  return jan_4 - timedelta(days=(jan_4.weekday() + 1) % 7)


def get_amazon_week_dates(year: int, week_num: int):
  week_1_sun = get_amazon_week_1_start(year)
  target_sun = week_1_sun + timedelta(weeks=week_num - 1)
  return [target_sun + timedelta(days=i) for i in range(7)]


def get_current_amazon_week_info():
  today = datetime.today()
  current_year = today.year

  w1_start = get_amazon_week_1_start(current_year)

  if today < w1_start:
    op_year = current_year - 1
    w1_start = get_amazon_week_1_start(op_year)
  else:
    next_w1_start = get_amazon_week_1_start(current_year + 1)
    if today >= next_w1_start:
      op_year = current_year + 1
      w1_start = next_w1_start
    else:
      op_year = current_year

  days_diff = (today - w1_start).days
  week_num = (days_diff // 7) + 1
  return op_year, week_num


def build_blank_schedule_from_drivers(drivers_df, day_headers):
  if drivers_df is None or drivers_df.empty:
    return pd.DataFrame(
        columns=["Driver Name"] + day_headers + ["Notes / Requests"]
    )

  active_drivers = (
      drivers_df[
          drivers_df["Status"].astype(str).str.strip().str.upper() == "ACTIVE"
      ].copy()
      if "Status" in drivers_df.columns
      else drivers_df.copy()
  )

  init_sch = []
  for _, row in active_drivers.iterrows():
    full_name = str(row.get("Driver Name", "")).strip()
    if not full_name:
      continue
    parts = full_name.split(" ", 1)
    first_name = parts[0] if len(parts) > 1 else full_name
    last_name = parts[1] if len(parts) > 1 else ""

    driver_row = {
        "Driver Name": (
            f"{first_name} {last_name}".strip()
            if (first_name or last_name)
            else full_name
        ),
        "First Name": first_name,
        "Last Name": last_name,
        "Notes / Requests": "",
    }
    for dh in day_headers:
      driver_row[dh] = ""

    init_sch.append(driver_row)

  return pd.DataFrame(init_sch)


def render_scheduler_tab():
  st.subheader("📅 JNAL Operations: Scheduling & Long-Range Calendar")

  tab_weekly, tab_pto = st.tabs(
      ["Weekly Shift Scheduler", "Long-Range PTO & Availability Calendar"]
  )

  drivers_df = st.session_state.get("drivers_df")
  active_user = st.session_state.get("user_name", "Admin")

  if "pto_df" not in st.session_state:
    st.session_state["pto_df"] = load_long_range_pto_storage()

  if "weekly_targets_dict" not in st.session_state:
    st.session_state["weekly_targets_dict"] = load_weekly_targets_storage()

  # ==========================================
  # TAB 1: WEEKLY SHIFT SCHEDULER (AMAZON WEEKS 1-53)
  # ==========================================
  with tab_weekly:
    c_date, c_info = st.columns([1, 2])
    with c_date:
      curr_op_year, curr_amazon_week = get_current_amazon_week_info()

      sel_year = st.selectbox(
          "Operating Year",
          options=[curr_op_year - 1, curr_op_year, curr_op_year + 1],
          index=1,
      )

      sel_amazon_week = st.number_input(
          "Amazon Operating Week #",
          min_value=1,
          max_value=53,
          value=curr_amazon_week,
          step=1,
      )

      week_datetime_objs = get_amazon_week_dates(
          int(sel_year), int(sel_amazon_week)
      )
      week_dates = [dt.date() for dt in week_datetime_objs]

      start_date = week_dates[0]
      end_date = week_dates[6]

      week_label = (
          f"Amazon Week {sel_amazon_week} ({start_date.strftime('%d-%b')} to"
          f" {end_date.strftime('%d-%b')})"
      )
      st.caption(f"**Cycle Window:** {week_label} *(Sun - Sat Operational)*")

    with c_info:
      st.markdown("### 🎯 Daily Route Targets & 15% Sweeper Buffer")
      st.caption(
          "Adjust expected route counts per day. The auto-scheduler adds a 15%"
          " sweeper/helper buffer automatically."
      )

    day_keys = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    day_headers = [f"{d_date.strftime('%a %d %b')}" for d_date in week_dates]
    day_key_to_header = dict(zip(day_keys, day_headers))

    week_key_str = f"{int(sel_year)}-W{int(sel_amazon_week):02d}"
    stored_week_targets = st.session_state["weekly_targets_dict"].get(
        week_key_str, {}
    )

    default_targets = {
        "Sun": 26,
        "Mon": 25,
        "Tue": 25,
        "Wed": 28,
        "Thu": 24,
        "Fri": 24,
        "Sat": 0,
    }

    target_cols = st.columns(7)
    expected_routes_dict = {}
    targets_changed = False

    for i, d_key in enumerate(day_keys):
      d_header = day_key_to_header[d_key]
      default_val = stored_week_targets.get(
          d_key, default_targets.get(d_key, 25)
      )

      with target_cols[i]:
        new_val = st.number_input(
            d_header,
            min_value=0,
            value=int(default_val),
            key=f"target_route_{sel_year}_{sel_amazon_week}_{d_key}",
        )
        expected_routes_dict[d_header] = new_val
        if new_val != default_val:
          targets_changed = True

    if targets_changed:
      if week_key_str not in st.session_state["weekly_targets_dict"]:
        st.session_state["weekly_targets_dict"][week_key_str] = {}
      for d_key in day_keys:
        st.session_state["weekly_targets_dict"][week_key_str][d_key] = (
            expected_routes_dict[day_key_to_header[d_key]]
        )
      save_weekly_targets_storage(st.session_state["weekly_targets_dict"])

    loaded_key = st.session_state.get("loaded_week_key")
    if (
        "schedule_df" not in st.session_state
        or st.session_state["schedule_df"] is None
        or st.session_state["schedule_df"].empty
        or loaded_key != week_key_str
    ):
      loaded_sch = load_local_schedule(int(sel_year), int(sel_amazon_week))
      pto_data = st.session_state["pto_df"]

      if loaded_sch.empty:
        sch_df = build_blank_schedule_from_drivers(drivers_df, day_headers)
      else:
        sch_df = loaded_sch.copy()

        # Sync active drivers list (remove inactive, add newly hired active drivers)
        if (
            drivers_df is not None
            and not drivers_df.empty
            and "Status" in drivers_df.columns
        ):
          active_df = drivers_df[
              drivers_df["Status"].astype(str).str.strip().str.upper()
              == "ACTIVE"
          ]
          active_names_map = {
              str(n).strip().lower(): str(n).strip()
              for n in active_df["Driver Name"].dropna()
          }
          if active_names_map:
            sch_df["__dn_lower"] = (
                sch_df["Driver Name"].astype(str).str.strip().str.lower()
            )
            sch_df = (
                sch_df[sch_df["__dn_lower"].isin(active_names_map.keys())]
                .drop(columns=["__dn_lower"])
                .reset_index(drop=True)
            )

            existing_lower = set(
                sch_df["Driver Name"].astype(str).str.strip().str.lower()
            )
            missing_rows = []
            for dn_low, dn_orig in active_names_map.items():
              if dn_low not in existing_lower:
                parts = dn_orig.split(" ", 1)
                new_r = {
                    "Driver Name": dn_orig,
                    "First Name": parts[0],
                    "Last Name": parts[1] if len(parts) > 1 else "",
                    "Notes / Requests": "",
                }
                for dh in day_headers:
                  new_r[dh] = ""
                missing_rows.append(new_r)
            if missing_rows:
              sch_df = pd.concat(
                  [sch_df, pd.DataFrame(missing_rows)], ignore_index=True
              )

        # Align day columns to current selected week's dated headers
        has_exact_week_cols = all(dh in sch_df.columns for dh in day_headers)
        if not has_exact_week_cols:
          for d_key, d_header in day_key_to_header.items():
            if d_header not in sch_df.columns:
              matching_old_col = next(
                  (c for c in sch_df.columns if c.startswith(d_key)), None
              )
              if matching_old_col:
                sch_df.drop(columns=[matching_old_col], inplace=True)
              sch_df[d_header] = ""
          sch_df["Notes / Requests"] = ""

      if not sch_df.empty:
        if (
            "First Name" not in sch_df.columns
            or "Last Name" not in sch_df.columns
        ):
          if "Driver Name" in sch_df.columns:
            fn_list, ln_list = [], []
            for val in sch_df["Driver Name"]:
              name_str = str(val).strip()
              if "," in name_str:
                p = name_str.split(",", 1)
                ln_list.append(p[0].strip())
                fn_list.append(p[1].strip())
              else:
                p = name_str.split(" ", 1)
                fn_list.append(p[0].strip())
                ln_list.append(p[1].strip() if len(p) > 1 else "")
            sch_df["First Name"] = fn_list
            sch_df["Last Name"] = ln_list

        if "Driver Name" not in sch_df.columns:
          sch_df["Driver Name"] = (
              sch_df["First Name"].astype(str)
              + " "
              + sch_df["Last Name"].astype(str)
          ).str.strip()

      if "Notes / Requests" not in sch_df.columns:
        sch_df["Notes / Requests"] = ""
      sch_df["Notes / Requests"] = (
          sch_df["Notes / Requests"]
          .fillna("")
          .astype(str)
          .replace(["nan", "NaN", "None", "<NA>"], "")
      )

      for dh in day_headers:
        if dh not in sch_df.columns:
          sch_df[dh] = ""
        sch_df[dh] = sch_df[dh].fillna("").astype(str)
        sch_df.loc[
            sch_df[dh]
            .str.strip()
            .str.lower()
            .isin(["none", "nan", "nat", "<na>"]),
            dh,
        ] = ""

      # Apply Long-Range PTO & Availability constraints
      if not pto_data.empty and not sch_df.empty:
        for idx, d_row in sch_df.iterrows():
          fn = str(d_row.get("First Name", "")).strip()
          ln = str(d_row.get("Last Name", "")).strip()
          dn = str(d_row.get("Driver Name", "")).strip()

          d_full = f"{fn} {ln}".strip().lower() if (fn or ln) else dn.lower()
          d_reverse = (
              f"{ln}, {fn}".strip().lower() if (fn or ln) else dn.lower()
          )

          notes_list = []
          for _, pto_row in pto_data.iterrows():
            pto_name = str(pto_row.get("Driver Name", "")).strip().lower()

            if pto_name and (
                pto_name == d_full
                or pto_name == d_reverse
                or (dn and pto_name == dn.lower())
                or (d_full and pto_name in d_full)
            ):
              try:
                p_start = pd.to_datetime(pto_row["Start Date"]).date()
                p_end = pd.to_datetime(pto_row["End Date"]).date()
                cat = str(pto_row.get("Category", ""))
                note = str(pto_row.get("Reason / Notes", ""))

                overlaps_week = False
                for day_idx, d_date in enumerate(week_dates):
                  header_name = day_headers[day_idx]
                  day_name_str = day_keys[day_idx]

                  if p_start <= d_date <= p_end:
                    overlaps_week = True
                    if "No Sundays" in cat and day_name_str == "Sun":
                      sch_df.at[idx, header_name] = "Rqst Off"
                    elif cat in [
                        "Approved PTO",
                        "Unpaid Leave",
                        "Appointment / Partial Off",
                        "Other Constraint",
                    ]:
                      sch_df.at[idx, header_name] = "Rqst Off"

                if overlaps_week:
                  notes_list.append(
                      f"{cat} ({p_start.strftime('%d-%b')} to"
                      f" {p_end.strftime('%d-%b')}): {note}"
                  )
              except Exception:
                pass

          if notes_list:
            existing_notes = str(d_row.get("Notes / Requests", "")).strip()
            combined = " | ".join(notes_list)
            if combined not in existing_notes:
              sch_df.at[idx, "Notes / Requests"] = (
                  f"{existing_notes} | {combined}".strip(" |")
                  if existing_notes
                  else combined
              )

      ordered_cols = ["Driver Name"] + day_headers + ["Notes / Requests"]
      for c in ["First Name", "Last Name"]:
        if c in sch_df.columns and c not in ordered_cols:
          ordered_cols.append(c)

      existing_ordered = [c for c in ordered_cols if c in sch_df.columns]
      sch_df = sch_df[existing_ordered]

      sort_cols = [
          c
          for c in ["First Name", "Last Name", "Driver Name"]
          if c in sch_df.columns
      ]
      if sort_cols:
        st.session_state["schedule_df"] = sch_df.sort_values(
            by=sort_cols, ascending=True
        ).reset_index(drop=True)
      else:
        st.session_state["schedule_df"] = sch_df.copy()

      st.session_state["loaded_week_key"] = week_key_str

    def on_schedule_change():
      changes = st.session_state.get("weekly_schedule_editor_state")
      if changes and "schedule_df" in st.session_state:
        visible_indices = st.session_state.get("visible_schedule_indices", [])
        for vis_idx, col_changes in changes.get("edited_rows", {}).items():
          actual_idx = (
              visible_indices[int(vis_idx)]
              if int(vis_idx) < len(visible_indices)
              else int(vis_idx)
          )
          for col_name, new_val in col_changes.items():
            if col_name in st.session_state["schedule_df"].columns:
              clean_val = (
                  ""
                  if new_val is None
                  or str(new_val).strip().lower() in ["none", "nan", "nat"]
                  else str(new_val).strip()
              )
              st.session_state["schedule_df"].at[actual_idx, col_name] = (
                  clean_val
              )

    # ==========================================
    # LIVE COVERAGE & DAILY ROLE BREAKDOWN
    # ==========================================
    st.markdown("### 📊 Live Coverage & Daily Role Breakdown (with +15% Buffer)")
    metrics_cols = st.columns(7)

    work_shifts = ["Driver", "Helper", "OPS-AM", "OPS-PM"]
    sch_ref_metrics = st.session_state["schedule_df"]

    for i, d_header in enumerate(day_headers):
      if d_header in sch_ref_metrics.columns:
        col_vals = sch_ref_metrics[d_header].astype(str).str.strip()
        total_working = int(col_vals.isin(work_shifts).sum())
        drv_cnt = int((col_vals == "Driver").sum())
        hlp_cnt = int((col_vals == "Helper").sum())
        ops_cnt = int(col_vals.isin(["OPS-AM", "OPS-PM"]).sum())
      else:
        total_working = drv_cnt = hlp_cnt = ops_cnt = 0

      base_target = expected_routes_dict.get(d_header, 0)
      buffered_target = (
          int((base_target * 1.15) + 0.99) if base_target > 0 else 0
      )
      delta = total_working - buffered_target

      with metrics_cols[i]:
        st.metric(
            label=d_header,
            value=total_working,
            delta=delta,
            delta_color="normal",
        )
        st.caption(
            f"🚐 **{drv_cnt}** Drv | 🦺 **{hlp_cnt}** Hlp | 🎧 **{ops_cnt}** OPS"
        )

    st.markdown("---")

    # ==========================================
    # OVERTIME WARNING BADGE (> 4 SHIFTS / > 40 HRS)
    # ==========================================
    existing_day_cols = [c for c in day_headers if c in sch_ref_metrics.columns]
    ot_drivers = []
    if not sch_ref_metrics.empty and existing_day_cols:
      shift_counts = sch_ref_metrics[existing_day_cols].isin(work_shifts).sum(
          axis=1
      )
      ot_mask = shift_counts > 4
      for idx_ot in sch_ref_metrics[ot_mask].index:
        d_name_ot = sch_ref_metrics.at[idx_ot, "Driver Name"]
        cnt_ot = int(shift_counts.at[idx_ot])
        est_hrs = cnt_ot * 10
        ot_drivers.append(f"**{d_name_ot}** ({cnt_ot} shifts / ~{est_hrs} hrs)")

    if ot_drivers:
      st.warning(
          f"⏱️ **Overtime Alert ({len(ot_drivers)} team member(s) over 4 shifts"
          f" / 40 hrs):** {', '.join(ot_drivers)}"
      )

    # ==========================================
    # CONFLICT ALERT BANNER
    # ==========================================
    conflict_count = 0
    conflict_details = []
    if (
        "schedule_df" in st.session_state
        and not st.session_state["schedule_df"].empty
    ):
      sch_check = st.session_state["schedule_df"]
      for _, r_item in sch_check.iterrows():
        notes_str = str(r_item.get("Notes / Requests", "")).strip()
        if notes_str and notes_str.lower() != "nan":
          d_name = r_item.get("Driver Name", "Driver")
          for dh in day_headers:
            shift_val = str(r_item.get(dh, "")).strip()
            if shift_val in work_shifts:
              conflict_count += 1
              conflict_details.append(
                  f"• **{d_name}** scheduled on **{dh}** ({shift_val}) despite"
                  f" active calendar constraint: *{notes_str[:70]}*"
              )

    if conflict_count > 0:
      with st.expander(
          f"⚠️ **Schedule Conflict Alert: {conflict_count} potential overlap(s)"
          " detected with calendar constraints**",
          expanded=True,
      ):
        st.warning(
            "Review the drivers scheduled below who have active long-range PTO"
            " or availability notes for the week:"
        )
        for cd in conflict_details[:5]:
          st.markdown(cd)
        if len(conflict_details) > 5:
          st.caption(f"...and {len(conflict_details) - 5} more conflicts.")

    # ==========================================
    # ROLE & AVAILABILITY FILTER TOGGLES
    # ==========================================
    f_col1, f_col2 = st.columns([2, 2])
    with f_col1:
      schedule_view_filter = st.selectbox(
          "🔍 Filter Schedule View",
          options=[
              "Show All Active Drivers",
              "Show Scheduled Only (Drivers/Helpers/OPS)",
              "Show Available / Unscheduled Only",
              "Show Over 4 Shifts (OT Risk)",
              "Show with Calendar Notes / Requests",
          ],
          key="sched_view_filter_sel",
      )
    with f_col2:
      day_quick_focus = st.selectbox(
          "📅 Highlight Specific Day Column",
          options=["None (Show All Days)"] + day_headers,
          key="sched_day_focus_sel",
      )

    # ==========================================
    # AUTO-SCHEDULER (ROLE-AWARE, BALANCED DEMAND & 15% BUFFER)
    # ==========================================
    with st.expander(
        "🤖 Advanced Auto-Scheduler (+15% Sweeper Buffer, Role-Aware &"
        " Cross-Week Fatigue Guard)",
        expanded=False,
    ):
      st.caption(
          "Distributes up to 4 shifts/week using scorecard priority, directory"
          " roles (OPS-AM/PM, Sweeper/Helper, Driver), shift preferences,"
          " balanced daily demand, and a 5-consecutive-day cap across weeks."
      )

      auto_c1, auto_c2, _ = st.columns([1, 1, 2])
      with auto_c1:
        clear_existing_auto = st.checkbox(
            "Reset non-PTO shifts before generating",
            value=False,
            key="chk_clear_before_auto",
        )
      with auto_c2:
        max_consec_days = st.number_input(
            "Max Consecutive Days",
            min_value=4,
            max_value=6,
            value=5,
            step=1,
            key="num_max_consec_days",
        )

      if st.button(
          "🚀 Run Buffered Auto-Scheduler",
          type="primary",
          key="btn_run_pattern_auto",
      ):
        prev_year = (
            int(sel_year) if int(sel_amazon_week) > 1 else int(sel_year) - 1
        )
        prev_week = (
            int(sel_amazon_week) - 1 if int(sel_amazon_week) > 1 else 52
        )
        prev_week_df = load_local_schedule(prev_year, prev_week)

        updated_sch = auto_generate_pattern_weekly_schedule(
            st.session_state["schedule_df"],
            day_headers,
            expected_routes_dict,
            drivers_df=drivers_df,
            target_shifts_per_driver=4,
            prev_week_schedule_df=prev_week_df,
            max_consecutive_days=int(max_consec_days),
            clear_existing_non_pto=clear_existing_auto,
        )

        st.session_state["schedule_df"] = updated_sch.copy()
        log_dispatch_action(
            f"Ran role-aware buffered auto-scheduler for {week_label}.",
            username=active_user,
        )
        st.success(
            "Successfully auto-generated weekly schedule with role assignments,"
            " balanced daily demand, and +15% sweeper/helper buffer!"
        )
        st.rerun()

    # ==========================================
    # BULK MULTI-DRIVER SHIFT ASSIGNMENT TOOL
    # ==========================================
    with st.expander("⚡ Bulk Assign Shifts to Multiple Drivers", expanded=False):
      st.caption(
          "Select multiple drivers below, pick the target day(s) and shift"
          " type, then click apply."
      )

      all_schedule_drivers = (
          st.session_state["schedule_df"]["Driver Name"]
          .dropna()
          .unique()
          .tolist()
          if "schedule_df" in st.session_state
          and not st.session_state["schedule_df"].empty
          else []
      )

      bulk_sel_drivers = st.multiselect(
          "Select Drivers",
          options=all_schedule_drivers,
          key="bulk_drivers_sel",
      )

      b_col1, b_col2 = st.columns(2)
      with b_col1:
        bulk_sel_days = st.multiselect(
            "Select Days",
            options=day_headers,
            default=day_headers,
            key="bulk_days_sel",
        )
      with b_col2:
        bulk_sel_shift = st.selectbox(
            "Assign Shift Type",
            options=[
                "",
                "Driver",
                "Helper",
                "On-Call",
                "Off",
                "OPS-AM",
                "OPS-PM",
                "Rqst Off",
            ],
            key="bulk_shift_sel",
        )

      if st.button(
          "🚀 Apply Bulk Shift Assignment",
          type="primary",
          key="btn_apply_bulk",
      ):
        if not bulk_sel_drivers:
          st.warning("Please select at least one driver.")
        elif not bulk_sel_days:
          st.warning("Please select at least one day.")
        else:
          sch_df_ref = st.session_state["schedule_df"]
          for idx, row in sch_df_ref.iterrows():
            d_name = str(row.get("Driver Name", "")).strip()
            if d_name in bulk_sel_drivers:
              for d_day in bulk_sel_days:
                if d_day in sch_df_ref.columns:
                  sch_df_ref.at[idx, d_day] = bulk_sel_shift

          st.session_state["schedule_df"] = sch_df_ref.copy()
          log_dispatch_action(
              f"Bulk assigned shift '{bulk_sel_shift}' for"
              f" {len(bulk_sel_drivers)} drivers across {len(bulk_sel_days)}"
              " days.",
              username=active_user,
          )
          st.success(
              f"Successfully updated shifts for {len(bulk_sel_drivers)}"
              " drivers!"
          )
          st.rerun()

    df_display = st.session_state["schedule_df"].copy()
    df_display["Total Days"] = (
        df_display[existing_day_cols].isin(work_shifts).sum(axis=1)
    )
    df_display["OT Status"] = df_display["Total Days"].apply(
        lambda x: f"⚠️ OT ({int(x)*10}h)" if x > 4 else "✅ Reg"
    )

    if schedule_view_filter == "Show Scheduled Only (Drivers/Helpers/OPS)":
      df_display = df_display[df_display["Total Days"] > 0]
    elif schedule_view_filter == "Show Available / Unscheduled Only":
      df_display = df_display[df_display["Total Days"] == 0]
    elif schedule_view_filter == "Show Over 4 Shifts (OT Risk)":
      df_display = df_display[df_display["Total Days"] > 4]
    elif schedule_view_filter == "Show with Calendar Notes / Requests":
      df_display = df_display[
          df_display["Notes / Requests"].astype(str).str.strip() != ""
      ]

    st.session_state["visible_schedule_indices"] = df_display.index.tolist()

    display_cols = ["Driver Name"] + existing_day_cols
    if (
        day_quick_focus != "None (Show All Days)"
        and day_quick_focus in existing_day_cols
    ):
      display_cols = ["Driver Name", day_quick_focus] + [
          c for c in existing_day_cols if c != day_quick_focus
      ]

    display_cols.extend(["Total Days", "OT Status"])
    if "Notes / Requests" in df_display.columns:
      display_cols.append("Notes / Requests")

    df_display = df_display[display_cols]

    st.caption(
        "Assign shift options. Leave cells blank if available but not"
        " scheduled. Long-range requests are auto-populated as 'Rqst Off'."
    )

    shift_options = [
        "",
        "Driver",
        "Helper",
        "On-Call",
        "Off",
        "OPS-AM",
        "OPS-PM",
        "Rqst Off",
    ]

    sch_config = {
        "Driver Name": st.column_config.TextColumn(
            "Driver Name", disabled=True
        ),
        "Total Days": st.column_config.NumberColumn(
            "Total Days", disabled=True, format="%d days"
        ),
        "OT Status": st.column_config.TextColumn("Status", disabled=True),
        "Notes / Requests": st.column_config.TextColumn(
            "Notes / Requests",
            help="Synced automatically from Long-Range Calendar.",
        ),
    }
    for dh in day_headers:
      if dh in display_cols:
        sch_config[dh] = st.column_config.SelectboxColumn(
            dh, options=shift_options, required=False
        )

    editor_height = min(max(350, len(df_display) * 38 + 50), 750)
    st.data_editor(
        df_display,
        column_config=sch_config,
        use_container_width=True,
        num_rows="fixed",
        hide_index=True,
        height=editor_height,
        key="weekly_schedule_editor_state",
        on_change=on_schedule_change,
    )

    c_s1, c_s2 = st.columns(2)
    with c_s1:
      if st.button("💾 Save Weekly Schedule to Cloud Storage", type="primary"):
        save_weekly_schedule_to_storage(
            st.session_state["schedule_df"],
            year=int(sel_year),
            week_num=int(sel_amazon_week),
        )
        log_dispatch_action(
            f"Saved weekly schedule ({week_label}) to Cloud Storage.",
            username=active_user,
        )
        st.success(f"Saved {week_label} permanently to Cloud Storage!")

    st.markdown("---")

    st.subheader("📢 Discord Announcement Broadcast (#weekly-schedule)")
    discord_text = generate_discord_schedule(
        st.session_state["schedule_df"], week_str=week_label
    )

    with st.expander(
        "🚀 Post Schedule Directly to Discord Channel", expanded=True
    ):
      st.code(discord_text, language="text")
      webhook_input = st.text_input(
          "Discord Webhook URL",
          value=DISCORD_WEBHOOK_URL,
          type="password",
          key="disc_webhook_weekly",
      )
      if st.button(
          "Broadcast Schedule to Discord Channel",
          type="primary",
          key="btn_disc_weekly",
      ):
        if webhook_input.strip():
          success, msg = send_discord_webhook(
              webhook_input.strip(), discord_text
          )
          if success:
            log_dispatch_action(
                f"Broadcast weekly schedule to Discord ({week_label}).",
                username=active_user,
            )
            st.success(msg)
          else:
            st.error(msg)
        else:
          st.warning("Please provide a valid Discord Webhook URL.")

  # ==========================================
  # TAB 2: LONG-RANGE PTO & AVAILABILITY CALENDAR
  # ==========================================
  with tab_pto:
    st.markdown("### 🌴 Long-Range Driver PTO & Requests Tracker")
    st.caption(
        "Log upcoming driver time-off, doctor appointments, or availability"
        " blocks well in advance to prevent weekly scheduling errors."
    )

    with st.form("pto_entry_form", clear_on_submit=True):
      st.markdown("#### Log New Request")
      f_col1, f_col2, f_col3, f_col4 = st.columns(4)

      driver_names = []
      if drivers_df is not None and "Driver Name" in drivers_df.columns:
        driver_names = sorted(
            drivers_df["Driver Name"].dropna().unique().tolist()
        )
      elif (
          "schedule_df" in st.session_state
          and not st.session_state["schedule_df"].empty
      ):
        sch_ref = st.session_state["schedule_df"]
        if "Driver Name" in sch_ref.columns:
          driver_names = sorted(sch_ref["Driver Name"].unique().tolist())
        elif "First Name" in sch_ref.columns and "Last Name" in sch_ref.columns:
          driver_names = sorted(
              (sch_ref["First Name"] + " " + sch_ref["Last Name"])
              .unique()
              .tolist()
          )
      else:
        driver_names = ["Manual Entry Required"]

      with f_col1:
        sel_driver = st.selectbox("Driver Name", options=driver_names)
      with f_col2:
        start_p_date = st.date_input(
            "Start Date", value=datetime.today(), key="pto_start_input"
        )
      with f_col3:
        end_p_date = st.date_input(
            "End Date", value=datetime.today(), key="pto_end_input"
        )
      with f_col4:
        category = st.selectbox(
            "Category",
            options=[
                "Approved PTO",
                "Unpaid Leave",
                "Appointment / Partial Off",
                "No Sundays",
                "Other Constraint",
            ],
        )

      reason_notes = st.text_input(
          "Reason / Notes (e.g., Family vacation, Doctor visit)"
      )

      submitted_pto = st.form_submit_button(
          "➕ Add to Long-Range Calendar", type="primary"
      )
      if submitted_pto:
        new_row = {
            "Driver Name": str(sel_driver).strip(),
            "Start Date": start_p_date.strftime("%Y-%m-%d"),
            "End Date": end_p_date.strftime("%Y-%m-%d"),
            "Category": str(category),
            "Reason / Notes": str(reason_notes),
        }
        st.session_state["pto_df"] = pd.concat(
            [st.session_state["pto_df"], pd.DataFrame([new_row])],
            ignore_index=True,
        )

        save_long_range_pto_storage(st.session_state["pto_df"])

        if "schedule_df" in st.session_state:
          del st.session_state["schedule_df"]
        if "loaded_week_key" in st.session_state:
          del st.session_state["loaded_week_key"]

        log_dispatch_action(
            f"Added long-range PTO request for {sel_driver} ({start_p_date} to"
            f" {end_p_date}).",
            username=active_user,
        )
        st.success(
            f"Successfully recorded PTO request for {sel_driver}! Saved to"
            " Cloud Storage and synchronized."
        )
        st.rerun()

    st.markdown("---")
    st.markdown("### 📋 Active Requests Log")

    def on_pto_change():
      changes = st.session_state.get("pto_editor_state")
      if changes and "pto_df" in st.session_state:
        for row_idx, col_changes in changes.get("edited_rows", {}).items():
          for col_name, new_val in col_changes.items():
            st.session_state["pto_df"].at[row_idx, col_name] = str(new_val)

    pto_config = {
        "Driver Name": st.column_config.TextColumn("Driver Name"),
        "Start Date": st.column_config.TextColumn("Start Date"),
        "End Date": st.column_config.TextColumn("End Date"),
        "Category": st.column_config.SelectboxColumn(
            "Category",
            options=[
                "Approved PTO",
                "Unpaid Leave",
                "Appointment / Partial Off",
                "No Sundays",
                "Other Constraint",
            ],
            required=True,
        ),
        "Reason / Notes": st.column_config.TextColumn("Reason / Notes"),
    }

    edited_pto_df = st.data_editor(
        st.session_state["pto_df"],
        column_config=pto_config,
        use_container_width=True,
        num_rows="dynamic",
        hide_index=True,
        key="pto_editor_state",
        on_change=on_pto_change,
    )

    c_p1, c_p2 = st.columns(2)
    with c_p1:
      if st.button(
          "💾 Save Long-Range Calendar to Cloud Storage",
          type="primary",
          key="save_pto_disk",
      ):
        save_long_range_pto_storage(edited_pto_df)
        st.session_state["pto_df"] = load_long_range_pto_storage()

        if "schedule_df" in st.session_state:
          del st.session_state["schedule_df"]
        if "loaded_week_key" in st.session_state:
          del st.session_state["loaded_week_key"]

        log_dispatch_action(
            "Updated long-range PTO calendar database in Cloud Storage.",
            username=active_user,
        )
        st.success(
            "Long-range calendar saved to Cloud Storage and weekly schedule"
            " synchronized!"
        )
        st.rerun()
