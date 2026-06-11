"""One-off flash backfill: has_product_placement for the existing template library.

Cheap binary question per template on gemini-flash (NOT the pro awareness judge —
this is a layout attribute, no calibration needed). 16 concurrent workers, true
async, resumable (WHERE has_product_placement IS NULL). ~3,200 templates, ~$1.
"""
import os, sys, json, base64, asyncio, time
sys.path.insert(0, "/Users/ryemckenzie/conductor/workspaces/viraltracker/khartoum")
from dotenv import load_dotenv
load_dotenv("/Users/ryemckenzie/conductor/workspaces/viraltracker/khartoum/.env")
from supabase import create_client
from viraltracker.services.gemini_service import GeminiService

PROMPT = """Look at this ad image. Answer ONE question:

Is an identifiable PRODUCT CONTAINER (bottle, jar, pack, box, stick pack, tub, pouch)
visible anywhere in the frame — whether it is the hero, a co-hero, or just a small
corner pack-shot?

People, food/drink without packaging, logos alone, and text do NOT count. Only an
actual product container counts.

Return ONLY valid JSON: {"has_product_placement": true} or {"has_product_placement": false}"""

sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])


async def main():
    gemini = GeminiService(model="gemini-flash-latest")
    done, skipped, t0 = 0, 0, time.time()
    bad = set()
    while True:
        q = (sb.table("scraped_templates")
             .select("id, storage_path")
             .is_("has_product_placement", "null")
             .not_.is_("storage_path", "null"))
        if bad:
            q = q.not_.in_("id", list(bad))
        batch = q.limit(64).execute().data or []
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
                    resp = await gemini.analyze_image_async(b64, PROMPT)
                    clean = resp.strip()
                    if clean.startswith("```"):
                        clean = clean.split("```")[1]
                        if clean.startswith("json"):
                            clean = clean[4:]
                    val = json.loads(clean.strip()).get("has_product_placement")
                    if not isinstance(val, bool):
                        skipped += 1; bad.add(t["id"]); return
                    await asyncio.to_thread(
                        lambda: sb.table("scraped_templates")
                        .update({"has_product_placement": val}).eq("id", t["id"]).execute()
                    )
                    done += 1
                except Exception as e:
                    skipped += 1; bad.add(t["id"])
                    print(f"  ERR {t['id'][:8]} {str(e)[:70]}", flush=True)

        await asyncio.gather(*(grade(t) for t in batch))
        rate = done / max(1, (time.time() - t0) / 60)
        print(f"...{done} done, {skipped} skipped ({rate:.0f}/min)", flush=True)

    true_n = sb.table("scraped_templates").select("id", count="exact").eq("has_product_placement", True).execute().count
    false_n = sb.table("scraped_templates").select("id", count="exact").eq("has_product_placement", False).execute().count
    print(f"\nDONE: {done} graded ({skipped} skipped) | with placement: {true_n} | without: {false_n}", flush=True)

asyncio.run(main())
