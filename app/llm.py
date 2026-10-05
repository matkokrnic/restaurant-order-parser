import logging

import httpx
from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from app.prompt import build_response_schema, build_system_instruction, build_user_message
from app.schemas import LLMResult

log = logging.getLogger("order")


class LLMError(Exception):
    """An LLM failure already mapped to the HTTP status and error code the API returns."""

    def __init__(self, code: str, status_code: int, detail: str):
        super().__init__(detail)
        self.code = code
        self.status_code = status_code
        self.detail = detail


class GeminiParser:
    def __init__(self, api_key: str, model: str, timeout_s: float, menu: list[dict]):
        self.model = model
        # timeout is in milliseconds in google-genai. No retry_options => the SDK does not retry.
        self.client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=int(timeout_s * 1000)),
        )
        self.config = types.GenerateContentConfig(
            system_instruction=build_system_instruction(menu),
            temperature=0,
            response_mime_type="application/json",
            response_json_schema=build_response_schema([m["id"] for m in menu]),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),  # no tools
        )

    def parse(self, text: str) -> LLMResult:
        """Ask the model; retry once if the output is not valid JSON matching LLMResult."""
        for attempt in (1, 2):
            raw = self._call(text)
            log.info("raw model output (attempt %d): %s", attempt, raw)
            try:
                return LLMResult.model_validate_json(raw)
            except ValidationError as e:
                log.warning("invalid model output (attempt %d): %s", attempt, e.errors()[0]["msg"])
        raise LLMError("llm_invalid_output", 502, "The model returned invalid output twice.")

    def _call(self, text: str) -> str:
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=build_user_message(text),
                config=self.config,
            )
        except httpx.TimeoutException:
            raise LLMError("llm_timeout", 504, "The model did not respond in time.")
        except httpx.HTTPError as e:
            raise LLMError("llm_error", 502, f"Could not reach the model: {type(e).__name__}")
        except errors.APIError as e:
            log.warning("Gemini API error %s: %s", e.code, e.message)
            if e.code == 429:
                raise LLMError("llm_rate_limited", 503, "Model rate limit reached, try again later.")
            raise LLMError("llm_error", 502, f"Model API error {e.code}.")
        # response.text is None when the model returns no text (e.g. blocked); that counts as invalid.
        return response.text or ""
