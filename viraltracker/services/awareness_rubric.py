"""Shared consumer-awareness rubric — Eugene Schwartz's 5 stages of awareness
(Breakthrough Advertising, 1966) refined with modern direct-response practice.

Single source of truth injected into the ad-creative classification prompts so the
awareness buckets are consistent across creative types. Wired into the video deep-
analysis + legacy video prompts today; the image/copy/LP classifiers can adopt the
same constant when their prompt version is next bumped (left untouched for now to
avoid mass re-classification of already-cached image ads).

Synthesized + adversarially verified 2026-06-05 (3-researcher panel -> synthesis ->
red-team), hardened by an independent Codex research + adversarial review (which
corrected an over-broad "cold brand/category mention = solution_aware" rule toward
Schwartz's true desire/result-aware stage 3), and live-calibrated against Martin
video classifications. Core principle: classify by the knowledge state the ad's
OPENING *presumes*, not what it merely mentions.

Contains no curly braces, so it is safe to pass as a ``.format`` substitution value.
"""

AWARENESS_RUBRIC = """Awareness = what the PROSPECT already knows. Classify by the knowledge state the opening PRESUMES (treats as given), NOT what it merely mentions. Naming a brand, category, or mechanism does NOT raise the stage if the ad is still INTRODUCING it cold. If the ad must teach a thing, the viewer is on the LOWER side of that seam.

The 5 stages (cold to hot):
- unaware - Knows nothing relevant; the opening presumes NO felt problem. Tells: pure curiosity/story/identity or surprising-fact/contrarian leads with NO specific symptom or pain the viewer would recognize in themselves. A personal STORY that enumerates specific recognizable symptoms is problem_aware, not unaware - judge the substance, not the narrative framing.
- problem_aware - Feels or recognizes the pain/need, but the opening does not presume prior knowledge of a solution path. Tells: symptom/audience callouts and problem agitation. It may mention a category/mechanism only if it is clearly teaching it cold, not relying on prior familiarity.
- solution_aware - Knows or immediately recognizes the desired result/solution path, but does NOT yet know that this product is the answer. Tells: desired-outcome leads, known-category comparisons ("not a sleep pill"), "tried everything" claims, alternatives, demos, or mechanisms presented as the way to get the desired result. A cold brand mention alone is NOT enough.
- product_aware - Presumes you already know YOUR product; deciding if it's best. Tells: brand-vs-named-rival comparison ("switched from X"), "you've seen us everywhere", objection-handling on this product, OR an opening that goes STRAIGHT into reviewing/endorsing the specific named product (testimonial-first, "why I love [Brand]") with features/mechanism used as proof of THIS product's superiority and NO category/problem bridge.
- most_aware - Already wants it; needs a reason to act now. Tells: the LEAD is the deal/terms (price, discount, urgency, code, "back in stock"), presuming desire is settled.

Boundary tests (one decidable question each; tie -> pick the LOWER side):
- unaware vs problem_aware: Does the opening presume a problem the viewer ALREADY feels? Merely surfacing one = unaware; presuming felt pain = problem_aware.
- problem_aware vs solution_aware: Does the opening rely on the viewer already wanting a result, knowing a solution path/category, having tried alternatives, or understanding a mechanism as a MEANS to the result? Yes = solution_aware. A mechanism explained as the ROOT CAUSE of the problem (no fix offered yet) stays problem_aware. Mere cold introduction of a brand/category/mechanism does not raise the stage.
- solution_aware vs product_aware: Does the opening do any BRIDGE/introduction work - presenting the product as the answer to a desired result/category? Bridging/introducing it = solution_aware. If it SKIPS the bridge and opens straight into reviewing/endorsing the NAMED product (social proof + proof of its superiority), presuming you are already evaluating it = product_aware.
- product_aware vs most_aware: Is the LEAD an actual OFFER/deal (price, discount, urgency, scarcity) presuming desire is settled? Yes = most_aware. A hard CTA ("click the link") or a results-timeline that still sells on the product's MERIT/claims is product_aware, not most_aware.

Skip pure attention-grabs ("STOP SCROLLING!") and judge the substantive message. Do NOT conflate awareness with market sophistication: unique mechanisms, enlarged claims, and identity hooks are sophistication/proof/angle devices. They affect awareness only when the creative presumes the viewer already understands the problem, result, category, or product.

A testimonial/review does NOT set the stage by itself - the CONTENT does. For a testimonial opening, judge the focus of the first ~10s: pain/symptoms/emotional struggle only, no fix named ("so exhausted I couldn't even play with my kids") = problem_aware; a general category, ingredient, or lifestyle change, NOT your brand ("once I started taking pine bark extract, my brain fog cleared") = solution_aware; the specific BRAND named as what they took, presuming you know it ("I just started taking Navitol and my energy is back") = product_aware.

Worked examples (opening unless noted):
- "Cortisol Reducer NOT a sleep pill" over a 3:13 AM clock -> solution_aware (positions against a known category + presents the mechanism as the MEANS; the problem visual does not lower it).
- "Your cortisol is up, you don't sleep; you don't sleep, your cortisol's up - a vicious cycle" (names the SAME mechanism but as the ROOT CAUSE, no fix offered) -> problem_aware (root-cause education deepens problem-awareness; mechanism-as-cause is not mechanism-as-means).
- Opens on a customer testimonial of the named brand ("Wow, I started taking Navitol and my energy improved") + "one thing I love about Navitol..." + mechanism (blood-brain barrier) used as proof of its superiority, with NO category/problem bridge -> product_aware (review/endorsement posture presumes the viewer is already evaluating the named product; classic retargeting copy). Contrast: a brand named while still BRIDGING from a desired result ("tired? there's a better way, it's called X") would be solution_aware.
- "My wife got very unwell - exhausted, brain fog, trouble sleeping" (a personal story enumerating specific recognizable symptoms) -> problem_aware (symptom callout presumes a felt problem; the story framing does not make it unaware).
- "Always tired moms... STOP SCROLLING!" -> skip the grab; classify the first substantive line ("always tired moms" = problem_aware).
- ENDING example: shows the branded bottle, lists the product's specific benefits + proof, with a "click the link" CTA and a results timeline but NO discount/urgency/deal -> product_aware (selling on the product's MERIT), NOT most_aware (which LEADS with the offer/deal)."""


# ---------------------------------------------------------------------------
# Shared awareness VOCABULARY — the one-definition home.
# Every consumer (ads image/video classifiers, the TEMPLATE classifier, scorers,
# UI labels) derives from these constants. Do NOT define a second copy anywhere:
# duplicated vocabularies are exactly the drift this module exists to prevent.
# ---------------------------------------------------------------------------

# Canonical enum order: least-aware -> most-aware. The INDEX+1 is the canonical
# 1-5 ordinal used wherever awareness is stored/compared as an INT
# (scraped_templates.awareness_level, SelectionContext.awareness_stage).
AWARENESS_LEVELS_ORDERED = (
    "unaware", "problem_aware", "solution_aware", "product_aware", "most_aware",
)

# The ONLY values allowed by the awareness CHECK constraints
# (ad_image_analysis.awareness_level, ad_creative_classifications.*_awareness_level).
VALID_AWARENESS_LEVELS = frozenset(AWARENESS_LEVELS_ORDERED)

# enum <-> INT ordinal (lossless both ways; locked by a tripwire test).
AWARENESS_LEVEL_ORDER = {lvl: i + 1 for i, lvl in enumerate(AWARENESS_LEVELS_ORDERED)}
AWARENESS_INT_TO_LEVEL = {i + 1: lvl for i, lvl in enumerate(AWARENESS_LEVELS_ORDERED)}

# INT -> human display label ("Problem Aware") — drives all UI labels/badges.
AWARENESS_LEVEL_LABELS = {
    i + 1: lvl.replace("_", " ").title() for i, lvl in enumerate(AWARENESS_LEVELS_ORDERED)
}


def normalize_awareness_level(value):
    """Lower/strip/space->underscore an awareness label; return None if not canonical.

    The trust-boundary normalizer for ALL Gemini-returned awareness labels: recovers
    casing/spacing variants ("Product Aware" -> product_aware), nulls true garbage so
    off-rubric output degrades to None instead of violating a DB CHECK constraint.
    """
    if not value or not isinstance(value, str):
        return None
    norm = value.strip().lower().replace(" ", "_")
    return norm if norm in VALID_AWARENESS_LEVELS else None
