"""
Ad Creator V2 Intelligence Guide — styled HTML reference for how the system learns.
"""

import streamlit as st

st.set_page_config(
    page_title="V2 Intelligence Guide",
    page_icon="🧠",
    layout="wide"
)

from viraltracker.ui.auth import require_auth
require_auth()

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

st.markdown("""
<style>
    .guide-container {
        max-width: 960px;
        margin: 0 auto;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        color: #e0e0e0;
        line-height: 1.7;
    }
    .guide-container h1.guide-title {
        font-size: 2.2rem;
        font-weight: 700;
        margin-bottom: 0.25rem;
        color: #ffffff;
    }
    .guide-container .guide-subtitle {
        font-size: 1rem;
        color: #888;
        margin-bottom: 2rem;
    }
    .guide-container h2 {
        font-size: 1.5rem;
        font-weight: 600;
        color: #ffffff;
        margin-top: 2.5rem;
        margin-bottom: 0.75rem;
        padding-bottom: 0.4rem;
        border-bottom: 1px solid #333;
    }
    .guide-container h3 {
        font-size: 1.15rem;
        font-weight: 600;
        color: #d0d0d0;
        margin-top: 1.5rem;
        margin-bottom: 0.5rem;
    }
    .guide-container p, .guide-container li {
        font-size: 0.95rem;
        color: #c0c0c0;
    }
    .guide-container ul { padding-left: 1.5rem; }
    .guide-container li { margin-bottom: 0.35rem; }
    .guide-container code {
        background: #1a1a2e;
        color: #7dd3fc;
        padding: 2px 6px;
        border-radius: 4px;
        font-size: 0.85rem;
    }
    .guide-container pre {
        background: #0f0f1a;
        border: 1px solid #222;
        border-radius: 8px;
        padding: 1rem;
        overflow-x: auto;
        font-size: 0.85rem;
        color: #a0d0a0;
        line-height: 1.5;
    }

    /* Big Picture box */
    .big-picture {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border: 1px solid #2a2a4a;
        border-radius: 12px;
        padding: 1.5rem 2rem;
        margin: 1.5rem 0;
    }
    .big-picture pre {
        background: transparent;
        border: none;
        padding: 0;
        margin: 0.75rem 0 0 0;
        color: #7dd3fc;
        font-size: 0.9rem;
    }

    /* Layer cards */
    .layer-card {
        background: #111827;
        border: 1px solid #1f2937;
        border-radius: 12px;
        padding: 1.5rem 2rem;
        margin: 1.25rem 0;
    }
    .layer-card .layer-badge {
        display: inline-block;
        font-size: 0.7rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        padding: 3px 10px;
        border-radius: 100px;
        margin-bottom: 0.75rem;
    }
    .badge-instant  { background: #065f46; color: #6ee7b7; }
    .badge-weekly   { background: #1e3a5f; color: #7dd3fc; }
    .badge-per-ad   { background: #4c1d95; color: #c4b5fd; }
    .badge-on-demand { background: #78350f; color: #fcd34d; }
    .badge-always   { background: #831843; color: #f9a8d4; }

    .layer-card h3 {
        margin-top: 0;
        font-size: 1.25rem;
        color: #f3f4f6;
    }
    .layer-card p { color: #9ca3af; }

    /* Scorer table */
    .scorer-table {
        width: 100%;
        border-collapse: collapse;
        margin: 1rem 0;
        font-size: 0.9rem;
    }
    .scorer-table th {
        text-align: left;
        padding: 0.5rem 0.75rem;
        color: #9ca3af;
        font-weight: 600;
        font-size: 0.8rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        border-bottom: 1px solid #374151;
    }
    .scorer-table td {
        padding: 0.5rem 0.75rem;
        border-bottom: 1px solid #1f2937;
        color: #d1d5db;
    }
    .scorer-table tr:hover td { background: #1f2937; }
    .weight-bar {
        display: inline-block;
        height: 8px;
        border-radius: 4px;
        background: #3b82f6;
        vertical-align: middle;
        margin-left: 6px;
    }

    /* Phase badges */
    .phase-badge {
        display: inline-block;
        font-size: 0.75rem;
        font-weight: 600;
        padding: 2px 10px;
        border-radius: 100px;
    }
    .phase-cold { background: #1e3a5f; color: #7dd3fc; }
    .phase-warm { background: #78350f; color: #fcd34d; }
    .phase-hot  { background: #7f1d1d; color: #fca5a5; }

    /* Timeline table */
    .timeline-table {
        width: 100%;
        border-collapse: collapse;
        margin: 1rem 0;
        font-size: 0.9rem;
    }
    .timeline-table th {
        text-align: left;
        padding: 0.6rem 0.75rem;
        color: #9ca3af;
        font-weight: 600;
        font-size: 0.8rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        border-bottom: 1px solid #374151;
    }
    .timeline-table td {
        padding: 0.6rem 0.75rem;
        border-bottom: 1px solid #1f2937;
        color: #d1d5db;
    }
    .timeline-table tr:hover td { background: #1f2937; }

    /* Callout boxes */
    .callout {
        border-radius: 10px;
        padding: 1rem 1.25rem;
        margin: 1.25rem 0;
        font-size: 0.9rem;
    }
    .callout-blue {
        background: #0c2d48;
        border-left: 4px solid #3b82f6;
        color: #93c5fd;
    }
    .callout-green {
        background: #052e16;
        border-left: 4px solid #22c55e;
        color: #86efac;
    }
    .callout-amber {
        background: #2a1f00;
        border-left: 4px solid #f59e0b;
        color: #fcd34d;
    }
    .callout strong { color: #ffffff; }

    /* Bottom line box */
    .bottom-line {
        background: linear-gradient(135deg, #1a1a2e 0%, #1e293b 100%);
        border: 2px solid #3b82f6;
        border-radius: 12px;
        padding: 1.5rem 2rem;
        margin: 2rem 0;
    }
    .bottom-line h3 { color: #3b82f6; margin-top: 0; }

    /* Job SQL blocks */
    .job-block {
        background: #0f0f1a;
        border: 1px solid #1f2937;
        border-radius: 8px;
        padding: 1rem 1.25rem;
        margin: 0.75rem 0;
    }
    .job-block .job-name {
        font-weight: 700;
        color: #7dd3fc;
        font-size: 0.95rem;
        margin-bottom: 0.35rem;
    }
    .job-block .job-desc {
        color: #9ca3af;
        font-size: 0.85rem;
        margin-bottom: 0.5rem;
    }
    .job-block code {
        font-size: 0.8rem;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# HTML content
# ---------------------------------------------------------------------------

st.markdown("""
<div class="guide-container">

<h1 class="guide-title">V2 Intelligence System</h1>
<p class="guide-subtitle">How the Ad Creator V2 learns and gets smarter over time</p>

<!-- ===== BIG PICTURE ===== -->
<div class="big-picture">
<h3 style="color:#7dd3fc; margin-top:0;">The Feedback Loop</h3>
<p style="color:#94a3b8; margin-bottom:0.5rem;">The entire intelligence system is one continuous loop. The more ads you create and review, the smarter every layer gets.</p>
<pre>You create ads
  → System reviews them (approve / reject)
  → You override some of those decisions
  → Approved ads go live on Meta → performance data flows back
  → Weekly jobs analyze everything
  → Next batch of ads uses what the system learned</pre>
</div>

<!-- ===== LAYER 1 ===== -->
<div class="layer-card">
<span class="layer-badge badge-instant">Instant</span>
<h3>Layer 1 — Template Scoring</h3>
<p>When you use <strong>Smart Select</strong>, the system scores every template against 8 criteria to pick the best ones for your brand.</p>

<table class="scorer-table">
<tr><th>Scorer</th><th>What It Asks</th><th>Default Weight</th></tr>
<tr><td><strong>Asset Match</strong></td><td>Do our product images fit this template's layout?</td><td>1.0 <span class="weight-bar" style="width:100px"></span></td></tr>
<tr><td><strong>Unused Bonus</strong></td><td>Have we never tried this template?</td><td>0.8 <span class="weight-bar" style="width:80px"></span></td></tr>
<tr><td><strong>Category Match</strong></td><td>Is this template's type what we're looking for?</td><td>0.6 <span class="weight-bar" style="width:60px"></span></td></tr>
<tr><td><strong>Belief Clarity</strong></td><td>How well does this template convey belief messaging?</td><td>0.6 <span class="weight-bar" style="width:60px"></span></td></tr>
<tr><td><strong>Awareness Align</strong></td><td>Does the template match the customer's awareness stage?</td><td>0.5 <span class="weight-bar" style="width:50px"></span></td></tr>
<tr><td><strong>Audience Match</strong></td><td>Is it designed for our target demographic?</td><td>0.4 <span class="weight-bar" style="width:40px"></span></td></tr>
<tr><td><strong>Fatigue</strong></td><td>Have we overused this template recently?</td><td>0.4 <span class="weight-bar" style="width:40px"></span></td></tr>
<tr><td><strong>Performance</strong></td><td>How often have ads from this template been approved?</td><td>0.3 <span class="weight-bar" style="width:30px"></span></td></tr>
</table>

<div class="callout callout-blue">
<strong>These weights aren't permanent.</strong> Layer 4 (Scorer Weight Learning) gradually adjusts them based on which scorers actually predict good ads for your brand.
</div>
</div>

<!-- ===== LAYER 2 ===== -->
<div class="layer-card">
<span class="layer-badge badge-weekly">Weekly</span>
<h3>Layer 2 — Quality Calibration</h3>
<p>The automated review uses a 16-check rubric (9 visual + 5 content + 2 congruence). Sometimes it's wrong. This layer watches your <strong>overrides</strong> and proposes threshold adjustments.</p>

<h3>How It Works</h3>
<ol>
<li>Every week, the system analyzes your recent overrides</li>
<li>Calculates <strong>false positive rate</strong> (approved ads you rejected) and <strong>false negative rate</strong> (rejected ads you approved)</li>
<li>If either rate is too high, proposes a threshold change</li>
<li>You review the proposal in <strong>Platform Settings → Calibration Proposals</strong></li>
<li>Activate it or dismiss it with a reason</li>
</ol>

<div class="callout callout-green">
<strong>Example:</strong> The system keeps rejecting ads with a congruence score of 0.58, but you keep overriding them to approved. Calibration will propose lowering the threshold from 0.60 to 0.55 so those borderline ads pass automatically.
</div>
</div>

<!-- ===== LAYER 3 ===== -->
<div class="layer-card">
<span class="layer-badge badge-per-ad">Per Ad</span>
<h3>Layer 3 — Creative Genome</h3>
<p>Every ad gets tagged with <strong>creative elements</strong> — hook type, color mode, template category, awareness stage, canvas size, content source. The Genome tracks how each element value performs over time using real Meta Ads data.</p>

<h3>Maturation Windows</h3>
<table class="scorer-table">
<tr><th>Metric</th><th>Matures After</th><th>Min Impressions</th></tr>
<tr><td>CTR</td><td>3 days</td><td>500</td></tr>
<tr><td>Conversion Rate</td><td>7 days</td><td>500</td></tr>
<tr><td>ROAS</td><td>10 days</td><td>500</td></tr>
</table>

<p>After maturation, performance is normalized against your brand's baselines and converted into a composite <strong>reward score</strong> (0–1), weighted by campaign objective:</p>

<table class="scorer-table">
<tr><th>Campaign Type</th><th>CTR</th><th>Conv</th><th>ROAS</th></tr>
<tr><td>Conversions</td><td>20%</td><td>50%</td><td>30%</td></tr>
<tr><td>Sales</td><td>20%</td><td>30%</td><td>50%</td></tr>
<tr><td>Traffic</td><td>60%</td><td>20%</td><td>20%</td></tr>
<tr><td>Awareness</td><td>70%</td><td>10%</td><td>20%</td></tr>
</table>

<div class="callout callout-blue">
<strong>This is the foundation.</strong> Layers 4, 5, 6, and 7 all depend on the Genome's reward data. The more ads you push live and let mature, the better everything else gets.
</div>
</div>

<!-- ===== LAYER 4 ===== -->
<div class="layer-card">
<span class="layer-badge badge-weekly">Weekly</span>
<h3>Layer 4 — Scorer Weight Learning</h3>
<p>Learns the <strong>optimal scorer weights</strong> for your brand using Thompson Sampling. Instead of static defaults, the system figures out which of the 8 scorers actually predict good ads.</p>

<h3>The Three Phases</h3>
<table class="scorer-table">
<tr><th>Phase</th><th>Observations</th><th>Behavior</th></tr>
<tr><td><span class="phase-badge phase-cold">Cold</span></td><td>0 – 29</td><td>Static weights only. Learning hasn't started yet.</td></tr>
<tr><td><span class="phase-badge phase-warm">Warm</span></td><td>30 – 99</td><td>Gradual blend of static + learned weights. Data is starting to matter.</td></tr>
<tr><td><span class="phase-badge phase-hot">Hot</span></td><td>100+</td><td>Fully learned weights. The system knows what works for your brand.</td></tr>
</table>

<p>"Observations" = ads that have both selection snapshot data AND a performance reward score.</p>

<h3>Safety Rails</h3>
<ul>
<li>No weight drops below <code>0.1</code> — nothing gets zeroed out</li>
<li>No weight exceeds <code>2.0</code></li>
<li>Max change per weekly update: <code>±0.15</code> per scorer</li>
</ul>
</div>

<!-- ===== LAYER 5 ===== -->
<div class="layer-card">
<span class="layer-badge badge-weekly">Weekly</span>
<h3>Layer 5 — Interaction Detection</h3>
<p>Discovers which creative element <strong>pairs</strong> work well together (synergies) and which hurt each other (conflicts).</p>

<p>For every element pair, it compares the <em>actual</em> average reward when both appear together vs the <em>expected</em> reward if they were independent. Uses bootstrap confidence intervals (1,000 iterations) to confirm the effect is real.</p>

<div class="callout callout-green">
<strong>Synergy example:</strong> "before_after template + 1080×1350 canvas" → <span style="color:#22c55e">+12% lift</span>. These perform 12% better together than you'd expect from each alone.
</div>
<div class="callout callout-amber">
<strong>Conflict example:</strong> "meme template + premium color mode" → <span style="color:#f59e0b">−8% drag</span>. These don't mix well for your brand.
</div>

<ul>
<li>Requires 10+ ads per element pair</li>
<li>Effect threshold: ±5% to be flagged</li>
<li>Keeps top 15 interactions ranked by effect size</li>
</ul>
</div>

<!-- ===== LAYER 6 ===== -->
<div class="layer-card">
<span class="layer-badge badge-weekly">Weekly</span>
<h3>Layer 6 — Whitespace Identification</h3>
<p>Finds <strong>untested</strong> element combinations that <em>should</em> perform well based on what's known about each individual element.</p>

<p>Think of it as "suggested experiments." The system says: <em>"You've never tried quote_card + awareness stage 3, but both do well individually — this combo is worth trying."</em></p>

<pre>predicted potential = avg(score A, score B)
                    + synergy bonus (from Layer 5)
                    + novelty bonus (decays with usage)</pre>

<p>Filters: both elements score &gt; 0.5, used &lt; 5 times, no known conflicts. Surfaces top 20 candidates.</p>
</div>

<!-- ===== LAYER 7 ===== -->
<div class="layer-card">
<span class="layer-badge badge-weekly">Weekly</span>
<h3>Layer 7 — Visual Style Clustering</h3>
<p>Groups your ads by <strong>visual similarity</strong> using DBSCAN clustering on visual embeddings, then correlates each cluster with performance.</p>

<h3>How It Works</h3>
<ol>
<li>Every reviewed ad gets a visual embedding (Gemini Flash descriptor → OpenAI embedding)</li>
<li>DBSCAN groups visually similar ads into clusters</li>
<li>Each cluster gets labeled with common visual traits (layout, colors, style)</li>
<li>Clusters are ranked by average reward score</li>
</ol>

<div class="callout callout-blue">
<strong>Diversity check:</strong> When generating new ads, the system checks if a new ad is &gt; 90% similar to an existing cluster centroid. If so, it flags a diversity warning to avoid visual repetition.
</div>
</div>

<!-- ===== LAYER 8 ===== -->
<div class="layer-card">
<span class="layer-badge badge-on-demand">On Demand</span>
<h3>Layer 8 — Generation Experiments</h3>
<p>A/B test different generation strategies. Change one thing about the pipeline and measure whether it actually helps.</p>

<h3>Experiment Types</h3>
<ul>
<li><strong>prompt_version</strong> — test different prompts</li>
<li><strong>pipeline_config</strong> — test different pipeline settings</li>
<li><strong>review_rubric</strong> — test different review criteria</li>
<li><strong>element_strategy</strong> — test different creative element approaches</li>
</ul>

<p>Uses <strong>Mann-Whitney U test</strong> for statistical comparison. Each ad is a binary outcome (approved or not). Deterministic arm assignment via SHA-256 hashing ensures retries land in the same arm.</p>

<ul>
<li>Max 1 active experiment per brand</li>
<li>Default: 50/50 split, 20 ads minimum per arm</li>
<li>Winner declared at p &lt; 0.05</li>
</ul>
</div>

<!-- ===== LAYER 9 ===== -->
<div class="layer-card">
<span class="layer-badge badge-always">Always On</span>
<h3>Layer 9 — Cross-Brand Transfer</h3>
<p>Lets a new brand <strong>bootstrap</strong> from an established brand's data instead of starting from zero.</p>

<ul>
<li>Opt-in per brand in Brand Manager</li>
<li>Only aggregate stats cross boundaries — no raw ad data</li>
<li>Weighted by brand similarity (cosine similarity of element score vectors)</li>
<li>All transferred data shrunk by <strong>70%</strong> (0.3× multiplier) so own data dominates quickly</li>
</ul>

<div class="callout callout-green">
<strong>Use it when</strong> launching a new brand in the same org as an established one, especially if they target similar audiences.
</div>
<div class="callout callout-amber">
<strong>Don't use it when</strong> brands are in completely different categories or have conflicting visual identities.
</div>
</div>

<!-- ===== HOW TO USE IT ===== -->
<h2>How to Activate It</h2>

<div class="layer-card" style="border-color:#3b82f6;">
<h3 style="color:#3b82f6;">Step 1: Verify Scheduled Jobs</h3>
<p>You need these jobs running for each brand. Check in the Scheduled Tasks page.</p>

<div class="job-block">
<div class="job-name">genome_validation</div>
<div class="job-desc">Runs Layers 4–7: scorer weights, interactions, whitespace, clustering</div>
<code>Cron: 0 4 * * 0 (Sundays 4am)</code>
</div>

<div class="job-block">
<div class="job-name">quality_calibration</div>
<div class="job-desc">Runs Layer 2: analyzes overrides, proposes threshold changes</div>
<code>Cron: 0 3 * * 6 (Saturdays 3am)</code>
</div>

<div class="job-block">
<div class="job-name">creative_genome_update</div>
<div class="job-desc">Runs Layer 3: fetches Meta performance data, computes rewards</div>
<code>Cron: 0 5 * * * (Daily 5am)</code>
</div>
</div>

<div class="layer-card" style="border-color:#3b82f6;">
<h3 style="color:#3b82f6;">Step 2: Create Ads with Smart Select</h3>
<p>Use <strong>Smart Select</strong> mode for template selection. This generates the selection data that scorer weight learning needs. Run 2–3 batches per week with 3–5 templates each.</p>
</div>

<div class="layer-card" style="border-color:#3b82f6;">
<h3 style="color:#3b82f6;">Step 3: Review & Override Ads</h3>
<p><strong>This is the most important step.</strong> After each batch:</p>
<ol>
<li>Go to <strong>View Results</strong></li>
<li><strong>Override Approve</strong> any rejected ads that are actually good</li>
<li><strong>Override Reject</strong> any approved ads that are actually bad</li>
<li>For exceptional ads, use <strong>Mark as Exemplar</strong></li>
</ol>
<div class="callout callout-green" style="margin-bottom:0;">
<strong>Target: 10–20 overrides per week.</strong> This is the primary signal for Layers 2, 3, 4, and 5.
</div>
</div>

<div class="layer-card" style="border-color:#3b82f6;">
<h3 style="color:#3b82f6;">Step 4: Push Ads to Meta</h3>
<p>Approved ads need to go live so performance data (CTR, conversions, ROAS) can flow back. The Genome needs at least 3 days + 500 impressions per ad to start learning.</p>
</div>

<div class="layer-card" style="border-color:#3b82f6;">
<h3 style="color:#3b82f6;">Step 5: Check Weekly Progress</h3>
<p>After the weekly jobs run, check <strong>Platform Settings</strong>:</p>
<ul>
<li><strong>Scorer Weights tab</strong> — are observations increasing?</li>
<li><strong>Interaction Effects tab</strong> — any synergies or conflicts found?</li>
<li><strong>Visual Clusters tab</strong> — any visual style patterns forming?</li>
<li><strong>Calibration Proposals tab</strong> — any threshold adjustments proposed?</li>
</ul>
</div>

<!-- ===== TIMELINE ===== -->
<h2>Expected Timeline</h2>

<table class="timeline-table">
<tr><th>Milestone</th><th>When</th><th>What Unlocks</th></tr>
<tr><td>First batch created</td><td>Day 1</td><td>Layer 1 — template scoring with static weights</td></tr>
<tr><td>10+ overrides</td><td>Week 1–2</td><td>Layer 2 — calibration starts proposing changes</td></tr>
<tr><td>Ads live on Meta 3+ days</td><td>Week 1–2</td><td>Layer 3 — genome starts computing rewards</td></tr>
<tr><td>30+ observations with rewards</td><td>Week 3–6</td><td>Layer 4 enters <span class="phase-badge phase-warm">warm</span> phase</td></tr>
<tr><td>50+ ads with element tags</td><td>Week 4–8</td><td>Layer 5 — interaction detection kicks in</td></tr>
<tr><td>Visual embeddings stored</td><td>After deploy</td><td>Layer 7 — visual clustering begins</td></tr>
<tr><td>100+ observations with rewards</td><td>Week 8–12</td><td>Layer 4 enters <span class="phase-badge phase-hot">hot</span> phase — fully learned</td></tr>
</table>

<!-- ===== BOTTOM LINE ===== -->
<div class="bottom-line">
<h3>The Bottom Line</h3>
<p style="color:#e0e0e0; font-size: 1.05rem; margin-bottom: 0.5rem;">Two things make everything work:</p>
<ol style="color:#e0e0e0; font-size: 1rem;">
<li><strong>Create ads regularly</strong> — at least 2–3 batches per week using Smart Select</li>
<li><strong>Override the review decisions</strong> — approve good rejected ads, reject bad approved ads, at least 10–20 per week</li>
</ol>
<p style="color:#9ca3af; margin-bottom:0;">Everything else is automated.</p>
</div>

<!-- ===== WHERE TO SEE EVERYTHING ===== -->
<h2>Where to See Everything</h2>

<table class="timeline-table">
<tr><th>Layer</th><th>Location</th></tr>
<tr><td>Template Scoring</td><td>Ad Creator V2 → Smart Select → Preview</td></tr>
<tr><td>Quality Calibration</td><td>Platform Settings → Calibration Proposals</td></tr>
<tr><td>Creative Genome</td><td>Runs in background — feeds all other layers</td></tr>
<tr><td>Scorer Weights</td><td>Platform Settings → Scorer Weights</td></tr>
<tr><td>Interactions</td><td>Platform Settings → Interaction Effects</td></tr>
<tr><td>Whitespace</td><td>Advisory context during ad generation</td></tr>
<tr><td>Visual Clusters</td><td>Platform Settings → Visual Clusters</td></tr>
<tr><td>Experiments</td><td>Platform Settings → Generation Experiments</td></tr>
<tr><td>Cross-Brand</td><td>Brand Manager → toggle per brand</td></tr>
</table>

</div>
""", unsafe_allow_html=True)
