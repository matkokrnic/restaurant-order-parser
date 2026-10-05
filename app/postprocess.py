"""Turn the model's answer into the public response. The model's output is never trusted:
every menu fact (valid ids, meatless items) comes from the menu file."""

from app.schemas import LLMResult

MAX_QUANTITY = 50


def postprocess(result: LLMResult, menu: list[dict]) -> dict:
    valid_ids = {m["id"] for m in menu}
    unavailable = [{"text": u.text.strip(), "quantity": u.quantity} for u in result.unavailable]
    clarification = []

    # Sum quantities per menu id. An unknown id is moved to unavailable under the words
    # the guest used, so it is never dropped and never replaced with a guess.
    totals: dict[str, int] = {}
    spoken: dict[str, str] = {}
    for item in result.items:
        if item.id in valid_ids:
            totals[item.id] = totals.get(item.id, 0) + item.quantity
            spoken.setdefault(item.id, item.text.strip())
        else:
            unavailable.append({"text": item.text.strip() or item.id, "quantity": item.quantity})

    items = []
    for menu_id, quantity in totals.items():
        if quantity > MAX_QUANTITY:
            # Implausibly large: ask instead of silently clamping.
            clarification.append({"text": spoken[menu_id], "quantity": quantity, "options": [menu_id]})
        elif quantity > 0:
            items.append({"id": menu_id, "quantity": quantity})

    for c in result.needs_clarification:
        options = [o for o in dict.fromkeys(c.options) if o in valid_ids]
        if options:
            clarification.append({"text": c.text.strip(), "quantity": c.quantity, "options": options})
        else:
            unavailable.append({"text": c.text.strip(), "quantity": c.quantity})

    # quantity <= 0 means the guest cancelled it.
    return {
        "items": items,
        "unavailable": [u for u in unavailable if u["quantity"] > 0 and u["text"]],
        "needs_clarification": [c for c in clarification if c["quantity"] > 0],
        "suggestions": compute_suggestions(result, menu),
    }


def compute_suggestions(result: LLMResult, menu: list[dict]) -> list[str]:
    if result.dietary_filter == "bez_mesa":
        # Computed from the menu, the model's ids are ignored. Drinks are trivially meatless,
        # the guest is asking about food.
        return [m["id"] for m in menu if m["bez_mesa"] and m["kategorija"] != "piće"]
    if result.is_menu_question:
        valid_ids = {m["id"] for m in menu}
        return [s for s in dict.fromkeys(result.suggestions) if s in valid_ids]
    return []
