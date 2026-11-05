import os
import io
import datetime
import logging
import tempfile
import pandas as pd
import streamlit as st

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Configuration & Storage Abstraction
STORAGE_MODE = os.getenv("STORAGE_MODE", "LOCAL").upper()
MASTER_FLEET_PATH = os.getenv("MASTER_FLEET_PATH", "master_fleet.xlsx")
MASTER_PHONES_PATH = os.getenv("MASTER_PHONES_PATH", "master_phones.xlsx")
CLOSING_CHECKLIST_PATH = os.getenv("CLOSING_CHECKLIST_PATH", "closing_checklist_log.xlsx")
ACCESS_CODES_PATH = os.getenv("ACCESS_CODES_PATH", "access_codes.xlsx")
MASTER_DRIVERS_PATH = os.getenv("MASTER_DRIVERS_PATH", "master_drivers.xlsx")
WEEKLY_SCHEDULE_PATH = os.getenv("WEEKLY_SCHEDULE_PATH", "weekly_schedule.xlsx")
SCORECARDS_PATH = os.getenv("SCORECARDS_PATH", "master_scorecards.xlsx")
ATTENDANCE_LOG_PATH = os.getenv("ATTENDANCE_LOG_PATH", "attendance_log.xlsx")
INCIDENTS_LOG_PATH = os.getenv("INCIDENTS_LOG_PATH", "master_incidents.xlsx")
HISTORY_DIR = os.getenv("HISTORY_DIR", "history")
LOG_FILE_PATH = os.getenv("DISPATCH_LOG_PATH", "dispatch_audit.log")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# Cloud S3 Configuration
AWS_S3_BUCKET = os.getenv("AWS_S3_BUCKET", "")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")

# User Credentials
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS")
DISPATCH_USER = os.getenv("DISPATCH_USER", "dispatch")
DISPATCH_PASS = os.getenv("DISPATCH_PASS")

USER_CREDENTIALS = {
    ADMIN_USER: {
        "password": ADMIN_PASS if ADMIN_PASS else "jna2026!",
        "role": "Admin",
        "name": "Operations Manager"
    },
    DISPATCH_USER: {
        "password": DISPATCH_PASS if DISPATCH_PASS else "ddk6dispatch",
        "role": "Dispatcher",
        "name": "Dispatch Desk"
    }
}

# Configure Local Dispatch Action Logger
logging.basicConfig(
    filename=LOG_FILE_PATH,
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] (User: %(user)s) - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

def log_dispatch_action(action_msg, username="System"):
    """Logs dispatch operations (driver swaps, van reassignments, EROs) to disk for auditing."""
    logger = logging.getLogger("DispatchAudit")
    logger.info(action_msg, extra={"user": username})

def safe_save_dataframe(df, file_path):
    """Saves a DataFrame to disk using atomic writing."""
    if df is None or df.empty:
        return
    
    dir_name = os.path.dirname(file_path)
    if dir_name and not os.path.exists(dir_name):
        os.makedirs(dir_name, exist_ok=True)
        
    ext = os.path.splitext(file_path)[1].lower()
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext, dir=dir_name if dir_name else ".") as tmp:
        tmp_path = tmp.name

    try:
        if ext in ['.xlsx', '.xls']:
            df.to_excel(tmp_path, index=False)
        else:
            df.to_csv(tmp_path, index=False)
        os.replace(tmp_path, file_path)
    except Exception as e:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise e

def authenticate_user(username, password):
    u_clean = str(username).strip()
    p_clean = str(password).strip()
    
    if u_clean in USER_CREDENTIALS:
        expected_pass = USER_CREDENTIALS[u_clean]["password"]
        if expected_pass and p_clean == str(expected_pass).strip():
            log_dispatch_action(f"User '{u_clean}' signed into Command Center workspace.", username=u_clean)
            return True, USER_CREDENTIALS[u_clean]["role"], USER_CREDENTIALS[u_clean]["name"]
    return False, None, None

def ensure_history_dir():
    if STORAGE_MODE == "LOCAL" and not os.path.exists(HISTORY_DIR):
        os.makedirs(HISTORY_DIR, exist_ok=True)

def cleanup_old_snapshots(days_to_keep=30):
    if STORAGE_MODE == "LOCAL" and os.path.exists(HISTORY_DIR):
        now = datetime.datetime.now()
        cutoff = datetime.timedelta(days=days_to_keep)
        for filename in os.listdir(HISTORY_DIR):
            if (filename.startswith("roster_") or filename.startswith("closing_checklist_")) and filename.endswith(".xlsx"):
                filepath = os.path.join(HISTORY_DIR, filename)
                file_mtime = datetime.datetime.fromtimestamp(os.path.getmtime(filepath))
                if now - file_mtime > cutoff:
                    try:
                        os.remove(filepath)
                    except Exception as e:
                        print(f"Error purging old snapshot {filename}: {e}")

def save_snapshot_file(roster_df, filename):
    if roster_df is None or roster_df.empty:
        return
        
    if STORAGE_MODE == "CLOUD" and AWS_S3_BUCKET:
        try:
            import boto3
            s3_client = boto3.client(
                's3',
                aws_access_key_id=AWS_ACCESS_KEY_ID,
                aws_secret_access_key=AWS_SECRET_ACCESS_KEY
            )
            buffer = io.BytesIO()
            roster_df.to_excel(buffer, index=False)
            buffer.seek(0)
            s3_key = f"{HISTORY_DIR}/{filename}"
            s3_client.upload_fileobj(buffer, AWS_S3_BUCKET, s3_key)
            return
        except Exception as e:
            print(f"Error saving snapshot to S3: {e}. Falling back to local disk storage.")

    ensure_history_dir()
    filepath = os.path.join(HISTORY_DIR, filename)
    safe_save_dataframe(roster_df, filepath)

def save_daily_closing_checklist(closing_df):
    if closing_df is None or closing_df.empty:
        return

    safe_save_dataframe(closing_df, CLOSING_CHECKLIST_PATH)
    date_stamp = pd.Timestamp.now().strftime('%Y-%m-%d')
    snapshot_fname = f"closing_checklist_{date_stamp}.xlsx"
    save_snapshot_file(closing_df, snapshot_fname)

def list_snapshot_files():
    if STORAGE_MODE == "CLOUD" and AWS_S3_BUCKET:
        try:
            import boto3
            s3_client = boto3.client(
                's3',
                aws_access_key_id=AWS_ACCESS_KEY_ID,
                aws_secret_access_key=AWS_SECRET_ACCESS_KEY
            )
            response = s3_client.list_objects_v2(Bucket=AWS_S3_BUCKET, Prefix=f"{HISTORY_DIR}/")
            files = []
            if 'Contents' in response:
                for obj in response['Contents']:
                    fname = os.path.basename(obj['Key'])
                    if fname.startswith("roster_") and fname.endswith(".xlsx"):
                        files.append(fname)
            return sorted(files, reverse=True)
        except Exception as e:
            print(f"Error reading S3 snapshots: {e}")

    if os.path.exists(HISTORY_DIR):
        return sorted(
            [f for f in os.listdir(HISTORY_DIR) if f.startswith("roster_") and f.endswith(".xlsx")],
            reverse=True
        )
    return []

def load_snapshot_file(filename):
    if STORAGE_MODE == "CLOUD" and AWS_S3_BUCKET:
        try:
            import boto3
            s3_client = boto3.client(
                's3',
                aws_access_key_id=AWS_ACCESS_KEY_ID,
                aws_secret_access_key=AWS_SECRET_ACCESS_KEY
            )
            s3_key = f"{HISTORY_DIR}/{filename}"
            obj = s3_client.get_object(Bucket=AWS_S3_BUCKET, Key=s3_key)
            return pd.read_excel(io.BytesIO(obj['Body'].read())).astype(str)
        except Exception as e:
            print(f"Error reading S3 snapshot file: {e}")

    filepath = os.path.join(HISTORY_DIR, filename)
    return pd.read_excel(filepath).astype(str)

def process_access_data(access_df):
    if access_df is None or access_df.empty:
        return pd.DataFrame(columns=["Location", "Code", "Special Instructions"])

    df = access_df.copy()
    loc_col = next((c for c in df.columns if 'location' in str(c).lower() or 'address' in str(c).lower() or 'building' in str(c).lower()), df.columns[0])
    code_col = next((c for c in df.columns if 'code' in str(c).lower() or 'gate' in str(c).lower() or 'pin' in str(c).lower()), df.columns[1] if len(df.columns) > 1 else df.columns[0])
    notes_col = next((c for c in df.columns if 'instruction' in str(c).lower() or 'note' in str(c).lower() or 'remark' in str(c).lower()), df.columns[2] if len(df.columns) > 2 else df.columns[0])

    out_df = pd.DataFrame()
    out_df['Location'] = df[loc_col].astype(str).str.strip()
    out_df['Code'] = df[code_col].astype(str).str.strip()
    out_df['Special Instructions'] = df[notes_col].astype(str).str.strip()
    return out_df

# Centralized Dataset File Loaders (Returns .copy() to prevent Streamlit cache object mutation)
@st.cache_data(ttl=60, show_spinner=False)
def load_local_fleet():
    if os.path.exists(MASTER_FLEET_PATH):
        try:
            from modules.fleet import process_fleet_data
            vans_raw = pd.read_excel(MASTER_FLEET_PATH) if MASTER_FLEET_PATH.endswith(('.xlsx', '.xls')) else pd.read_csv(MASTER_FLEET_PATH)
            return process_fleet_data(vans_raw).copy()
        except Exception: pass
    return None

@st.cache_data(ttl=60, show_spinner=False)
def load_local_phones():
    if os.path.exists(MASTER_PHONES_PATH):
        try:
            from modules.fleet import process_phone_data
            phones_raw = pd.read_excel(MASTER_PHONES_PATH) if MASTER_PHONES_PATH.endswith(('.xlsx', '.xls')) else pd.read_csv(MASTER_PHONES_PATH)
            return process_phone_data(phones_raw).copy()
        except Exception: pass
    return None

@st.cache_data(ttl=60, show_spinner=False)
def load_local_drivers():
    if os.path.exists(MASTER_DRIVERS_PATH):
        try:
            from modules.fleet import process_driver_data
            drivers_raw = pd.read_excel(MASTER_DRIVERS_PATH) if MASTER_DRIVERS_PATH.endswith(('.xlsx', '.xls')) else pd.read_csv(MASTER_DRIVERS_PATH)
            return process_driver_data(drivers_raw).copy()
        except Exception: pass
    return pd.DataFrame(columns=["Driver Name", "Transporter ID", "Phone Number", "Status", "Role", "Hire Date", "Preferred Shifts", "Overall Score", "Standing"])

@st.cache_data(ttl=60, show_spinner=False)
def load_local_schedule():
    if os.path.exists(WEEKLY_SCHEDULE_PATH):
        try:
            df = pd.read_excel(WEEKLY_SCHEDULE_PATH) if WEEKLY_SCHEDULE_PATH.endswith(('.xlsx', '.xls')) else pd.read_csv(WEEKLY_SCHEDULE_PATH)
            if 'Driver Name' in df.columns:
                df['first_name'] = df['Driver Name'].astype(str).str.strip().str.split().str[0].str.upper()
                df = df.sort_values(by=['first_name', 'Driver Name'], ascending=[True, True]).drop(columns=['first_name']).reset_index(drop=True)
            return df.copy()
        except Exception: pass
    return pd.DataFrame(columns=["Driver Name", "Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"])

@st.cache_data(ttl=60, show_spinner=False)
def load_local_scorecards():
    if os.path.exists(SCORECARDS_PATH):
        try:
            df = pd.read_excel(SCORECARDS_PATH) if SCORECARDS_PATH.endswith(('.xlsx', '.xls')) else pd.read_csv(SCORECARDS_PATH)
            return df.copy()
        except Exception: pass
    return pd.DataFrame()

@st.cache_data(ttl=60, show_spinner=False)
def load_local_access_codes():
    if os.path.exists(ACCESS_CODES_PATH):
        try:
            raw_codes = pd.read_excel(ACCESS_CODES_PATH) if ACCESS_CODES_PATH.endswith(('.xlsx', '.xls')) else pd.read_csv(ACCESS_CODES_PATH)
            return process_access_data(raw_codes).copy()
        except Exception: pass
    return pd.DataFrame(columns=["Location", "Code", "Special Instructions"])

@st.cache_data(ttl=10, show_spinner=False)
def load_local_attendance_log():
    """Loads recorded driver attendance infractions from disk."""
    if os.path.exists(ATTENDANCE_LOG_PATH):
        try:
            df = pd.read_excel(ATTENDANCE_LOG_PATH) if ATTENDANCE_LOG_PATH.endswith(('.xlsx', '.xls')) else pd.read_csv(ATTENDANCE_LOG_PATH)
            return df.copy()
        except Exception: pass
    return pd.DataFrame(columns=["Date", "Driver Name", "Infraction Type", "Logged By", "Notes"])

@st.cache_data(ttl=10, show_spinner=False)
def load_local_incidents_log():
    """Loads recorded safety, driving, and behavior incident logs from disk."""
    if os.path.exists(INCIDENTS_LOG_PATH):
        try:
            df = pd.read_excel(INCIDENTS_LOG_PATH) if INCIDENTS_LOG_PATH.endswith(('.xlsx', '.xls')) else pd.read_csv(INCIDENTS_LOG_PATH)
            return df.copy()
        except Exception: pass
    return pd.DataFrame(columns=["Date", "Driver Name", "Severity", "Category", "Infraction / Detail", "Van Bumper", "Logged By", "Notes"])

def save_driver_incident(driver_name, severity, category, infraction_detail, van_bumper, logged_by, notes):
    """Appends a new driving or behavior incident record atomically to disk."""
    incidents_df = load_local_incidents_log()
    new_record = {
        "Date": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
        "Driver Name": str(driver_name).strip(),
        "Severity": str(severity).strip(),
        "Category": str(category).strip(),
        "Infraction / Detail": str(infraction_detail).strip(),
        "Van Bumper": str(van_bumper).strip(),
        "Logged By": str(logged_by).strip(),
        "Notes": str(notes).strip()
    }
    updated_df = pd.concat([incidents_df, pd.DataFrame([new_record])], ignore_index=True)
    safe_save_dataframe(updated_df, INCIDENTS_LOG_PATH)
    return updated_df