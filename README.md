# Utility Bill Decoder

**Women Tech Quest 2026 – Build Track Submission**

Reads K-Electric (KE), LESCO, and IESCO electricity bill images. Uses Gemini vision to extract structured data (Level 1) and answer plain-English questions about the bill (Level 2). Outputs two CSV files.

---

## Pipeline

```
bill image
   |
   v
[1] image_prep          EXIF rotate, upscale 2-3x (LESCO), 3 overlapping crops
   |
   v
[2] Level 1 extraction  Gemini vision, strict JSON schema, temp 0, seed 42
   |
   v
[3] normalize           Pure Python: numbers, dates, types, signs, null rules
   |        \
   |         → if checks fail: ONE targeted re-read (max), then accept and log
   v
[4] level1.csv row

bill image
   |
   v
[5] Bill facts           Gemini vision: usage/billing history, line items, messages
   |
   v
[6] Level 2 plan         Gemini: per question, which values + safe math expressions
   |
   v
[7] Python calculator    Evaluates expressions via restricted AST evaluator (no LLM math)
   |
   v
[8] Level 2 write        Gemini: plain English answers from computed values
   |
   v
[9] Answer checks        Non-empty, English, PII scrubbed
   |
   v
[10] level2.csv rows
```

**Design principle:** The model reads and writes. Python calculates and validates.

---

## Python Version

Python **3.14.0** (tested). Requires Python 3.11+.

---

## Setup

```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

pip install -r requirements.txt

# Copy and fill in your API key:
cp .env.example .env
# Edit .env: paste your Google AI Studio key into API_KEY=
```

---

## Run – Batch (one command)

```bash
# Training bills (5 bills, 60 Level 2 rows):
python main.py \
  --bills input/train/bills \
  --level1-template input/train/level1_template.csv \
  --level2-template input/train/level2_template.csv \
  --out output/

# Test bills (10 bills, 120 Level 2 rows) – run this when test files arrive at 12:30:
python main.py \
  --bills input/test/bills \
  --level1-template input/test/csv/level1.csv \
  --level2-template input/test/csv/level2.csv \
  --out output/
```

Optional flags:
- `--only KESC_0008` – process one bill only
- `--no-cache` – disable disk cache
- `--skip-level2` – extract Level 1 only

---

## Run – Web UI (Flask)

```bash
python app.py
# Open: http://localhost:5000
```

Upload a bill photo, see extracted fields and ask questions. Same pipeline as the CLI.

---

## Design Decisions

1. **Image direct to model** – No pre-OCR. Gemini reads the raw image with full context, which handles tilted photos, mixed Urdu/English, and varying layouts better than OCR + regex.
2. **Three images per call** – Full image + top-half crop + bottom-half crop. Small print on KE bills (charges table) is most reliably read from the crops.
3. **LESCO upscaling** – LESCO bills are phone photos with glare and low resolution. `image_prep.py` upscales 2–3x and sharpens before sending.
4. **JSON schema (Pydantic + `response_mime_type`)** – Forces the model into the exact Level 1 schema. No regex parsing of free-form text.
5. **Python calculates, model writes** – `safe_calc.py` evaluates math expressions via a restricted AST evaluator. The model is never asked to do arithmetic.
6. **Validation and targeted re-read** – `validate.py` checks internal consistency (sum of charges vs total, readings vs units). On failure, one re-read call names the failing fields. Never more than one retry per bill.
7. **Disk cache + temperature 0 + seed 42** – Same input → same output on re-run. Cache key is SHA-256 of (image bytes + prompt + model + schema name).
8. **Fallback model** – Auto-switches from `gemini-3.5-flash-lite` to `gemini-3.1-flash-lite` after 2+ consecutive 429 or 5xx errors.
9. **Null over guess** – Anything blank, unreadable, under a grey box, or non-numeric becomes `null`. Zero is a real value and is kept.
10. **No PII in output** – `pii_guard.py` scrubs digit strings >8 digits and CNIC patterns from all answer text. Level 1 schema never requests names, addresses, or numbers.

---

## AI Usage

### Models and APIs
- **`gemini-3.5-flash-lite`** (primary) via Google AI Studio Gemini API – all extraction and answer calls
- **`gemini-3.1-flash-lite`** (fallback) via Google AI Studio Gemini API – auto-switched on rate limit / server errors

### Services
- **Google AI Studio** – API access for both Gemini models
- Local OCR / prebuilt invoice extractors: **none**

### AI tools used to write this code
- **Google Antigravity** – primary coding assistant (wrote all source files)
- **Claude** (Claude Sonnet 4.6) – architecture planning

---

## Known Limitations

1. **Bar chart history (KE bills)** – The 13-month usage bar chart is hard to read. Values with small bars or low contrast may be missing from `usage_history`.
2. **Heavily tilted LESCO photos** – Extreme tilt (>30°) can cause some fields to be returned as null even with upscaling.
3. **Grey box fields** – Any field under a redacted grey box is correctly returned as null (this is expected and scored as correct).
4. **Net metering (KESC_0004, LESCO_0005)** – Multi-row meter registers: only the first row is used for readings. The readings-vs-units check is skipped for these bills.
5. **IESCO / LESCO charge itemisation** – These providers do not print itemised charge lines. The "IESCO and LESCO special rule" in `level1_system.md` maps Total Electricity Charges → energy, Subsidies → subsidy, Taxes → total_taxes.

---

## Project Structure

```
main.py              CLI entry point
app.py               Flask web server (thin layer over src/)
src/
  config.py          Reads .env
  llm_client.py      Gemini wrapper: rate limit, retry, cache
  image_prep.py      EXIF rotate, upscale, crop
  schemas.py         Pydantic models for Level 1, facts, plan
  prompts/           System prompts (markdown)
  level1.py          Extraction + retry logic
  normalize.py       Deterministic cleanup
  validate.py        Consistency checks
  facts.py           Bill facts extraction
  safe_calc.py       Restricted expression evaluator
  level2.py          Plan → compute → write
  pii_guard.py       PII scrubbing
  csv_io.py          CSV read/write/verify
scripts/
  make_submission.py Build and verify submission.zip
tests/
  test_normalize.py
  test_safe_calc.py
  test_csv_io.py
  fixtures/kesc_0008_expected.json   (guide answer, tests only)
```
