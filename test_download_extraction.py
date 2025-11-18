"""Test script to verify structured result extraction for download buttons."""
import asyncio
from viraltracker.agent import agent, AgentDependencies
from viraltracker.services.models import OutlierResult, HookAnalysisResult

async def test_extraction():
    """Test that we can extract structured results from agent response."""
    # Create dependencies
    deps = AgentDependencies.create(project_name='yakety-pack-instagram')

    # Run agent with a query that triggers find_outliers_tool
    result = await agent.run(
        "Show me the top 3 viral tweets from the last week",
        deps=deps
    )

    print("=" * 80)
    print("TESTING STRUCTURED RESULT EXTRACTION")
    print("=" * 80)

    # Try to extract structured result using the same logic as app.py
    structured_result = None

    if hasattr(result, 'all_messages'):
        for msg in result.all_messages():
            # Check message parts for ToolReturnPart
            if hasattr(msg, 'parts'):
                for part in msg.parts:
                    # ToolReturnPart has a 'content' attribute with the structured result
                    if part.__class__.__name__ == 'ToolReturnPart' and hasattr(part, 'content'):
                        if isinstance(part.content, (OutlierResult, HookAnalysisResult)):
                            structured_result = part.content
                            print(f"✅ FOUND STRUCTURED RESULT!")
                            print(f"   Type: {type(structured_result).__name__}")
                            if isinstance(structured_result, OutlierResult):
                                print(f"   Outlier count: {structured_result.outlier_count}")
                                print(f"   Total tweets: {structured_result.total_tweets}")
                            break
            if structured_result:
                break

    if not structured_result:
        print("❌ NO STRUCTURED RESULT FOUND")
        print("This means download buttons won't appear!")
        return False

    print("\n" + "=" * 80)
    print("CONVERSION TEST")
    print("=" * 80)

    # Test JSON conversion
    try:
        json_data = structured_result.model_dump_json(indent=2)
        print(f"✅ JSON conversion successful ({len(json_data)} bytes)")
    except Exception as e:
        print(f"❌ JSON conversion failed: {e}")
        return False

    # Test markdown conversion
    try:
        md_data = structured_result.to_markdown()
        print(f"✅ Markdown conversion successful ({len(md_data)} bytes)")
    except Exception as e:
        print(f"❌ Markdown conversion failed: {e}")
        return False

    print("\n" + "=" * 80)
    print("✅ ALL TESTS PASSED - Download buttons should work!")
    print("=" * 80)
    return True

if __name__ == '__main__':
    success = asyncio.run(test_extraction())
    exit(0 if success else 1)
