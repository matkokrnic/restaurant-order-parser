import json
from pathlib import Path

MENU_PATH = Path(__file__).resolve().parent.parent / "data" / "jelovnik.json"


def load_menu(path: Path = MENU_PATH) -> list[dict]:
    """Load the menu file. Every fact about the menu comes from here."""
    with open(path, encoding="utf-8") as f:
        menu = json.load(f)
    ids = [item["id"] for item in menu]
    if len(ids) != len(set(ids)):
        raise ValueError(f"Duplicate menu ids in {path}")
    return menu
