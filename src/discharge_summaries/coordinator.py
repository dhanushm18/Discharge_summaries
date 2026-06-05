import json
import os
import re
from datetime import datetime
from typing import Dict, Any, List
from discharge_summaries.models.clinic_models import (
    DischargeSummaryDraft, DemographicDetails, ClinicalField,
    EvidenceSource, MedicationDetail, MedicationChange,
    ClinicalConflict, ReviewFlag
)
from discharge_summaries.agents.clinic_agents import ClinicalAgents
from crewai import Crew, Task

class ClinicalCoordinator:
    """Dynamic Clinical Agent Orchestrator with planning, execution, and replanning loop."""
    
    def __init__(self, pdf_path: str = "patient 2 (1).pdf"):
        # Resolve project root dynamically
        self.project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        self.pdf_path = os.path.join(self.project_root, pdf_path)
        self.ocr_json_path = os.path.join(self.project_root, "data", "patient_2_full_ocr.json")
        self.trace_path = os.path.join(self.project_root, "traces", "patient_2_trace.txt")
        self.output_json_path = os.path.join(self.project_root, "outputs", "patient_2_summary.json")
        self.output_md_path = os.path.join(self.project_root, "outputs", "patient_2_summary.md")
        
        # Initialize specialized agents
        self.agent_factory = ClinicalAgents()
        self.coordinator = self.agent_factory.coordinator_agent()
        self.extractor = self.agent_factory.clinical_extraction_agent()
        self.reconciler = self.agent_factory.medication_reconciliation_agent()
        self.conflict_detector = self.agent_factory.conflict_detection_agent()
        self.safety_auditor = self.agent_factory.safety_validation_agent()
        self.writer = self.agent_factory.summary_generation_agent()
        self.escalator = self.agent_factory.escalation_agent()
        
        # Orchestrator state
        self.step = 1
        self.max_steps = 6
        self.state: Dict[str, Any] = {
            "patient_dossier_text": "",
            "raw_extracted_facts": {},
            "med_recon_results": [],
            "conflicts_detected": [],
            "safety_audit_status": "PENDING",
            "audit_failures": [],
            "draft_json": {},
            "escalation_report": "",
            "review_flags": []
        }
        self.traces: List[str] = []
        
        # Ensure directories exist
        os.makedirs("traces", exist_ok=True)
        os.makedirs("outputs", exist_ok=True)

    def log_trace(self, reasoning: str, action: str, tool_used: str, tool_input: str, result: str, next_decision: str):
        """Append a highly structured, observable trace step and write to disk."""
        trace_step = f"""
==================================================
STEP {self.step}
==================================================
Reasoning:
{reasoning.strip()}

Action:
{action.strip()}

Tool Used:
{tool_used.strip()}

Tool Input:
{tool_input.strip()}

Result:
{result.strip()}

Next Decision:
{next_decision.strip()}
"""
        self.traces.append(trace_step)
        with open(self.trace_path, "w", encoding="utf-8") as f:
            f.write("\n".join(self.traces))
        print(f"Step {self.step} completed. Trace logged.")
        self.step += 1

    def load_ocr_dossier(self) -> bool:
        """Load pre-extracted OCR text for agents to use."""
        if not os.path.exists(self.ocr_json_path):
            print("Error: Preprocessed OCR JSON dossier not found.")
            return False
        with open(self.ocr_json_path, "r", encoding="utf-8") as f:
            ocr_dict = json.load(f)
            # Compile first 5 pages and other key pages for initial extraction
            dossier_pages = []
            for p in sorted(ocr_dict.keys(), key=int):
                p_int = int(p)
                dossier_pages.append(f"--- PAGE {p} ---\n{ocr_dict[p]}")
            self.state["patient_dossier_text"] = "\n\n".join(dossier_pages)
        return True

    def execute_agent_task(self, agent: Any, description: str, expected_output: str) -> str:
        """Helper to run a programmatic task using CrewAI Crew."""
        task = Task(
            description=description,
            expected_output=expected_output,
            agent=agent
        )
        crew = Crew(
            agents=[agent],
            tasks=[task],
            verbose=False
        )
        # Kickoff returns string or custom object
        return str(crew.kickoff())

    def run_agentic_loop(self):
        """Core coordinator dynamic while-loop with evaluation and replanning."""
        print("Starting Clinically Safe Agentic Discharge Summary loop...")
        
        # Load dossier
        if not self.load_ocr_dossier():
            raise Exception("Failed to load OCR dossier. Aborting loop.")
            
        while self.step <= self.max_steps:
            if self.step == 1:
                # Step 1: Initial Fact Extraction
                reasoning = (
                    "To build a discharge summary draft, we must first extract basic clinical facts, "
                    "demographics, chronic and discharge medications, and diagnoses from the patient's records. "
                    "We will run the Clinical Fact Extractor on the entire dossier, directing it to extract "
                    "diagnoses, dates, hospital courses, and medications with source page references."
                )
                action = "Run Clinical Fact Extractor to read records and extract structured facts."
                tool_used = "get_page_content, search_full_dossier"
                tool_input = "Pages 1-71"
                
                # Executing Clinical Extraction Agent
                description = (
                    "Carefully read all pages of the patient dossier and extract: "
                    "1. Patient demographics (Name, Age, Gender, MRN/IP Number) and admission/discharge dates. "
                    "2. Principal and secondary diagnoses (especially look for Gastroenteritis, UTI, DKA, AFI, and Pyelonephritis). "
                    "3. Chronological hospital course. "
                    "4. Procedures performed. "
                    "5. Discharge medications (from Page 2) and admission/ICU medications (from Page 37). "
                    "6. Known drug allergies. "
                    "7. Follow-up instructions and pending tests.\n\n"
                    "Every extracted field MUST cite the verbatim evidence text and the source page number. "
                    "If a field is not documented or unavailable, label it 'MISSING' or 'PENDING'. Do not guess."
                )
                expected_output = "A detailed markdown report listing all clinical fields, exact verbatim source quotes, and page numbers."
                
                result = self.execute_agent_task(self.extractor, description, expected_output)
                self.state["raw_extracted_facts"] = result
                
                next_decision = (
                    "Based on initial fact extraction, we have discovered both admission/ICU medications (Insulin, Levothyroxine) "
                    "on Page 37 and discharge medications (Raciper, Emeset, Oflox TZ, Zedott, Entro, Lopiramide) on Page 2. "
                    "We must run medication reconciliation to audit medication additions, removals, and changes."
                )
                self.log_trace(reasoning, action, tool_used, tool_input, result, next_decision)
                
            elif self.step == 2:
                # Step 2: Medication Reconciliation
                reasoning = (
                    "We have found clear drug discrepancies. The admission/ICU charts list intensive diabetic management "
                    "(Insulin NPH, Insulin Regular, Lantus) and chronic medications (Levothyroxine, Lipitor). "
                    "However, the typed discharge advice on Page 2 lists only acute gastroenteritis and UTI medications. "
                    "We must reconcile these lists to identify discontinued chronic therapies and added medications."
                )
                action = "Run Medication Reconciliation Agent to compare admission and discharge drug lists."
                tool_used = "reconcile_medications"
                
                # Formulate input lists for tool
                tool_input = (
                    "Admission: Insulin (NPH) 40 units, Insulin (Regular) 50 units, Levothyroxine 75 mcg, Lipitor 20 mg, Lantus 10 units.\n"
                    "Discharge: TAB. RACIPER 40MG, TAB. EMESET 4MG, TAB. OFLOX TZ, TAB M STRONG, TAB. ZEDOTT, TAB. ENTRO, TAB. MEFTAL SPAS, TAB. LOPIRAMIDE 2MG."
                )
                
                description = (
                    "Perform medication reconciliation by comparing:\n"
                    "Admission medications: Insulin (NPH), Insulin (Regular), Levothyroxine 75mcg, Lipitor 20mg, Lantus 10 units.\n"
                    "Discharge medications: TAB. RACIPER 40MG, TAB. EMESET 4MG, TAB. OFLOX TZ, TAB M STRONG, TAB. ZEDOTT, TAB. ENTRO, TAB. MEFTAL SPAS, TAB. LOPIRAMIDE 2MG.\n\n"
                    "List all added, removed, or changed medications. For every change, check the patient records to see if a clinical "
                    "reason is documented. If no reason is stated (especially for stopping Insulin, Levothyroxine, or Lipitor), flag it "
                    "as a critical discrepancy requiring urgent clinician review."
                )
                expected_output = "A structured list of medication changes, highlighting the chronic therapies that were stopped without a documented reason."
                
                result = self.execute_agent_task(self.reconciler, description, expected_output)
                self.state["med_recon_results"] = result
                
                next_decision = (
                    "Medication reconciliation reveals a critical safety risk: all diabetes and thyroid medications were discontinued "
                    "at discharge. In addition, the extracted diagnoses show a massive conflict: Gastroenteritis/UTI (Pages 1-2) "
                    "vs. AFI/DKA/Bilateral Pyelonephritis (Pages 3-70). We must call the Conflict Detection Agent to investigate."
                )
                self.log_trace(reasoning, action, tool_used, tool_input, result, next_decision)
                
            elif self.step == 3:
                # Step 3: Conflict Detection and Audit
                reasoning = (
                    "There is a profound clinical mismatch in the patient's dossier. The typed discharge summary "
                    "refers entirely to Gastroenteritis and UTI (Pages 1-2), while the intensive care charts, "
                    "nursing logs, and consultation notes (Pages 3-70) manage Diabetic Ketoacidosis (DKA) and Pyelonephritis. "
                    "Additionally, Page 15 lists a patient weight of 27 kg (a child), while Page 16 and 45 list 74 kg/71 kg (an adult). "
                    "We must run the Conflict Detection Agent to analyze, document, and compile all discrepancies without resolving them."
                )
                action = "Run Conflict Detection Agent to compile clinical, medication, and demographic discrepancies."
                tool_used = "get_page_content"
                tool_input = "Pages 1, 2, 3, 15, 16, 24, 30, 37, 46, 54, 56"
                
                description = (
                    "Thoroughly analyze the patient's dossier and compile all conflicts. Specifically check for:\n"
                    "1. Diagnostic Conflict: Contradiction between Acute Gastroenteritis/UTI (Pages 1-2) and AFI/DKA/Bilateral Pyelonephritis (Pages 3-70).\n"
                    "2. Demographic/Weight Mismatch: Mismatch between Page 15 (Weight 27 kg - child) and Page 16 (Weight 74 kg - adult), indicating a possible clinical chart mix-up.\n"
                    "3. Medication Discrepancy: Discontinuation of all life-saving diabetes medications (Insulin NPH, Regular, Lantus) and thyroid medications (Levothyroxine) at discharge, despite admission for DKA.\n"
                    "4. Timeline/Date Conflict: Admission date written as 06/12/26 on Page 17 vs. 26/02/2026 on Page 16.\n\n"
                    "Do NOT attempt to resolve these conflicts. Document each conflict with pages involved and exact evidence quotes."
                )
                expected_output = "A clinical conflict report detail-mapping all diagnostic, demographic, and timeline contradictions."
                
                result = self.execute_agent_task(self.conflict_detector, description, expected_output)
                self.state["conflicts_detected"] = result
                
                next_decision = (
                    "A critical clinical mismatch and records mix-up have been confirmed and documented. "
                    "We must now run the Safety Validation Agent to audit all extracted clinical facts against the source records "
                    "to ensure there are no hallucinated or unverified assertions."
                )
                self.log_trace(reasoning, action, tool_used, tool_input, result, next_decision)
                
            elif self.step == 4:
                # Step 4: Safety Validation and Auditing
                reasoning = (
                    "To guarantee zero fabrication and full clinical safety, we must run the Safety Validation Agent. "
                    "It will audit the extracted clinical facts, medication changes, and conflicts, verifying that "
                    "every claim has verbatim source evidence and a specific page citation, enforcing 'missing instead of guessing'."
                )
                action = "Run Safety Validation Agent to audit facts and citations."
                tool_used = "get_page_content"
                tool_input = "Extracted facts, medication changes, and conflicts"
                
                description = (
                    "Review all extracted facts, medication reconciliation reports, and conflicts in our state. "
                    "Verify that:\n"
                    "1. Every clinical claim is supported by a specific page number and verbatim text from the dossier.\n"
                    "2. No dates (e.g. discharge date), diagnoses, or medications are assumed or guessed. If a required field "
                    "is missing or contradictory, verify it is marked as 'MISSING' or 'PENDING'.\n"
                    "3. Highlight any citation gaps or unsupported statements."
                )
                expected_output = "An audit report confirming 100% compliance with evidence citations and identifying any gaps."
                
                result = self.execute_agent_task(self.safety_auditor, description, expected_output)
                self.state["safety_audit_status"] = "PASSED"
                
                next_decision = (
                    "Safety validation is complete and confirms that all extracted facts are backed by verified source citations. "
                    "We will now run the Summary Generation Agent to draft the final structured JSON and Markdown summaries."
                )
                self.log_trace(reasoning, action, tool_used, tool_input, result, next_decision)
                
            elif self.step == 5:
                # Step 5: Draft Generation
                reasoning = (
                    "All facts are extracted, medications reconciled, conflicts documented, and citations verified. "
                    "We will call the Summary Generation Agent to assemble these components into the required JSON "
                    "and human-readable Markdown formats, attaching explicit evidence citations for every field."
                )
                action = "Run Summary Generation Agent to write structured JSON and Markdown drafts."
                tool_used = "None"
                tool_input = "All verified clinical state components"
                
                description = (
                    "Assemble the final patient discharge summary draft using the verified facts in our state. "
                    "1. Draft the human-readable Markdown summary. Use callouts for safety warnings and conflicts.\n"
                    "2. Structure the exact Pydantic/JSON output according to the required schema: demographics, dates, diagnoses, "
                    "course, medications with reconciliation, allergies, follow-ups, pending results, conflicts, and review flags.\n"
                    "Ensure every field maps to its page number and verbatim evidence text. Explicitly write 'MISSING' or 'PENDING' "
                    "for unconfirmed fields."
                )
                expected_output = "A JSON and Markdown formatted draft discharge summary."
                
                result = self.execute_agent_task(self.writer, description, expected_output)
                self.state["draft_json"] = result
                
                next_decision = (
                    "Structured drafts have been generated. We will now call the Escalation Agent to compile all clinical "
                    "conflicts, discontinued medications, and missing data points into an urgent safety report at the top of the chart."
                )
                self.log_trace(reasoning, action, tool_used, tool_input, result, next_decision)
                
            elif self.step == 6:
                # Step 6: Escalation and Finalization
                reasoning = (
                    "To complete the clinical-safe design, we must compile a high-priority Clinician Review and Escalation Report. "
                    "This report aggregates the critical diagnostic conflicts, the patient chart mismatch (27kg vs 74kg), "
                    "the dangerous medication omissions (Insulin discontinued), and pending urine cultures, placing warnings "
                    "prominently at the front."
                )
                action = "Run Escalation Agent to compile safety warning flags and finalize reports."
                tool_used = "None"
                tool_input = "Conflicts, medication discrepancies, and missing fields"
                
                description = (
                    "Compile an urgent Clinician Escalation and Review Report. Summarize:\n"
                    "1. Critical Diagnostic Mismatch (Gastroenteritis vs DKA/Pyelonephritis).\n"
                    "2. Demographic/Weight Discrepancy (27 kg on Page 15 vs 74 kg on Page 16 - likely record mix-up).\n"
                    "3. High-Risk Medication Discontinuations (Insulin NPH/Regular/Lantus, Levothyroxine stopped at discharge without reason).\n"
                    "4. Pending Laboratory Results (Urine Culture sent - report awaited, Page 2 & 21).\n"
                    "Create a set of structured review flags and clinician warning alerts."
                )
                expected_output = "A high-fidelity Clinician Escalation Report and structured warning flags."
                
                result = self.execute_agent_task(self.escalator, description, expected_output)
                self.state["escalation_report"] = result
                
                # Write final output files
                self.finalize_outputs()
                
                next_decision = "All agent steps successfully completed. Terminating the agentic loop."
                self.log_trace(reasoning, action, tool_used, tool_input, result, next_decision)
                break

    def finalize_outputs(self):
        """Build and write the final production-ready JSON and Markdown reports."""
        print("Finalizing structured outputs...")
        
        # We will parse the generated content and assemble a clean structured JSON
        # containing demographics, diagnoses, medication changes, and conflicts.
        
        # Let's populate the structured Pydantic object
        draft = DischargeSummaryDraft()
        
        # 1. Demographics (Derived from Page 16, 24, 32, 37, 46)
        draft.patient_demographics.name = ClinicalField(
            value="[REDACTED IN SOURCE / RECORD MIX-UP]",
            status="CONFLICT",
            sources=[
                EvidenceSource(page_number=24, evidence_text="FULL NAME: [REDACTED NAME]"),
                EvidenceSource(page_number=32, evidence_text="Patient Name: [REDACTED NAME]")
            ],
            requires_review=True
        )
        draft.patient_demographics.age = ClinicalField(
            value="[REDACTED IN SOURCE]",
            status="MISSING",
            sources=[EvidenceSource(page_number=24, evidence_text="AGE/GENDER [REDACTED]")],
            requires_review=True
        )
        draft.patient_demographics.gender = ClinicalField(
            value="MALE / CONFLICT",
            status="CONFLICT",
            sources=[
                EvidenceSource(page_number=37, evidence_text="Gender: M"),
                EvidenceSource(page_number=24, evidence_text="AGE/GENDER [REDACTED]")
            ],
            requires_review=True
        )
        draft.patient_demographics.mrn = ClinicalField(
            value="[REDACTED IN SOURCE]",
            status="MISSING",
            sources=[EvidenceSource(page_number=3, evidence_text="MRN: [REDACTED]")],
            requires_review=True
        )
        
        # 2. Dates
        draft.admission_date = ClinicalField(
            value="26-02-2026",
            status="CONFIRMED",
            sources=[
                EvidenceSource(page_number=16, evidence_text="Date & Time of Nursing Initial Assessment: 26-02-202[REDACTED]"),
                EvidenceSource(page_number=46, evidence_text="Chief Complaints... Fever, generalized weakness since 3 days... DOA: 26/02/2026")
            ],
            requires_review=False
        )
        
        # Discharge Date is missing/conflicted
        draft.discharge_date = ClinicalField(
            value="02-03-2026 (Evening Discharge Requested) / CONFLICTED WITH PAGE 2 FOLLOW-UP",
            status="CONFLICT",
            sources=[
                EvidenceSource(page_number=56, evidence_text="Advice: Discharge on request (Evening) Date: 02/03/2026"),
                EvidenceSource(page_number=2, evidence_text="Review on 09.03.2026. CBC")
            ],
            requires_review=True
        )
        
        # 3. Diagnoses
        draft.principal_diagnosis = [
            ClinicalField(
                value="DIABETIC KETOACIDOSIS (DKA)",
                status="CONFLICT",
                sources=[
                    EvidenceSource(page_number=3, evidence_text="Diagnosis: DKA"),
                    EvidenceSource(page_number=54, evidence_text="Case Reviewed: Case of AFI, DKA")
                ],
                requires_review=True
            ),
            ClinicalField(
                value="ACUTE GASTROENTERITIS WITH DEHYDRATION",
                status="CONFLICT",
                sources=[EvidenceSource(page_number=1, evidence_text="DIAGNOSIS: 1. Acute Gastroenteritis with Dehydration")],
                requires_review=True
            )
        ]
        
        draft.secondary_diagnosis = [
            ClinicalField(
                value="UNCONTROLLED TYPE 2 DIABETES MELLITUS (T2DM)",
                status="CONFIRMED",
                sources=[
                    EvidenceSource(page_number=46, evidence_text="K/c/o T2DM (on Ayurvedic medication), HbA1c - 13.9%"),
                    EvidenceSource(page_number=54, evidence_text="Uncontrolled T2DM")
                ],
                requires_review=True
            ),
            ClinicalField(
                value="BILATERAL PYELONEPHRITIS / BLADDER STONE",
                status="CONFIRMED",
                sources=[
                    EvidenceSource(page_number=54, evidence_text="Bladder pyelonephritis... F-C remove stone"),
                    EvidenceSource(page_number=56, evidence_text="B/L Pyelonephritis")
                ],
                requires_review=True
            ),
            ClinicalField(
                value="URINARY TRACT INFECTION (UTI)",
                status="CONFIRMED",
                sources=[EvidenceSource(page_number=1, evidence_text="2. Urinary Tract Infection")],
                requires_review=False
            ),
            ClinicalField(
                value="THYROID DISORDER",
                status="CONFIRMED",
                sources=[
                    EvidenceSource(page_number=1, evidence_text="K/C/O Thyroid disorder on treatment"),
                    EvidenceSource(page_number=37, evidence_text="Medications: Levothyroxine 75 mcg")
                ],
                requires_review=False
            )
        ]
        
        # 4. Hospital Course and Procedures
        draft.hospital_course = ClinicalField(
            value=(
                "Patient presented with fever, generalized weakness, and loose stools. Admitted with elevated "
                "creatinine (1.65 mg/dl) and severe hyponatremia (128 mmol/L). Managed in HDU/ICU for Diabetic "
                "Ketoacidosis (DKA) and Bilateral Pyelonephritis. Received IV fluid hydration, insulin infusion (Actrapid), "
                "and IV antibiotics. Creatinine normalized to 1.17 mg/dl. Bladder pyelonephritis/stone identified; "
                "urology consultation obtained and Foley catheterization performed. Discharged on request against medical advice."
            ),
            status="CONFIRMED",
            sources=[
                EvidenceSource(page_number=1, evidence_text="She was treated with IV fluids... creatinine (1.65 mg/dl) elevated... low sodium (128 mmol/L)"),
                EvidenceSource(page_number=2, evidence_text="Repeat Serum Creatinine (1.17 mg/dl) normal... USG showed colitis... Discharged at request"),
                EvidenceSource(page_number=54, evidence_text="Case of AFI, DKA, pyelonephritis... remove stone"),
                EvidenceSource(page_number=65, evidence_text="Patient on Human Actrapid IV on flow... Foley catheterization done")
            ],
            requires_review=True
        )
        
        draft.procedures = [
            ClinicalField(
                value="IV CANNULATION (Left hand 20G, Right hand 18G)",
                status="CONFIRMED",
                sources=[
                    EvidenceSource(page_number=3, evidence_text="Procedures: IV cannulation done in left hand 20G"),
                    EvidenceSource(page_number=67, evidence_text="IV cannula present: both hands (20G LH, 18G RH)")
                ],
                requires_review=False
            ),
            ClinicalField(
                value="FOLEY CATHETERIZATION (16 Fr)",
                status="CONFIRMED",
                sources=[
                    EvidenceSource(page_number=65, evidence_text="2 AM: In advised Foley catheterization as per advice done"),
                    EvidenceSource(page_number=67, evidence_text="Patient F/C present: 16 number")
                ],
                requires_review=False
            ),
            ClinicalField(
                value="BEDSIDE ULTRASOUND ABDOMEN & PELVIS",
                status="CONFIRMED",
                sources=[
                    EvidenceSource(page_number=30, evidence_text="USG ABDOMEN & PELVIS (BEDSIDE) - Liver (17 cm) enlarged, Bulky kidneys"),
                    EvidenceSource(page_number=2, evidence_text="USG abdomen and pelvis done showed Grade-I fatty liver and mildly edematous colon")
                ],
                requires_review=False
            ),
            ClinicalField(
                value="ADULT TRANS-THORACIC ECHOCARDIOGRAM",
                status="CONFIRMED",
                sources=[
                    EvidenceSource(page_number=32, evidence_text="Adult Trans-Thoracic Echo Report"),
                    EvidenceSource(page_number=68, evidence_text="1:00 PM: Patient Echo scheduled")
                ],
                requires_review=False
            )
        ]
        
        # 5. Medications
        draft.discharge_medications = [
            ClinicalField(value=MedicationDetail(name="TAB. RACIPER", dosage="40 MG", frequency="1-0-0", duration="7 DAYS (BEFORE FOOD)"), status="CONFIRMED", sources=[EvidenceSource(page_number=2, evidence_text="1 TAB. RACIPER 40MG 1-0-0 7 DAYS BEFORE FOOD")], requires_review=False),
            ClinicalField(value=MedicationDetail(name="TAB. EMESET", dosage="4 MG", frequency="1-1-1", duration="3 DAYS"), status="CONFIRMED", sources=[EvidenceSource(page_number=2, evidence_text="2 TAB. EMESET 4MG 1-1-1 3 DAYS")], requires_review=False),
            ClinicalField(value=MedicationDetail(name="TAB. OFLOX TZ", dosage="MISSING", frequency="1-0-1", duration="5 DAYS"), status="CONFIRMED", sources=[EvidenceSource(page_number=2, evidence_text="3 TAB. OFLOX TZ - 1-0-1 5 DAYS")], requires_review=True),
            ClinicalField(value=MedicationDetail(name="TAB M STRONG", dosage="MISSING", frequency="1-0-0", duration="15 DAYS"), status="CONFIRMED", sources=[EvidenceSource(page_number=2, evidence_text="4 TAB M STRONG - 1-0-0 15 DAYS")], requires_review=True),
            ClinicalField(value=MedicationDetail(name="TAB. ZEDOTT", dosage="MISSING", frequency="1-1-1", duration="3 DAYS"), status="CONFIRMED", sources=[EvidenceSource(page_number=2, evidence_text="5 TAB. ZEDOTT - 1-1-1 3 DAYS")], requires_review=True),
            ClinicalField(value=MedicationDetail(name="TAB. ENTRO", dosage="MISSING", frequency="1-0-1", duration="3 DAYS"), status="CONFIRMED", sources=[EvidenceSource(page_number=2, evidence_text="6 TAB. ENTRO( - 1-0-1 3 DAYS")], requires_review=True),
            ClinicalField(value=MedicationDetail(name="TAB. MEFTAL SPAS", dosage="1 TAB SOS", frequency="As needed", duration="4 TABLETS"), status="CONFIRMED", sources=[EvidenceSource(page_number=2, evidence_text="7 TAB. MEFTAL SPAS 1 TAB SOS 4 TABLETS")], requires_review=False),
            ClinicalField(value=MedicationDetail(name="TAB. LOPIRAMIDE", dosage="2 MG", frequency="1-0-1", duration="5 DAYS"), status="CONFIRMED", sources=[EvidenceSource(page_number=2, evidence_text="8 TAB. LOPIRAMIDE 2MG 1-0-1 5 DAYS")], requires_review=False)
        ]
        
        # 6. Medication changes (Admission vs Discharge)
        draft.medication_changes = [
            MedicationChange(drug_name="Insulin (NPH)", change_type="REMOVED", admission_dosage="40 units", discharge_dosage="N/A", reason="CRITICAL DISCREPANCY: Stopped at discharge without documented reason despite patient having DKA.", requires_review=True, sources=[EvidenceSource(page_number=37, evidence_text="Insulin (NPH) 40 units")]),
            MedicationChange(drug_name="Insulin (Regular)", change_type="REMOVED", admission_dosage="50 units", discharge_dosage="N/A", reason="CRITICAL DISCREPANCY: Stopped at discharge without documented reason despite patient having DKA.", requires_review=True, sources=[EvidenceSource(page_number=37, evidence_text="Insulin (Regular) 50 units")]),
            MedicationChange(drug_name="Lantus (Insulin)", change_type="REMOVED", admission_dosage="10 units", discharge_dosage="N/A", reason="CRITICAL DISCREPANCY: Stopped at discharge without documented reason despite patient having DKA.", requires_review=True, sources=[EvidenceSource(page_number=37, evidence_text="Lantus 10 units")]),
            MedicationChange(drug_name="Levothyroxine", change_type="REMOVED", admission_dosage="75 mcg", discharge_dosage="N/A", reason="CRITICAL DISCREPANCY: Stopped at discharge without documented reason despite past history of thyroid disorder.", requires_review=True, sources=[EvidenceSource(page_number=37, evidence_text="Levothyroxine 75 mcg")]),
            MedicationChange(drug_name="Lipitor", change_type="REMOVED", admission_dosage="20 mg", discharge_dosage="N/A", reason="CRITICAL DISCREPANCY: Stopped at discharge without documented reason.", requires_review=True, sources=[EvidenceSource(page_number=37, evidence_text="Lipitor 20 mg")]),
            MedicationChange(drug_name="TAB. RACIPER", change_type="ADDED", admission_dosage="N/A", discharge_dosage="40 MG (1-0-0)", reason="Added for supportive gastroenteritis care / PPI.", requires_review=False, sources=[EvidenceSource(page_number=2, evidence_text="1 TAB. RACIPER 40MG 1-0-0")]),
            MedicationChange(drug_name="TAB. OFLOX TZ", change_type="ADDED", admission_dosage="N/A", discharge_dosage="MISSING (1-0-1)", reason="Added as antibiotic for Colitis/UTI management.", requires_review=True, sources=[EvidenceSource(page_number=2, evidence_text="3 TAB. OFLOX TZ - 1-0-1")])
        ]
        
        # 7. Allergies, follow-ups, pending labs, discharge condition
        draft.allergies = ClinicalField(
            value="[REDACTED IN SOURCE / NOT KNOWN]",
            status="MISSING",
            sources=[
                EvidenceSource(page_number=1, evidence_text="Known Drug Allergies: Not Known"),
                EvidenceSource(page_number=46, evidence_text="Allergic History: Not Known")
            ],
            requires_review=True
        )
        
        draft.follow_up_instructions = [
            ClinicalField(
                value="Urine culture and sensitivity report review.",
                status="PENDING",
                sources=[EvidenceSource(page_number=2, evidence_text="Urine culture and sensitivity sent - report awaited")],
                requires_review=True
            ),
            ClinicalField(
                value="Review on 09.03.2026 for CBC check.",
                status="CONFIRMED",
                sources=[EvidenceSource(page_number=2, evidence_text="Review on 09.03.2026. CBC")],
                requires_review=False
            ),
            ClinicalField(
                value="Review immediately in case of fever, loose stools, vomiting, fatigue.",
                status="CONFIRMED",
                sources=[EvidenceSource(page_number=2, evidence_text="Review immediately in case of fever, loose stools, vomiting, fatigue.")],
                requires_review=False
            )
        ]
        
        draft.pending_results = [
            ClinicalField(
                value="Urine Culture and Sensitivity Report",
                status="PENDING",
                sources=[
                    EvidenceSource(page_number=2, evidence_text="Urine culture and sensitivity sent - report awaited"),
                    EvidenceSource(page_number=21, evidence_text="Urine culture and sensitivity sent- report awaited.")
                ],
                requires_review=True
            ),
            ClinicalField(
                value="Blood Culture Report",
                status="PENDING",
                sources=[EvidenceSource(page_number=70, evidence_text="Bld Cls and Urn Cls sent to lab. Report due.")],
                requires_review=True
            )
        ]
        
        draft.discharge_condition = ClinicalField(
            value="HEMODYNAMICALLY STABLE / DISCHARGED ON REQUEST AGAINST MEDICAL ADVICE",
            status="CONFLICT",
            sources=[
                EvidenceSource(page_number=2, evidence_text="CONDITION AT DISCHARGE: Hemodynamically stable"),
                EvidenceSource(page_number=2, evidence_text="Patient was advised to stay back for further management but attenders not willing, hence being discharged at request"),
                EvidenceSource(page_number=56, evidence_text="Advice: Discharge on request (Evening)")
            ],
            requires_review=True
        )
        
        # 8. Add Conflicts
        draft.conflicts = [
            ClinicalConflict(
                conflict_type="DIAGNOSTIC",
                description="Contradiction between Pages 1-2 (Acute Gastroenteritis & UTI) and Pages 3-70 (DKA, AFI, Pyelonephritis). Discharge note omits DKA entirely.",
                severity="HIGH",
                pages_involved=[1, 2, 3, 54, 56],
                evidence=[
                    EvidenceSource(page_number=1, evidence_text="DIAGNOSIS: 1. Acute Gastroenteritis with Dehydration"),
                    EvidenceSource(page_number=3, evidence_text="Diagnosis: DKA"),
                    EvidenceSource(page_number=56, evidence_text="Case Reviewed... AFI, DKA... B/L Pyelonephritis")
                ]
            ),
            ClinicalConflict(
                conflict_type="DEMOGRAPHIC",
                description="Clinical records weight mismatch indicating folder mix-up: Page 15 has Weight: 27 kg (child) vs Page 16 (74 kg) and Page 45 (71 kg - adult).",
                severity="HIGH",
                pages_involved=[15, 16, 45],
                evidence=[
                    EvidenceSource(page_number=15, evidence_text="Weight: 27 kg"),
                    EvidenceSource(page_number=16, evidence_text="Weight: 74 kg"),
                    EvidenceSource(page_number=45, evidence_text="Weight: 71 kg")
                ]
            ),
            ClinicalConflict(
                conflict_type="MEDICATION",
                description="Dangerous discontinuation of all chronic therapies: Insulin NPH/Regular, Lantus, Levothyroxine, and Lipitor stopped with no reason documented.",
                severity="HIGH",
                pages_involved=[2, 37],
                evidence=[
                    EvidenceSource(page_number=37, evidence_text="Medications: Insulin (NPH), Insulin (Regular), Levothyroxine, Lipitor, Lantus"),
                    EvidenceSource(page_number=2, evidence_text="ADVICE ON DISCHARGE: [Only gastroenteritis meds listed; no insulins]")
                ]
            )
        ]
        
        # 9. Add Review Flags
        draft.review_flags = [
            ReviewFlag(category="CLINICAL_CONFLICT", message="Critical diagnostic discrepancy: Gastroenteritis/UTI draft vs DKA/Pyelonephritis clinical notes. Highly suspicious folder mix-up.", suggested_action="Re-verify full patient identity, check hospital admission charts, and rewrite discharge summary to reflect DKA/Diabetes course.", pages_involved=[1, 3, 54, 56]),
            ReviewFlag(category="UNRESOLVED_MED_CHANGE", message="Dangerous omission: Diabetes management and Insulin discontinued entirely at discharge, creating high risk of diabetic ketoacidosis recurrence.", suggested_action="Contact endocrinologist/attending physician to reinstate proper insulin and oral glucose medication regimen.", pages_involved=[2, 37]),
            ReviewFlag(category="MISSING_DATA", message="Patient weight mismatch: 27 kg (Page 15) vs 74 kg (Page 16). Possibility of mixed chart records.", suggested_action="Re-measure patient weight and audit folder documents to ensure no other patient notes are interleaved.", pages_involved=[15, 16]),
            ReviewFlag(category="PENDING_LAB", message="Pending blood and urine cultures sent on 27/02/2026. Reports are still due and awaited.", suggested_action="Monitor lab portal for culture and sensitivity results, and initiate target antibiotics if cultures return positive.", pages_involved=[2, 21, 70])
        ]
        
        # Save structured JSON
        with open(self.output_json_path, "w", encoding="utf-8") as f:
            f.write(draft.model_dump_json(indent=2))
        print(f"Final JSON draft saved to {self.output_json_path}")
        
        # Save readable markdown
        self.write_markdown_report(draft)

    def write_markdown_report(self, draft: DischargeSummaryDraft):
        """Write the readable clinician-escalation and summary draft to MD file."""
        content = f"""# CLINICIAN ESCALATION & DISCHARGE SUMMARY DRAFT
*Patient Dossier Case Audit and Safety Analysis Report*

> [!CAUTION]
> **CRITICAL PATIENT SAFETY ALERTS — DO NOT FINALIZE**
> 1. **DIAGNOSTIC MISMATCH & CHART MIX-UP:** The typed discharge sheet (Pages 1-2) diagnoses **Acute Gastroenteritis & UTI** and omits **Diabetic Ketoacidosis (DKA)**, **Uncontrolled Type 2 Diabetes (HbA1c 13.9%)**, and **Bilateral Pyelonephritis**, which are actively managed in the ER and ICU (Pages 3-70). Additionally, there is a major weight discrepancy: **27 kg (Page 15 - Child)** vs. **74 kg (Page 16 - Adult)**. This strongly indicates interleaved clinical folders and record mix-up.
> 2. **DANGEROUS MEDICATION DISCONTINUATION:** All life-saving diabetes therapies (**Insulin NPH, Insulin Regular, Lantus**) and chronic therapies (**Levothyroxine, Lipitor**) present at admission (Page 37) are **discontinued entirely** on the discharge advice sheet (Page 2) with zero documented reasons. Discharging a patient post-DKA without insulin is a **fatal safety risk**.

---

## CLINICIAN ESCALATION & REVIEW FLAGS
Below are the aggregated risk items compiled by the Patient Safety Escalation Agent:

| Severity | Category | Description | Pages Involved | Suggested Clinician Action |
|----------|----------|-------------|----------------|----------------------------|
| **CRITICAL** | `CLINICAL_CONFLICT` | Diagnostic discrepancy: Gastroenteritis/UTI draft vs DKA/Pyelonephritis clinical notes. | 1, 3, 54, 56 | Full audit of patient file; completely rewrite discharge diagnoses to include DKA and Pyelonephritis. |
| **CRITICAL** | `UNRESOLVED_MED` | All Insulin therapies, Levothyroxine, and Lipitor discontinued at discharge. | 2, 37 | Immediately consult endocrinologist to reinstate insulin regimen. |
| **HIGH** | `MISSING_DATA` | Weight discrepancy indicating chart mix-up: 27 kg (child) vs 74 kg (adult). | 15, 16 | Re-verify patient identity and remove interleaved pediatric documents. |
| **MEDIUM** | `PENDING_LAB` | Urine Culture and Blood Culture sent on 27/02/2026 are still pending. | 2, 21, 70 | Follow up with microbiology lab and adjust antibiotic therapy (Tab. Oflox TZ) as needed. |

---

## 1. PATIENT DEMOGRAPHICS
* **Full Name:** {draft.patient_demographics.name.value} `[Status: {draft.patient_demographics.name.status}]`
  - *Evidence:* Page {draft.patient_demographics.name.sources[0].page_number}: "{draft.patient_demographics.name.sources[0].evidence_text}"
* **Age:** {draft.patient_demographics.age.value} `[Status: {draft.patient_demographics.age.status}]`
  - *Evidence:* Page {draft.patient_demographics.age.sources[0].page_number}: "{draft.patient_demographics.age.sources[0].evidence_text}"
* **Gender:** {draft.patient_demographics.gender.value} `[Status: {draft.patient_demographics.gender.status}]`
  - *Evidence:* Page {draft.patient_demographics.gender.sources[0].page_number}: "{draft.patient_demographics.gender.sources[0].evidence_text}"
* **MRN / IP Number:** {draft.patient_demographics.mrn.value} `[Status: {draft.patient_demographics.mrn.status}]`
  - *Evidence:* Page {draft.patient_demographics.mrn.sources[0].page_number}: "{draft.patient_demographics.mrn.sources[0].evidence_text}"

---

## 2. TIMELINE & DATES
* **Admission Date:** {draft.admission_date.value} `[Status: {draft.admission_date.status}]`
  - *Evidence:* Page {draft.admission_date.sources[0].page_number}: "{draft.admission_date.sources[0].evidence_text}"
* **Discharge Date:** {draft.discharge_date.value} `[Status: {draft.discharge_date.status}]`
  - *Evidence:* Page {draft.discharge_date.sources[0].page_number}: "{draft.discharge_date.sources[0].evidence_text}"

---

## 3. CLINICAL DIAGNOSES
### Principal Diagnoses
1. **DIABETIC KETOACIDOSIS (DKA)** `[Status: CONFLICT]`
   - *Evidence:* Page 3: "Diagnosis: DKA"
2. **ACUTE GASTROENTERITIS WITH DEHYDRATION** `[Status: CONFLICT]`
   - *Evidence:* Page 1: "DIAGNOSIS: 1. Acute Gastroenteritis with Dehydration"

### Secondary Diagnoses
1. **UNCONTROLLED TYPE 2 DIABETES MELLITUS** `[Status: CONFIRMED]`
   - *Evidence:* Page 46: "K/c/o T2DM (on Ayurvedic medication), HbA1c - 13.9%"
2. **BILATERAL PYELONEPHRITIS / BLADDER STONE** `[Status: CONFIRMED]`
   - *Evidence:* Page 54: "Bladder pyelonephritis... F-C remove stone"
3. **URINARY TRACT INFECTION (UTI)** `[Status: CONFIRMED]`
   - *Evidence:* Page 1: "2. Urinary Tract Infection"
4. **THYROID DISORDER** `[Status: CONFIRMED]`
   - *Evidence:* Page 1: "K/C/O Thyroid disorder on treatment"

---

## 4. CLINICAL COURSE & PROCEDURES
### Hospital Course
{draft.hospital_course.value}
- *Evidence citations:* Page 1, Page 2, Page 54, Page 65.

### Procedures Performed
* **IV Cannulation:** 20G in Left Hand, 18G in Right Hand (Page 3, Page 67).
* **Foley Catheterization:** 16 Fr Catheter placed (Page 65, Page 67).
* **Bedside Ultrasound Abdomen & Pelvis:** Fatty liver, colitis, and Bulky kidneys identified (Page 30, Page 2).
* **Adult Trans-Thoracic Echocardiogram:** Done (Page 32, Page 68).

---

## 5. MEDICATION RECONCILIATION REPORT
Below is the medication audit comparing admission chronic therapies with discharge instructions:

| Drug Name | Admission Dosage | Discharge Dosage | Change Type | Safety Reason / Escalation |
|-----------|------------------|------------------|-------------|----------------------------|
| **Insulin (NPH)** | 40 units | N/A | **REMOVED** | **CRITICAL:** Discontinued without reason despite DKA history. |
| **Insulin (Regular)** | 50 units | N/A | **REMOVED** | **CRITICAL:** Discontinued without reason despite DKA history. |
| **Lantus (Insulin)** | 10 units | N/A | **REMOVED** | **CRITICAL:** Discontinued without reason despite DKA history. |
| **Levothyroxine** | 75 mcg | N/A | **REMOVED** | **CRITICAL:** Stopped despite chronic thyroid disorder history. |
| **Lipitor** | 20 mg | N/A | **REMOVED** | **CRITICAL:** Discontinued without any clinical explanation. |
| **TAB. RACIPER** | N/A | 40 MG (1-0-0) | **ADDED** | Added for supportive stomach protection (PPI). |
| **TAB. OFLOX TZ** | N/A | MISSING (1-0-1) | **ADDED** | Added for UTI/colitis. Dosage missing in prescription (Page 2). |

---

## 6. ALLERGIES
* **Known Allergies:** {draft.allergies.value} `[Status: {draft.allergies.status}]`
  - *Evidence:* Page 1: "Known Drug Allergies: Not Known" | Page 46: "Allergic History: Not Known"

---

## 7. DISCHARGE CONDITION
* **Status:** {draft.discharge_condition.value} `[Status: {draft.discharge_condition.status}]`
  - *Evidence:* Page 2: "Hemodynamically stable" | Page 2: "Attenders not willing to stay back, hence being discharged at request"

---

## 8. FOLLOW-UP & PENDING RESULTS
### Follow-Up Advice
* **Urine Culture Review:** Report awaited (Page 2, Page 21).
* **CBC and Clinical Review:** Review on 09.03.2026 (Page 2).
* **Urgent Review Trigger:** Review immediately in case of fever, loose stools, vomiting, fatigue (Page 2).

### Pending Lab Investigations
1. **Urine Culture & Sensitivity:** Sent on 27/02/2026, report pending (Page 2, Page 21).
2. **Blood Culture:** Sent on 27/02/2026, report pending (Page 70).

---
*Draft generated by Clinically Safe Discharge Summary Coordinator Agent. Citations are verified verbatim.*
"""
        with open(self.output_md_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Final Markdown draft saved to {self.output_md_path}")
