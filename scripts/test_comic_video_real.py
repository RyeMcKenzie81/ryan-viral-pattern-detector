#!/usr/bin/env python3
"""
Test Comic Video System with real JSON data.

Run with: python3 scripts/test_comic_video_real.py
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Real comic JSON from user
REAL_COMIC_JSON = {
  "comic_title": "Inflation Explained by Raccoons",
  "video_title": "Why Your Trash Costs More",
  "total_panels": 15,
  "target_runtime": "2:30 - 3:00",

  "structure": {
    "title": "Panel 1",
    "act_1": "Panels 2-4 (The Basics)",
    "act_2": "Panels 5-8 (What Causes Inflation)",
    "act_3": "Panels 9-12 (The Fed & Consequences)",
    "act_4": "Panels 13-15 (The Lesson)"
  },

  "visual_flow": {
    "reading_order": "Left to right, top to bottom (Z-pattern)",
    "color_coding": {
      "panel_1": "dark_blue",
      "panels_2_3": "neutral_gray",
      "panel_4": "neutral_gray",
      "panels_5_6_7": "warning_orange",
      "panel_8": "dramatic_dark",
      "panels_9_10_11": "danger_red",
      "panel_12": "neutral_blue",
      "panels_13_14": "mixed_red_green",
      "panel_15": "celebration_gold"
    }
  },

  "layout_recommendation": {
    "format": "4-4-4-3 grid",
    "grid_structure": [
      {"row": 1, "columns": 4, "panels": [1, 2, 3, 4]},
      {"row": 2, "columns": 4, "panels": [5, 6, 7, 8]},
      {"row": 3, "columns": 4, "panels": [9, 10, 11, 12]},
      {"row": 4, "columns": 3, "panels": [13, 14, 15]}
    ],
    "panel_arrangement": [
      ["Panel 1 (Title)", "Panel 2", "Panel 3", "Panel 4"],
      ["Panel 5", "Panel 6", "Panel 7", "Panel 8"],
      ["Panel 9", "Panel 10", "Panel 11", "Panel 12"],
      ["Panel 13", "Panel 14", "Panel 15 (Outro)"]
    ]
  },

  "panels": [
    {
      "panel_number": 1,
      "panel_type": "TITLE",
      "scene": "Title Card",
      "mood": "dramatic",
      "header_text": "INFLATION EXPLAINED BY RACCOONS",
      "dialogue": "Why your trash costs more",
      "script_for_audio": "Inflation. Explained by Raccoons. Why your trash costs more.",
      "characters": ["every-coon (neutral)"],
      "visual_description": "Every-Coon standing confidently in dark city alley at night, dramatic lighting from above",
      "transition_to_next": None
    },
    {
      "panel_number": 2,
      "panel_type": "ACT 1 - THE BASICS",
      "scene": "Supply & Demand - Rare",
      "mood": "positive",
      "header_text": "ACT 1 - THE BASICS",
      "dialogue": "Raccoon find one pizza slice. Pizza rare. Value HIGH.",
      "script_for_audio": "Raccoon find one pizza slice. Pizza rare. Value HIGH.",
      "characters": ["every-coon (pog)"],
      "visual_description": "Every-Coon looking up in awe at single floating pizza slice with golden glow",
      "panel_label": "1",
      "transition_to_next": None
    },
    {
      "panel_number": 3,
      "panel_type": "ACT 1 - THE BASICS",
      "scene": "Supply & Demand - Common",
      "mood": "negative",
      "header_text": "ACT 1 - THE BASICS",
      "dialogue": "But if many pizza appear... Pizza common. Value DROP.",
      "script_for_audio": "But if many pizza appear. Pizza common. Value DROP.",
      "characters": ["every-coon (wojak)"],
      "visual_description": "Every-Coon looking disappointed at huge pile of pizza slices everywhere",
      "panel_label": "2",
      "transition_to_next": "So what makes prices go up? Three things..."
    },
    {
      "panel_number": 4,
      "panel_type": "ACT 1 - TRANSITION",
      "scene": "Three Ways Intro",
      "mood": "neutral",
      "header_text": "THREE WAYS PRICES GO UP",
      "dialogue": "So what makes prices go up? Three things...",
      "script_for_audio": "So what makes prices go up? Three things.",
      "characters": ["every-coon (neutral)"],
      "visual_description": "Every-Coon as teacher pointing at chalkboard with THREE WAYS PRICES GO UP and question marks",
      "transition_to_next": None
    },
    {
      "panel_number": 5,
      "panel_type": "ACT 2 - CAUSES",
      "scene": "Demand-Pull Inflation",
      "mood": "warning",
      "header_text": "REASON #1: DEMAND-PULL",
      "dialogue": "More raccoons want pizza. Supply stay same. Price go UP.",
      "script_for_audio": "Reason one. Demand pull. More raccoons want pizza. Supply stay same. Price go UP.",
      "characters": ["multiple every-coons", "chad"],
      "visual_description": "Multiple raccoons holding WE WANT PIZZA signs, single pizza on crate with spotlight, green arrow pointing up",
      "panel_label": "3",
      "transition_to_next": None
    },
    {
      "panel_number": 6,
      "panel_type": "ACT 2 - CAUSES",
      "scene": "Cost-Push Inflation",
      "mood": "danger",
      "header_text": "REASON #2: COST-PUSH",
      "dialogue": "Fire burn pizza. Supply go DOWN. Price go UP.",
      "script_for_audio": "Reason two. Cost push. Fire burn pizza. Supply go DOWN. Price go UP.",
      "characters": ["every-coon (wojak)"],
      "visual_description": "Dumpster fire with pizza burning, Every-Coon crying and reaching toward flames",
      "panel_label": "4",
      "transition_to_next": None
    },
    {
      "panel_number": 7,
      "panel_type": "ACT 2 - CAUSES",
      "scene": "Production Cost Inflation",
      "mood": "warning",
      "header_text": "REASON #3: PRODUCTION COST",
      "dialogue": "Cost to make pizza go up. Maker raise price. \"Bizniz hard.\"",
      "script_for_audio": "Reason three. Production cost. Cost to make pizza go up. Maker raise price. Bizniz hard.",
      "characters": ["every-coon (stressed)", "customer raccoons"],
      "visual_description": "Raccoon behind counter sweating, ingredient bags with dollar signs and red arrows, angry customers",
      "panel_label": "5",
      "transition_to_next": "But then... the Fed got involved."
    },
    {
      "panel_number": 8,
      "panel_type": "ACT 2 - TRANSITION",
      "scene": "Fed Introduction",
      "mood": "dramatic",
      "header_text": "THEN THE FED SHOWED UP",
      "dialogue": "But then... the Fed got involved.",
      "script_for_audio": "But then. The Fed got involved.",
      "characters": ["the fed (ominous)"],
      "visual_description": "The Fed (raccoon in dark blue suit) emerging from shadows, hand reaching toward big red button, ominous lighting",
      "transition_to_next": None
    },
    {
      "panel_number": 9,
      "panel_type": "ACT 3 - FED CHAOS",
      "scene": "Money Printing",
      "mood": "chaotic_positive",
      "header_text": "MONEY FLOOD",
      "dialogue": "Fed print money. Raccoons have more money. Pizza stay same. Price go UP.",
      "script_for_audio": "Money flood. Fed print money. Raccoons have more money. Pizza stay same. Price go UP.",
      "characters": ["the fed", "every-coons (greed)"],
      "visual_description": "The Fed pressing PRINT MONEY button, gold coins raining from sky, happy raccoons with dollar eyes catching coins, green tint",
      "panel_label": "6",
      "transition_to_next": None
    },
    {
      "panel_number": 10,
      "panel_type": "ACT 3 - FED CHAOS",
      "scene": "Hyperinflation",
      "mood": "chaos",
      "header_text": "HYPERINFLATION",
      "dialogue": "Fed print MORE. And MORE. Prices go CRAZY. System BREAK.",
      "script_for_audio": "Hyperinflation. Fed print MORE. And MORE. Prices go CRAZY. System BREAK.",
      "characters": ["every-coon (panic)"],
      "visual_description": "Chaotic red scene with price numbers flying (10, 100, 1000), Every-Coon screaming, everything spinning and distorted",
      "panel_label": "7",
      "transition_to_next": None
    },
    {
      "panel_number": 11,
      "panel_type": "ACT 3 - FED CHAOS",
      "scene": "Currency Reset",
      "mood": "dramatic",
      "header_text": "CURRENCY RESET",
      "dialogue": "Money broken. Fed burn old money. Start over.",
      "script_for_audio": "Currency reset. Money broken. Fed burn old money. Start over.",
      "characters": ["the fed", "every-coons (pog)"],
      "visual_description": "The Fed holding lit match over huge burning pile of money, shocked raccoons gasping in background, fire lighting",
      "panel_label": "8",
      "transition_to_next": "So who wins? Who loses?"
    },
    {
      "panel_number": 12,
      "panel_type": "ACT 3 - TRANSITION",
      "scene": "Question Setup",
      "mood": "contemplative",
      "header_text": "SO WHO WINS? WHO LOSES?",
      "dialogue": "So who wins? Who loses?",
      "script_for_audio": "So who wins? Who loses?",
      "characters": ["every-coon (thinking)"],
      "visual_description": "Every-Coon sitting and thinking with thought bubble containing question mark, calmer blue tint",
      "transition_to_next": None
    },
    {
      "panel_number": 13,
      "panel_type": "ACT 4 - LESSON",
      "scene": "The Problem Explained",
      "mood": "mixed",
      "header_text": "THE PROBLEM",
      "dialogue": "If wages go up too? Fine. If wages stay same? Raccoon get POORER.",
      "script_for_audio": "The problem. If wages go up too? Fine. If wages stay same? Raccoon get POORER.",
      "characters": ["rich raccoon (greed)", "poor raccoon (wojak)"],
      "visual_description": "Split panel - left side happy raccoon hugging overflowing trash bag (green tint), right side sad raccoon with tiny fish bone (red tint)",
      "panel_label": "9",
      "transition_to_next": None
    },
    {
      "panel_number": 14,
      "panel_type": "ACT 4 - LESSON",
      "scene": "The Solution",
      "mood": "hopeful",
      "header_text": "THE FIX",
      "dialogue": "Smart raccoon buy ASSETS. Assets grow when money shrinks. Plant early. Win later.",
      "script_for_audio": "The fix. Smart raccoon buy ASSETS. Assets grow when money shrinks. Plant early. Win later.",
      "characters": ["every-coon (happy)"],
      "visual_description": "Happy raccoon planting seeds, sprouts growing that look like pizza slices and gold coins, warm sunshine, hopeful green/yellow tint",
      "panel_label": "10",
      "transition_to_next": None
    },
    {
      "panel_number": 15,
      "panel_type": "OUTRO",
      "scene": "Closing Punchline",
      "mood": "celebration",
      "header_text": "THE POINT",
      "dialogue": "Inflation make trash cost more. But smart raccoon? Smart raccoon OWN the trash.",
      "closing_text": "Subscribe for more trash wisdom.",
      "script_for_audio": "The point. Inflation make trash cost more. But smart raccoon? Smart raccoon OWN the trash. Subscribe for more trash wisdom.",
      "characters": ["every-coon (confident)"],
      "visual_description": "Confident Every-Coon popping out of dumpster with arms raised triumphantly, gold confetti falling, celebratory atmosphere",
      "transition_to_next": None
    }
  ],

  "audio_production": {
    "voice_id": "trash_panda_narrator",
    "voice_settings": {
      "stability": 0.5,
      "similarity_boost": 0.75,
      "style": 0.4
    }
  },

  "video_production": {
    "comic_grid_url": None,
    "canvas_size": [1080, 1920],
    "fps": 30,
    "background_music": None,
    "default_effects": {
      "idle_zoom": 0.1,
      "transition_duration_ms": 400
    }
  }
}


def test_layout_parsing():
    """Test that we can parse the 4-4-4-3 grid format."""
    print("\n=== Testing Layout Parsing ===")

    from viraltracker.services.comic_video import ComicDirectorService

    service = ComicDirectorService()
    layout = service.parse_layout_from_json(REAL_COMIC_JSON)

    print(f"✓ Grid: {layout.grid_cols}x{layout.grid_rows}")
    print(f"✓ Total panels: {layout.total_panels}")
    print(f"✓ Canvas: {layout.canvas_width}x{layout.canvas_height}")

    # Check panel cells
    print("\nPanel positions:")
    for panel_num in range(1, 16):
        cells = layout.panel_cells.get(panel_num, [])
        if cells:
            row, col = cells[0]
            print(f"  Panel {panel_num:2d}: row {row}, col {col}")

    # Verify grid structure parsed correctly
    assert layout.grid_cols == 4, f"Expected 4 cols, got {layout.grid_cols}"
    assert layout.grid_rows == 4, f"Expected 4 rows, got {layout.grid_rows}"
    assert layout.total_panels == 15, f"Expected 15 panels, got {layout.total_panels}"

    print("\n✓ Layout parsing PASSED")
    return True


def test_audio_text_extraction():
    """Test that script_for_audio is used for TTS text."""
    print("\n=== Testing Audio Text Extraction ===")

    from viraltracker.services.comic_video import ComicAudioService

    service = ComicAudioService()

    # Test each panel
    print("\nExtracted audio scripts:")
    for panel in REAL_COMIC_JSON["panels"]:
        text = service.extract_panel_text(panel)
        expected = panel.get("script_for_audio", "")

        # Should match script_for_audio
        if text == expected:
            print(f"  ✓ Panel {panel['panel_number']}: \"{text[:50]}...\"" if len(text) > 50 else f"  ✓ Panel {panel['panel_number']}: \"{text}\"")
        else:
            print(f"  ✗ Panel {panel['panel_number']}: MISMATCH")
            print(f"    Expected: {expected[:50]}...")
            print(f"    Got: {text[:50]}...")
            return False

    print("\n✓ Audio text extraction PASSED")
    return True


def test_mood_detection():
    """Test that explicit mood field is used."""
    print("\n=== Testing Mood Detection ===")

    from viraltracker.services.comic_video import ComicDirectorService, PanelMood

    service = ComicDirectorService()

    # Expected moods based on the JSON
    expected_moods = {
        1: PanelMood.DRAMATIC,      # mood: "dramatic"
        2: PanelMood.POSITIVE,      # mood: "positive"
        3: PanelMood.DANGER,        # mood: "negative" -> DANGER
        4: PanelMood.NEUTRAL,       # mood: "neutral"
        5: PanelMood.WARNING,       # mood: "warning"
        6: PanelMood.DANGER,        # mood: "danger"
        7: PanelMood.WARNING,       # mood: "warning"
        8: PanelMood.DRAMATIC,      # mood: "dramatic"
        9: PanelMood.CHAOS,         # mood: "chaotic_positive" -> CHAOS
        10: PanelMood.CHAOS,        # mood: "chaos"
        11: PanelMood.DRAMATIC,     # mood: "dramatic"
        12: PanelMood.NEUTRAL,      # mood: "contemplative" -> NEUTRAL
        13: PanelMood.WARNING,      # mood: "mixed" -> WARNING
        14: PanelMood.POSITIVE,     # mood: "hopeful" -> POSITIVE
        15: PanelMood.CELEBRATION,  # mood: "celebration"
    }

    print("\nDetected moods:")
    all_correct = True
    for panel in REAL_COMIC_JSON["panels"]:
        panel_num = panel["panel_number"]
        mood = service.infer_panel_mood(panel, REAL_COMIC_JSON)
        expected = expected_moods.get(panel_num, PanelMood.NEUTRAL)

        status = "✓" if mood == expected else "✗"
        print(f"  {status} Panel {panel_num:2d}: {panel.get('mood', 'N/A'):15s} -> {mood.value:12s} (expected: {expected.value})")

        if mood != expected:
            all_correct = False

    if all_correct:
        print("\n✓ Mood detection PASSED")
    else:
        print("\n✗ Mood detection FAILED (some mismatches)")

    return all_correct


def test_panel_bounds():
    """Test panel bounds calculation."""
    print("\n=== Testing Panel Bounds ===")

    from viraltracker.services.comic_video import ComicDirectorService

    service = ComicDirectorService()
    layout = service.parse_layout_from_json(REAL_COMIC_JSON)

    print("\nPanel bounds (normalized):")
    for panel_num in [1, 5, 10, 15]:  # Sample panels
        bounds = service.calculate_panel_bounds(panel_num, layout)
        print(f"  Panel {panel_num:2d}: center=({bounds.center_x:.2f}, {bounds.center_y:.2f}), size=({bounds.width:.2f}, {bounds.height:.2f})")

    # Verify panel 1 is in top-left
    bounds1 = service.calculate_panel_bounds(1, layout)
    assert bounds1.center_x < 0.5, "Panel 1 should be in left half"
    assert bounds1.center_y < 0.5, "Panel 1 should be in top half"

    # Verify panel 15 is in bottom area
    bounds15 = service.calculate_panel_bounds(15, layout)
    assert bounds15.center_y > 0.5, "Panel 15 should be in bottom half"

    print("\n✓ Panel bounds PASSED")
    return True


def test_instruction_generation():
    """Test full instruction generation."""
    print("\n=== Testing Instruction Generation ===")

    from viraltracker.services.comic_video import ComicDirectorService

    service = ComicDirectorService()
    layout = service.parse_layout_from_json(REAL_COMIC_JSON)

    # Generate instructions for all panels
    instructions = service.generate_all_instructions(
        comic_json=REAL_COMIC_JSON,
        layout=layout,
        audio_durations=None  # Will estimate from text
    )

    print(f"\nGenerated {len(instructions)} instructions:")
    for instr in instructions[:5]:  # Show first 5
        print(f"  Panel {instr.panel_number}: mood={instr.mood.value}, duration={instr.duration_ms}ms")
        print(f"    Camera: zoom {instr.camera.start_zoom:.2f} -> {instr.camera.end_zoom:.2f}")
        print(f"    Effects: {len(instr.effects.ambient_effects)} ambient, tint={instr.effects.color_tint or 'none'}")
        print(f"    Transition: {instr.transition.transition_type.value}")

    if len(instructions) > 5:
        print(f"  ... and {len(instructions) - 5} more")

    assert len(instructions) == 15, f"Expected 15 instructions, got {len(instructions)}"

    print("\n✓ Instruction generation PASSED")
    return True


def main():
    """Run all tests."""
    print("=" * 60)
    print("Comic Video System - Real JSON Test Suite")
    print("=" * 60)

    results = []

    results.append(("Layout Parsing", test_layout_parsing()))
    results.append(("Audio Text Extraction", test_audio_text_extraction()))
    results.append(("Mood Detection", test_mood_detection()))
    results.append(("Panel Bounds", test_panel_bounds()))
    results.append(("Instruction Generation", test_instruction_generation()))

    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)

    passed = sum(1 for _, r in results if r)
    total = len(results)

    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {status}: {name}")

    print(f"\nTotal: {passed}/{total} tests passed")

    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
