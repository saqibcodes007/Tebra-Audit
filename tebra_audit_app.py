# -----------------------------------------------------------------------------
# Streamlit App for Tebra Audit - Pediatrics West Version (vID Match)
# -----------------------------------------------------------------------------

import streamlit as st
import pandas as pd
import zeep
import zeep.helpers
from zeep.exceptions import Fault as SoapFault
from requests import Session
from zeep.transports import Transport
import datetime
import time
import re
from collections import defaultdict
import io

# -----------------------------------------------------------------------------
# PART 1: Core Logic (Utilities, API Calls - Mostly Unchanged)
# -----------------------------------------------------------------------------

# --- Utility Functions ---
# [Keep all utility functions: normalize_code, split_codes, normalize_string,
#  normalize_policy_number, compare_providers, validate_codes, format_audit_reasons]
def normalize_code(code):
    if not code: return ''
    code = str(code).upper().strip()
    code = re.sub(r'[^A-Z0-9]', '', code)
    if code.startswith('ICD'): code = code[3:]
    elif code.startswith('CPT'): code = code[3:]
    if code.endswith('F'): code = code[:-1] + 'F'
    return code
def split_codes(code_str):
    if not code_str: return []
    return [normalize_code(c) for c in str(code_str).split(",") if c.strip()]
def normalize_string(value):
    if not value: return ''
    value = str(value)
    value = re.sub(r'[^a-zA-Z0-9]', ' ', value)
    return ' '.join(value.lower().split())
def normalize_policy_number(number):
    if not number: return ''
    number = str(number)
    number = re.sub(r'[^A-Z0-9]', '', number.upper())
    return number.lstrip('0')
def compare_providers(tebra_provider, excel_provider):
    if not tebra_provider or not excel_provider: return False
    tebra_norm = normalize_string(tebra_provider)
    excel_norm = normalize_string(excel_provider)
    if (tebra_norm == excel_norm or tebra_norm in excel_norm or excel_norm in tebra_norm): return True
    tebra_last = tebra_norm.split(',')[0].strip()
    excel_last = excel_norm.split(',')[0].strip()
    return tebra_last == excel_last
def validate_codes(codes, code_type):
    valid_codes = []
    for code in codes:
        if not code: continue
        if code_type == 'ICD':
            if (len(code) >= 3 and len(code) <= 7 and code[0].isalpha() and code[1:].isalnum()): valid_codes.append(code)
        elif code_type == 'CPT':
            if len(code) == 5 and code[:4].isdigit() and (code[4].isalpha() or not code[4].isdigit()): valid_codes.append(code)
            elif len(code) == 5 and code[0].isalpha() and code[1:].isdigit(): valid_codes.append(code)
            elif code.endswith('F') and code[:-1].isdigit(): valid_codes.append(code)
    return valid_codes
def format_audit_reasons(reasons): # Used for Excel Summary
    if not reasons: return ''
    reason_counts = defaultdict(int)
    for reason in reasons: reason_counts[reason] += 1
    formatted = []
    for reason, count in reason_counts.items():
        if count > 1: formatted.append(f"{reason} ({count}x)")
        else: formatted.append(reason)
    return ' | '.join(formatted)

# --- Tebra API Interaction Functions ---
# [Keep create_api_client, build_request_header, search_tebra_patient,
#  get_tebra_patient_details, get_patient_codes_and_providers_from_charges]
@st.cache_resource
def create_api_client(wsdl_url):
    st.info("🔌 Connecting to Tebra SOAP API...")
    try:
        session = Session(); session.timeout = 60
        transport = Transport(session=session, timeout=60)
        client = zeep.Client(wsdl=wsdl_url, transport=transport)
        st.success("✅ Connected to Tebra API.")
        return client
    except Exception as e: st.error(f"❌ Failed to connect to Tebra API: {e}"); return None
def build_request_header(credentials, client):
    try:
        header_type = client.get_type('ns0:RequestHeader')
        password = credentials['Password'].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;').replace("'", '&apos;')
        return header_type(CustomerKey=credentials['CustomerKey'], User=credentials['User'], Password=password)
    except Exception as e: st.error(f"Error building request header: {e}"); return None
@st.cache_data(ttl=300)
def search_tebra_patient(_client, _header, practice_details, patient_name):
    # st.write(f"   (API Call: Searching Tebra for: {patient_name})")
    try:
        filter_type = _client.get_type('ns0:PatientFilter'); patient_filter = filter_type(PracticeName=practice_details['PracticeName'], FullName=patient_name)
        fields_type = _client.get_type('ns0:PatientFieldsToReturn'); fields = fields_type(ID=True, DOB=True, PracticeName=True)
        request_type = _client.get_type('ns0:GetPatientsReq'); request = request_type(RequestHeader=_header, Filter=patient_filter, Fields=fields)
        response = _client.service.GetPatients(request=request); time.sleep(0.5)
        if not response or not response.Patients or not response.Patients.PatientData: return None
        patient_data = response.Patients.PatientData; patient = zeep.helpers.serialize_object(patient_data[0] if isinstance(patient_data, list) else patient_data, dict)
        return patient
    except SoapFault as soap_error: st.error(f"❌ SOAP Error during patient search ({patient_name}): {soap_error.message}"); return None
    except Exception as e: st.error(f"❌ Error during patient search ({patient_name}): {e}"); return None
@st.cache_data(ttl=300)
def get_tebra_patient_details(_client, _header, patient_id):
    # st.write(f"   (API Call: Fetching details for Patient ID: {patient_id})")
    try:
        request_type = _client.get_type('ns0:GetPatientReq'); filter_type = client.get_type('ns0:SinglePatientFilter'); patient_filter = filter_type(PatientID=patient_id)
        request = request_type(RequestHeader=_header, Filter=patient_filter)
        response = _client.service.GetPatient(request=request); time.sleep(0.25)
        if not response or not response.Patient: return None
        patient_details = zeep.helpers.serialize_object(response.Patient, dict)
        return patient_details
    except SoapFault as soap_error: st.error(f"❌ SOAP Error fetching details for Patient ID {patient_id}: {soap_error.message}"); return None
    except Exception as e: st.error(f"❌ Error in GetPatient for ID {patient_id}: {e}"); return None
@st.cache_data(ttl=300)
def get_patient_codes_and_providers_from_charges(_client, _header, patient_name, practice_name, dos):
    # st.write(f"   (API Call: Fetching charges for {patient_name} on {dos})")
    all_codes = []; all_providers = set()
    try:
        dos_date = pd.to_datetime(dos).strftime('%m/%d/%Y') if dos else None
        if not dos_date: return [], set()
        filter_type = _client.get_type('ns0:ChargeFilter'); request_type = client.get_type('ns0:GetChargesReq')
        charge_filter = filter_type( PracticeName=practice_name, PatientName=patient_name, FromServiceDate=dos_date, ToServiceDate=dos_date, IncludeUnapprovedCharges='true')
        response = _client.service.GetCharges(request=request_type(RequestHeader=_header, Filter=charge_filter)); time.sleep(0.5)
        if response and response.Charges and response.Charges.ChargeData:
            charges = response.Charges.ChargeData; charges = [charges] if not isinstance(charges, list) else charges
            for charge in charges:
                charge_dict = zeep.helpers.serialize_object(charge)
                icd_fields = ['EncounterDiagnosisID1','EncounterDiagnosisID2','EncounterDiagnosisID3','EncounterDiagnosisID4','DiagnosisCode1','DiagnosisCode2','PrimaryDiagnosisCode','SecondaryDiagnosisCode']
                cpt_fields = ['ProcedureCode', 'CPTCode', 'ServiceCode']
                for field in icd_fields:
                    if field in charge_dict and charge_dict[field]: all_codes.append({'type': 'ICD', 'code': normalize_code(charge_dict[field])})
                for field in cpt_fields:
                     if field in charge_dict and charge_dict[field]: all_codes.append({'type': 'CPT', 'code': normalize_code(charge_dict[field])})
                if 'DiagnosisCodes' in charge_dict and charge_dict['DiagnosisCodes']:
                    diags = charge_dict['DiagnosisCodes']
                    if isinstance(diags, dict) and 'ChargeDiagnosisCodeData' in diags:
                         diag_data = diags['ChargeDiagnosisCodeData']; diag_data = [diag_data] if not isinstance(diag_data, list) else diag_data
                         for d in diag_data:
                             d_dict = zeep.helpers.serialize_object(d);
                             if 'Code' in d_dict and d_dict['Code']: all_codes.append({'type': 'ICD', 'code': normalize_code(d_dict['Code'])})
                provider_fields = ['RenderingProviderName','SchedulingProviderName','SupervisingProviderName','ReferringProviderName']
                for field in provider_fields:
                    if field in charge_dict and charge_dict[field]: all_providers.add(str(charge_dict[field]).strip())
    except SoapFault as soap_error: st.error(f"❌ SOAP Error fetching charges for {patient_name} on {dos}: {soap_error.message}")
    except Exception as e: st.error(f"❌ Error fetching charges for {patient_name} on {dos}: {str(e)}")
    seen = set(); unique_codes = []
    for code in all_codes:
        code_key = (code['type'], code['code'])
        if code_key not in seen and code['code']: seen.add(code_key); unique_codes.append(code)
    return unique_codes, all_providers

# --- REMOVED compare_insurance_data function ---
# We will implement the ID check directly in the loop

# -----------------------------------------------------------------------------
# PART 2: Streamlit UI Setup
# -----------------------------------------------------------------------------
st.set_page_config(layout="wide")
st.title("🩺 Tebra Audit Tool for Pediatrics West")
st.subheader("By Panacea Smart Solutions")

# --- Input Section (Sidebar) ---
st.sidebar.header("Configuration")
st.sidebar.subheader("🔑 Tebra API Credentials")
practice_name = st.sidebar.text_input("Practice Name", key="practice_name")
customer_key = st.sidebar.text_input("Customer Key", type="password", key="customer_key")
user = st.sidebar.text_input("Username (email)", key="user")
password = st.sidebar.text_input("Password", type="password", key="password")
st.sidebar.subheader("📄 Upload Audit File")
uploaded_file = st.sidebar.file_uploader("Upload Excel (.xlsx) or CSV (.csv) file", type=['xlsx', 'csv'], key="uploader")

# -----------------------------------------------------------------------------
# PART 3: Main Audit Logic & UI Display (Implementing ID Match Logic)
# -----------------------------------------------------------------------------
if st.sidebar.button("🚀 Run Audit", key="run_button"):
    if not all([practice_name, customer_key, user, password]):
        st.warning("🚨 Please enter all Tebra API credentials.")
    elif uploaded_file is None:
        st.warning("🚨 Please upload the audit file.")
    else:
        st.info("⏳ Audit process started...")
        df = None
        try: # Read Excel/CSV
            file_name = uploaded_file.name
            if file_name.lower().endswith('.csv'): df = pd.read_csv(uploaded_file, dtype=str)
            elif file_name.lower().endswith('.xlsx'): df = pd.read_excel(uploaded_file, dtype=str)
            df = df.fillna('')
            st.success(f"✅ Successfully read '{file_name}' with {len(df)} rows.")
        except Exception as e: st.error(f"❌ Error reading file: {e}"); st.stop()

        # Column Mapping & Verification
        mapping = { 'patient_name': 'Patient Name', 'dob': 'Patient DOB', 'policy_number': 'Patient Policy Num', 'group_number': 'Patient Group Num', 'insurance_company': 'Insurance Name', 'provider': 'Provider Name', 'encounter_id': 'Encounter ID', 'claim_id': 'Claim ID', 'dos': 'Date Of Service', 'icd': 'Diagnosis Code', 'icd2': 'Diagnosis Code2', 'cpt': 'Procedure Code', 'location': 'Location Name' }
        missing_columns = [col for col in mapping.values() if col not in df.columns]
        if missing_columns: st.error(f"❌ Missing required columns: {', '.join(missing_columns)}"); st.stop()
        else: st.info("✅ All required columns found in the uploaded file.")

        # Prepare DataFrame
        patient_columns = [ mapping['patient_name'], mapping['dob'], mapping['policy_number'], mapping['group_number'], mapping['insurance_company'], mapping['provider'], mapping['encounter_id'], mapping['dos'] ]
        ffillable_cols = [col for col in patient_columns if col in df.columns]
        df[ffillable_cols] = df[ffillable_cols].ffill()
        df.reset_index(drop=True, inplace=True)

        # API Client Setup
        TEBRA_WSDL_URL = "https://webservice.kareo.com/services/soap/2.1/KareoServices.svc?singleWsdl"
        client = create_api_client(TEBRA_WSDL_URL)

        if client:
            credentials = {"CustomerKey": customer_key, "User": user, "Password": password}
            practice_details = {"PracticeName": practice_name}
            header = build_request_header(credentials, client)

            if header:
                st.info("🕵️ Starting data audit...")
                audit_results_detailed_text = []
                audit_df = df.copy()
                audit_df['Audit Results'] = 'Pending'
                audit_df['Reason For Invalid'] = ''

                progress_bar = st.progress(0)
                total_rows = len(audit_df)
                tebra_data_cache = {}

                # --- Main Audit Loop ---
                for idx, row in audit_df.iterrows():
                    progress_text = f"Processing row {idx+1} of {total_rows}..."; progress_bar.progress((idx + 1) / total_rows, text=progress_text)
                    # Extract data
                    patient_name=str(row.get(mapping['patient_name'], '')).strip()
                    dob=str(row.get(mapping['dob'], '')).strip()
                    policy_num=str(row.get(mapping['policy_number'], '')).strip()
                    excel_insurance=str(row.get(mapping['insurance_company'], '')).strip()
                    excel_provider=str(row.get(mapping['provider'], '')).strip()
                    dos=str(row.get(mapping['dos'], '')).strip()
                    claim_id=str(row.get(mapping['claim_id'], '')).strip()
                    excel_icd_raw=str(row.get(mapping['icd'], '')).strip()
                    excel_icd2_raw=str(row.get(mapping['icd2'], '')).strip()
                    combined_excel_icd=excel_icd_raw + (f",{excel_icd2_raw}" if excel_icd_raw and excel_icd2_raw else excel_icd2_raw)
                    excel_cpt_raw=str(row.get(mapping['cpt'], '')).strip()

                    # *** NEW: Extract Company ID from Excel Insurance Name ***
                    excel_company_id = None
                    match = re.search(r'\((\d+)\)$', excel_insurance) # Find digits in parentheses at the end
                    if match:
                        excel_company_id = match.group(1) # Get the number inside parentheses

                    row_audit_details = { field: {'status': 'Pending', 'reason': ''} for field in ['policy', 'insurance', 'provider', 'icd', 'cpt'] }
                    overall_status = 'Verified'; all_reasons_for_excel = []

                    if not all([patient_name, dos]):
                        overall_status = 'Skipped'; reason = "Missing Patient Name or DOS"; all_reasons_for_excel.append(reason)
                        row_audit_details = {k: {'status': 'Skipped', 'reason': reason} for k in row_audit_details}
                    else:
                        # Get Tebra Data
                        cache_key = (patient_name, practice_name, dos)
                        if cache_key not in tebra_data_cache:
                            tebra_codes, tebra_providers_charge = get_patient_codes_and_providers_from_charges(client, header, patient_name, practice_name, dos)
                            tebra_patient_search_result = search_tebra_patient(client, header, practice_details, patient_name)
                            tebra_patient_details = get_tebra_patient_details(client, header, tebra_patient_search_result['ID']) if tebra_patient_search_result else None
                            tebra_data_cache[cache_key] = {'codes': tebra_codes or [], 'providers_charge': tebra_providers_charge or set(), 'details': tebra_patient_details}

                        cached_data = tebra_data_cache[cache_key]
                        tebra_icds = {c['code'] for c in cached_data['codes'] if c['type'] == 'ICD' and c['code']}
                        tebra_cpts = {c['code'] for c in cached_data['codes'] if c['type'] == 'CPT' and c['code']}
                        tebra_providers = set(cached_data['providers_charge'])
                        tebra_details = cached_data['details']
                        if tebra_details and tebra_details.get('PrimaryProvider'):
                             primary_provider = tebra_details['PrimaryProvider']
                             if isinstance(primary_provider, dict) and primary_provider.get('FullName'): tebra_providers.add(primary_provider['FullName'].strip())
                             elif isinstance(primary_provider, str): tebra_providers.add(primary_provider.strip())

                        no_tebra_data = not tebra_details and not tebra_icds and not tebra_cpts and not tebra_providers
                        if no_tebra_data:
                             overall_status = 'Invalid'; reason = "Patient/Charge data not found in Tebra"; all_reasons_for_excel.append(reason)
                             row_audit_details = {k: {'status': 'Invalid', 'reason': reason} for k in row_audit_details}
                        else:
                            # --- Perform Audits and Populate Detailed Results ---
                            try:
                                # 1. Gather Tebra Policy Numbers and Company IDs
                                tebra_policy_nums_found = set()
                                tebra_company_ids_found = set()
                                if tebra_details and tebra_details.get('Cases') and tebra_details['Cases'].get('PatientCaseData'):
                                    cases_data = tebra_details['Cases']['PatientCaseData']; cases_data = [cases_data] if not isinstance(cases_data, list) else cases_data
                                    for case in cases_data:
                                        if case and case.get('InsurancePolicies') and case['InsurancePolicies'].get('PatientInsurancePolicyData'):
                                            policies_data = case['InsurancePolicies']['PatientInsurancePolicyData']; policies_data = [policies_data] if not isinstance(policies_data, list) else policies_data
                                            for p_data in policies_data:
                                                p_dict = zeep.helpers.serialize_object(p_data, dict) if p_data else {}
                                                num = str(p_dict.get('Number', '')).strip()
                                                comp_id = str(p_dict.get('CompanyID', '')).strip() # Get CompanyID
                                                if num: tebra_policy_nums_found.add(num)
                                                if comp_id: tebra_company_ids_found.add(comp_id) # Store CompanyID

                                # 2. *** NEW Insurance Name Check (using Company ID) ***
                                if excel_company_id:
                                    if excel_company_id in tebra_company_ids_found:
                                        row_audit_details['insurance']['status'] = 'Verified'
                                    else:
                                        overall_status = 'Invalid'
                                        reason = f"Excel Company ID: {excel_company_id}; Tebra Company IDs Found: {', '.join(sorted(list(tebra_company_ids_found))) or 'None'}"
                                        row_audit_details['insurance']['status'] = 'Invalid'
                                        row_audit_details['insurance']['reason'] = reason
                                        all_reasons_for_excel.append(f"Ins Company ID Mismatch ({excel_company_id})")
                                else:
                                    # Handle case where ID couldn't be parsed from Excel
                                    overall_status = 'Invalid'
                                    reason = f"Could not parse Company ID from Excel entry: '{excel_insurance}'"
                                    row_audit_details['insurance']['status'] = 'Invalid'
                                    row_audit_details['insurance']['reason'] = reason
                                    all_reasons_for_excel.append("Ins Name Format Error (No ID)")

                                # 3. *** Policy Number Check (Independent) ***
                                if policy_num: # Only check if excel has a policy number
                                    if policy_num in tebra_policy_nums_found:
                                        row_audit_details['policy']['status'] = 'Verified'
                                    else:
                                        overall_status = 'Invalid'
                                        reason = f"Excel Policy: {policy_num}; Tebra Policies Found: {', '.join(sorted(list(tebra_policy_nums_found))) or 'None'}"
                                        row_audit_details['policy']['status'] = 'Invalid'
                                        row_audit_details['policy']['reason'] = reason
                                        all_reasons_for_excel.append(f"Policy# Mismatch ({policy_num})")
                                else:
                                    row_audit_details['policy']['status'] = 'Verified' # No policy number provided in Excel to check

                                # 4. Provider Check
                                provider_match = False; excel_provider_norm = normalize_string(excel_provider)
                                if excel_provider_norm:
                                    if excel_provider_norm in {normalize_string(p) for p in tebra_providers}: provider_match = True
                                    else:
                                        for tebra_prov in tebra_providers:
                                            if compare_providers(tebra_prov, excel_provider): provider_match = True; break
                                if not provider_match and excel_provider:
                                    overall_status = 'Invalid'; all_reasons_for_excel.append("Provider Mismatch")
                                    tebra_providers_str = ", ".join(sorted(list(tebra_providers))) or "None"
                                    row_audit_details['provider']['status'] = 'Invalid'
                                    row_audit_details['provider']['reason'] = f"Excel: '{excel_provider}'; Tebra Providers Found: {tebra_providers_str}"
                                else: row_audit_details['provider']['status'] = 'Verified'

                                # 5. ICD Check
                                excel_icds_norm = set(validate_codes(split_codes(combined_excel_icd), 'ICD'))
                                missing_icds = excel_icds_norm - tebra_icds
                                if missing_icds:
                                    overall_status = 'Invalid'; codes_str = ', '.join(sorted(list(missing_icds)))
                                    all_reasons_for_excel.append(f"Invalid ICD(s): {codes_str}")
                                    row_audit_details['icd']['status'] = 'Invalid'
                                    excel_icd_str = ', '.join(sorted(list(excel_icds_norm))) or "None"; tebra_icd_str = ', '.join(sorted(list(tebra_icds))) or "None"
                                    row_audit_details['icd']['reason'] = f"Excel code(s) missing in Tebra: {codes_str}. (Excel had: {excel_icd_str}; Tebra had: {tebra_icd_str})"
                                else: row_audit_details['icd']['status'] = 'Verified'

                                # 6. CPT Check
                                excel_cpts_norm = set(validate_codes(split_codes(excel_cpt_raw), 'CPT'))
                                missing_cpts = excel_cpts_norm - tebra_cpts
                                if missing_cpts:
                                    overall_status = 'Invalid'; codes_str = ', '.join(sorted(list(missing_cpts)))
                                    all_reasons_for_excel.append(f"Invalid CPT(s): {codes_str}")
                                    row_audit_details['cpt']['status'] = 'Invalid'
                                    excel_cpt_str = ', '.join(sorted(list(excel_cpts_norm))) or "None"; tebra_cpt_str = ', '.join(sorted(list(tebra_cpts))) or "None"
                                    row_audit_details['cpt']['reason'] = f"Excel code(s) missing in Tebra: {codes_str}. (Excel had: {excel_cpt_str}; Tebra had: {tebra_cpt_str})"
                                else: row_audit_details['cpt']['status'] = 'Verified'

                            except Exception as e_audit:
                                st.error(f"🚨 Error during audit logic for row {idx+1}: {e_audit}")
                                overall_status = 'Error'; reason = f"System error: {str(e_audit)}"
                                all_reasons_for_excel.append(reason)
                                row_audit_details = {k: {'status': 'Error', 'reason': reason} for k in row_audit_details}

                    # --- Format and Store Results for UI ---
                    audit_df.loc[idx, 'Audit Results'] = overall_status
                    audit_df.loc[idx, 'Reason For Invalid'] = format_audit_reasons(all_reasons_for_excel)

                    result_text = f"Patient Name: {patient_name} | Claim ID: {claim_id or 'N/A'} | DOS: {dos}\n"
                    result_text += "AUDIT RESULT:\n"
                    def format_detail_line(number, field_name, details):
                        padded_name = field_name.ljust(22); line = f"{number}. {padded_name}: {details['status']}"
                        if details['status'] not in ['Verified', 'Pending'] and details['reason']: line += f" (Reason: {details['reason']})"
                        return line + "\n"
                    # Use the row_audit_details populated by the new logic
                    result_text += format_detail_line(1, 'Patient Policy Number', row_audit_details['policy'])
                    result_text += format_detail_line(2, 'Insurance Name', row_audit_details['insurance']) # Status now based on CompanyID match
                    result_text += format_detail_line(3, 'Provider Name', row_audit_details['provider'])
                    result_text += format_detail_line(4, 'ICD-10 Code(s)', row_audit_details['icd'])
                    result_text += format_detail_line(5, 'CPT Code(s)', row_audit_details['cpt'])

                    audit_results_detailed_text.append(result_text + "-"*40)

                # --- End of Loop ---
                progress_bar.empty(); st.success("✅ Audit Complete!")
                st.subheader("📊 Audit Results Detail")
                st.text_area("Detailed Audit Log (per patient)", "".join(audit_results_detailed_text), height=500)
                st.subheader("⬇️ Download Results Summary")
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer: audit_df.to_excel(writer, index=False, sheet_name='AuditResults')
                output.seek(0)
                st.download_button(label="Download Audited Excel File", data=output, file_name="tebra_audit_results.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

            else: st.error("❌ Could not build Tebra request header.")
        else: st.error("❌ Could not connect to Tebra API.")
else:
    st.info("ℹ️ Enter Tebra credentials and upload your file, then click 'Run Audit'.")

# -----------------------------------------------------------------------------
# How to Run
# -----------------------------------------------------------------------------