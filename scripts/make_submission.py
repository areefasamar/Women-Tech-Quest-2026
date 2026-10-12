"""
scripts/make_submission.py – build submission.zip and verify it.
"""
from __future__ import annotations
import os, sys, re, json, csv, zipfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
OUTPUT_DIR = ROOT / "output"


def check(cond: bool, msg: str) -> bool:
    if cond:
        print(f"  PASS  {msg}")
    else:
        print(f"  FAIL  {msg}")
    return cond


def main():
    zip_path = ROOT / "submission.zip"

    # ── build ZIP ─────────────────────────────────────────────────────────────
    exclude_patterns = {
        ".env", "cache", "venv", "__pycache__", "input", "logs",
        "submission.zip", ".git",
    }
    exclude_exts = {".jpg", ".jpeg", ".png", ".webp", ".pkl", ".zip", ".pyc"}

    def should_include(path: Path) -> bool:
        parts = set(path.parts)
        if any(p in exclude_patterns for p in parts):
            return False
        if path.suffix.lower() in exclude_exts:
            return False
        return True

    source_files = [
        f for f in ROOT.rglob("*")
        if f.is_file() and should_include(f.relative_to(ROOT))
    ]

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Output CSVs
        for csv_name in ("level1.csv", "level2.csv"):
            p = OUTPUT_DIR / csv_name
            if p.exists():
                zf.write(p, f"output/{csv_name}")
        # Source files
        for f in source_files:
            rel = f.relative_to(ROOT)
            zf.write(f, f"source/{rel}")
        # Demo video if present
        for ext in ("mp4", "mov", "webm"):
            demo = ROOT / f"demo/demo.{ext}"
            if demo.exists():
                zf.write(demo, f"demo/demo.{ext}")
                break

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"\nSubmission ZIP: {zip_path}  ({size_mb:.2f} MB)\n")

    # ── verify ────────────────────────────────────────────────────────────────
    results = []

    # Size
    results.append(check(size_mb <= 15, f"ZIP size ≤ 15 MB (actual {size_mb:.2f} MB)"))

    # CSVs exist
    for name, expected_rows in [("level1.csv", 10), ("level2.csv", 120)]:
        p = OUTPUT_DIR / name
        if not p.exists():
            results.append(check(False, f"{name} exists"))
            continue
        results.append(check(True, f"{name} exists"))
        with open(p, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        results.append(check(len(rows) == expected_rows,
                             f"{name} has {expected_rows} rows (actual {len(rows)})"))
        # No empty cells
        empty_found = False
        for row in rows:
            for k, v in row.items():
                if not v or not str(v).strip():
                    empty_found = True
                    break
        results.append(check(not empty_found, f"{name} no empty cells"))
        # JSON parseable (level1 only)
        if name == "level1.csv":
            bad = 0
            for row in rows:
                try:
                    obj = json.loads(row.get("json", "{}"))
                    if not isinstance(obj, dict) or len(obj) < 10:
                        bad += 1
                except Exception:
                    bad += 1
            results.append(check(bad == 0, f"level1.csv all JSON parses ({bad} bad)"))

    # Required source files
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
    for req in ("source/README.md", "source/.env.example", "source/requirements.txt"):
        results.append(check(req in names, f"{req} present in ZIP"))

    # No .env file
    results.append(check("source/.env" not in names, "No .env in ZIP"))

    # No API key string
    api_key_found = False
    with zipfile.ZipFile(zip_path) as zf:
        for name in names:
            if name.endswith(".py") or name.endswith(".md") or name.endswith(".txt"):
                try:
                    content = zf.read(name).decode("utf-8", errors="ignore")
                    if re.search(r"AIza[0-9A-Za-z_\-]{35}", content):
                        api_key_found = True
                except Exception:
                    pass
    results.append(check(not api_key_found, "No API key found in any source file"))

    # README has AI usage section
    readme_ok = False
    try:
        with zipfile.ZipFile(zip_path) as zf:
            readme = zf.read("source/README.md").decode("utf-8", errors="ignore")
            readme_ok = "AI usage" in readme or "ai usage" in readme.lower()
    except Exception:
        pass
    results.append(check(readme_ok, "README contains 'AI usage' section"))

    # Demo
    demo_present = any(n.startswith("demo/") for n in names)
    demo_valid = any(n.endswith((".mp4", ".mov", ".webm")) for n in names if n.startswith("demo/"))
    if demo_present:
        results.append(check(demo_valid, "Demo file is .mp4, .mov or .webm"))
    else:
        print("  NOTE  No demo video found (optional but worth 5 points)")

    # Summary
    passed = sum(results)
    total = len(results)
    print(f"\n{'='*50}")
    print(f"Result: {passed}/{total} checks passed")
    if passed < total:
        print("Fix the FAIL items before submitting.")
    else:
        print("All checks passed! Ready to submit.")
    print(f"{'='*50}\n")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
