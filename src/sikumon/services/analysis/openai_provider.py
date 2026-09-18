"""OpenAI Responses API integration with Pydantic Structured Outputs."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol, cast

from pydantic import ValidationError

from sikumon.config.constants import ANALYSIS_REQUEST_TIMEOUT_SECONDS
from sikumon.services.analysis.provider import (
    AnalysisAuthenticationError,
    AnalysisNetworkError,
    AnalysisProvider,
    AnalysisProviderError,
    AnalysisProviderFactory,
    AnalysisProviderRefusalError,
    AnalysisProviderRequest,
    AnalysisProviderResult,
    AnalysisRateLimitError,
    AnalysisServerError,
    AnalysisStructuredOutputError,
)
from sikumon.services.analysis.schemas import MeetingAnalysisPayload


class _Usage(Protocol):
    input_tokens: int
    output_tokens: int


class _ParsedResponse(Protocol):
    status: str
    output_parsed: object | None
    output: Sequence[object]
    usage: _Usage | None


class _ResponsesAPI(Protocol):
    def parse(self, **kwargs: object) -> _ParsedResponse: ...


class _Client(Protocol):
    responses: _ResponsesAPI

    def close(self) -> None: ...


ClientFactory = Callable[[str], _Client]


class OpenAIAnalysisProvider(AnalysisProvider):
    def __init__(
        self,
        api_key: str,
        model: str,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._client_factory = client_factory or self._default_client

    @staticmethod
    def _default_client(api_key: str) -> _Client:
        from openai import OpenAI

        return cast(
            _Client,
            OpenAI(
                api_key=api_key,
                timeout=ANALYSIS_REQUEST_TIMEOUT_SECONDS,
                max_retries=0,
            ),
        )

    def analyze(self, request: AnalysisProviderRequest) -> AnalysisProviderResult:
        from openai import APIConnectionError, APIStatusError, APITimeoutError

        client = self._client_factory(self._api_key)
        input_text = request.transcript_input
        if request.correction_instruction:
            input_text = f"{request.correction_instruction}\n\n{input_text}"
        try:
            response = client.responses.parse(
                model=self._model,
                instructions=request.instructions,
                input=input_text,
                text_format=MeetingAnalysisPayload,
                store=False,
            )
        except (APIConnectionError, APITimeoutError) as error:
            raise AnalysisNetworkError(type(error).__name__) from error
        except APIStatusError as error:
            if error.status_code in (401, 403):
                raise AnalysisAuthenticationError("OpenAI credential rejected") from error
            if error.status_code == 429:
                raise AnalysisRateLimitError("OpenAI rate limit") from error
            if error.status_code >= 500:
                raise AnalysisServerError("OpenAI server error") from error
            raise AnalysisProviderError(f"OpenAI HTTP {error.status_code}") from error
        except ValidationError as error:
            raise AnalysisStructuredOutputError("Pydantic structured output failure") from error
        except Exception as error:
            # SDK failures remain behind a stable provider boundary and are never shown raw.
            raise AnalysisProviderError(type(error).__name__) from error
        finally:
            client.close()

        if response.status != "completed":
            raise AnalysisProviderError(f"Incomplete OpenAI response: {response.status}")
        if response.output_parsed is None:
            if self._contains_refusal(response.output):
                raise AnalysisProviderRefusalError("OpenAI refusal")
            raise AnalysisStructuredOutputError("Missing parsed structured output")
        usage = response.usage
        return AnalysisProviderResult(
            payload=response.output_parsed,
            input_tokens=usage.input_tokens if usage is not None else None,
            output_tokens=usage.output_tokens if usage is not None else None,
        )

    @staticmethod
    def _contains_refusal(output: Sequence[object]) -> bool:
        for item in output:
            content = cast(Sequence[object], getattr(item, "content", ()))
            if any(getattr(part, "type", None) == "refusal" for part in content):
                return True
        return False


class OpenAIAnalysisProviderFactory(AnalysisProviderFactory):
    def __init__(self, model: str) -> None:
        self._model = model

    def create(self, api_key: str) -> AnalysisProvider:
        return OpenAIAnalysisProvider(api_key, self._model)
