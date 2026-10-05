from app.menu import load_menu
from app.postprocess import MAX_QUANTITY, postprocess
from tests.conftest import llm_result

MENU = load_menu()


def item(id, quantity, text=None):
    return {"id": id, "text": text or id, "quantity": quantity}


def test_valid_items_pass_through():
    out = postprocess(llm_result(items=[item("margarita", 2), item("coca_cola", 1)]), MENU)
    assert out["items"] == [{"id": "margarita", "quantity": 2}, {"id": "coca_cola", "quantity": 1}]


def test_always_four_keys():
    out = postprocess(llm_result(), MENU)
    assert out == {"items": [], "unavailable": [], "needs_clarification": [], "suggestions": []}


def test_unknown_id_moves_to_unavailable_with_spoken_text():
    out = postprocess(llm_result(items=[item("hamburger", 2, text="hamburgera")]), MENU)
    assert out["items"] == []
    assert out["unavailable"] == [{"text": "hamburgera", "quantity": 2}]


def test_unknown_id_without_text_falls_back_to_id():
    out = postprocess(llm_result(items=[item("lazanje", 1, text=" ")]), MENU)
    assert out["unavailable"] == [{"text": "lazanje", "quantity": 1}]


def test_model_unavailable_is_kept():
    out = postprocess(llm_result(unavailable=[{"text": "pepsi", "quantity": 3}]), MENU)
    assert out["unavailable"] == [{"text": "pepsi", "quantity": 3}]


def test_zero_or_negative_quantity_is_dropped():
    out = postprocess(llm_result(
        items=[item("margarita", 0), item("pivo", -1)],
        unavailable=[{"text": "fanta", "quantity": 0}],
        needs_clarification=[{"text": "salata", "quantity": 0, "options": ["cezar_salata"]}],
    ), MENU)
    assert out == {"items": [], "unavailable": [], "needs_clarification": [], "suggestions": []}


def test_same_id_twice_is_summed():
    out = postprocess(llm_result(items=[item("pivo", 2), item("margarita", 1), item("pivo", 1)]), MENU)
    assert out["items"] == [{"id": "pivo", "quantity": 3}, {"id": "margarita", "quantity": 1}]


def test_quantity_over_max_needs_clarification():
    out = postprocess(llm_result(items=[item("margarita", MAX_QUANTITY + 1, text="margarita")]), MENU)
    assert out["items"] == []
    assert out["needs_clarification"] == [
        {"text": "margarita", "quantity": MAX_QUANTITY + 1, "options": ["margarita"]}
    ]


def test_quantity_at_max_is_accepted():
    out = postprocess(llm_result(items=[item("pivo", MAX_QUANTITY)]), MENU)
    assert out["items"] == [{"id": "pivo", "quantity": MAX_QUANTITY}]


def test_clarification_options_filtered_to_valid_ids():
    out = postprocess(llm_result(needs_clarification=[
        {"text": "salata", "quantity": 1, "options": ["cezar_salata", "grcka_salata", "mijesana_salata"]}
    ]), MENU)
    assert out["needs_clarification"] == [
        {"text": "salata", "quantity": 1, "options": ["cezar_salata", "mijesana_salata"]}
    ]


def test_clarification_without_valid_options_becomes_unavailable():
    out = postprocess(llm_result(needs_clarification=[
        {"text": "juha", "quantity": 2, "options": ["pileca_juha"]}
    ]), MENU)
    assert out["needs_clarification"] == []
    assert out["unavailable"] == [{"text": "juha", "quantity": 2}]


def test_meatless_suggestions_come_from_menu_not_model():
    out = postprocess(llm_result(
        is_menu_question=True, dietary_filter="bez_mesa", suggestions=["capricciosa", "pivo"],
    ), MENU)
    assert out["suggestions"] == ["margarita", "vegetariana", "quattro_formaggi", "mijesana_salata"]
    assert out["items"] == []


def test_other_question_suggestions_filtered_and_deduplicated():
    out = postprocess(llm_result(
        is_menu_question=True, suggestions=["diavola", "nepostojeca", "diavola"],
    ), MENU)
    assert out["suggestions"] == ["diavola"]


def test_suggestions_ignored_when_not_a_question():
    out = postprocess(llm_result(suggestions=["diavola"]), MENU)
    assert out["suggestions"] == []
