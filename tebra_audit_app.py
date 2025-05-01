# -*- coding: utf-8 -*-
"""
Streamlit App for Tebra Audit v2 (Corrected Syntax Error)
"""

# -----------------------------------------------------------------------------
# PART 1: Dependencies
# -----------------------------------------------------------------------------
import streamlit as st
import pandas as pd
import zeep
import zeep.helpers
from zeep.exceptions import Fault as SoapFault
from requests import Session
from zeep.transports import Transport
import datetime # Import the module
import time
import re
from decimal import Decimal, ROUND_HALF_UP
import io
import base64 # For download link

# -----------------------------------------------------------------------------
# PART 5: Utility Functions
# -----------------------------------------------------------------------------
# (These functions remain the same as the final working version in Colab,
#  except for the corrected normalize_dob)

print("--- Defining Utility Functions (Part 5 - Corrected normalize_dob) ---") # Keep print for debugging module load

def normalize_string(text, remove_spaces=False):
  if isinstance(text, str): text = text.lower().strip(); text = re.sub(r'[.,()-]', '', text);
  if remove_spaces: text = re.sub(r'\s+', '', text)
  else: text = ' '.join(text.split())
  return text; return text
def normalize_code(code):
  if isinstance(code, str): return re.sub(r'[^a-zA-Z0-9]', '', code).upper()
  elif isinstance(code, (int, float)): return str(int(code))
  return code
def normalize_name(name):
    if isinstance(name, str): name = re.sub(r'[,.\s]*(md|do|rn|np|pa|pcp|facp|dpm|lcsw|lpcc|rnfa|fnp|aprn)[\s.]*$', '', name.strip(), flags=re.IGNORECASE | re.DOTALL); name = name.lower(); name = re.sub(r'(?<![-’\'])[,."](?![-’\'])', '', name); name = ' '.join(name.split()); return name
    return name
def compare_names(excel_name, tebra_name):
    norm_excel = normalize_name(excel_name); norm_tebra = normalize_name(tebra_name);
    if not norm_excel or not norm_tebra: return not norm_excel and not norm_tebra
    parts_excel = norm_excel.split(); parts_tebra = norm_tebra.split();
    if not parts_excel or not parts_tebra: return False
    first_name_match = (parts_excel[0] == parts_tebra[0]); last_name_match = (parts_excel[-1] == parts_tebra[-1])
    return first_name_match and last_name_match

# *** CORRECTED normalize_dob function ***
def normalize_dob(date_input):
    """
    Attempts to parse a date string or datetime object into YYYY-MM-DD format.
    Handles MM/DD/YYYY and YYYY-MM-DD string inputs.
    """
    if date_input is None:
        return None

    date_str = None
    # Check if input is datetime.datetime object
    if isinstance(date_input, datetime.datetime):
        try:
            return date_input.strftime('%Y-%m-%d')
        except ValueError:
             # st.warning(f"Could not format datetime object {date_input}.") # Optional UI warning
             return None
    # Check if input is already a string
    elif isinstance(date_input, str):
        date_str = date_input.strip()
    # Try converting other types to string
    else:
        try:
            date_str = str(date_input).strip()
        except Exception:
            # st.warning(f"Could not convert date input '{date_input}' to string.") # Optional UI warning
            return None

    # *** Check if date_str became empty AFTER potential conversion/stripping ***
    if not date_str:
        return None

    # At this point, date_str should be a non-empty string
    # Clean up potential time part
    try:
        date_part = date_str.split()[0]
    except IndexError:
        # st.warning(f"Could not extract date part from '{date_str}'.") # Optional UI warning
        return None
    except AttributeError: # Should not happen if not date_str check above worked
        return None

    # Try parsing known formats
    try:
        dt = datetime.datetime.strptime(date_part, '%m/%d/%Y')
        return dt.strftime('%Y-%m-%d')
    except ValueError:
        try:
            dt = datetime.datetime.strptime(date_part, '%Y-%m-%d')
            return dt.strftime('%Y-%m-%d')
        except ValueError:
            # st.warning(f"Could not parse date string '{date_part}' using known formats.") # Optional UI warning
            return None
# *** End of corrected normalize_dob ***

def compare_dob(excel_dob_input, tebra_dob_str):
    norm_excel = normalize_dob(excel_dob_input); norm_tebra = normalize_dob(tebra_dob_str)
    if not norm_excel or not norm_tebra: return False if norm_excel or norm_tebra else True
    return norm_excel == norm_tebra
def get_nested_attribute(obj, attribute_path, default=None):
    current = obj;
    try:
        for attr in attribute_path.split('.'):
            if current is None: return default
            current = getattr(current, attr, None)
        return current if current is not None else default
    except AttributeError: return default
def round_half_up(n, decimals=2):
    if n is None: return None
    try: number = Decimal(str(n))
    except (decimal.InvalidOperation, ValueError, TypeError): return None
    quantizer = Decimal('1e-' + str(decimals)); return number.quantize(quantizer, rounding=ROUND_HALF_UP)
def compare_providers(excel_provider, tebra_provider): return compare_names(excel_provider, tebra_provider)
def compare_pos_codes(excel_pos, tebra_pos):
    norm_excel = normalize_string(excel_pos, remove_spaces=True); norm_tebra = normalize_string(str(tebra_pos), remove_spaces=True)
    if not norm_excel or not norm_tebra: return not norm_excel and not norm_tebra
    if norm_excel == 'office' and norm_tebra == '11': return True
    if ('telehealth' in norm_excel and 'home' in norm_excel) and norm_tebra == '10': return True
    if norm_excel == norm_tebra: return True; return False
def compare_ins_plans(excel_plan, tebra_plan): # Assuming this custom logic is desired now
    norm_excel = normalize_string(excel_plan, remove_spaces=True); norm_tebra = normalize_string(tebra_plan, remove_spaces=True)
    if not norm_excel or not norm_tebra: return not norm_excel and not norm_tebra
    excel_is_bcbs = norm_excel == 'bcbs'; tebra_is_bluecross = 'bluecross' in norm_tebra or 'bcbs' in norm_tebra
    if excel_is_bcbs and tebra_is_bluecross: return True
    if tebra_is_bluecross and ('bluecross' in norm_excel or 'bcbs' in norm_excel): return True
    if norm_excel == norm_tebra: return True; return False
def format_mismatch_reason(field, excel_val, tebra_val, identifier=None):
  excel_str = str(excel_val) if excel_val is not None else 'NULL'; tebra_str = str(tebra_val) if tebra_val is not None else 'NULL'
  reason = f"{field} Mismatch (Excel: '{excel_str}', Tebra: '{tebra_str}')"
  if identifier: reason += f" for Claim ID {identifier}"
  return reason
# --- End of Part 5 Functions ---

# -----------------------------------------------------------------------------
# PART 2 & 6 Functions (Adapted for Streamlit where needed)
# -----------------------------------------------------------------------------

@st.cache_resource(ttl=3600)
def create_api_client(wsdl_url="https://webservice.kareo.com/services/soap/2.1/KareoServices.svc?singleWsdl"):
    st.write("🔌 Connecting to Tebra SOAP API...")
    try:
        session = Session(); session.timeout = 120; transport = Transport(session=session, timeout=120)
        client = zeep.Client(wsdl=wsdl_url, transport=transport)
        st.write("✅ Connected to Tebra API.")
        return client
    except Exception as e: st.error(f"❌ Failed to connect to Tebra API: {e}"); return None

def build_request_header(credentials, client):
    if not client: st.error("❌ Cannot build header without API client."); return None
    try:
        header_type = client.get_type('ns0:RequestHeader')
        return header_type(CustomerKey=credentials['CustomerKey'], User=credentials['User'], Password=credentials['Password'])
    except Exception as e: st.error(f"❌ Error building request header: {e}"); return None

def get_tebra_patient_soap(client, header, patient_id):
    soap_method_name = "GetPatient"; request_type_name = '{http://www.kareo.com/api/schemas/}GetPatientReq'; filter_type_name = '{http://www.kareo.com/api/schemas/}SinglePatientFilter'
    try: patient_id_int = int(patient_id)
    except (ValueError, TypeError): return None, f"Invalid Patient ID format: '{patient_id}'."
    try:
        SinglePatientFilter_Type = client.get_type(filter_type_name); GetPatientReq_Type = client.get_type(request_type_name)
        filter_object = SinglePatientFilter_Type(PatientID=patient_id_int); patient_request_object = GetPatientReq_Type(RequestHeader=header, Filter=filter_object)
        response = client.service.GetPatient(request=patient_request_object)
        if hasattr(response, 'ErrorResponse') and response.ErrorResponse.IsError: error_msg = get_nested_attribute(response, 'ErrorResponse.ErrorMessage', 'Unknown API error'); return None, f"API Error ({soap_method_name}): {error_msg}"
        if not hasattr(response, 'Patient') or not response.Patient: return None, f"Patient data object not found in response for ID {patient_id_int}."
        return response, None
    except zeep.exceptions.Fault as fault: return None, f"SOAP Fault ({soap_method_name} {patient_id_int}): {fault.message}"
    except (TypeError, AttributeError, ValueError, zeep.exceptions.Error) as e: return None, f"Zeep/Request Error ({soap_method_name} {patient_id_int}): {type(e).__name__} - {e}"
    except Exception as e: return None, f"Unexpected Error ({soap_method_name} {patient_id_int}): {type(e).__name__} - {e}"

def get_tebra_charges_soap(client, header, patient_name, dos_datetime):
    soap_method_name = "GetCharges"; request_type_name = '{http://www.kareo.com/api/schemas/}GetChargesReq'; filter_type_name = '{http://www.kareo.com/api/schemas/}ChargeFilter'
    try: dos_str = dos_datetime.strftime('%Y-%m-%d')
    except (AttributeError) as e: return [], f"Invalid DOS input for GetCharges: '{dos_datetime}'. Error: {e}"
    if not patient_name: return [], "Cannot fetch charges without a valid patient name."
    try:
        ChargeFilter_Type = client.get_type(filter_type_name); GetChargesReq_Type = client.get_type(request_type_name)
        charge_filter_object = ChargeFilter_Type(PatientName=patient_name, FromServiceDate=dos_str, ToServiceDate=dos_str)
        charge_request_object = GetChargesReq_Type(RequestHeader=header, Filter=charge_filter_object)
        response = client.service.GetCharges(request=charge_request_object)
        if hasattr(response, 'ErrorResponse') and response.ErrorResponse.IsError: error_msg = get_nested_attribute(response, 'ErrorResponse.ErrorMessage', 'Unknown API error'); return [], f"API Error ({soap_method_name}): {error_msg}"
        charges_data_container = get_nested_attribute(response, 'Charges.ChargeData', default=[]);
        if charges_data_container is None: charges_list = []
        elif not isinstance(charges_data_container, list): charges_list = [charges_data_container]
        else: charges_list = charges_data_container
        return charges_list, None
    except zeep.exceptions.Fault as fault: return [], f"SOAP Fault ({soap_method_name} '{patient_name}', {dos_str}): {fault.message}"
    except (TypeError, AttributeError, ValueError, zeep.exceptions.Error) as e: return [], f"Zeep/Request Error ({soap_method_name} '{patient_name}', {dos_str}): {type(e).__name__} - {e}"
    except Exception as e: return [], f"Unexpected Error ({soap_method_name} '{patient_name}', {dos_str}): {type(e).__name__} - {e}"

def find_matching_charge(excel_row_data, tebra_charges_list):
    excel_claim_id = None
    try:
        if isinstance(excel_row_data, pd.Series):
            excel_cpt = normalize_code(excel_row_data.get('ProcedureCode')); excel_charge = round_half_up(excel_row_data.get('ServiceChargeAmount'), decimals=2); excel_claim_id = str(excel_row_data.get('claimID', 'UNKNOWN'))
        else:
             excel_cpt = normalize_code(excel_row_data.get('ProcedureCode')); excel_charge = round_half_up(excel_row_data.get('ServiceChargeAmount'), decimals=2); excel_claim_id = str(excel_row_data.get('claimID', 'UNKNOWN'))
        potential_matches = []
        for tebra_charge in tebra_charges_list:
            tebra_cpt = normalize_code(get_nested_attribute(tebra_charge, 'ProcedureCode'))
            if excel_cpt == tebra_cpt: potential_matches.append(tebra_charge)
        if not potential_matches: return None, f"CPT Mismatch (Excel CPT: {excel_cpt} not found in Tebra charges for Claim ID {excel_claim_id})"
        for tebra_charge in potential_matches:
            tebra_charge_amt = round_half_up(get_nested_attribute(tebra_charge, 'TotalCharges'), decimals=2)
            if excel_charge is not None and tebra_charge_amt is not None and excel_charge == tebra_charge_amt: return tebra_charge, None
        first_potential_tebra_amt = round_half_up(get_nested_attribute(potential_matches[0], 'TotalCharges'), decimals=2) if potential_matches else 'N/A'
        return None, f"Amount Mismatch (Excel: {excel_charge}, Tebra: {first_potential_tebra_amt} for Claim ID {excel_claim_id})"
    except Exception as e:
        claim_id_str = excel_claim_id if excel_claim_id is not None else 'UNKNOWN'
        return None, f"Code error in find_matching_charge for Claim ID {claim_id_str}: {e}"
# --- End of Part 6 Functions ---

# -----------------------------------------------------------------------------
# Streamlit App Main Section
# -----------------------------------------------------------------------------

st.set_page_config(layout="wide")
st.title("🩺 Tebra Charge Audit Tool - By Panacea Smart Solutions")
st.markdown("Upload your Excel audit file and enter Tebra credentials to run the audit.")

# --- Input Area ---
with st.sidebar:
    st.header("Tebra Credentials")
    practice_name = st.text_input("Practice Name", key="practice_name")
    customer_key = st.text_input("Customer Key", type="password", key="customer_key")
    username = st.text_input("Username (email)", key="username")
    password = st.text_input("Password", type="password", key="password")

    st.header("Upload Audit File")
    uploaded_file = st.file_uploader("Choose an Excel file (.xlsx)", type=["xlsx"])

run_button = st.button("Run Audit")

# --- Processing and Output Area ---
if run_button and uploaded_file:
    if not all([practice_name, customer_key, username, password]): st.error("❌ Please enter all Tebra credentials.")
    else:
        st.info("🚀 Starting Audit Process...")
        with st.spinner('Connecting to Tebra API...'):
            client = create_api_client()
            if client: credentials = {"CustomerKey": customer_key, "User": username, "Password": password}; header = build_request_header(credentials, client)
            else: header = None
        if not client or not header: st.error("❌ Tebra connection failed."); st.stop()
        st.success("✅ Connected to Tebra.")

        try:
            st.info(f"Reading Excel file: {uploaded_file.name}")
            df = pd.read_excel(uploaded_file, dtype={'PatientID': str, 'claimID': str, 'EncounterID': str}, engine='openpyxl', keep_default_na=False) # Ensure IDs read as string
            df = df.fillna('')
            df.reset_index(inplace=True); df.rename(columns={'index': 'Original Excel Row Index'}, inplace=True)
            st.success(f"✅ Read {len(df)} rows from Excel file.")
        except Exception as e: st.error(f"❌ Error reading Excel file: {e}"); st.stop()

        # Simplified column check
        required_cols_list = ['PatientID', 'PatientName', 'DOB', 'DateOfService', 'RenderingProvider','ReferringProvider', 'PlaceOfServiceCode', 'ProcedureCode','ProcedureModifier1', 'ProcedureModifier2', 'ProcedureModifier3', 'ProcedureModifier4','ServiceUnitCount', 'EncounterDiagnosisID1', 'EncounterDiagnosisID2','EncounterDiagnosisID3', 'EncounterDiagnosisID4', 'ServiceChargeAmount','PriIns_CompanyName', 'PriIns_CompanyPlanName', 'EncounterID', 'claimID']
        if not all(col in df.columns for col in required_cols_list):
             st.error("❌ Error: One or more required columns are missing. Check file headers."); st.stop()
        else: st.success("✅ Required Excel columns verified.")

        tebra_patient_cache = {}; tebra_charges_cache = {}; audit_results_list = []
        total_rows = len(df); progress_bar = st.progress(0); status_text = st.empty()

        st.info("⏳ Running comparisons against Tebra data...")
        start_time = time.time()

        for index, row in df.iterrows():
            excel_row_num_display = index + 2
            percent_complete = (index + 1) / total_rows; progress_bar.progress(min(1.0, percent_complete)); status_text.text(f"Processing Excel row {excel_row_num_display}/{total_rows+1}...")
            current_result_data = {"Excel Row": excel_row_num_display, "Status": "Error", "Reason": "Processing started", "Excel Data": row.to_dict()}
            mismatch_reasons = []; excel_patient_id_str = None; excel_claim_id = None

            # 1. Extract Data
            try:
                excel_patient_id_str = str(row.get('PatientID', '')).strip(); excel_claim_id = str(row.get('claimID', 'UNKNOWN'))
                if not excel_patient_id_str: raise ValueError("Missing PatientID")
                current_result_data["Excel PatientID"] = excel_patient_id_str; current_result_data["Excel claimID"] = excel_claim_id
                excel_patient_name_raw = row.get('PatientName'); excel_dob_raw = row.get('DOB'); excel_dos_raw = row.get('DateOfService')
                if pd.isna(excel_dos_raw): raise ValueError("Missing DateOfService")
                try: excel_dos_dt = excel_dos_raw if isinstance(excel_dos_raw, datetime.datetime) else pd.to_datetime(excel_dos_raw).to_pydatetime()
                except Exception as date_err: raise ValueError(f"Invalid DateOfService format '{excel_dos_raw}': {date_err}") from date_err
                excel_dos_str = excel_dos_dt.strftime('%Y-%m-%d')
                current_result_data["Excel DOS"] = excel_dos_str; current_result_data["Excel ProcCode"] = row.get('ProcedureCode')
            except Exception as e: current_result_data["Reason"] = f"Error reading Excel data: {e}"; audit_results_list.append(current_result_data); continue

            # 2. Get Patient
            tebra_patient_response, api_error_pat = tebra_patient_cache.get(excel_patient_id_str, (None, None))
            if tebra_patient_response is None and api_error_pat is None: tebra_patient_response, api_error_pat = get_tebra_patient_soap(client, header, excel_patient_id_str); tebra_patient_cache[excel_patient_id_str] = (tebra_patient_response, api_error_pat)

            # 3. Process Patient
            tebra_patient_name_for_filter = None
            if api_error_pat: mismatch_reasons.append(f"Patient Fetch Error: {api_error_pat}"); current_result_data["Status"] = "Error"
            elif not tebra_patient_response or not hasattr(tebra_patient_response, 'Patient') or not tebra_patient_response.Patient: mismatch_reasons.append(f"No valid Tebra patient data for ID {excel_patient_id_str}."); current_result_data["Status"] = "Error"
            else:
                try:
                    tebra_patient_data = tebra_patient_response.Patient; tebra_patient_name_for_filter = get_nested_attribute(tebra_patient_data, 'PatientFullName'); tebra_first_name = get_nested_attribute(tebra_patient_data, 'FirstName'); tebra_last_name = get_nested_attribute(tebra_patient_data, 'LastName'); tebra_dob_str = get_nested_attribute(tebra_patient_data, 'DOB')
                    if not tebra_patient_name_for_filter and tebra_first_name and tebra_last_name: tebra_patient_name_for_filter = f"{tebra_first_name} {tebra_last_name}"
                    tebra_name_for_compare = tebra_patient_name_for_filter if tebra_patient_name_for_filter else "MISSING_NAME"
                    excel_name_parts = [p.strip() for p in str(excel_patient_name_raw).split(',')] if excel_patient_name_raw else []; excel_name_normalized = f"{excel_name_parts[1]} {excel_name_parts[0]}" if len(excel_name_parts)==2 else excel_patient_name_raw
                    if not compare_names(excel_name_normalized, tebra_name_for_compare): mismatch_reasons.append(format_mismatch_reason("Patient Name", excel_patient_name_raw, tebra_name_for_compare))
                    if not compare_dob(excel_dob_raw, tebra_dob_str): mismatch_reasons.append(format_mismatch_reason("Patient DOB", excel_dob_raw, tebra_dob_str))
                    if not mismatch_reasons: current_result_data["Status"] = "Pending"
                except Exception as e: mismatch_reasons.append(f"Error processing Tebra patient data: {e}"); current_result_data["Status"] = "Error"

            # 4. Get Charges
            tebra_charges = []; api_error_chg = None
            proceed_to_charge_check = (current_result_data["Status"] != "Error" and tebra_patient_name_for_filter)
            if proceed_to_charge_check:
                cache_key_chg = (tebra_patient_name_for_filter, excel_dos_str)
                tebra_charges, api_error_chg = tebra_charges_cache.get(cache_key_chg, ([], None))
                if not tebra_charges and api_error_chg is None: tebra_charges, api_error_chg = get_tebra_charges_soap(client, header, tebra_patient_name_for_filter, excel_dos_dt); tebra_charges_cache[cache_key_chg] = (tebra_charges, api_error_chg)

            # 5. Process Charges & Compare
            if proceed_to_charge_check:
                if api_error_chg: mismatch_reasons.append(f"Charge Fetch Error: {api_error_chg}"); current_result_data["Status"] = "Error"
                elif not tebra_charges: mismatch_reasons.append("No matching charge found in Tebra (None returned for name/DOS)"); current_result_data["Status"] = "Mismatch"
                else:
                    matching_tebra_charge, find_charge_reason = find_matching_charge(row, tebra_charges)
                    if not matching_tebra_charge: mismatch_reasons.append(find_charge_reason); current_result_data["Status"] = "Mismatch"
                    else:
                        if current_result_data["Status"] == "Pending": current_result_data["Status"] = "Match";
                        else: current_result_data["Status"] = "Mismatch"
                        def check_field(excel_val, tebra_val, field_name, compare_func, identifier):
                             if not compare_func(excel_val, tebra_val): mismatch_reasons.append(format_mismatch_reason(field_name, excel_val, tebra_val, identifier=identifier)); current_result_data["Status"] = "Mismatch"
                        compare_normalized_str = lambda x, y: normalize_string(x) == normalize_string(y)
                        compare_normalized_num_str = lambda x, y: normalize_code(str(x)) == normalize_code(str(y))
                        check_field(row.get('claimID'), get_nested_attribute(matching_tebra_charge, 'ID'), "Claim ID", compare_normalized_num_str, identifier=excel_claim_id)
                        check_field(row.get('EncounterID'), get_nested_attribute(matching_tebra_charge, 'EncounterID'), "Encounter ID", compare_normalized_num_str, identifier=excel_claim_id)
                        check_field(row.get('RenderingProvider'), get_nested_attribute(matching_tebra_charge, 'RenderingProviderName'), "Rendering Provider", compare_providers, identifier=excel_claim_id)
                        excel_ref_provider = row.get('ReferringProvider'); tebra_ref_provider = get_nested_attribute(matching_tebra_charge, 'ReferringProviderName')
                        if excel_ref_provider and not pd.isna(excel_ref_provider): check_field(excel_ref_provider, tebra_ref_provider, "Referring Provider", compare_providers, identifier=excel_claim_id)
                        elif tebra_ref_provider: mismatch_reasons.append(format_mismatch_reason("Referring Provider", excel_ref_provider, tebra_ref_provider, identifier=excel_claim_id)); current_result_data["Status"] = "Mismatch"
                        check_field(row.get('ServiceLocationName'), get_nested_attribute(matching_tebra_charge, 'ServiceLocationName'), "Service Location", compare_normalized_str, identifier=excel_claim_id)
                        if not compare_pos_codes(row.get('PlaceOfServiceCode'), get_nested_attribute(matching_tebra_charge, 'ServiceLocationPlaceOfServiceCode')): mismatch_reasons.append(format_mismatch_reason("PlaceOfService Code", row.get('PlaceOfServiceCode'), get_nested_attribute(matching_tebra_charge, 'ServiceLocationPlaceOfServiceCode'), identifier=excel_claim_id)); current_result_data["Status"] = "Mismatch"
                        try:
                             excel_units_str = str(row.get('ServiceUnitCount', '0')).strip(); excel_units = Decimal(excel_units_str) if excel_units_str else Decimal(0)
                             tebra_units_str = str(get_nested_attribute(matching_tebra_charge, 'Units', '0')).strip(); tebra_units = Decimal(tebra_units_str) if tebra_units_str else Decimal(0)
                             if excel_units != tebra_units: mismatch_reasons.append(format_mismatch_reason("Service Units", excel_units_str, tebra_units_str, identifier=excel_claim_id)); current_result_data["Status"] = "Mismatch"
                        except (TypeError, ValueError, decimal.InvalidOperation) as unit_err: mismatch_reasons.append(f"Unit Comparison Error for Claim ID {excel_claim_id}: {unit_err}"); current_result_data["Status"] = "Mismatch"
                        check_field(row.get('PriIns_CompanyName'), get_nested_attribute(matching_tebra_charge, 'PrimaryInsuranceCompanyName'), "Primary Ins Company", compare_normalized_str, identifier=excel_claim_id)
                        # Positional Modifier Check
                        for i in range(1, 5):
                            excel_mod_raw = row.get(f'ProcedureModifier{i}'); tebra_mod_raw = get_nested_attribute(matching_tebra_charge, f'ProcedureModifier{i}'); excel_mod_norm = normalize_code(excel_mod_raw); tebra_mod_norm = normalize_code(tebra_mod_raw); is_excel_empty = not excel_mod_norm; is_tebra_empty = not tebra_mod_norm
                            if is_excel_empty and is_tebra_empty: continue
                            if is_excel_empty != is_tebra_empty or excel_mod_norm != tebra_mod_norm: mismatch_reasons.append(format_mismatch_reason(f"Modifier {i}", excel_mod_raw, tebra_mod_raw, identifier=excel_claim_id)); current_result_data["Status"] = "Mismatch"
                        # Positional ICD Check
                        for i in range(1, 5):
                            excel_icd_raw = row.get(f'EncounterDiagnosisID{i}'); tebra_icd_raw = get_nested_attribute(matching_tebra_charge, f'EncounterDiagnosisID{i}'); excel_icd_norm = normalize_code(excel_icd_raw); tebra_icd_norm = normalize_code(tebra_icd_raw); is_excel_empty = not excel_icd_norm; is_tebra_empty = not tebra_icd_norm
                            if is_excel_empty and is_tebra_empty: continue
                            if is_excel_empty != is_tebra_empty or excel_icd_norm != tebra_icd_norm: mismatch_reasons.append(format_mismatch_reason(f"ICD {i}", excel_icd_raw, tebra_icd_raw, identifier=excel_claim_id)); current_result_data["Status"] = "Mismatch"

            # --- 6. Finalize Reason ---
            if current_result_data["Status"] == "Match": current_result_data["Reason"] = "Verified"
            elif mismatch_reasons: current_result_data["Reason"] = "; ".join(mismatch_reasons)
            elif current_result_data["Status"] == "Error" and current_result_data["Reason"] == "Processing started": current_result_data["Reason"] = "Unknown processing error occurred." # Update default reason if needed

            audit_results_list.append(current_result_data)
            # Don't print per-row results to UI

        # --- End of Loop ---
        end_time = time.time()
        status_text.text(f"Audit Completed in {end_time - start_time:.2f} seconds.")
        progress_bar.progress(1.0) # Ensure bar is full

        # --- 7. Post-Processing & Display ---
        if not audit_results_list: st.warning("No results were generated.")
        else:
            df_detailed_results = pd.DataFrame(audit_results_list); df_output = df.copy()
            status_map = {"Match": "Verified", "Mismatch": "Invalid", "Error": "Invalid", "Pending": "Invalid"}
            # Use original index if available for alignment, otherwise assume order is preserved
            df_output['Audit Results'] = df_detailed_results['Status'].map(status_map).fillna("Invalid").values
            df_output['Reason for Invalid'] = df_detailed_results.apply(lambda x: x['Reason'] if x['Status'] != "Match" else "", axis=1).values

            st.subheader("Audit Summary")
            summary_df = df_output["Audit Results"].value_counts().reset_index(); summary_df.columns = ['Audit Results', 'Count']
            st.dataframe(summary_df, hide_index=True)

            st.subheader("Invalid Records Summary")
            invalid_df = df_output[df_output["Audit Results"] == "Invalid"].copy()
            if not invalid_df.empty:
                 display_cols_summary = ['Excel Row', 'Audit Results', 'PatientID', 'DateOfService', 'ProcedureCode', 'Reason for Invalid']
                 # Add Excel Row number using index + 2 from original df if 'Original Excel Row Index' exists
                 if 'Original Excel Row Index' in invalid_df.columns: invalid_df.insert(0, 'Excel Row', invalid_df['Original Excel Row Index'] + 2)
                 else: invalid_df.insert(0, 'Excel Row', invalid_df.index + 2) # Fallback to current index
                 # Ensure all columns exist before trying to display
                 display_cols_summary = [col for col in display_cols_summary if col in invalid_df.columns]
                 st.dataframe(invalid_df[display_cols_summary], hide_index=True, use_container_width=True) # Use container width for better display
            else: st.success("✅ No invalid records found!")

            st.subheader("Download Full Results")
            @st.cache_data
            def to_excel(df_to_convert):
                output = io.BytesIO();
                with pd.ExcelWriter(output, engine='openpyxl') as writer: df_to_convert.to_excel(writer, index=False, sheet_name='Audit Results');
                return output.getvalue()
            excel_bytes = to_excel(df_output)
            timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            st.download_button(label="📥 Download Results as Excel", data=excel_bytes, file_name=f"Tebra_Audit_Results_{timestamp}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

else:
    # Show instructions if button not pressed or file not uploaded
    if not uploaded_file: st.info("Please upload an Excel file using the sidebar.")
    if not all([practice_name, customer_key, username, password]): st.info("Please enter Tebra credentials in the sidebar.")
    if uploaded_file and all([practice_name, customer_key, username, password]) and not run_button: st.info("Click 'Run Audit' to begin.")
