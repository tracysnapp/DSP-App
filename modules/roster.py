import pandas as pd
from modules.fleet import process_fleet_data, process_phone_data, find_matching_phone

def condense_service_type(raw_type):
    s = str(raw_type).strip()
    s_upper = s.upper()
    if 'ON-ROAD EXPERIENCE' in s_upper or 'ON ROAD EXPERIENCE' in s_upper:
        return 'ORE'
    elif 'EXTRA LARGE' in s_upper:
        return 'XL'
    elif 'LARGE' in s_upper:
        return 'L'
    elif 'NURSERY' in s_upper:
        level = ''.join(filter(str.isdigit, s_upper))
        return f"Nursery {level}" if level else "Nursery"
    elif 'MEDIUM' in s_upper or 'STANDARD' in s_upper:
        return 'M'
    return s

def get_prioritized_reserve_drivers(roster_df, schedule_df, master_drivers_df, day_of_week='Mon'):
    prioritized_options = []
    seen = set()

    if roster_df is not None and not roster_df.empty and 'Helper' in roster_df.columns:
        helpers = roster_df['Helper'].dropna().unique()
        for h in helpers:
            h_clean = str(h).strip()
            if h_clean and h_clean.lower() not in ['nan', 'none', 'null', '']:
                label = f"⭐ {h_clean} (Assigned Helper)"
                prioritized_options.append((label, h_clean))
                seen.add(h_clean.lower())

    if schedule_df is not None and not schedule_df.empty and day_of_week in schedule_df.columns:
        standbys = schedule_df[schedule_df[day_of_week].astype(str).str.upper().isin(['ON-CALL', 'ON CALL', 'STANDBY'])]['Driver Name'].unique()
        for s in standbys:
            s_clean = str(s).strip()
            if s_clean and s_clean.lower() not in seen:
                label = f"🕒 {s_clean} (Scheduled On-Call)"
                prioritized_options.append((label, s_clean))
                seen.add(s_clean.lower())

    if master_drivers_df is not None and not master_drivers_df.empty:
        active_drivers = master_drivers_df[master_drivers_df['Status'].astype(str).str.upper() == 'ACTIVE']['Driver Name'].unique()
        for d in active_drivers:
            d_clean = str(d).strip()
            if d_clean and d_clean.lower() not in seen:
                label = f"👤 {d_clean} (Active Driver)"
                prioritized_options.append((label, d_clean))
                seen.add(d_clean.lower())

    return prioritized_options

def run_auto_assignment(routes_df, vans_df, phones_df=None):
    vans_df = process_fleet_data(vans_df)
    routes = routes_df.copy()
    
    clean_cols = [str(c).strip() for c in routes.columns]
    routes.columns = clean_cols
    
    route_code_col = next((c for c in routes.columns if 'route' in c.lower() and 'code' in c.lower()), routes.columns[0])
    service_type_col = next((c for c in routes.columns if 'service' in c.lower() and 'type' in c.lower()), routes.columns[5] if len(routes.columns) > 5 else routes.columns[0])
    driver_name_col = next((c for c in routes.columns if 'driver' in c.lower() and 'name' in c.lower()), routes.columns[3] if len(routes.columns) > 3 else routes.columns[0])
    dep_time_col = next((c for c in routes.columns if 'departure' in c.lower() and 'time' in c.lower()), routes.columns[14] if len(routes.columns) > 14 else routes.columns[0])

    def get_van_priority_score(row):
        st_raw = str(row[service_type_col]).strip().upper() if pd.notna(row[service_type_col]) else ''
        if 'ON-ROAD EXPERIENCE' in st_raw or 'ON ROAD EXPERIENCE' in st_raw or 'ORE' in st_raw:
            return 99
        elif 'EXTRA LARGE' in st_raw or 'XL' in st_raw:
            return 1
        elif 'LARGE' in st_raw or 'L' in st_raw:
            return 2
        return 3

    routes['van_priority'] = routes.apply(get_van_priority_score, axis=1)
    routes = routes.sort_values(by=['van_priority', route_code_col], ascending=[True, True]).reset_index(drop=True)

    status_col_name = next((c for c in vans_df.columns if str(c).strip().lower() in ['status', 'status_clean']), 'Status')
    active_mask = vans_df[status_col_name].astype(str).str.strip().str.upper().isin(['UP', 'ACTIVE', 'OPERATIONAL', 'WORKABLE', 'AVAILABLE']) if status_col_name in vans_df.columns else [True] * len(vans_df)
    available_vans = vans_df[active_mask].copy()
    
    # SORT FLEET BY PRIORITY_RANK IF PRESENT
    if 'priority_rank' in available_vans.columns:
        available_vans = available_vans.sort_values(by='priority_rank', ascending=True).reset_index(drop=True)
    
    phone_map = {}
    if phones_df is not None and not phones_df.empty:
        p_clean = process_phone_data(phones_df)
        active_p = p_clean[~p_clean['status_clean'].isin(['INACTIVE', 'RETIRED', 'DELETED'])] if 'status_clean' in p_clean.columns else p_clean
        phone_map = dict(zip(active_p['device_clean'], active_p['number_clean']))

    FALLBACK_HIERARCHY = {
        'EXTRA LARGE': ['XL', 'L', 'M'],
        'LARGE': ['L', 'XL', 'M'],
        'MEDIUM': ['M', 'L', 'XL'],
        'ON-ROAD EXPERIENCE': ['M', 'L', 'XL'],
        'ON ROAD EXPERIENCE': ['M', 'L', 'XL'],
    }

    def get_priority_list(req_type_clean):
        for key in FALLBACK_HIERARCHY:
            if key in req_type_clean:
                return FALLBACK_HIERARCHY[key]
        return ['M', 'L', 'XL']

    output_rows = []

    for idx, (_, route) in enumerate(routes.iterrows()):
        route_code = str(route[route_code_col]).strip() if pd.notna(route[route_code_col]) else ''
        raw_req_type = str(route[service_type_col]).strip() if pd.notna(route[service_type_col]) else ''
        driver_name = str(route[driver_name_col]).strip() if pd.notna(route[driver_name_col]) else ''
        dep_time_raw = str(route[dep_time_col]).strip() if pd.notna(route[dep_time_col]) else ''
        
        req_type_clean = raw_req_type.upper()
        short_req_type = condense_service_type(raw_req_type)
        priority_list = get_priority_list(req_type_clean)
        
        matched_van = None
        matched_code_used = None
        
        st_bracket_col = next((c for c in available_vans.columns if str(c).strip().lower() in ['size bracket', 'st', 'servicetype']), 'Size Bracket')
        vin_col = next((c for c in available_vans.columns if str(c).strip().lower() in ['vin', 'vin_clean']), 'VIN')

        for code in priority_list:
            matches = available_vans[available_vans[st_bracket_col].astype(str).str.strip().str.upper() == code]
            if not matches.empty:
                matched_van = matches.iloc[0]
                matched_code_used = code
                break
        
        if matched_van is not None:
            bumper_raw = matched_van.get('Van Bumper', matched_van.get('vehicleName', 'UNNAMED'))
            bumper_no = str(bumper_raw).strip()
            if bumper_no.endswith('.0'):
                bumper_no = bumper_no[:-2]
            selected_st = str(matched_van.get(st_bracket_col, matched_code_used)).strip()
            chosen_vin = str(matched_van.get(vin_col, '')).strip()
            
            is_priority_forced = matched_van.get('priority_rank', 10) == 1
            if is_priority_forced:
                remarks = 'PRIORITY VAN LOCKED'
            elif matched_code_used != priority_list[0]:
                remarks = f'FALLBACK ({short_req_type} -> {selected_st})'
            else:
                remarks = ''

            available_vans = available_vans[available_vans[vin_col] != chosen_vin]
        else:
            bumper_no = 'UNASSIGNED'
            selected_st = 'N/A'
            remarks = f'NO VANS AVAILABLE ({short_req_type})'

        assigned_phone, phone_number = find_matching_phone(bumper_no, phone_map) if bumper_no != 'UNASSIGNED' else ('', '')

        try:
            dep_dt = pd.to_datetime(dep_time_raw, format='mixed', errors='coerce')
            if pd.isna(dep_dt):
                dep_dt = pd.to_datetime(f"{pd.Timestamp.now().strftime('%Y-%m-%d')} {dep_time_raw}")
                
            wave_dt = dep_dt - pd.Timedelta(minutes=20)
            show_dt = wave_dt - pd.Timedelta(minutes=30)
            end_dt = show_dt + pd.Timedelta(hours=10)

            dep_str = dep_dt.strftime('%I:%M %p').lstrip('0')
            wave_str = wave_dt.strftime('%I:%M %p').lstrip('0')
            show_str = show_dt.strftime('%I:%M %p').lstrip('0')
            end_str = end_dt.strftime('%I:%M %p').lstrip('0')
        except Exception:
            dep_str = dep_time_raw
            wave_str = 'N/A'
            show_str = 'N/A'
            end_str = 'N/A'

        pad_assignment = 'Pad A' if idx % 2 == 0 else 'Pad B'

        row = {
            'Route': str(route_code),
            'Req Size': str(short_req_type),
            'Van Bumper': str(bumper_no),
            'Sel Size': str(selected_st),
            'Driver': str(driver_name),
            'Helper': '',
            'Wave': str(wave_str),
            'Pad': str(pad_assignment),
            'Departure': str(dep_str),
            'Phone ID': str(assigned_phone),
            'Phone Number': str(phone_number),
            'Show Time': str(show_str),
            'Shift End': str(end_str),
            'Remarks': str(remarks)
        }
        output_rows.append(row)

    return pd.DataFrame(output_rows).astype(str)

def calculate_ops_metrics(roster_df, fleet_df):
    if roster_df is None or roster_df.empty:
        return {}

    total_routes = len(roster_df)
    status_col_name = next((c for c in fleet_df.columns if str(c).strip().lower() in ['status', 'status_clean']), 'Status') if fleet_df is not None else 'Status'
    active_fleet = len(fleet_df[fleet_df[status_col_name].astype(str).str.strip().str.upper().isin(['UP', 'ACTIVE', 'OPERATIONAL', 'WORKABLE', 'AVAILABLE'])]) if fleet_df is not None and status_col_name in fleet_df.columns else 0
    grounded_fleet = len(fleet_df[fleet_df[status_col_name].astype(str).str.strip().str.upper() == 'DOWN']) if fleet_df is not None and status_col_name in fleet_df.columns else 0

    fallback_count = len(roster_df[roster_df['Remarks'].str.contains('FALLBACK', case=False, na=False)])
    unassigned_count = len(roster_df[roster_df['Van Bumper'] == 'UNASSIGNED'])
    sweeper_count = len(roster_df[roster_df['Route'].str.startswith('S-', na=False) | roster_df['Route'].str.contains('SWEEPER', case=False, na=False)])

    size_counts = roster_df['Req Size'].value_counts().to_dict()

    return {
        "total_routes": total_routes,
        "active_fleet": active_fleet,
        "grounded_fleet": grounded_fleet,
        "fallback_count": fallback_count,
        "unassigned_count": unassigned_count,
        "sweeper_count": sweeper_count,
        "size_counts": size_counts
    }

def update_closing_checklist_assignments(roster_df, session_state):
    if roster_df is None or roster_df.empty:
        return

    new_assignments = []
    for idx, row in roster_df.iterrows():
        driver_val = row.get('Driver', '')
        helper_val = row.get('Helper', '')
        van_num = str(row.get('Van Bumper', '')).strip()

        if pd.notna(driver_val) and str(driver_val).strip() and str(driver_val).strip().lower() not in ['nan', 'none', 'null']:
            new_assignments.append({"Van": van_num, "Driver Name": str(driver_val).strip()})

        if pd.notna(helper_val) and str(helper_val).strip() and str(helper_val).strip().lower() not in ['nan', 'none', 'null']:
            new_assignments.append({"Van": van_num, "Driver Name": f"{str(helper_val).strip()} (Helper)"})

    new_assignments_df = pd.DataFrame(new_assignments)
    closing_df = session_state.get('closing_df', None)

    # Migrate older 'Van Number' column if present
    if closing_df is not None and 'Van Number' in closing_df.columns:
        closing_df = closing_df.rename(columns={'Van Number': 'Van'})

    if closing_df is None or closing_df.empty or "Van" not in closing_df.columns:
        merged_closing = new_assignments_df.copy()
    else:
        merged_closing = pd.merge(new_assignments_df, closing_df, on=["Van", "Driver Name"], how="left")

    default_cols = [
        "Driver Name", "Van", "Clock out time", "DVIC Complete", 
        "Damage?", "Cleaned?", "Keys Returned", "Phone Returned", 
        "Portable Charger", "Fuel Card Returned", "Fuel Level", 
        "Packages/Returns Handled", "Remarks", "DA Signature"
    ]

    for col in default_cols:
        merged_closing[col] = merged_closing[col].fillna("") if col in merged_closing.columns else ""

    merged_closing['van_num_sort'] = pd.to_numeric(merged_closing['Van'].astype(str).str.extract(r'(\d+)', expand=False), errors='coerce').fillna(999999)
    merged_closing['is_helper'] = merged_closing['Driver Name'].str.contains(r'\(Helper\)', case=False, na=False)
    merged_closing = merged_closing.sort_values(by=['van_num_sort', 'Van', 'is_helper', 'Driver Name'], ascending=[True, True, True, True])
    session_state['closing_df'] = merged_closing[default_cols].drop(columns=['van_num_sort', 'is_helper'], errors='ignore').reset_index(drop=True)

def get_sorted_roster(df):
    if df is None or df.empty:
        return df
    sorted_df = df.copy()
    sorted_df['wave_dt'] = pd.to_datetime(sorted_df['Wave'], format='mixed', errors='coerce')
    sorted_df['first_name'] = sorted_df['Driver'].astype(str).str.strip().str.split().str[0].str.upper()
    return sorted_df.sort_values(by=['wave_dt', 'first_name'], ascending=[True, True], na_position='last').drop(columns=['wave_dt', 'first_name']).reset_index(drop=True)

def generate_printable_html(df):
    today_str = pd.Timestamp.now().strftime("%A, %B %d, %Y")
    headers = "".join([f"<th class='remarks-col'>{col}</th>" if str(col).strip().upper() == "REMARKS" else f"<th class='compact-col'>{col}</th>" for col in df.columns])
    
    rows_html = ""
    last_wave = None
    for idx, row in df.iterrows():
        current_wave = str(row.get('Wave', '')).strip()
        bg_style = "background-color: #f9f9f9;" if idx % 2 == 0 else ""
        divider_class = " wave-divider page-break" if idx > 0 and current_wave != last_wave else ""
        cells = "".join([f"<td class='remarks-col'>{row[col]}</td>" if str(col).strip().upper() == "REMARKS" else f"<td class='compact-col'>{row[col]}</td>" for col in df.columns])
        rows_html += f"<tr class='{divider_class}' style='{bg_style}'>{cells}</tr>"
        last_wave = current_wave
        
    return f"""<!DOCTYPE html><html><head><style>
        body {{ font-family: Arial, sans-serif; margin: 5px; color: #111; }}
        .header-title {{ text-align: center; margin-bottom: 4px; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 9.5px; table-layout: auto; }}
        tr.wave-divider td {{ border-top: 3px solid #000 !important; }}
        th {{ background-color: #232f3e; color: white; padding: 4px; border: 1px solid #000; text-align: left; font-size: 8.5px; }}
        td {{ padding: 2.5px 4px; border: 1px solid #999; font-size: 8.5px; }}
        .compact-col {{ width: 1%; white-space: nowrap; }}
        .remarks-col {{ width: auto; white-space: normal; }}
        @media print {{ button {{ display: none; }} @page {{ margin: 0.2in; size: landscape; }} }}
    </style></head><body>
        <div class="header-title"><h2>DAILY DISPATCH & LAUNCH ROSTER</h2><p><strong>Date:</strong> {today_str} | <strong>Total Routes:</strong> {len(df)}</p></div>
        <button onclick="window.print()" style="margin-bottom: 8px; padding: 6px 12px; background-color: #0073bb; color: white; border: none; border-radius: 4px; font-weight: bold;">🖨️ Print Roster / Save to PDF</button>
        <table><thead><tr>{headers}</tr></thead><tbody>{rows_html}</tbody></table>
    </body></html>"""

def generate_printable_closing_html(df):
    today_str = pd.Timestamp.now().strftime("%A, %B %d, %Y")
    headers = "".join([f"<th class='signature-col'>{col}</th>" if str(col).strip().upper() in ["DA SIGNATURE", "SIGNATURE"] else f"<th class='compact-col'>{col}</th>" for col in df.columns])
    
    rows_html = ""
    for idx, row in df.iterrows():
        bg_style = "background-color: #f9f9f9;" if idx % 2 == 0 else ""
        cells = "".join([f"<td class='signature-col'>{(row[col] if col in ['Driver Name', 'Van'] else '')}</td>" if str(col).strip().upper() in ["DA SIGNATURE", "SIGNATURE"] else f"<td class='compact-col'>{(row[col] if col in ['Driver Name', 'Van'] else '')}</td>" for col in df.columns])
        rows_html += f"<tr style='{bg_style}'>{cells}</tr>"
        
    return f"""<!DOCTYPE html><html><head><style>
        body {{ font-family: Arial, sans-serif; margin: 5px; color: #111; }}
        .header-title {{ text-align: center; margin-bottom: 4px; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 8.5px; table-layout: auto; }}
        th {{ background-color: #131921; color: white; padding: 4px 3px; border: 1px solid #000; text-align: center; font-size: 8px; }}
        td {{ padding: 2px 3px; border: 1px solid #777; height: 15px; font-size: 8px; }}
        .compact-col {{ width: 1%; white-space: nowrap; }}
        .signature-col {{ width: auto; white-space: normal; }}
        @media print {{ button {{ display: none; }} @page {{ margin: 0.2in; size: landscape; }} }}
    </style></head><body>
        <div class="header-title"><h2>END OF DAY DRIVER CLOSING & DEBRIEF CHECKLIST</h2><p><strong>Date:</strong> {today_str} | <strong>Total Drivers/Vans:</strong> {len(df)}</p></div>
        <button onclick="window.print()" style="margin-bottom: 8px; padding: 6px 12px; background-color: #0073bb; color: white; border: none; border-radius: 4px; font-weight: bold;">🖨️ Print Closing Checklist / Save to PDF</button>
        <table><thead><tr>{headers}</tr></thead><tbody>{rows_html}</tbody></table>
    </body></html>"""
