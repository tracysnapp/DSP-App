import json
import math
import urllib.request
import pandas as pd


def _find_day_column(columns, day_prefix):
  """Matches either 'Sun' or dated headers like 'Sun 15 Nov'."""
  prefix_lower = day_prefix.lower()
  if day_prefix in columns:
    return day_prefix
  return next(
      (c for c in columns if str(c).strip().lower().startswith(prefix_lower)),
      None,
  )


def send_discord_webhook(webhook_url, content_text):
  """Posts plain or markdown-formatted message strings directly to a Discord channel via Webhook."""
  if not webhook_url or not webhook_url.startswith("http"):
    return False, "Invalid or missing Discord Webhook URL."

  payload = {"content": content_text}
  data = json.dumps(payload).encode("utf-8")
  headers = {
      "Content-Type": "application/json",
      "User-Agent": "Python-DSP-CommandCenter",
  }

  try:
    req = urllib.request.Request(
        webhook_url, data=data, headers=headers, method="POST"
    )
    with urllib.request.urlopen(req) as response:
      if response.status in [200, 204]:
        return True, "Successfully published announcement to Discord!"
      return False, f"Discord returned HTTP status {response.status}"
  except Exception as e:
    return False, f"Failed to post to Discord: {str(e)}"


def generate_discord_schedule(schedule_df, week_str="18-Oct to 24-Oct"):
  """
    Generates a tabular monospace Discord schedule announcement sorted alphabetically by First Name.
    Supports both Sun-Sat and dated column headers (e.g. 'Sun 15 Nov') and shift codes.
    """
  if schedule_df is None or schedule_df.empty:
    return "```\nNo weekly schedule available.\n```"

  df = schedule_df.copy()

  if "Last Name" not in df.columns or "First Name" not in df.columns:
    if "Driver Name" in df.columns:

      def split_name(val):
        parts = str(val).strip().split(" ", 1)
        if len(parts) == 2:
          return parts[1], parts[0]  # Last, First
        return parts[0], ""

      df["Last Name"], df["First Name"] = zip(
          *df["Driver Name"].apply(split_name)
      )
    else:
      df["Last Name"] = "Driver"
      df["First Name"] = ""

  days_order = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
  day_col_map = {}
  for d in days_order:
    matched = _find_day_column(df.columns, d)
    if matched:
      day_col_map[d] = matched
    else:
      df[d] = ""
      day_col_map[d] = d

  def clean_shift(val):
    s = str(val).strip().upper()
    if s in ["DRIVER"]:
      return "Driver"
    elif s in ["HELPER"]:
      return "Helper"
    elif s in ["OPS-AM", "OPS-PM", "OPS", "OPS DISPATCH", "OPS CLOSEOUT"]:
      return "OPS"
    elif s in ["ON-CALL", "ON CALL", "STANDBY"]:
      return "OnCall"
    elif s in ["RQST OFF", "REQUEST OFF", "PTO", "RQSTOFF"]:
      return "RqstOff"
    return ""

  for d in days_order:
    src_col = day_col_map[d]
    df[d] = df[src_col].apply(clean_shift)

  df = df.sort_values(
      by=["First Name", "Last Name"], ascending=[True, True]
  ).reset_index(drop=True)

  header_str = (
      f"{'Last Name':<12} | {'First Name':<10} | {'Sun':<7} | {'Mon':<7} |"
      f" {'Tue':<7} | {'Wed':<7} | {'Thu':<7} | {'Fri':<7} | {'Sat':<7}"
  )
  divider = "-" * len(header_str)

  lines = [
      f"**📅 WEEKLY DISPATCH SCHEDULE ({week_str.upper()})**",
      "```text",
      header_str,
      divider,
  ]

  for _, row in df.iterrows():
    last_n = str(row["Last Name"])[:12]
    first_n = str(row["First Name"])[:10]

    sun_v = str(row["Sun"])[:7]
    mon_v = str(row["Mon"])[:7]
    tue_v = str(row["Tue"])[:7]
    wed_v = str(row["Wed"])[:7]
    thu_v = str(row["Thu"])[:7]
    fri_v = str(row["Fri"])[:7]
    sat_v = str(row["Sat"])[:7]

    row_str = (
        f"{last_n:<12} | {first_n:<10} | {sun_v:<7} | {mon_v:<7} |"
        f" {tue_v:<7} | {wed_v:<7} | {thu_v:<7} | {fri_v:<7} | {sat_v:<7}"
    )
    lines.append(row_str)

  lines.append("```")
  return "\n".join(lines)


def generate_discord_top_drivers(
    top_drivers_df, week_str="2026-W41", min_pkg_threshold=100
):
  """
    Generates Discord Top Driver Announcements filtering out nursery / ultra-low volume routes 
    to ensure bonus recognition goes to full-volume DAs.
    """
  if top_drivers_df is None or top_drivers_df.empty:
    return "No scorecard metrics available."

  md = f"🏆 **TOP DRIVER RECOGNITION - WEEK {week_str.upper()}** 🏆\n"
  md += (
      "Congratulations to our top performing Delivery Associates of the week!"
      " Thank you for your dedication to safety and delivery excellence!\n\n"
  )

  medals = [
      "🥇 **1ST PLACE**",
      "🥈 **2ND PLACE**",
      "🥉 **3RD PLACE**",
      "⭐ **TOP PERFORMER**",
      "⭐ **TOP PERFORMER**",
  ]

  score_col = (
      "Unified_Composite_Score"
      if "Unified_Composite_Score" in top_drivers_df.columns
      else "Overall Score"
  )

  filtered_df = (
      top_drivers_df[
          top_drivers_df["Packages Delivered"] >= min_pkg_threshold
      ].copy()
      if "Packages Delivered" in top_drivers_df.columns
      else top_drivers_df.copy()
  )
  sorted_top = filtered_df.sort_values(
      by=[score_col, "Packages Delivered"], ascending=[False, False]
  ).reset_index(drop=True)

  for idx, row in sorted_top.head(5).iterrows():
    medal = medals[idx] if idx < len(medals) else "⭐ **TOP PERFORMER**"
    d_name = row["Driver Name"]
    score = row[score_col]
    standing = row.get("Overall Standing", "Platinum")
    fico = row.get("FICO", "850")
    pkgs = row.get("Packages Delivered", "0")

    md += f"{medal}: **{d_name}**\n"
    md += (
        f"   • DQI Score: `{score}` | Standing: `{standing}` | FICO: `{fico}`"
        f" | Packages: `{pkgs}`\n\n"
    )

  md += "Keep up the fantastic work team! 🚛💨"
  return md


def _get_trailing_work_streak(driver_name_lower, prev_week_df, work_shifts):
  """Counts consecutive work shifts at the end of the previous week (ending Saturday)."""
  if (
      prev_week_df is None
      or prev_week_df.empty
      or "Driver Name" not in prev_week_df.columns
  ):
    return 0

  match = prev_week_df[
      prev_week_df["Driver Name"].astype(str).str.strip().str.lower()
      == driver_name_lower
  ]
  if match.empty:
    return 0

  row = match.iloc[0]
  days_order = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
  streak = 0
  for d in reversed(days_order):
    col = _find_day_column(prev_week_df.columns, d)
    if not col:
      break
    val = str(row.get(col, "")).strip()
    if val in work_shifts:
      streak += 1
    else:
      break
  return streak


def _would_exceed_consecutive_limit(
    row,
    day_headers,
    candidate_idx,
    work_shifts,
    trailing_prev_streak=0,
    max_consecutive=5,
):
  """Checks if scheduling candidate_idx would create more than max_consecutive straight work days."""
  worked = [str(row.get(dh, "")).strip() in work_shifts for dh in day_headers]
  worked[candidate_idx] = True

  streak = trailing_prev_streak
  for is_working in worked:
    if is_working:
      streak += 1
      if streak > max_consecutive:
        return True
    else:
      streak = 0
  return False


def auto_generate_pattern_weekly_schedule(
    schedule_df,
    day_headers,
    expected_routes_dict,
    drivers_df=None,
    target_shifts_per_driver=4,
    min_shifts_per_driver=2,
    prev_week_schedule_df=None,
    max_consecutive_days=5,
    clear_existing_non_pto=False,
):
  """
    Two-pass, role-aware, demand-balanced auto-scheduler:
    - Pass 1: Ensures every available team member receives at least `min_shifts_per_driver` (2 shifts/week)
      in scorecard-rank order so lower-ranked drivers aren't shut out.
    - Pass 2: Tops up drivers in scorecard-rank order up to `target_shifts_per_driver` (4 shifts/week)
      within daily +15% buffered targets.
    """
  if schedule_df is None or schedule_df.empty:
    return schedule_df

  df = schedule_df.copy()
  work_shifts = ["Driver", "Helper", "OPS-AM", "OPS-PM"]
  protected_statuses = ["Rqst Off", "Off", "On-Call"]

  if clear_existing_non_pto:
    for idx, row in df.iterrows():
      for dh in day_headers:
        val = str(row.get(dh, "")).strip()
        if val not in protected_statuses:
          df.at[idx, dh] = ""

  pref_map = {}
  score_map = {}
  role_map = {}

  if (
      drivers_df is not None
      and not drivers_df.empty
      and "Driver Name" in drivers_df.columns
  ):
    p_col = next(
        (
            c
            for c in drivers_df.columns
            if "pref" in c.lower()
            or "shift" in c.lower()
            or "pattern" in c.lower()
        ),
        None,
    )
    s_col = next(
        (
            c
            for c in drivers_df.columns
            if "score" in c.lower() or "rank" in c.lower()
        ),
        None,
    )
    r_col = next((c for c in drivers_df.columns if "role" in c.lower()), None)

    for _, r in drivers_df.iterrows():
      d_name = str(r.get("Driver Name", "")).strip().lower()
      if p_col:
        pref_map[d_name] = str(r.get(p_col, "Any")).strip()
      if r_col:
        role_map[d_name] = str(r.get(r_col, "Driver Associate")).strip()
      if s_col:
        try:
          score_map[d_name] = float(r.get(s_col, 100.0))
        except Exception:
          score_map[d_name] = 100.0

  df["__temp_score"] = (
      df["Driver Name"]
      .astype(str)
      .str.strip()
      .str.lower()
      .map(score_map)
      .fillna(100.0)
  )
  df = df.sort_values(by="__temp_score", ascending=False).reset_index(drop=True)

  front_half_indices = [0, 1, 2, 3]  # Sun, Mon, Tue, Wed
  back_half_indices = [3, 4, 5, 6]  # Wed, Thu, Fri, Sat

  buffered_targets = {
      dh: (
          int(math.ceil(expected_routes_dict.get(dh, 0) * 1.15))
          if expected_routes_dict.get(dh, 0) > 0
          else 0
      )
      for dh in day_headers
  }

  trailing_streaks = {
      idx: _get_trailing_work_streak(
          str(row.get("Driver Name", "")).strip().lower(),
          prev_week_schedule_df,
          work_shifts,
      )
      for idx, row in df.iterrows()
  }

  def _assign_shifts_up_to_cap(shift_cap, allow_overflow_for_minimum=False):
    for idx, row in df.iterrows():
      d_name = str(row.get("Driver Name", "")).strip().lower()
      current_shifts = sum(
          1
          for dh in day_headers
          if str(df.at[idx, dh]).strip() in work_shifts
      )
      if current_shifts >= shift_cap:
        continue

      driver_pref = pref_map.get(d_name, "Any").title()
      driver_role = role_map.get(d_name, "Driver Associate").lower()
      trailing_streak = trailing_streaks[idx]

      if "Front" in driver_pref:
        # Preferred front-half days first, then remaining active days if needed to meet minimum
        fallback_days = sorted(
            [i for i in range(len(day_headers)) if i not in front_half_indices],
            key=lambda i: (
                buffered_targets[day_headers[i]]
                - len(df[df[day_headers[i]].isin(work_shifts)])
            ),
            reverse=True,
        )
        candidate_indices = list(front_half_indices) + (
            fallback_days if allow_overflow_for_minimum else []
        )
      elif "Back" in driver_pref:
        fallback_days = sorted(
            [i for i in range(len(day_headers)) if i not in back_half_indices],
            key=lambda i: (
                buffered_targets[day_headers[i]]
                - len(df[df[day_headers[i]].isin(work_shifts)])
            ),
            reverse=True,
        )
        candidate_indices = list(back_half_indices) + (
            fallback_days if allow_overflow_for_minimum else []
        )
      else:
        candidate_indices = sorted(
            range(len(day_headers)),
            key=lambda i: (
                buffered_targets[day_headers[i]]
                - len(df[df[day_headers[i]].isin(work_shifts)])
            ),
            reverse=True,
        )

      for day_idx in candidate_indices:
        if current_shifts >= shift_cap:
          break

        dh = day_headers[day_idx]
        existing_val = str(df.at[idx, dh]).strip()

        if existing_val != "" and existing_val.lower() not in ["none", "nan"]:
          continue

        base_target = expected_routes_dict.get(dh, 0)
        buf_target = buffered_targets[dh]
        if buf_target <= 0:
          continue

        day_current_total = len(df[df[dh].isin(work_shifts)])
        if day_current_total >= buf_target:
          continue

        if _would_exceed_consecutive_limit(
            df.loc[idx],
            day_headers,
            day_idx,
            work_shifts,
            trailing_prev_streak=trailing_streak,
            max_consecutive=max_consecutive_days,
        ):
          continue

        if "operations manager" in driver_role or "dispatcher" in driver_role:
          am_count = len(df[df[dh] == "OPS-AM"])
          pm_count = len(df[df[dh] == "OPS-PM"])
          shift_label = "OPS-AM" if am_count <= pm_count else "OPS-PM"
        elif "sweeper" in driver_role:
          shift_label = "Helper"
        else:
          active_drivers_today = len(df[df[dh] == "Driver"])
          shift_label = (
              "Driver" if active_drivers_today < base_target else "Helper"
          )

        df.at[idx, dh] = shift_label
        current_shifts += 1

  # Pass 1: Guarantee minimum 2 shifts/week across all drivers in priority order
  _assign_shifts_up_to_cap(
      min_shifts_per_driver, allow_overflow_for_minimum=True
  )

  # Pass 2: Top up highest-priority drivers up to full 4 shifts/week
  _assign_shifts_up_to_cap(
      target_shifts_per_driver, allow_overflow_for_minimum=False
  )

  df = df.drop(columns=["__temp_score"], errors="ignore")
  sort_cols = [
      c
      for c in ["First Name", "Last Name", "Driver Name"]
      if c in df.columns
  ]
  if sort_cols:
    df = df.sort_values(by=sort_cols, ascending=True).reset_index(drop=True)

  return df


def calculate_driver_attendance_metrics(schedule_df, attendance_log_df):
  """
    Cross-references scheduled shift counts against logged infractions in attendance_log.xlsx.
    Supports both Sun-Sat and dated headers ('Sun 15 Nov', etc.).
    """
  if schedule_df is None or schedule_df.empty:
    return pd.DataFrame(
        columns=[
            "Driver Name",
            "Scheduled Shifts",
            "Late Starts",
            "Call-Outs",
            "No-Shows",
            "Incomplete Shifts",
            "Total Infractions",
            "Reliability Rating",
        ]
    )

  records = []
  infractions_by_driver = {}
  if attendance_log_df is not None and not attendance_log_df.empty:
    for _, row in attendance_log_df.iterrows():
      d = str(row.get("Driver Name", "")).strip()
      itype = str(row.get("Infraction Type", "")).strip().upper()
      if d:
        if d not in infractions_by_driver:
          infractions_by_driver[d] = {
              "LATE": 0,
              "CALLOUT": 0,
              "NOSHOW": 0,
              "INCOMPLETE": 0,
          }

        if "LATE" in itype:
          infractions_by_driver[d]["LATE"] += 1
        elif "CALL-OUT" in itype or "CALLOUT" in itype:
          infractions_by_driver[d]["CALLOUT"] += 1
        elif "NO-SHOW" in itype or "NOSHOW" in itype:
          infractions_by_driver[d]["NOSHOW"] += 1
        elif "INCOMPLETE" in itype or "LEFT EARLY" in itype:
          infractions_by_driver[d]["INCOMPLETE"] += 1

  days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
  day_cols = [
      c for d in days if (c := _find_day_column(schedule_df.columns, d))
  ]

  for _, row in schedule_df.iterrows():
    d_name = str(row.get("Driver Name", "")).strip()
    if not d_name:
      continue

    scheduled_cnt = 0
    for col in day_cols:
      shift_val = str(row.get(col, "")).strip().upper()
      if shift_val in [
          "DRIVER",
          "HELPER",
          "OPS-AM",
          "OPS-PM",
          "OPS",
          "ON-CALL",
          "STANDBY",
      ]:
        scheduled_cnt += 1

    d_counts = infractions_by_driver.get(
        d_name, {"LATE": 0, "CALLOUT": 0, "NOSHOW": 0, "INCOMPLETE": 0}
    )
    total_inf = (
        d_counts["LATE"]
        + d_counts["CALLOUT"]
        + d_counts["NOSHOW"]
        + d_counts["INCOMPLETE"]
    )

    if total_inf == 0:
      rating = "⭐⭐⭐⭐⭐ Excellent"
    elif total_inf <= 2:
      rating = "⭐⭐⭐⭐ Good"
    elif total_inf <= 4:
      rating = "⚠️ Needs Improvement"
    else:
      rating = "🚨 Critical Action Required"

    records.append({
        "Driver Name": d_name,
        "Scheduled Shifts": scheduled_cnt,
        "Late Starts": d_counts["LATE"],
        "Call-Outs": d_counts["CALLOUT"],
        "No-Shows": d_counts["NOSHOW"],
        "Incomplete Shifts": d_counts["INCOMPLETE"],
        "Total Infractions": total_inf,
        "Reliability Rating": rating,
    })

  return (
      pd.DataFrame(records)
      .sort_values(
          by=["Total Infractions", "Driver Name"], ascending=[False, True]
      )
      .reset_index(drop=True)
  )
