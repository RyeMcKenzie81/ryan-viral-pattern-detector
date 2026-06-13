"""Awareness rubric anchor suite — the regression harness for rubric/model changes.

Re-grades the 6 hand-certified anchor templates (5 distinct, the corner-signature
anchor twice as a stability check) through the EXACT production template-analysis
path and compares against the certified levels. READ-ONLY: nothing is written.

Run after ANY change to AWARENESS_RUBRIC / STATIC_AWARENESS_TELLS wording, the
template prompt, or the classification model. A failing anchor means the change
over-corrected (or the model drifted — see the 2026-06-12 gemini-pro-latest
repoint incident). Exit code 0 = all anchors hold.

Usage:
    python3 scripts/anchor_suite.py                      # production model
    python3 scripts/anchor_suite.py --model gemini-3.1-pro-preview
"""
import argparse
import asyncio
import base64
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from supabase import create_client  # noqa: E402

from viraltracker.services.awareness_rubric import (  # noqa: E402
    AWARENESS_RUBRIC,
    AWARENESS_LEVEL_ORDER,
    normalize_awareness_level,
)
from viraltracker.services.gemini_service import GeminiService  # noqa: E402
from viraltracker.services.template_queue_service import (  # noqa: E402
    TEMPLATE_ANALYSIS_PROMPT,
    TEMPLATE_AWARENESS_MODEL,
)

# Hand-certified during the 2026-06 rubric certification (see memory:
# awareness-rubric-platform-consistency). Do NOT swap anchors casually — each
# encodes a settled doctrine point the user calibrated personally.
ANCHORS = [
    ("10c91491-9a71-41a5-aa9a-458b27173e46", 2, "Hairfinity corner sig #1 (signature exclusion)"),
    ("10c91491-9a71-41a5-aa9a-458b27173e46", 2, "Hairfinity corner sig #2 (stability re-run)"),
    ("097d226c-d294-4e75-9bce-f512a03c004d", 3, "Paloma hero-pack bridge (floor + introduction)"),
    ("004ab3bd-32ed-415b-9094-f2a8bb405bac", 4, "Primal Viking USP story (unnamed-rival superiority)"),
    ("03e53202-3551-4e22-b4aa-f449481c2184", 5, "Mars Men banner sale (offer prominence)"),
    ("d2515fac-e9a3-420b-918b-5b9e5115e7cc", 1, "tea flat-lay aesthetic (desire creation)"),
]


def parse_awareness(response_text):
    clean = response_text.strip()
    if clean.startswith("```"):
        clean = clean.split("```")[1]
        if clean.startswith("json"):
            clean = clean[4:]
    try:
        s = json.loads(clean.strip())
    except json.JSONDecodeError:
        return None
    raw = s.get("awareness_level")
    enum_level = normalize_awareness_level(raw) if isinstance(raw, str) else None
    return AWARENESS_LEVEL_ORDER[enum_level] if enum_level else None


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=TEMPLATE_AWARENESS_MODEL,
                    help="Gemini model id (default: production TEMPLATE_AWARENESS_MODEL)")
    args = ap.parse_args()

    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
    gemini = GeminiService(model=args.model)
    print(f"anchor suite on model: {args.model}")

    ids = list({a[0] for a in ANCHORS})
    rows = {r["id"]: r for r in (
        sb.table("scraped_templates")
        .select("id, storage_path, source_brand, source_landing_page, awareness_level")
        .in_("id", ids).execute().data or []
    )}

    sem = asyncio.Semaphore(3)
    results = []

    async def grade(anchor):
        tid, expected, label = anchor
        async with sem:
            t = rows.get(tid)
            if not t or not t.get("storage_path"):
                return (label, expected, None, "TEMPLATE MISSING")
            bucket, path = t["storage_path"].split("/", 1)
            img = await asyncio.to_thread(sb.storage.from_(bucket).download, path)
            prompt = TEMPLATE_ANALYSIS_PROMPT.format(
                page_name=t.get("source_brand") or "Unknown Brand",
                link_url=t.get("source_landing_page") or "Not available",
                awareness_rubric=AWARENESS_RUBRIC,
            )
            resp = await gemini.analyze_image_async(
                base64.b64encode(img).decode("utf-8"), prompt
            )
            got = parse_awareness(resp)
            return (label, expected, got, None)

    results = await asyncio.gather(*(grade(a) for a in ANCHORS))
    passes = 0
    for label, expected, got, err in results:
        ok = got == expected
        passes += ok
        status = "PASS" if ok else f"FAIL ({err})" if err else "FAIL"
        print(f"  [{status:>4}] expected L{expected}, got "
              f"{'L' + str(got) if got else '?'} — {label}")
    print(f"\n{passes}/{len(ANCHORS)} anchors hold")
    return 0 if passes == len(ANCHORS) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
