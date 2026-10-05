# Restaurant order parser

FastAPI servis koji gostovu rečenicu na hrvatskom (iz telefonskog naručivanja) pretvara u strukturirane stavke narudžbe s jelovnika `data/jelovnik.json`, uz pomoć Gemini modela.

**Princip:** LLM razumije jezik, a kod posjeduje svaku činjenicu o jelovniku. Izlaz modela se nikad ne uzima zdravo za gotovo: kod provjerava svaki `id`, količinu i prijedlog prema jelovniku, a ono što ne prođe provjeru premješta među `unavailable` umjesto da to tiho odbaci ili zamijeni nečim sličnim.

## Pokretanje

Potreban je Python 3.11+ i Gemini API ključ (besplatni tier: https://aistudio.google.com/apikey).

PowerShell:
```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:GEMINI_API_KEY = "<vaš ključ>"      # ili kopirajte .env.example u .env
uvicorn app.main:app --port 8000
```

bash:
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export GEMINI_API_KEY="<vaš ključ>"
uvicorn app.main:app --port 8000
```

Bez `GEMINI_API_KEY` servis odbija start s jasnom porukom. Opcionalno: `GEMINI_MODEL` (zadano `gemini-3.5-flash-lite`), `LLM_TIMEOUT_S` (zadano 10).

Primjer:
```bash
curl -X POST localhost:8000/order -H "Content-Type: application/json" \
     -d '{"text": "dva hamburgera i jednu margaritu"}'
```
```json
{"items":[{"id":"margarita","quantity":1}],"unavailable":[{"text":"hamburger","quantity":2}],"needs_clarification":[],"suggestions":[]}
```

Testovi (bez mreže, LLM je zamijenjen lažnim): `pytest`
Eval na stvarnom modelu: `python eval/run_eval.py [--model ...] [--runs 3] [--delay 6]`

## Format odgovora

Uvijek su prisutna sva četiri ključa (prazne liste kad nema ničega):

```json
{
  "items": [{"id": "margarita", "quantity": 2}],
  "unavailable": [{"text": "hamburger", "quantity": 2}],
  "needs_clarification": [{"text": "salata", "quantity": 1, "options": ["cezar_salata", "mijesana_salata"]}],
  "suggestions": ["margarita", "vegetariana"]
}
```

Predloženi format proširen je s dva ključa:
- **`needs_clarification`**: kad gost kaže nešto općenito što odgovara više stavki ("jednu pizzu", "salatu"). Odabir jedne bila bi zamjena, izbacivanje bi izgubilo narudžbu, a nije ni "nedostupno". Asistent treba pitati gosta koju točno želi. Ovdje završavaju i nerealno velike količine (> 50), umjesto da ih kod tiho smanji.
- **`suggestions`**: `id`-jevi s jelovnika kao odgovor na pitanje ("imate li nešto bez mesa?"). Pitanja nikad ne stvaraju stavke narudžbe. Za upit "bez mesa" prijedloge računa kod iz polja `bez_mesa` u jelovniku (samo hrana, ne pića), a ne model.

Greške imaju uvijek isti oblik `{"error": "<kod>", "detail": "<poruka>"}`: prazan ili predug tekst (> 500 znakova) i neispravno tijelo zahtjeva vraćaju 422 bez poziva modela, istek vremena 504 `llm_timeout`, ograničenje kvote 503 `llm_rate_limited`, ostale greške API-ja 502 `llm_error`, a neispravan izlaz modela (nakon jednog ponovnog pokušaja) 502 `llm_invalid_output`.

## Kako radi

1. `app/prompt.py`: jelovnik (id, naziv, kategorija) ide u sistemsku uputu; gostov tekst ide u korisničku poruku unutar `<guest_utterance>` oznaka i tretira se isključivo kao podatak, ne kao uputa.
2. `app/llm.py`: Gemini vraća JSON prema shemi (temperatura 0). Polje `id` je enum izgrađen iz datoteke jelovnika pri pokretanju, pa nova stavka na jelovniku ne traži promjenu koda. Uz `id` model vraća i izgovorene riječi (`text`), da bi kod mogao nevaljanu stavku premjestiti u `unavailable` bez gubitka.
3. `app/postprocess.py`: čiste funkcije, potpuno pokrivene testovima. Nepoznat `id` ide u `unavailable`, količina ≤ 0 se izbacuje (otkazano), isti `id` dvaput se zbraja, opcije pojašnjenja filtriraju se na valjane `id`-jeve, prijedlozi se provjeravaju prema jelovniku.

## Što bi se dalo poboljšati

Modifikatori i napomene uz stavku ("margarita bez luka", "veliko pivo") trenutno se gube; trebalo bi ih dodati kao polje `note` po stavci. Servis je bez stanja: pravi razgovor traži pamćenje narudžbe kroz više rečenica ("i još jednu takvu"), uz razrješavanje `needs_clarification` u sljedećem koraku. Ulaz dolazi iz prepoznavanja govora, pa bi pomoglo podešavanje na tipične ASR greške (fonetsko podudaranje, n-best hipoteze) i mjerenje na stvarnim snimkama umjesto na tipkanim rečenicama.

## Kako provjeriti da sustav radi dobro

1. **Unit testovi** (`tests/`) za svu determinističku logiku: pravila naknadne obrade, validaciju ulaza, mapiranje grešaka (timeout, kvota, smeće od modela uz jedan ponovni pokušaj). Model je zamijenjen lažnim, bez mreže.
2. **Eval skup** (`eval/cases.yaml`, 35 rečenica po kategorijama) na stvarnom modelu, kao regresijski test pri svakoj promjeni prompta i za usporedbu modela. Zamjene (nešto čega nema na jelovniku pretvoreno u stavku s jelovnika) broje se posebno i tvrda su metrika: cilj je 0, jer znače da gostu stiže pogrešna hrana. Primjeri iz prompta namjerno nisu iz eval skupa, da eval ne mjeri pamćenje.
3. **U produkciji:** logira se ulaz, sirovi izlaz modela, konačni odgovor i latencija po zahtjevu; uzorak razgovora redovito pregledava čovjek; asistent gostu na kraju ponavlja narudžbu na potvrdu, pa greška ne prolazi neopaženo.

Napomena: sadržaj poslan na besplatni Gemini tier Google koristi za poboljšanje svojih proizvoda, pa stvarni podaci gostiju zahtijevaju plaćeni tier.

## Rezultati evaluacije

> **Još nije pokrenuto.** API ključ dostupan tijekom izrade bio je nevažeći (`API_KEY_INVALID`), pa stvarni rezultati ovdje još ne postoje i nisu izmišljeni. Zadani model `gemini-3.5-flash-lite` je privremen dok eval ne pokaže koji je bolji.
>
> ```
> python eval/run_eval.py --model gemini-3.5-flash-lite
> python eval/run_eval.py --model gemini-3.8-flash
> python eval/run_eval.py --model <bolji> --runs 3
> ```
