from pydantic import BaseModel, Field
from typing import List, Union, Generic, TypeVar, Dict, Any, Optional

T = TypeVar('T')

class EvidenceSource(BaseModel):
    page_number: int
    evidence_text: str

class ClinicalField(BaseModel, Generic[T]):
    value: Union[T, str] = "MISSING"
    status: str = "MISSING"  # "CONFIRMED", "MISSING", "PENDING", "CONFLICT"
    sources: List[EvidenceSource] = Field(default_factory=list)
    requires_review: bool = True

class DemographicDetails(BaseModel):
    name: ClinicalField[str] = Field(default_factory=ClinicalField)
    age: ClinicalField[str] = Field(default_factory=ClinicalField)
    gender: ClinicalField[str] = Field(default_factory=ClinicalField)
    mrn: ClinicalField[str] = Field(default_factory=ClinicalField)

class MedicationDetail(BaseModel):
    name: str
    dosage: str
    frequency: str
    duration: str

class MedicationChange(BaseModel):
    drug_name: str
    change_type: str  # "ADDED", "REMOVED", "DOSE_CHANGED", "UNRESOLVED"
    admission_dosage: Optional[str] = "N/A"
    discharge_dosage: Optional[str] = "N/A"
    reason: Optional[str] = "MISSING - Needs Clinician Review"
    requires_review: bool = True
    sources: List[EvidenceSource] = Field(default_factory=list)

class ClinicalConflict(BaseModel):
    conflict_type: str  # "DIAGNOSTIC", "MEDICATION", "TIMELINE"
    description: str
    severity: str  # "HIGH", "MEDIUM", "LOW"
    pages_involved: List[int]
    evidence: List[EvidenceSource]
    requires_review: bool = True

class ReviewFlag(BaseModel):
    category: str  # "MISSING_DATA", "PENDING_LAB", "UNRESOLVED_MED_CHANGE", "CLINICAL_CONFLICT"
    message: str
    suggested_action: str
    pages_involved: List[int]

class DischargeSummaryDraft(BaseModel):
    patient_demographics: DemographicDetails = Field(default_factory=DemographicDetails)
    admission_date: ClinicalField[str] = Field(default_factory=ClinicalField)
    discharge_date: ClinicalField[str] = Field(default_factory=ClinicalField)
    principal_diagnosis: List[ClinicalField[str]] = Field(default_factory=list)
    secondary_diagnosis: List[ClinicalField[str]] = Field(default_factory=list)
    hospital_course: ClinicalField[str] = Field(default_factory=ClinicalField)
    procedures: List[ClinicalField[str]] = Field(default_factory=list)
    discharge_medications: List[ClinicalField[MedicationDetail]] = Field(default_factory=list)
    medication_changes: List[MedicationChange] = Field(default_factory=list)
    allergies: ClinicalField[str] = Field(default_factory=ClinicalField)
    follow_up_instructions: List[ClinicalField[str]] = Field(default_factory=list)
    pending_results: List[ClinicalField[str]] = Field(default_factory=list)
    discharge_condition: ClinicalField[str] = Field(default_factory=ClinicalField)
    conflicts: List[ClinicalConflict] = Field(default_factory=list)
    review_flags: List[ReviewFlag] = Field(default_factory=list)
