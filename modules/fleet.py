import pandas as pd

def process_fleet_data(vans_df):
    """Cleans and normalizes master_fleet.xlsx columns with proper typed values."""
    if vans_df is None or vans_df.empty:
        return pd.DataFrame()

    df = vans_df.copy()
    bumper_col = next((c for c in df.columns if str(c).strip().lower() in ['bumper #', 'bumper', 'vehiclename']), None)
    st_col = next((c for c in df.columns if str(c).strip().lower() in ['st', 'servicetype']), None)
    status_col = next((c for c in df.columns if str(c).strip().lower() in ['status']), None)
    vin_col = next((c for c in df.columns if str(c).strip().lower() in ['vin']), None)

    def clean_str(val):
        s = str(val).strip()
        if s.endswith('.0'):
            s = s[:-2]
        return s

    df['vehicleName'] = df[bumper_col].apply(clean_str) if bumper_col else 'UNNAMED'
    df['status_clean'] = df[status_col].astype(str).str.strip().str.upper() if status_col else 'UP'
    df['serviceType_clean'] = df[st_col].astype(str).str.strip().str.upper() if st_col else 'M'
    df['vin_clean'] = df[vin_col].astype(str).str.strip() if vin_col else df['vehicleName']
    return df

def process_phone_data(phones_df):
    """Cleans and standardizes master_phones.xlsx data."""
    if phones_df is None or phones_df.empty:
        return pd.DataFrame(columns=['device_clean', 'number_clean', 'status_clean'])

    df = phones_df.copy()
    device_col = next((c for c in df.columns if 'device' in str(c).lower() or 'name' in str(c).lower() or 'phone' in str(c).lower()), df.columns[0])
    num_col = next((c for c in df.columns if 'number' in str(c).lower() or 'phone' in str(c).lower()), df.columns[1] if len(df.columns) > 1 else df.columns[0])
    status_col = next((c for c in df.columns if 'status' in str(c).lower()), None)

    def clean_val(val):
        s = str(val).strip()
        if s.endswith('.0'):
            s = s[:-2]
        return s

    df['device_clean'] = df[device_col].apply(clean_val)
    df['number_clean'] = df[num_col].apply(clean_val)
    df['status_clean'] = df[status_col].astype(str).str.strip().str.upper() if status_col else 'ACTIVE'

    return df

def process_driver_data(drivers_df):
    """Standardizes master_drivers.xlsx dataset preserving numeric score types."""
    if drivers_df is None or drivers_df.empty:
        return pd.DataFrame(columns=["Driver Name", "Transporter ID", "Phone Number", "Status", "Role", "Hire Date", "Preferred Shifts", "Overall Score", "Standing"])

    df = drivers_df.copy()
    cols = [str(c).strip() for c in df.columns]
    df.columns = cols

    name_col = next((c for c in df.columns if 'driver' in c.lower() or 'name' in c.lower() or 'associate' in c.lower()), df.columns[0])
    trans_col = next((c for c in df.columns if 'transporter' in c.lower()), None)
    phone_col = next((c for c in df.columns if 'phone' in c.lower()), None)
    status_col = next((c for c in df.columns if 'status' in c.lower()), None)
    role_col = next((c for c in df.columns if 'role' in c.lower() or 'position' in c.lower()), None)
    score_col = next((c for c in df.columns if 'score' in c.lower() or 'rank' in c.lower()), None)
    standing_col = next((c for c in df.columns if 'standing' in c.lower() or 'tier' in c.lower()), None)

    out = pd.DataFrame()
    out['Driver Name'] = df[name_col].astype(str).str.strip()
    out['Transporter ID'] = df[trans_col].astype(str).str.strip() if trans_col else ''
    out['Phone Number'] = df[phone_col].astype(str).str.strip() if phone_col else ''
    out['Status'] = df[status_col].astype(str).str.strip().str.upper() if status_col else 'ACTIVE'
    out['Role'] = df[role_col].astype(str).str.strip() if role_col else 'Driver Associate'
    out['Hire Date'] = df['Hire Date'].astype(str).str.strip() if 'Hire Date' in df.columns else ''
    out['Preferred Shifts'] = df['Preferred Shifts'].astype(str).str.strip() if 'Preferred Shifts' in df.columns else 'Mon,Tue,Wed,Thu,Fri,Sat,Sun'
    out['Overall Score'] = pd.to_numeric(df[score_col], errors='coerce').fillna(100.0).astype(float) if score_col else 100.0
    out['Standing'] = df[standing_col].astype(str).str.strip() if standing_col else 'Fantastic'

    return out

def find_matching_phone(bumper, phone_map):
    """Auto-pairs van bumper numbers to mobile devices."""
    if not phone_map:
        return '', ''

    b_str = str(bumper).strip()
    if b_str.endswith('.0'):
        b_str = b_str[:-2]
        
    if b_str in phone_map:
        return b_str, phone_map[b_str]
        
    b_no_zero = b_str.lstrip('0')
    if b_no_zero in phone_map:
        return b_no_zero, phone_map[b_no_zero]
        
    digits_only = ''.join(filter(str.isdigit, b_str))
    if digits_only and digits_only in phone_map:
        return digits_only, phone_map[digits_only]
        
    digits_no_zero = digits_only.lstrip('0')
    if digits_no_zero and digits_no_zero in phone_map:
        return digits_no_zero, phone_map[digits_no_zero]

    return '', ''

def sync_live_roster_phones(roster_df, phones_df):
    """Re-syncs live roster Phone ID and Phone Number columns whenever the Master Phone Directory updates."""
    if roster_df is None or roster_df.empty or phones_df is None or phones_df.empty:
        return roster_df

    p_clean = process_phone_data(phones_df)
    active_p = p_clean[~p_clean['status_clean'].isin(['INACTIVE', 'RETIRED', 'DELETED'])] if 'status_clean' in p_clean.columns else p_clean
    phone_map = dict(zip(active_p['device_clean'], active_p['number_clean']))

    updated_roster = roster_df.copy()
    for idx, row in updated_roster.iterrows():
        bumper = str(row.get('Van Bumper', '')).strip()
        if bumper and bumper != 'UNASSIGNED':
            pid, pnum = find_matching_phone(bumper, phone_map)
            updated_roster.at[idx, 'Phone ID'] = pid
            updated_roster.at[idx, 'Phone Number'] = pnum

    return updated_roster