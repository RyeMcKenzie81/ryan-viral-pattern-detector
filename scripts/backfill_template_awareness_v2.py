"""Template awareness backfill — re-grade the full scraped_templates library onto the
calibrated rubric (template prompt v2).

Per the locked plan (D3 + Codex corrections):
- UNIFORM overwrite (human overrides included), but the old values are SNAPSHOTTED into
  ai_analysis_raw under 'pre_v2_backfill' (old int, old name, old raw) — nothing is lost.
- Resumable/idempotent: WHERE awareness_prompt_version IS DISTINCT FROM 'v2'; failed/
  skipped rows keep their old version and are retried on the next run.
- ONE shared GeminiService (per-instance rate limiter actually serializes).
- Off-enum/unparseable -> SKIP + log (never write garbage or NULL over a real label).
- Updates awareness_level + awareness_level_name + awareness_prompt_version together.
- Prints the old->new transition matrix at the end.
"""
import os, sys, json, base64, asyncio, time
from collections import defaultdict
sys.path.insert(0, "/Users/ryemckenzie/conductor/workspaces/viraltracker/khartoum")
from dotenv import load_dotenv
load_dotenv("/Users/ryemckenzie/conductor/workspaces/viraltracker/khartoum/.env")
from supabase import create_client

from viraltracker.services.template_queue_service import (
    TEMPLATE_ANALYSIS_PROMPT, TEMPLATE_AWARENESS_MODEL, TEMPLATE_ANALYSIS_PROMPT_VERSION,
)
from viraltracker.services.awareness_rubric import (
    AWARENESS_RUBRIC, AWARENESS_LEVEL_ORDER, AWARENESS_LEVEL_LABELS, normalize_awareness_level,
)
from viraltracker.services.gemini_service import GeminiService



VER = TEMPLATE_ANALYSIS_PROMPT_VERSION
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
print(f"backfill -> version {VER}, model {TEMPLATE_AWARENESS_MODEL}", flush=True)


def parse_awareness(response_text):
    clean = response_text.strip()
    if clean.startswith("```"):
        clean = clean.split("```")[1]
        if clean.startswith("json"):
            clean = clean[4:]
    try:
        s = json.loads(clean.strip())
    except json.JSONDecodeError:
        return None, None
    raw = s.get("awareness_level")
    enum_level = normalize_awareness_level(raw) if isinstance(raw, str) else None
    if enum_level is None:
        return None, None
    return AWARENESS_LEVEL_ORDER[enum_level], s.get("awareness_level_reasoning", "")


async def main():
    gemini = GeminiService(model=TEMPLATE_AWARENESS_MODEL)
    cell, done, skipped, t0 = defaultdict(int), 0, 0, time.time()
    bad = set()  # in-run skip ledger: corrupt/off-enum rows excluded from refetch

    while True:
        q = (sb.table("scraped_templates")
                 .select("id, storage_path, awareness_level, awareness_level_name, "
                         "source_brand, source_landing_page, ai_analysis_raw")
                 .neq("awareness_prompt_version", VER)
                 .not_.is_("storage_path", "null"))
        if bad:
            q = q.not_.in_("id", list(bad))
        batch = q.limit(50).execute().data or []
        # PostgREST neq excludes NULLs; fetch NULL-version rows explicitly too
        if len(batch) < 50:
            q2 = (sb.table("scraped_templates")
                      .select("id, storage_path, awareness_level, awareness_level_name, "
                              "source_brand, source_landing_page, ai_analysis_raw")
                      .is_("awareness_prompt_version", "null")
                      .not_.is_("storage_path", "null"))
            if bad:
                q2 = q2.not_.in_("id", list(bad))
            batch += q2.limit(50 - len(batch)).execute().data or []
        if not batch:
            break

        sem = asyncio.Semaphore(16)

        async def grade(t):
            nonlocal done, skipped
            async with sem:
                try:
                    bucket, path = t["storage_path"].split("/", 1)
                    img = await asyncio.to_thread(sb.storage.from_(bucket).download, path)
                    b64 = base64.b64encode(img).decode("utf-8")
                    prompt = TEMPLATE_ANALYSIS_PROMPT.format(
                        page_name=t.get("source_brand") or "Unknown Brand",
                        link_url=t.get("source_landing_page") or "Not available",
                        awareness_rubric=AWARENESS_RUBRIC,
                    )
                    resp = await gemini.analyze_image_async(b64, prompt)
                    new_int, reason = parse_awareness(resp)
                    if new_int is None:
                        skipped += 1; bad.add(t["id"])
                        print(f"  SKIP {t['id'][:8]} (unusable AI output)", flush=True)
                        return
                    new_raw = {
                        "awareness_level": new_int,
                        "awareness_level_reasoning": reason,
                        "awareness_prompt_version": VER,
                        "pre_v2_backfill": {
                            "awareness_level": t.get("awareness_level"),
                            "awareness_level_name": t.get("awareness_level_name"),
                            "ai_analysis_raw": t.get("ai_analysis_raw"),
                        },
                    }
                    await asyncio.to_thread(
                        lambda: sb.table("scraped_templates").update({
                            "awareness_level": new_int,
                            "awareness_level_name": AWARENESS_LEVEL_LABELS[new_int],
                            "awareness_prompt_version": VER,
                            "ai_analysis_raw": new_raw,
                        }).eq("id", t["id"]).execute()
                    )
                    cell[(t.get("awareness_level"), new_int)] += 1
                    done += 1
                except Exception as e:
                    skipped += 1; bad.add(t["id"])
                    print(f"  ERR {t['id'][:8]} {str(e)[:80]}", flush=True)

        await asyncio.gather(*(grade(t) for t in batch))
        rate = done / max(1, (time.time() - t0) / 60)
        print(f"...{done} done, {skipped} skipped ({rate:.1f}/min)", flush=True)

    print(f"\nDONE: {done} re-graded, {skipped} skipped (retry by re-running)")
    print("TRANSITION MATRIX (old -> new):")
    print("        new:  1    2    3    4    5")
    for old in [1, 2, 3, 4, 5, None]:
        row = "  ".join(f"{cell[(old, new)]:>4}" for new in range(1, 6))
        print(f"  old {str(old):>4}: {row}")

asyncio.run(main())
