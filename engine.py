import datetime
import io
import json
import logging
import os
import re
import tempfile
from google.cloud import storage
import pandas as pd
import streamlit as st

try:
  from dotenv import load_dotenv

  load_dotenv(override=False)
except ImportError:
  pass

# ---------------------------------------------------------
# CONFIGURATION & STORAGE ABSTRACTION
# ---------------------------------------------------------
K_SERVICE = os.getenv("K_SERVICE")
if K_SERVICE:
  STORAGE_MODE = "CLOUD"
else:
  STORAGE_MODE = os.getenv("STORAGE_MODE", "CLOUD").upper()

GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "dsp-app-storage")

MASTER_FLEET_PATH = os.getenv("MASTER_FLEET_PATH", "master_fleet.xlsx")
MASTER_PHONES_PATH = os.getenv("MASTER_PHONES_PATH", "master_phones.xlsx")
CLOSING_CHECKLIST_PATH = os.getenv(
    "CLOSING_CHECKLIST_PATH", "closing_checklist_log.xlsx"
)
ACCESS_CODES_PATH = os.getenv("ACCESS_CODES_PATH", "access_codes.xlsx")
MASTER_DRIVERS_PATH = os.getenv("MASTER_DRIVERS_PATH", "master_drivers.xlsx")
WEEKLY_SCHEDULE_PATH = os.getenv("WEEKLY_SCHEDULE_PATH", "weekly_schedule.xlsx")
SCHEDULES_DIR = os.getenv("SCHEDULES_DIR", "schedules")
LONG_RANGE_PTO_PATH = os.getenv("LONG_RANGE_PTO_PATH", "long_range_pto.xlsx")
WEEKLY_TARGETS_PATH = os.getenv("WEEKLY_TARGETS_PATH", "weekly_targets.json")
STANDING_SCHEDULES_PATH = os.getenv(
    "STANDING_SCHEDULES_PATH", "standing_schedules.json"
)
SCORECARDS_PATH = os.getenv("SCORECARDS_PATH", "master_scorecards.xlsx")
ATTENDANCE_LOG_PATH = os.getenv("ATTENDANCE_LOG_PATH", "attendance_log.xlsx")
INCIDENTS_LOG_PATH = os.getenv("INCIDENTS_LOG_PATH", "master_incidents.xlsx")
HISTORY_DIR = os.getenv("HISTORY_DIR", "history")
LOG_FILE_PATH = os.getenv("DISPATCH_LOG_PATH", "dispatch_audit.log")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS")
DISPATCH_USER = os.getenv("DISPATCH_USER", "dispatch")
DISPATCH_PASS = os.getenv("DISPATCH_PASS")

USER_CREDENTIALS = {
    ADMIN_USER: {
        "password": ADMIN_PASS if ADMIN_PASS else "jna2026!",
        "role": "Admin",
        "name": "Operations Manager",
    },
    DISPATCH_USER: {
        "password": DISPATCH_PASS if DISPATCH_PASS else "ddk6dispatch",
        "role": "Dispatcher",
        "name": "Dispatch Desk",
    },
}

# ---------------------------------------------------------
# LOGGING SETUP
# ---------------------------------------------------------
logging.basicConfig(
    filename=LOG_FILE_PATH if STORAGE_MODE == "LOCAL" else None,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (User: %(user)s) - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def log_dispatch_action(action_msg, username="System"):
  """Logs dispatch operations to console/disk auditing logs."""
  logger = logging.getLogger("DispatchAudit")
  logger.info(action_msg, extra={"user": username})


# ---------------------------------------------------------
# GOOGLE CLOUD STORAGE HELPERS
# ---------------------------------------------------------
@st.cache_resource
def get_gcs_client():
  return storage.Client()


def get_gcs_bucket():
  client = get_gcs_client()
  return client.bucket(GCS_BUCKET_NAME)


def read_gcs_dataframe(blob_path: str) -> pd.DataFrame:
  try:
    bucket = get_gcs_bucket()
    blob = bucket.blob(blob_path)
    if not blob.exists():
      return pd.DataFrame()

    content = blob.download_as_bytes()
    buffer = io.BytesIO(content)
    if blob_path.endswith((".xlsx", ".xls")):
      return pd.read_excel(buffer)
    else:
      return pd.read_csv(buffer)
  except Exception as e:
    print(f"Error reading {blob_path} from GCS: {e}")
    return pd.DataFrame()


def save_gcs_dataframe(df: pd.DataFrame, blob_path: str):
  if df is None:
    return

  try:
    bucket = get_gcs_bucket()
    blob = bucket.blob(blob_path)
    buffer = io.BytesIO()

    if blob_path.endswith((".xlsx", ".xls")):
      with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
      content_type = (
          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
      )
    else:
      df.to_csv(buffer, index=False)
      content_type = "text/csv"

    blob.upload_from_string(buffer.getvalue(), content_type=content_type)
  except Exception as e:
    print(f"Error saving {blob_path} to GCS: {e}")


def safe_save_dataframe(df, file_path, allow_empty=False):
  if df is None or (df.empty and not allow_empty):
    return

  if STORAGE_MODE == "CLOUD":
    save_gcs_dataframe(df, file_path)
    return

  dir_name = os.path.dirname(file_path)
  if dir_name and not os.path.exists(dir_name):
    os.makedirs(dir_name, exist_ok=True)

  ext = os.path.splitext(file_path)[1].lower()
  with tempfile.NamedTemporaryFile(
      delete=False, suffix=ext, dir=dir_name if dir_name else "."
  ) as tmp:
    tmp_path = tmp.name

  try:
    if ext in [".xlsx", ".xls"]:
      df.to_excel(tmp_path, index=False)
    else:
      df.to_csv(tmp_path, index=False)
    os.replace(tmp_path, file_path)
  except Exception as e:
    if os.path.exists(tmp_path):
      os.remove(tmp_path)
    raise e


def load_dataframe_auto(file_path: str) -> pd.DataFrame:
  if STORAGE_MODE == "CLOUD":
    return read_gcs_dataframe(file_path)

  if os.path.exists(file_path):
    return (
        pd.read_excel(file_path)
        if file_path.endswith((".xlsx", ".xls"))
        else pd.read_csv(file_path)
    )
  return pd.DataFrame()


def load_json_auto(file_path: str) -> dict:
  if STORAGE_MODE == "CLOUD":
    try:
      bucket = get_gcs_bucket()
      blob = bucket.blob(file_path)
      if not blob.exists():
        return {}
      return json.loads(blob.download_as_text())
    except Exception as e:
      print(f"Error reading JSON {file_path} from GCS: {e}")
      return {}

  if os.path.exists(file_path):
    try:
      with open(file_path, "r") as f:
        return json.load(f)
    except Exception:
      pass
  return {}


def save_json_auto(data: dict, file_path: str):
  if STORAGE_MODE == "CLOUD":
    try:
      bucket = get_gcs_bucket()
      blob = bucket.blob(file_path)
      blob.upload_from_string(
          json.dumps(data, indent=2), content_type="application/json"
      )
    except Exception as e:
      print(f"Error saving JSON {file_path} to GCS: {e}")
    return

  dir_name = os.path.dirname(file_path)
  if dir_name and not os.path.exists(dir_name):
    os.makedirs(dir_name, exist_ok=True)
  with open(file_path, "w") as f:
    json.dump(data, f, indent=2)


# ---------------------------------------------------------
# AUTHENTICATION & HISTORY MANAGERS
# ---------------------------------------------------------
def authenticate_user(username, password):
  u_clean = str(username).strip()
  p_clean = str(password).strip()

  if u_clean in USER_CREDENTIALS:
    expected_pass = USER_CREDENTIALS[u_clean]["password"]
    if expected_pass and p_clean == str(expected_pass).strip():
      log_dispatch_action(
          f"User '{u_clean}' signed into Command Center workspace.",
          username=u_clean,
      )
      return (
          True,
          USER_CREDENTIALS[u_clean]["role"],
          USER_CREDENTIALS[u_clean]["name"],
      )
  return False, None, None


def ensure_history_dir():
  if STORAGE_MODE == "LOCAL" and not os.path.exists(HISTORY_DIR):
    os.makedirs(HISTORY_DIR, exist_ok=True)


def cleanup_old_snapshots(days_to_keep=30):
  cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
      days=days_to_keep
  )

  if STORAGE_MODE == "CLOUD":
    try:
      bucket = get_gcs_bucket()
      prefix = (
          f"{HISTORY_DIR}/" if not HISTORY_DIR.endswith("/") else HISTORY_DIR
      )
      blobs = bucket.list_blobs(prefix=prefix)
      for blob in blobs:
        if blob.name.endswith(".xlsx") and (
            "roster_" in blob.name or "closing_checklist_" in blob.name
        ):
          if blob.updated < cutoff:
            blob.delete()
    except Exception as e:
      print(f"Error cleaning up GCS snapshots: {e}")
    return

  if os.path.exists(HISTORY_DIR):
    now = datetime.datetime.now()
    local_cutoff = datetime.timedelta(days=days_to_keep)
    for filename in os.listdir(HISTORY_DIR):
      if (
          filename.startswith("roster_")
          or filename.startswith("closing_checklist_")
      ) and filename.endswith(".xlsx"):
        filepath = os.path.join(HISTORY_DIR, filename)
        file_mtime = datetime.datetime.fromtimestamp(os.path.getmtime(filepath))
        if now - file_mtime > local_cutoff:
          try:
            os.remove(filepath)
          except Exception as e:
            print(f"Error purging old local snapshot {filename}: {e}")


def save_snapshot_file(roster_df, filename):
  if roster_df is None or roster_df.empty:
    return

  blob_path = f"{HISTORY_DIR}/{filename}"
  safe_save_dataframe(roster_df, blob_path)


def save_daily_closing_checklist(closing_df):
  if closing_df is None or closing_df.empty:
    return

  safe_save_dataframe(closing_df, CLOSING_CHECKLIST_PATH)
  date_stamp = pd.Timestamp.now().strftime("%Y-%m-%d")
  snapshot_fname = f"closing_checklist_{date_stamp}.xlsx"
  save_snapshot_file(closing_df, snapshot_fname)


def list_snapshot_files():
  if STORAGE_MODE == "CLOUD":
    try:
      bucket = get_gcs_bucket()
      prefix = (
          f"{HISTORY_DIR}/" if not HISTORY_DIR.endswith("/") else HISTORY_DIR
      )
      blobs = bucket.list_blobs(prefix=prefix)
      files = []
      for blob in blobs:
        fname = os.path.basename(blob.name)
        if fname.startswith("roster_") and fname.endswith(".xlsx"):
          files.append(fname)
      return sorted(files, reverse=True)
    except Exception as e:
      print(f"Error reading GCS snapshots: {e}")
      return []

  if os.path.exists(HISTORY_DIR):
    return sorted(
        [
            f
            for f in os.listdir(HISTORY_DIR)
            if f.startswith("roster_") and f.endswith(".xlsx")
        ],
        reverse=True,
    )
  return []


def load_snapshot_file(filename):
  blob_path = f"{HISTORY_DIR}/{filename}"
  df = load_dataframe_auto(blob_path)
  if not df.empty:
    df_clean = df.fillna("").astype(str)
    return df_clean.replace(["nan", "NaN", "None", "<NA>"], "")
  return df


@st.cache_data(ttl=60, show_spinner=False)
def get_van_last_driven_dict():
  """Returns a dictionary mapping van bumpers to their last driven date from master fleet data instantly."""
  fleet_df = load_dataframe_auto(MASTER_FLEET_PATH)
  van_last_date = {}

  if fleet_df is not None and not fleet_df.empty:
    bumper_col = next(
        (
            c
            for c in fleet_df.columns
            if "bumper" in c.lower()
            or "vehicle" in c.lower()
            or "name" in c.lower()
        ),
        None,
    )
    date_col = next(
        (
            c
            for c in fleet_df.columns
            if "driven" in c.lower() or "date" in c.lower()
        ),
        None,
    )

    if bumper_col and date_col:
      for _, row in fleet_df.iterrows():
        b = str(row[bumper_col]).strip()
        d = str(row[date_col]).strip()
        if b and d and d.upper() not in ["NAN", "NONE", ""]:
          try:
            van_last_date[b] = pd.to_datetime(d).date()
          except Exception:
            continue

  return van_last_date


def update_van_last_driven(van_bumper, activity_date=None):
  """Updates the 'Last Driven' date for a specific van bumper in master_fleet.xlsx instantly."""
  if not van_bumper or str(van_bumper).strip().upper() in [
      "NAN",
      "NONE",
      "",
      "UNASSIGNED",
      "N/A",
  ]:
    return

  if activity_date is None:
    activity_date = datetime.date.today().strftime("%Y-%m-%d")

  fleet_df = load_dataframe_auto(MASTER_FLEET_PATH)
  if fleet_df is not None and not fleet_df.empty:
    bumper_col = next(
        (
            c
            for c in fleet_df.columns
            if "bumper" in c.lower()
            or "vehicle" in c.lower()
            or "name" in c.lower()
        ),
        fleet_df.columns[0],
    )
    date_col = next(
        (
            c
            for c in fleet_df.columns
            if "driven" in c.lower() or "date" in c.lower()
        ),
        None,
    )

    if not date_col:
      date_col = "Last Driven"
      fleet_df[date_col] = ""
    else:
      fleet_df[date_col] = fleet_df[date_col].astype(object)

    mask = (
        fleet_df[bumper_col].astype(str).str.strip().str.upper()
        == str(van_bumper).strip().upper()
    )
    if mask.any():
      fleet_df.loc[mask, date_col] = activity_date
      safe_save_dataframe(fleet_df, MASTER_FLEET_PATH)

      load_local_fleet.clear()
      get_van_last_driven_dict.clear()

      if "fleet_df" in st.session_state:
        st.session_state["fleet_df"] = load_local_fleet()


def process_access_data(access_df):
  if access_df is None or access_df.empty:
    return pd.DataFrame(columns=["Location", "Code", "Special Instructions"])

  df = access_df.copy()
  loc_col = next(
      (
          c
          for c in df.columns
          if "location" in str(c).lower()
          or "address" in str(c).lower()
          or "building" in str(c).lower()
      ),
      df.columns[0],
  )
  code_col = next(
      (
          c
          for c in df.columns
          if "code" in str(c).lower()
          or "gate" in str(c).lower()
          or "pin" in str(c).lower()
      ),
      df.columns[1] if len(df.columns) > 1 else df.columns[0],
  )
  notes_col = next(
      (
          c
          for c in df.columns
          if "instruction" in str(c).lower()
          or "note" in str(c).lower()
          or "remark" in str(c).lower()
      ),
      df.columns[2] if len(df.columns) > 2 else df.columns[0],
  )

  out_df = pd.DataFrame()
  out_df["Location"] = df[loc_col].astype(str).str.strip()
  out_df["Code"] = df[code_col].astype(str).str.strip()
  out_df["Special Instructions"] = df[notes_col].astype(str).str.strip()
  return out_df


@st.cache_data(ttl=60, show_spinner=False)
def load_local_fleet():
  df = load_dataframe_auto(MASTER_FLEET_PATH)
  if not df.empty:
    try:
      from modules.fleet import process_fleet_data

      return process_fleet_data(df).copy()
    except Exception:
      pass
  return None


@st.cache_data(ttl=60, show_spinner=False)
def load_local_phones():
  df = load_dataframe_auto(MASTER_PHONES_PATH)
  if not df.empty:
    try:
      from modules.fleet import process_phone_data

      return process_phone_data(df).copy()
    except Exception:
      pass
  return None


@st.cache_data(ttl=60, show_spinner=False)
def load_local_drivers():
  df = load_dataframe_auto(MASTER_DRIVERS_PATH)
  if not df.empty:
    try:
      from modules.fleet import process_driver_data

      return process_driver_data(df).copy()
    except Exception:
      pass
  return pd.DataFrame(
      columns=[
          "Driver Name",
          "Transporter ID",
          "Phone Number",
          "Status",
          "Role",
          "Hire Date",
          "Preferred Shifts",
          "Overall Score",
          "Standing",
      ]
  )


def get_week_schedule_path(year: int = None, week_num: int = None) -> str:
  if year is not None and week_num is not None:
    return f"{SCHEDULES_DIR}/schedule_{int(year)}_W{int(week_num):02d}.xlsx"
  return WEEKLY_SCHEDULE_PATH


@st.cache_data(ttl=60, show_spinner=False)
def load_local_schedule(year: int = None, week_num: int = None):
  df = pd.DataFrame()
  if year is not None and week_num is not None:
    week_path = get_week_schedule_path(year, week_num)
    df = load_dataframe_auto(week_path)

  # Fallback to legacy single-file schedule if per-week file does not exist yet
  if df.empty:
    df = load_dataframe_auto(WEEKLY_SCHEDULE_PATH)

  if not df.empty:
    try:
      if "Driver Name" in df.columns:
        df["first_name"] = (
            df["Driver Name"]
            .astype(str)
            .str.strip()
            .str.split()
            .str[0]
            .str.upper()
        )
        df = (
            df.sort_values(
                by=["first_name", "Driver Name"], ascending=[True, True]
            )
            .drop(columns=["first_name"])
            .reset_index(drop=True)
        )
      return df.copy()
    except Exception:
      pass
  return pd.DataFrame(
      columns=["Driver Name", "Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
  )


def save_weekly_schedule_to_storage(
    df: pd.DataFrame, year: int = None, week_num: int = None
):
  if df is None or df.empty:
    return
  if year is not None and week_num is not None:
    safe_save_dataframe(df, get_week_schedule_path(year, week_num))
  safe_save_dataframe(df, WEEKLY_SCHEDULE_PATH)
  load_local_schedule.clear()


@st.cache_data(ttl=60, show_spinner=False)
def load_long_range_pto_storage() -> pd.DataFrame:
  df = load_dataframe_auto(LONG_RANGE_PTO_PATH)
  if df.empty and os.path.exists("data/long_range_pto.csv"):
    try:
      df = pd.read_csv("data/long_range_pto.csv")
    except Exception:
      df = pd.DataFrame()

  if not df.empty:
    for col in df.columns:
      df[col] = (
          df[col]
          .fillna("")
          .astype(str)
          .replace(["nan", "NaN", "None", "<NA>"], "")
      )
    return df.copy()

  return pd.DataFrame(
      columns=[
          "Driver Name",
          "Start Date",
          "End Date",
          "Category",
          "Reason / Notes",
      ]
  )


def save_long_range_pto_storage(df: pd.DataFrame):
  clean_df = df.copy()
  for col in clean_df.columns:
    clean_df[col] = (
        clean_df[col]
        .fillna("")
        .astype(str)
        .replace(["nan", "NaN", "None", "<NA>"], "")
    )
  safe_save_dataframe(clean_df, LONG_RANGE_PTO_PATH, allow_empty=True)
  load_long_range_pto_storage.clear()


@st.cache_data(ttl=60, show_spinner=False)
def load_weekly_targets_storage() -> dict:
  data = load_json_auto(WEEKLY_TARGETS_PATH)
  if not data and os.path.exists("data/weekly_targets.json"):
    try:
      with open("data/weekly_targets.json", "r") as f:
        data = json.load(f)
    except Exception:
      data = {}
  return data if isinstance(data, dict) else {}


def save_weekly_targets_storage(targets_dict: dict):
  save_json_auto(targets_dict, WEEKLY_TARGETS_PATH)
  load_weekly_targets_storage.clear()


@st.cache_data(ttl=60, show_spinner=False)
def load_standing_schedules_storage() -> dict:
  """
    Loads standing / recurring fixed-day schedules keyed by driver name (lowercase):
    {
      "tracy snapp": {
          "driver_name": "Tracy Snapp",
          "days": ["Sun", "Mon", "Tue", "Wed"],
          "shift": "OPS-AM",
          "lock_only_fixed_days": True
      }
    }
    """
  data = load_json_auto(STANDING_SCHEDULES_PATH)
  return data if isinstance(data, dict) else {}


def save_standing_schedules_storage(rules_dict: dict):
  save_json_auto(rules_dict, STANDING_SCHEDULES_PATH)
  load_standing_schedules_storage.clear()


@st.cache_data(ttl=60, show_spinner=False)
def load_local_scorecards():
  df = load_dataframe_auto(SCORECARDS_PATH)
  return df.copy() if not df.empty else pd.DataFrame()


@st.cache_data(ttl=60, show_spinner=False)
def load_local_access_codes():
  df = load_dataframe_auto(ACCESS_CODES_PATH)
  if not df.empty:
    try:
      return process_access_data(df).copy()
    except Exception:
      pass
  return pd.DataFrame(columns=["Location", "Code", "Special Instructions"])


@st.cache_data(ttl=10, show_spinner=False)
def load_local_attendance_log():
  df = load_dataframe_auto(ATTENDANCE_LOG_PATH)
  return (
      df.copy()
      if not df.empty
      else pd.DataFrame(
          columns=[
              "Date",
              "Driver Name",
              "Infraction Type",
              "Logged By",
              "Notes",
          ]
      )
  )


@st.cache_data(ttl=10, show_spinner=False)
def load_local_incidents_log():
  df = load_dataframe_auto(INCIDENTS_LOG_PATH)
  return (
      df.copy()
      if not df.empty
      else pd.DataFrame(
          columns=[
              "Date",
              "Driver Name",
              "Severity",
              "Category",
              "Infraction / Detail",
              "Van Bumper",
              "Logged By",
              "Notes",
          ]
      )
  )


def save_driver_incident(
    driver_name,
    severity,
    category,
    infraction_detail,
    van_bumper,
    logged_by,
    notes,
):
  incidents_df = load_local_incidents_log()
  new_record = {
      "Date": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
      "Driver Name": str(driver_name).strip(),
      "Severity": str(severity).strip(),
      "Category": str(category).strip(),
      "Infraction / Detail": str(infraction_detail).strip(),
      "Van Bumper": str(van_bumper).strip(),
      "Logged By": str(logged_by).strip(),
      "Notes": str(notes).strip(),
  }
  updated_df = pd.concat(
      [incidents_df, pd.DataFrame([new_record])], ignore_index=True
  )
  safe_save_dataframe(updated_df, INCIDENTS_LOG_PATH)
  load_local_incidents_log.clear()
  return updated_df
