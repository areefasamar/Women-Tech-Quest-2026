# Bill Decoder: UI Design Spec (for Google Antigravity)

Reference design: `ui/index.html` (open it in a browser first). Build the real UI from it. Keep the look exactly. Replace the placeholders with live data.

## Change to the earlier build spec
Drop Streamlit. It cannot match this design (circle upload, floating bills). Use a tiny Flask or FastAPI server that serves `ui/index.html` and calls the same pipeline code from `src/`. Add the server package to `requirements.txt` with an exact version. Update the README run command and the AI usage section if needed.

## Look and feel (from the template)
- Fonts: Playfair Display (headings), Montserrat (labels, body). Loaded from Google Fonts with fallbacks.
- Colours: frame burgundy `#8b1a4a`, peach background `#fde6dd`, ink `#6b0f3f`, purple `#9a5bb5`, coral `#f4515f`, pink circle `#f9b4cb`, line `#f9a8b4`, leaf green `#1e7f66`, yellow `#f7d774`.
- Outer burgundy frame, peach stage, thin pink inner border line.
- Flat flower and leaf decorations in the corners (SVG, already in the file).
- A dark variant exists through CSS variables. Keep it.

## Hero
- Left: small coral caps label, huge purple serif "Bill", burgundy serif "Decoder", coral caps tagline, one short line of text, button "Add your bill".
- Right: big pink circle with a white round camera button, "Add your bill" and "PHOTO OR SCREENSHOT" under it, dashed white ring inside.
- Bill cards (KE, LESCO, IESCO) float around the circle, slightly tilted, with grey boxes like the redacted bills.
- Optional: swap the fake cards for the cropped training bills (grey boxes already hide identifiers). Keep each image small, so the ZIP stays under 15 MB.

## States
1. **Empty:** as above.
2. **Bill chosen:** the photo fills the circle (cover), camera hides, file name shows, "Decode it" button appears.
3. **Decoding:** disable the button, show "Reading your bill..." in the status line.
4. **Result:** scroll to the "Your bill, decoded" section. Left card fills with Level 1 fields. Right card is the Q&A.
5. **Error:** friendly line in the status area ("Could not read this bill. Try a clearer photo."). Never show raw errors or stack traces.

## Result section
- Bill details card: provider, tariff, bill month, units, charges and taxes (expandable list), current bill, pay by due date, pay after due date. Null shows as a dash.
- Ask card: three suggestion chips, a free text box, an answer box. Answers say when a value is an estimate.

## Endpoints
- `POST /api/decode` (multipart image) returns `{ "level1": {...}, "answers": {...} }`. Runs Level 1, bill facts and the plan/compute/write flow.
- `POST /api/ask` with `{ "bill_id": "...", "question": "..." }` returns `{ "answer": "..." }`. Reuses the stored facts for that upload, makes one call.
- Results are cached by image hash, so the same bill gives the same result.

## Rules
- No identifiers on screen. The Level 1 object has none by design.
- No API key in the browser. Only the server reads `.env`.
- Keep the UI in `ui/` and the pipeline in `src/`, so a design change cannot break the CSV run.
- Responsive: on phones the bills shrink, two of them hide, the cards stack.
- The demo video should show this page: pick a bill, see the fields, ask a question, then run the CSV batch from the terminal.
