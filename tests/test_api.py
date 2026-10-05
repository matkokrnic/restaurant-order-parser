from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from google.genai import errors

from app.llm import GeminiParser
from app.main import MENU, app
from tests.conftest import FakeParser, llm_result

KEYS = {"items", "unavailable", "needs_clarification", "suggestions"}


def gemini_parser_returning(*outcomes) -> GeminiParser:
    """A real GeminiParser whose SDK call returns the given texts or raises the given exceptions."""
    parser = GeminiParser(api_key="test-key", model="test-model", timeout_s=10, menu=MENU)
    remaining = list(outcomes)
    parser.calls = 0

    def generate_content(**kwargs):
        parser.calls += 1
        outcome = remaining.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(text=outcome)

    parser.client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    return parser


VALID_OUTPUT = (
    '{"items":[{"id":"margarita","text":"margarite","quantity":2}],"unavailable":[],'
    '"needs_clarification":[],"is_menu_question":false,"dietary_filter":"none","suggestions":[]}'
)


def test_order_happy_path(client_with):
    parser = FakeParser(llm_result(items=[{"id": "margarita", "text": "margarite", "quantity": 2}]))
    r = client_with(parser).post("/order", json={"text": "  dvije margarite  "})
    assert r.status_code == 200
    assert r.json() == {"items": [{"id": "margarita", "quantity": 2}], "unavailable": [],
                        "needs_clarification": [], "suggestions": []}
    assert parser.calls == ["dvije margarite"]  # input is stripped before the LLM sees it


def test_response_always_has_four_keys(client_with):
    r = client_with(FakeParser()).post("/order", json={"text": "koliko radite?"})
    assert r.status_code == 200
    assert set(r.json()) == KEYS


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_empty_text_is_rejected_without_calling_llm(client_with, text):
    parser = FakeParser()
    r = client_with(parser).post("/order", json={"text": text})
    assert r.status_code == 422
    assert r.json()["error"] == "empty_text"
    assert parser.calls == []


def test_too_long_text_is_rejected(client_with):
    parser = FakeParser()
    r = client_with(parser).post("/order", json={"text": "a" * 501})
    assert r.status_code == 422
    assert r.json()["error"] == "text_too_long"
    assert parser.calls == []


@pytest.mark.parametrize("body", [{}, {"tekst": "pivo"}, {"text": 5}, {"text": None}, []])
def test_malformed_body_is_rejected(client_with, body):
    r = client_with(FakeParser()).post("/order", json=body)
    assert r.status_code == 422
    assert set(r.json()) == {"error", "detail"}
    assert r.json()["error"] == "invalid_request"


def test_non_json_body_is_rejected(client_with):
    r = client_with(FakeParser()).post("/order", content=b"not json",
                                       headers={"content-type": "application/json"})
    assert r.status_code == 422
    assert r.json()["error"] == "invalid_request"


def test_unknown_id_from_model_lands_in_unavailable(client_with):
    parser = FakeParser(llm_result(items=[{"id": "hamburger", "text": "hamburger", "quantity": 2}]))
    r = client_with(parser).post("/order", json={"text": "dva hamburgera"})
    assert r.json()["items"] == []
    assert r.json()["unavailable"] == [{"text": "hamburger", "quantity": 2}]


# What the SDK really raises (verified live): ConnectTimeout when the connection is not made in time,
# ReadTimeout when the model is slow; a 504 APIError when Gemini's own deadline expires first.
@pytest.mark.parametrize("exc", [
    httpx.ConnectTimeout("timed out"),
    httpx.ReadTimeout("timed out"),
    errors.ServerError(504, {"error": {"message": "Deadline expired"}}),
])
def test_timeout_returns_504(client_with, exc):
    parser = gemini_parser_returning(exc)
    r = client_with(parser).post("/order", json={"text": "pivo"})
    assert r.status_code == 504
    assert r.json()["error"] == "llm_timeout"


def test_timeout_below_gemini_minimum_is_rejected():
    with pytest.raises(ValueError, match="at least 10"):
        GeminiParser(api_key="test-key", model="test-model", timeout_s=5, menu=MENU)


def test_connection_error_returns_502(client_with):
    parser = gemini_parser_returning(httpx.ConnectError("no route"))
    r = client_with(parser).post("/order", json={"text": "pivo"})
    assert r.status_code == 502
    assert r.json()["error"] == "llm_error"


def test_rate_limit_returns_503(client_with):
    parser = gemini_parser_returning(errors.ClientError(429, {"error": {"message": "quota"}}))
    r = client_with(parser).post("/order", json={"text": "pivo"})
    assert r.status_code == 503
    assert r.json()["error"] == "llm_rate_limited"


def test_other_api_error_returns_502(client_with):
    parser = gemini_parser_returning(errors.ServerError(500, {"error": {"message": "boom"}}))
    r = client_with(parser).post("/order", json={"text": "pivo"})
    assert r.status_code == 502
    assert r.json()["error"] == "llm_error"


def test_garbage_output_is_retried_once_then_502(client_with):
    parser = gemini_parser_returning("not json", '{"items": "wrong shape"}')
    r = client_with(parser).post("/order", json={"text": "pivo"})
    assert r.status_code == 502
    assert r.json()["error"] == "llm_invalid_output"
    assert parser.calls == 2


def test_garbage_then_valid_output_succeeds(client_with):
    parser = gemini_parser_returning(None, VALID_OUTPUT)  # None = model returned no text
    r = client_with(parser).post("/order", json={"text": "dvije margarite"})
    assert r.status_code == 200
    assert r.json()["items"] == [{"id": "margarita", "quantity": 2}]
    assert parser.calls == 2


def test_unknown_route_uses_error_format(client_with):
    r = client_with(FakeParser()).get("/nope")
    assert r.status_code == 404
    assert set(r.json()) == {"error", "detail"}


def test_health(client_with):
    r = client_with(FakeParser()).get("/health")
    assert r.json() == {"status": "ok", "model": "fake"}


def test_service_refuses_to_start_without_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        with TestClient(app):
            pass
