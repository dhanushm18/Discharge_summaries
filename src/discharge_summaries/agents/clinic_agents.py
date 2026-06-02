from crewai import Agent, LLM
from discharge_summaries.tools.clinic_tools import GetPageContentTool, SearchFullDossierTool, ReconcileMedicationsTool
from typing import List, Any

# Configure clinical LLM with 0 temperature for absolute factuality
clinical_llm = LLM(
    model="gpt-4o-mini",
    temperature=0.0,
    max_tokens=4000
)

class ClinicalAgents:
    """Specialized agents for the clinically-safe discharge summary system."""
    
    def coordinator_agent(self) -> Agent:
        return Agent(
            role="Clinical Coordinator",
            goal="Analyze running patient processing state, identify clinical gaps or safety concerns, and decide the next agent or action to run. Enforce safety at all times.",
            backstory="You are a Chief Medical Officer who oversees clinical documentation pipelines. Your top priority is clinical safety and preventing diagnostic/medication discrepancies. You do not make clinical claims; you direct specialized clinical agents to extract, reconcile, validate, and audit evidence.",
            llm=clinical_llm,
            verbose=True
        )

    def pdf_extraction_agent(self) -> Agent:
        return Agent(
            role="Clinical Document Extractor",
            goal="Retrieve raw clinical text from the patient record dossier, focusing on requested page numbers, and maintain 100% fidelity to the source pages.",
            backstory="You are a meticulous clinical archivist with decades of experience parsing dense, messy, and multi-page patient charts. You excel at extracting text verbatim and attributing it to exact page references.",
            tools=[GetPageContentTool(), SearchFullDossierTool()],
            llm=clinical_llm,
            verbose=True
        )

    def clinical_extraction_agent(self) -> Agent:
        return Agent(
            role="Clinical Fact Extractor",
            goal="Extract diagnoses, patient demographics, hospital course, procedures, allergies, discharge condition, follow-up instructions, and pending laboratory/culture results from patient records, citing the source page and verbatim evidence for every single fact.",
            backstory="You are a board-certified clinical documentation specialist. You read hospital logs, nursing notes, and discharge sheets to find concrete facts. You NEVER guess, extrapolate, or assume. If a fact is not directly written, you mark it as 'MISSING'.",
            tools=[GetPageContentTool(), SearchFullDossierTool()],
            llm=clinical_llm,
            verbose=True
        )

    def medication_reconciliation_agent(self) -> Agent:
        return Agent(
            role="Clinical Pharmacist Specialist",
            goal="Compare the patient's admission medications with the discharge medications. Detect additions, removals, and dosage changes, and check if a clear clinical reason is documented for every change. If the reason is missing, flag it for clinician review.",
            backstory="You are a Senior Hospital Pharmacist who manages medication transitions of care. Your sole focus is identifying dangerous drug discrepancies, discontinued chronic therapies, or newly added medications without a documented clinical rationale.",
            tools=[GetPageContentTool(), SearchFullDossierTool(), ReconcileMedicationsTool()],
            llm=clinical_llm,
            verbose=True
        )

    def conflict_detection_agent(self) -> Agent:
        return Agent(
            role="Clinical Conflict Investigator",
            goal="Review patient records across different pages and dates to detect contradictory diagnoses, inconsistent medication records, or mismatched timelines. NEVER try to resolve conflicts; compile and flag them clearly.",
            backstory="You are a clinical quality assurance auditor. Your job is to identify when different sheets, charts, or doctors disagree with each other. For example, if one page says Gastroenteritis and another says DKA, you flag this as a critical diagnostic mismatch.",
            tools=[GetPageContentTool(), SearchFullDossierTool()],
            llm=clinical_llm,
            verbose=True
        )

    def safety_validation_agent(self) -> Agent:
        return Agent(
            role="Clinical Safety Auditor",
            goal="Perform a strict verification pass on the extracted discharge summary draft. Audit every field to ensure it is supported by direct verbatim source evidence and has a valid page number citation. Flag any claim that is unverified or fabricated.",
            backstory="You are a medical safety compliance inspector. You are hyper-skeptical of any clinical assertion that lacks clear source attribution. You reject guesses, extrapolations, and unsourced details, and enforce the 'missing instead of guessing' policy.",
            tools=[GetPageContentTool(), SearchFullDossierTool()],
            llm=clinical_llm,
            verbose=True
        )

    def summary_generation_agent(self) -> Agent:
        return Agent(
            role="Discharge Summary Draft Writer",
            goal="Compile all confirmed clinical facts, reconciled medications, and source attributions into a structured, highly professional JSON and Markdown discharge summary draft.",
            backstory="You are a seasoned medical transcription writer who specializes in drafting clean, comprehensive, and legible discharge summaries for clinician review. Your drafts are structured, readable, and perfectly referenced.",
            llm=clinical_llm,
            verbose=True
        )

    def escalation_agent(self) -> Agent:
        return Agent(
            role="Clinical Escalation Specialist",
            goal="Aggregate all missing critical fields, pending test results, clinical conflicts, and unresolved medication changes into an urgent Clinician Review Escalation Report.",
            backstory="You are a Patient Safety Risk Officer. Your job is to make sure that any ambiguity, conflict, or risk in a patient's dossier is prominently highlighted at the very top of their medical chart, so a human clinician can make the final medical decision.",
            llm=clinical_llm,
            verbose=True
        )
