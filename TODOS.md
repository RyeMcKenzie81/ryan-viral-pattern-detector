# TODOS

## Event Retention Automation
**What:** Set up pg_cron to auto-delete activity_events older than 90 days.
**Status:** Migration added with one-time cleanup + cron SQL comment. Need to enable pg_cron on Supabase and schedule: `SELECT cron.schedule('activity-event-retention', '0 3 * * *', $$DELETE FROM activity_events WHERE created_at < now() - interval '90 days'$$);`
**Added:** 2026-03-30 from /plan-eng-review of Activity Feed feature.
**Updated:** 2026-03-31 — migration created, one-time cleanup included, pg_cron SQL documented.

## Activity Feed Phase 3 — Rich Media Cards
**What:** Facebook-style image grid cards in the Activity Feed. When ads finish generating, show a hero image + 3-4 thumbnails + "+N" overflow badge. Also applicable to template scraping (scraped creatives), asset downloads, and SEO images.
**Status:** Not started. Needs /office-hours → planning pipeline.
**Requires:** Storing image URLs in event `details` JSONB during emission; grid renderer in `render_event_card`; checking where generated ad images are stored.
**Added:** 2026-03-31 from user feedback on Activity Feed.
