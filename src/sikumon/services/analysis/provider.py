"""Cloud-analysis provider boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AnalysisProviderRequest:
    instructions: str
    transcript_input: str
    correction_instruction: str | None = None


@dataclass(frozen=True, slots=True)
class AnalysisProviderResult:
    payload: object
    input_tokens: int | None = None
    output_tokens: int | None = None


class AnalysisProviderError(RuntimeError):
    user_message = (
        "לא ניתן להשלים את ניתוח הפגישה. התמלול שמור ובטוח. "
        "בדקו את החיבור ונסו שוב."
    )


class AnalysisStructuredOutputError(AnalysisProviderError):
    """A response was received but no schema-valid payload was available."""


class AnalysisNetworkError(AnalysisProviderError):
    user_message = (
        "לא ניתן להתחבר ל-OpenAI. התמלול והניתוח הקודם נשמרו. "
        "בדקו את החיבור לאינטרנט ונסו שוב."
    )


class AnalysisAuthenticationError(AnalysisProviderError):
    user_message = "מפתח OpenAI נדחה. בדקו את המפתח בהגדרות ונסו שוב."


class AnalysisRateLimitError(AnalysisProviderError):
    user_message = "מגבלת השימוש ב-OpenAI הושגה. המתינו מעט ונסו שוב."


class AnalysisServerError(AnalysisProviderError):
    user_message = (
        "שירות OpenAI אינו זמין זמנית. התמלול והניתוח הקודם נשמרו. נסו שוב מאוחר יותר."
    )


class AnalysisProviderRefusalError(AnalysisProviderError):
    user_message = "OpenAI לא החזיר ניתוח לפגישה. אפשר לבדוק את התמלול ולנסות שוב."


class AnalysisProvider(Protocol):
    def analyze(self, request: AnalysisProviderRequest) -> AnalysisProviderResult: ...


class AnalysisProviderFactory(Protocol):
    def create(self, api_key: str) -> AnalysisProvider: ...
