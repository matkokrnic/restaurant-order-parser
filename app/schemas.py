from typing import Literal

from pydantic import BaseModel

MAX_TEXT_LENGTH = 500


# --- Public API ---

class OrderRequest(BaseModel):
    text: str


class OrderItem(BaseModel):
    id: str
    quantity: int


class UnavailableItem(BaseModel):
    text: str
    quantity: int


class ClarificationItem(BaseModel):
    text: str
    quantity: int
    options: list[str]


class OrderResponse(BaseModel):
    items: list[OrderItem] = []
    unavailable: list[UnavailableItem] = []
    needs_clarification: list[ClarificationItem] = []
    suggestions: list[str] = []


class ErrorResponse(BaseModel):
    error: str
    detail: str


# --- Internal: what the LLM must return (validated before use) ---

class LLMItem(BaseModel):
    id: str
    text: str  # what the guest actually said, kept so an invalid id is never lost
    quantity: int


class LLMUnavailable(BaseModel):
    text: str
    quantity: int


class LLMClarification(BaseModel):
    text: str
    quantity: int
    options: list[str]


class LLMResult(BaseModel):
    items: list[LLMItem]
    unavailable: list[LLMUnavailable]
    needs_clarification: list[LLMClarification]
    is_menu_question: bool
    dietary_filter: Literal["none", "bez_mesa"]
    suggestions: list[str]
