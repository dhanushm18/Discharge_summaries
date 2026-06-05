from crewai.tools import BaseTool
from pydantic import Field, BaseModel
import json
import os
import re
from typing import List, Dict, Any, Union

# Define input schemas for tools for CrewAI compatibility
class GetPageContentInput(BaseModel):
    pages: List[int] = Field(description="List of 1-indexed page numbers to read content from.")

class SearchFullDossierInput(BaseModel):
    query: str = Field(description="Keyword or regex pattern to search for in the medical dossier.")

class MedicationReconciliationInput(BaseModel):
    admission_meds: List[Dict[str, str]] = Field(description="List of dictionaries of admission medications, with keys: 'name', 'dosage', 'frequency', 'duration'.")
    discharge_meds: List[Dict[str, str]] = Field(description="List of dictionaries of discharge medications, with keys: 'name', 'dosage', 'frequency', 'duration'.")


class GetPageContentTool(BaseTool):
    name: str = "get_page_content"
    description: str = "Reads the exact transcribed text of specific 1-indexed page numbers from the patient dossier. Use this to inspect specific pages for clinical details."
    args_schema: Any = GetPageContentInput
    
    def _run(self, pages: List[int]) -> str:
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        json_path = os.path.join(project_root, "data", "patient_2_full_ocr.json")
        if not os.path.exists(json_path):
            return "Error: Transcribed patient JSON dossier is missing. Please run OCR preprocessing."
            
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            return f"Error loading dossier: {e}"
            
        results = []
        for p in pages:
            p_str = str(p)
            if p_str in data:
                results.append(f"--- PAGE {p} ---\n{data[p_str]}")
            else:
                results.append(f"--- PAGE {p} ---\n[Page not found in dossier]")
        return "\n\n".join(results)


class SearchFullDossierTool(BaseTool):
    name: str = "search_full_dossier"
    description: str = "Searches the entire patient medical dossier for a query string or keyword (case-insensitive) and returns a list of pages and snippets containing matches."
    args_schema: Any = SearchFullDossierInput
    
    def _run(self, query: str) -> str:
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        json_path = os.path.join(project_root, "data", "patient_2_full_ocr.json")
        if not os.path.exists(json_path):
            return "Error: Transcribed patient JSON dossier is missing."
            
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            return f"Error loading dossier: {e}"
            
        matches = []
        query_lower = query.lower()
        for p_str, text in sorted(data.items(), key=lambda x: int(x[0])):
            if query_lower in text.lower():
                # find context snippets
                lines = text.split("\n")
                snippets = []
                for line in lines:
                    if query_lower in line.lower():
                        snippets.append(line.strip())
                snippet_str = " | ".join(snippets[:3])
                matches.append(f"Page {p_str}: matches found. Snippets: {snippet_str[:150]}...")
                
        if not matches:
            return f"No matches found for query '{query}' in the entire dossier."
            
        return "\n".join(matches)


class ReconcileMedicationsTool(BaseTool):
    name: str = "reconcile_medications"
    description: str = "Compares admission medications vs discharge medications. Automatically identifies added, removed, or dose-changed medications. If a reason for change is not documented, flags for review."
    args_schema: Any = MedicationReconciliationInput
    
    def _run(self, admission_meds: List[Dict[str, str]], discharge_meds: List[Dict[str, str]]) -> str:
        # Standardize names to lower for comparison
        adm_dict = {m['name'].lower().strip(): m for m in admission_meds}
        dis_dict = {m['name'].lower().strip(): m for m in discharge_meds}
        
        changes = []
        
        # Check for additions and dose changes
        for d_name, d_med in dis_dict.items():
            if d_name not in adm_dict:
                # Added medication
                changes.append({
                    "drug_name": d_med['name'],
                    "change_type": "ADDED",
                    "admission_dosage": "N/A",
                    "discharge_dosage": f"{d_med['dosage']} ({d_med['frequency']})",
                    "reason": "MISSING - Needs Clinician Review",
                    "requires_review": True
                })
            else:
                # Exists in both, check dosage/frequency change
                a_med = adm_dict[d_name]
                if a_med['dosage'].lower().strip() != d_med['dosage'].lower().strip() or a_med['frequency'].lower().strip() != d_med['frequency'].lower().strip():
                    changes.append({
                        "drug_name": d_med['name'],
                        "change_type": "DOSE_CHANGED",
                        "admission_dosage": f"{a_med['dosage']} ({a_med['frequency']})",
                        "discharge_dosage": f"{d_med['dosage']} ({d_med['frequency']})",
                        "reason": "MISSING - Needs Clinician Review",
                        "requires_review": True
                    })
                    
        # Check for removals
        for a_name, a_med in adm_dict.items():
            if a_name not in dis_dict:
                # Removed medication
                changes.append({
                    "drug_name": a_med['name'],
                    "change_type": "REMOVED",
                    "admission_dosage": f"{a_med['dosage']} ({a_med['frequency']})",
                    "discharge_dosage": "N/A",
                    "reason": "MISSING - Needs Clinician Review",
                    "requires_review": True
                })
                
        if not changes:
            return "Medication Reconciliation: No changes found between admission and discharge medications."
            
        return json.dumps(changes, indent=2)
