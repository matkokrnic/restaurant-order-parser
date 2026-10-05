import logging
import os
import sys
import time
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.llm import GeminiParser, LLMError
from app.menu import load_menu
from app.postprocess import postprocess
from app.schemas import MAX_TEXT_LENGTH, ErrorResponse, OrderRequest, OrderResponse

load_dotenv()  # optional .env; real environment variables take precedence
sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252, guests speak Croatian
logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per Gemini call is noise
log = logging.getLogger("order")

DEFAULT_MODEL = "gemini-3.5-flash-lite"  # chosen from eval results, see README
MENU = load_menu()


def create_parser() -> GeminiParser:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set. Set it in the environment or in .env.")
    model = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
    timeout_s = float(os.environ.get("LLM_TIMEOUT_S", "10"))
    return GeminiParser(api_key, model, timeout_s, MENU)


def process_order(text: str, parser: GeminiParser) -> dict:
    """Core pipeline shared by the endpoint and the eval: model understands, code decides."""
    return postprocess(parser.parse(text), MENU)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.parser = create_parser()  # refuses to start without an API key
    log.info("using model %s", app.state.parser.model)
    yield


app = FastAPI(title="Restaurant order parser", lifespan=lifespan)


def get_parser(request: Request) -> GeminiParser:
    return request.app.state.parser


def error_response(status_code: int, error: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": error, "detail": detail})


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError):
    return error_response(422, "invalid_request", 'Body must be JSON: {"text": "<string>"}.')


@app.exception_handler(StarletteHTTPException)
async def handle_http_error(request: Request, exc: StarletteHTTPException):
    return error_response(exc.status_code, "http_error", str(exc.detail))


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception):
    log.exception("unexpected error")
    return error_response(500, "internal_error", "Unexpected server error.")


@app.get("/health")
def health(parser: GeminiParser = Depends(get_parser)):
    return {"status": "ok", "model": parser.model}


@app.post(
    "/order",
    response_model=OrderResponse,
    responses={422: {"model": ErrorResponse}, 502: {"model": ErrorResponse},
               503: {"model": ErrorResponse}, 504: {"model": ErrorResponse}},
)
def order(request: OrderRequest, parser: GeminiParser = Depends(get_parser)):
    text = request.text.strip()
    if not text:
        return error_response(422, "empty_text", "Text is empty.")
    if len(text) > MAX_TEXT_LENGTH:
        return error_response(422, "text_too_long", f"Text is longer than {MAX_TEXT_LENGTH} characters.")

    started = time.perf_counter()
    try:
        response = process_order(text, parser)
    except LLMError as e:
        log.warning("input=%r error=%s latency_ms=%d", text, e.code, (time.perf_counter() - started) * 1000)
        return error_response(e.status_code, e.code, e.detail)
    log.info("input=%r response=%s latency_ms=%d", text, response, (time.perf_counter() - started) * 1000)
    return response
