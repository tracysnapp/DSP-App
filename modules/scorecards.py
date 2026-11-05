import os
import re
import pandas as pd
from difflib import SequenceMatcher
from engine import SCORECARDS_PATH, safe_save_dataframe, load_local_incidents_log

def normalize_name(name_str):
    """
    Standardizes names by lowercasing, stripping punctuation, 
    and extracting first and last tokens (ignoring middle names).
    """
    if pd.isna(name_str) or not str(name_str).strip():
        return ""
    
    s = str(name_str).strip().lower()
    if ',' in s:
        parts = [p.strip() for p in s.split(',', 1)]
        if len(parts) == 2:
            s = f"{parts[1]} {parts[0]}"
            
    s = re.sub(r'[^a-z\s]', '', s)
    tokens = s.split()
    
    if not tokens:
        return ""
    if len(tokens) == 1:
        return tokens[0]
        
    return f"{tokens[0]} {tokens[-1]}"

def find_best_driver_match(target_key, available_keys, threshold=0.80):
    """Matches associate names across Cortex exports using string similarity and token normalization."""
    if not target_key or not available_keys:
        return None
    
    target_clean = str(target_key).strip().lower()
    target_norm = normalize_name(target_key)
    
    # 1. Exact string match
    for key in available_keys:
        if target_clean == str(key).strip().lower():
            return key

    # 2. Token Normalization Match (First + Last name)
    for key in available_keys:
        if target_norm and target_norm == normalize_name(key):
            return key

    # 3. Fuzzy match fallback
    best_match = None
    best_score = 0.0
    
    for key in available_keys:
        score = SequenceMatcher(None, target_clean, str(key).strip().lower()).ratio()
        if score > best_score and score >= threshold:
            best_score = score
            best_match = key
            
    return best_match

def get_driver_historical_trend(master_scorecards_df, driver_name):
    """
    Extracts chronological scorecard performance, DQI score trend, 
    and key metrics for a specific Driver Associate from master_scorecards.xlsx,
    incorporating driving/safety incidents.
    """
    if master_scorecards_df is None or master_scorecards_df.empty or 'Driver Name' not in master_scorecards_df.columns:
        return pd.DataFrame(), {}, pd.DataFrame()

    df = master_scorecards_df.copy()

    all_drivers = list(df['Driver Name'].dropna().unique())
    matched_name = find_best_driver_match(driver_name, all_drivers, threshold=0.80)
    
    if not matched_name:
        return pd.DataFrame(), {}, pd.DataFrame()

    driver_df = df[df['Driver Name'] == matched_name].copy()

    score_col = 'Unified_Composite_Score' if 'Unified_Composite_Score' in driver_df.columns else 'Overall Score'

    driver_df[score_col] = pd.to_numeric(driver_df[score_col].astype(str).str.replace('%', ''), errors='coerce').fillna(0.0)
    
    if 'Week' in driver_df.columns:
        driver_df = driver_df.sort_values(by='Week', ascending=True).reset_index(drop=True)

    tot_pkgs = pd.to_numeric(driver_df['Packages Delivered'], errors='coerce').sum() if 'Packages Delivered' in driver_df.columns else 0
    avg_dqi = driver_df[score_col].mean() if not driver_df.empty else 0.0
    max_dqi = driver_df[score_col].max() if not driver_df.empty else 0.0
    min_dqi = driver_df[score_col].min() if not driver_df.empty else 0.0
    
    recent_score = driver_df[score_col].iloc[-1] if not driver_df.empty else 0.0
    prev_score = driver_df[score_col].iloc[-2] if len(driver_df) > 1 else recent_score
    trend_delta = round(recent_score - prev_score, 2)

    # Incident History Extraction
    incidents_df = load_local_incidents_log()
    driver_incidents_df = pd.DataFrame()
    incident_count = 0
    if incidents_df is not None and not incidents_df.empty and 'Driver Name' in incidents_df.columns:
        inc_match_keys = list(incidents_df['Driver Name'].dropna().unique())
        matched_inc_name = find_best_driver_match(matched_name, inc_match_keys, threshold=0.80)
        if matched_inc_name:
            driver_incidents_df = incidents_df[incidents_df['Driver Name'] == matched_inc_name].sort_values(by='Date', ascending=False).reset_index(drop=True)
            incident_count = len(driver_incidents_df)

    summary = {
        "matched_name": matched_name,
        "weeks_tracked": len(driver_df),
        "avg_dqi": round(avg_dqi, 2),
        "max_dqi": round(max_dqi, 2),
        "min_dqi": round(min_dqi, 2),
        "recent_score": round(recent_score, 2),
        "trend_delta": trend_delta,
        "lifetime_packages": int(tot_pkgs) if pd.notna(tot_pkgs) else 0,
        "incident_count": incident_count
    }

    return driver_df, summary, driver_incidents_df

def calculate_unified_scorecard(overview_file, cdf_file=None, concessions_file=None, rts_file=None, dvic_file=None):
    """
    Enhanced DQI Engine:
    Incorporates Volume Exposure Load Normalization to prevent high-volume drivers from 
    being unfairly penalized relative to low-volume nursery routes.
    """
    if not overview_file:
        raise ValueError("Primary Overview Scorecard file is mandatory.")

    def load_df(file_item):
        if file_item is None:
            return None
        if isinstance(file_item, str):
            return pd.read_csv(file_item) if file_item.endswith('.csv') else pd.read_excel(file_item)
        else:
            try:
                return pd.read_csv(file_item)
            except Exception:
                file_item.seek(0)
                return pd.read_excel(file_item)

    # 1. Primary Overview Scorecard
    overview_df = load_df(overview_file)
    overview_df.columns = [str(c).strip() for c in overview_df.columns]

    week_col = next((c for c in overview_df.columns if 'week' in c.lower()), overview_df.columns[0])
    da_col = next((c for c in overview_df.columns if 'associate' in c.lower() or 'driver' in c.lower() or 'name' in c.lower()), overview_df.columns[1])
    transporter_col = next((c for c in overview_df.columns if 'transporter' in c.lower()), None)
    score_col = next((c for c in overview_df.columns if 'overall score' in c.lower()), None)
    standing_col = next((c for c in overview_df.columns if 'overall standing' in c.lower() or 'standing' in c.lower()), None)
    fico_col = next((c for c in overview_df.columns if 'fico metric' in c.lower() or 'fico score' in c.lower()), None)
    pkg_col = next((c for c in overview_df.columns if 'packages' in c.lower()), None)
    pod_col = next((c for c in overview_df.columns if 'pod' in c.lower() and 'tier' not in c.lower() and 'score' not in c.lower() and 'weight' not in c.lower()), None)

    summary = pd.DataFrame()
    summary['Week'] = overview_df[week_col].astype(str).str.strip()
    summary['Driver Name'] = overview_df[da_col].astype(str).str.strip().str.replace(r'\s+', ' ', regex=True)
    if transporter_col:
        summary['Transporter ID'] = overview_df[transporter_col].astype(str).str.strip()

    summary['Overall Score'] = pd.to_numeric(overview_df[score_col].astype(str).str.replace('%', ''), errors='coerce').fillna(0.0).astype(float) if score_col else 0.0
    summary['Overall Standing'] = overview_df[standing_col].astype(str).str.strip() if standing_col else 'N/A'
    summary['FICO'] = pd.to_numeric(overview_df[fico_col], errors='coerce').fillna(0.0).astype(float) if fico_col else 0.0
    summary['Packages Delivered'] = pd.to_numeric(overview_df[pkg_col], errors='coerce').fillna(0).astype(int) if pkg_col else 0
    if pod_col:
        summary['POD %'] = overview_df[pod_col].astype(str).str.strip()

    def clean_key(val):
        if pd.isna(val):
            return ""
        return re.sub(r'\s+', ' ', str(val)).strip().lower()

    summary['match_key'] = summary['Driver Name'].apply(clean_key)
    summary['cdf_penalty'] = 0.0
    summary['conc_penalty'] = 0.0
    summary['rts_penalty'] = 0.0
    summary['dvic_penalty'] = 0.0
    
    primary_keys = set(summary['match_key'].unique())

    # 2. Customer Delivery Feedback (CDF) Negative Log
    cdf_df = load_df(cdf_file)
    if cdf_df is not None and not cdf_df.empty:
        cdf_df.columns = [str(c).strip() for c in cdf_df.columns]
        c_name_col = next((c for c in cdf_df.columns if 'associate' in c.lower() or 'driver' in c.lower() or 'name' in c.lower()), cdf_df.columns[0])
        c_impact_col = next((c for c in cdf_df.columns if 'impact' in c.lower()), None)
        cdf_df['raw_key'] = cdf_df[c_name_col].apply(clean_key)

        for raw_k, group in cdf_df.groupby('raw_key'):
            matched_key = find_best_driver_match(raw_k, primary_keys)
            if matched_key:
                p = sum(5.0 if (c_impact_col and str(r[c_impact_col]).strip().upper() == 'YES') else 3.0 for _, r in group.iterrows())
                summary.loc[summary['match_key'] == matched_key, 'cdf_penalty'] += float(p)

    # 3. Delivery Concessions / DNRs
    conc_df = load_df(concessions_file)
    if conc_df is not None and not conc_df.empty:
        conc_df.columns = [str(c).strip() for c in conc_df.columns]
        cn_name_col = next((c for c in conc_df.columns if 'associate' in c.lower() or 'driver' in c.lower() or 'name' in c.lower()), conc_df.columns[0])
        cn_impact_col = next((c for c in conc_df.columns if 'impact' in c.lower()), None)
        conc_df['raw_key'] = conc_df[cn_name_col].apply(clean_key)

        for raw_k, group in conc_df.groupby('raw_key'):
            matched_key = find_best_driver_match(raw_k, primary_keys)
            if matched_key:
                p = sum(6.0 if (cn_impact_col and str(r[cn_impact_col]).strip().upper() == 'YES') else 4.0 for _, r in group.iterrows())
                summary.loc[summary['match_key'] == matched_key, 'conc_penalty'] += float(p)

    # 4. Quality RTS File
    rts_df = load_df(rts_file)
    if rts_df is not None and not rts_df.empty:
        rts_df.columns = [str(c).strip() for c in rts_df.columns]
        r_name_col = next((c for c in rts_df.columns if 'associate' in c.lower() or 'driver' in c.lower() or 'name' in c.lower()), rts_df.columns[0])
        r_code_col = next((c for c in rts_df.columns if 'code' in c.lower()), None)
        r_info_col = next((c for c in rts_df.columns if 'information' in c.lower() or 'additional' in c.lower() or 'contact' in c.lower()), None)

        def get_rts_pts(row):
            code = str(row[r_code_col]).strip() if r_code_col and r_code_col in row else ''
            
            info = ""
            if r_info_col and r_info_col in row and pd.notna(row[r_info_col]):
                info = str(row[r_info_col]).strip()

            if code == 'NO RTS CODE SELECTED':
                return 3.0
            if not info or info.lower() in ['nan', 'none', '']:
                return 0.0
            elif 'no after-hours contact' in info.lower():
                return 1.0
            elif any(term in info.lower() for term in ['no contact attempted', 'no compliant contact', 'text initiated']):
                return 2.0
            return 0.0

        rts_df['pts'] = rts_df.apply(get_rts_pts, axis=1)
        rts_df['raw_key'] = rts_df[r_name_col].apply(clean_key)

        for raw_k, group in rts_df.groupby('raw_key'):
            matched_key = find_best_driver_match(raw_k, primary_keys)
            if matched_key:
                summary.loc[summary['match_key'] == matched_key, 'rts_penalty'] += float(group['pts'].sum())

    # 5. DVIC Pre-Trip Inspection Audit Log
    dvic_df = load_df(dvic_file)
    if dvic_df is not None and not dvic_df.empty:
        dvic_df.columns = [str(c).strip() for c in dvic_df.columns]
        d_name_col = next((c for c in dvic_df.columns if 'transporter_name' in c.lower() or 'driver' in c.lower() or 'name' in c.lower()), dvic_df.columns[0])
        d_dur_col = next((c for c in dvic_df.columns if 'duration' in c.lower() or 'time' in c.lower()), None)

        if d_dur_col:
            dvic_df['raw_key'] = dvic_df[d_name_col].apply(clean_key)
            dvic_df['is_rushed'] = pd.to_numeric(dvic_df[d_dur_col], errors='coerce').fillna(999) < 90

            for raw_k, group in dvic_df.groupby('raw_key'):
                matched_key = find_best_driver_match(raw_k, primary_keys)
                if matched_key:
                    rushed_count = group['is_rushed'].sum()
                    summary.loc[summary['match_key'] == matched_key, 'dvic_penalty'] += float(rushed_count * 5.0)

    # VOLUME EXPOSURE LOAD NORMALIZATION
    summary['Total_Raw_Penalty'] = summary['cdf_penalty'] + summary['conc_penalty'] + summary['rts_penalty'] + summary['dvic_penalty']
    
    mean_team_pkgs = summary['Packages Delivered'].mean()
    if mean_team_pkgs <= 0:
        mean_team_pkgs = 1.0

    summary['Volume_Exposure_Factor'] = (mean_team_pkgs / summary['Packages Delivered'].replace(0, mean_team_pkgs)).clip(lower=0.5, upper=1.25)
    summary['Normalized_Penalty'] = summary['Total_Raw_Penalty'] * summary['Volume_Exposure_Factor']

    summary['Granular_Quality_Score'] = (100.0 - summary['Normalized_Penalty']).clip(lower=0.0, upper=100.0)
    summary['Unified_Composite_Score'] = (0.60 * summary['Overall Score']) + (0.40 * summary['Granular_Quality_Score'])
    summary['Unified_Composite_Score'] = summary['Unified_Composite_Score'].round(2)

    return summary.drop(columns=['match_key', 'cdf_penalty', 'conc_penalty', 'rts_penalty', 'dvic_penalty', 'Total_Raw_Penalty', 'Volume_Exposure_Factor', 'Normalized_Penalty'])

def append_to_master_scorecards_ledger(new_scorecard_df):
    """
    Appends the newly calculated weekly scorecard atomically to master_scorecards.xlsx.
    Deduplicates on (Week, Driver Name) so re-uploading updates existing records cleanly.
    """
    if new_scorecard_df is None or new_scorecard_df.empty:
        return pd.DataFrame()

    if os.path.exists(SCORECARDS_PATH):
        try:
            existing_df = pd.read_excel(SCORECARDS_PATH) if SCORECARDS_PATH.endswith(('.xlsx', '.xls')) else pd.read_csv(SCORECARDS_PATH)
            combined_df = pd.concat([existing_df, new_scorecard_df], ignore_index=True)
            combined_df = combined_df.drop_duplicates(subset=['Week', 'Driver Name'], keep='last').reset_index(drop=True)
        except Exception as e:
            print(f"Error loading existing scorecards ledger: {e}")
            combined_df = new_scorecard_df
    else:
        combined_df = new_scorecard_df

    safe_save_dataframe(combined_df, SCORECARDS_PATH)
    return combined_df

def get_all_time_leaderboard(master_scorecards_df, min_lifetime_deliveries=1000, active_drivers_only=False, drivers_df=None):
    """
    Enhanced Leaderboard:
    Calculates Package-Weighted DQI for career averages. 
    Optionally filters out inactive drivers when active_drivers_only=True.
    """
    cols_order = ["All-Time Rank", "Driver Name", "Weeks_Tracked", "Career_Avg_DQI", "Highest_DQI", "Lowest_DQI", "Lifetime_Packages", "Latest_Standing"]
    
    if master_scorecards_df is None or master_scorecards_df.empty:
        return pd.DataFrame(columns=cols_order)

    df = master_scorecards_df.copy()

    if active_drivers_only and drivers_df is not None and not drivers_df.empty:
        if 'Status' in drivers_df.columns and 'Driver Name' in drivers_df.columns:
            inactive_names = set(drivers_df[drivers_df['Status'].astype(str).str.upper() == 'INACTIVE']['Driver Name'].astype(str).str.strip().unique())
            df = df[~df['Driver Name'].astype(str).str.strip().isin(inactive_names)].copy()

    if df.empty:
        return pd.DataFrame(columns=cols_order)

    score_col = 'Unified_Composite_Score' if 'Unified_Composite_Score' in df.columns else 'Overall Score'

    # FIXED: Strip '%' characters prior to numeric casting
    df[score_col] = pd.to_numeric(df[score_col].astype(str).str.replace('%', ''), errors='coerce').fillna(0.0)
    df['Packages Delivered'] = pd.to_numeric(df.get('Packages Delivered', 0), errors='coerce').fillna(0)
    df['weighted_score_prod'] = df[score_col] * df['Packages Delivered']

    df = df.sort_values(by=['Week'], ascending=True)

    records = []
    for d_name, group in df.groupby('Driver Name'):
        weeks_cnt = group['Week'].nunique()
        tot_pkgs = int(group['Packages Delivered'].sum())
        
        career_avg = (group['weighted_score_prod'].sum() / tot_pkgs) if tot_pkgs > 0 else group[score_col].mean()
        
        highest = group[score_col].max()
        lowest = group[score_col].min()
        latest_standing = group['Overall Standing'].iloc[-1] if 'Overall Standing' in group.columns else 'N/A'

        records.append({
            "Driver Name": d_name,
            "Weeks_Tracked": weeks_cnt,
            "Career_Avg_DQI": round(career_avg, 2),
            "Highest_DQI": round(highest, 2),
            "Lowest_DQI": round(lowest, 2),
            "Lifetime_Packages": tot_pkgs,
            "Latest_Standing": latest_standing
        })

    leaderboard = pd.DataFrame(records)

    if leaderboard.empty:
        return pd.DataFrame(columns=cols_order)

    eligible_df = leaderboard[leaderboard['Lifetime_Packages'] >= min_lifetime_deliveries].copy()
    unranked_df = leaderboard[leaderboard['Lifetime_Packages'] < min_lifetime_deliveries].copy()

    eligible_df = eligible_df.sort_values(by=['Career_Avg_DQI', 'Lifetime_Packages'], ascending=[False, False]).reset_index(drop=True)
    eligible_df['All-Time Rank'] = (eligible_df.index + 1).astype(str)

    unranked_df = unranked_df.sort_values(by=['Lifetime_Packages', 'Career_Avg_DQI'], ascending=[False, False]).reset_index(drop=True)
    unranked_df['All-Time Rank'] = "Unranked (< 1k Delivered)"

    final_leaderboard = pd.concat([eligible_df, unranked_df], ignore_index=True)
    return final_leaderboard[cols_order]