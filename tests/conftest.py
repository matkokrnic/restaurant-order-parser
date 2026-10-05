import pytest
from fastapi.testclient import TestClient

from app.main import app, get_parser
from app.schemas import LLMResult


def llm_result(**fields) -> LLMResult:
    """An LLMResult with empty defaults, so tests only spell out what matters."""
    base = {"items": [], "unavailable": [], "needs_clarification": [],
            "is_menu_question": False, "dietary_filter": "none", "suggestions": []}
    return LLMResult(**(base | fields))


class FakeParser:
    model = "fake"

    def __init__(self, result: LLMResult | None = None):
        self.result = result or llm_result()
        self.calls = []

    def parse(self, text: str) -> LLMResult:
        self.calls.append(text)
        return self.result


@pytest.fixture
def client_with():
    """Returns a function that builds a TestClient whose LLM is the given parser.
    TestClient is not used as a context manager, so the lifespan (API key check) does not run."""
    def make(parser):
        app.dependency_overrides[get_parser] = lambda: parser
        return TestClient(app, raise_server_exceptions=False)
    yield make
    app.dependency_overrides.clear()
