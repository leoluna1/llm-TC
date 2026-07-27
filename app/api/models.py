from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any


class QuestionRequest(BaseModel):
    question: str = Field(..., description="Pregunta sobre el documento")
    session_id: str = Field(..., description="ID de la sesión")


class ClauseItem(BaseModel):
    title: str
    level: str  # critical | high | medium | low
    excerpt: str
    explanation: str


class RiskSummary(BaseModel):
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0


class RiskData(BaseModel):
    service_name: Optional[str] = None
    risk_level_overall: Optional[str] = None
    risk_summary: Optional[RiskSummary] = None
    clauses: Optional[List[ClauseItem]] = None
    jurisdiction: Optional[str] = None
    quick_verdict: Optional[str] = None


class DocumentResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    document_id: Optional[str] = None
    summary: Optional[str] = None
    risk_data: Optional[RiskData] = None
    key_clauses: Optional[List[str]] = None
    analysis: Optional[Dict[str, Any]] = None


class QuestionResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    question: str
    answer: Optional[str] = None


class ChatMessage(BaseModel):
    role: str
    content: str
    timestamp: Optional[str] = None


class ChatSession(BaseModel):
    session_id: str
    document_id: Optional[str] = None
    messages: List[ChatMessage] = Field(default_factory=list)


class SessionHistoryItem(BaseModel):
    session_id: str
    file_name: str
    uploaded_at: str
    risk_level_overall: Optional[str] = None
    service_name: Optional[str] = None


class CompareRequest(BaseModel):
    session_id_a: str = Field(..., description="ID de la primera sesión")
    session_id_b: str = Field(..., description="ID de la segunda sesión")
