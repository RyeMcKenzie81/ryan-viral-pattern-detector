"""Test script to inspect Pydantic AI result structure."""
import asyncio
import os
from viraltracker.agent import agent, AgentDependencies

async def test_result_structure():
    """Test what's in the agent result."""
    # Create dependencies
    deps = AgentDependencies.create(project_name='yakety-pack-instagram')

    # Run agent with a simple query
    result = await agent.run(
        "Show me the top 3 viral tweets from the last month",
        deps=deps
    )

    print("=" * 80)
    print("RESULT OBJECT ATTRIBUTES:")
    print("=" * 80)
    print(f"Type: {type(result)}")
    print(f"Dir: {[attr for attr in dir(result) if not attr.startswith('_')]}")
    print()

    print("=" * 80)
    print("RESULT.OUTPUT:")
    print("=" * 80)
    print(f"Type: {type(result.output)}")
    print(f"Content: {result.output[:500]}...")
    print()

    if hasattr(result, 'data'):
        print("=" * 80)
        print("RESULT.DATA:")
        print("=" * 80)
        print(f"Type: {type(result.data)}")
        print(f"Content: {result.data}")
        print()

    if hasattr(result, 'all_messages'):
        print("=" * 80)
        print("RESULT.ALL_MESSAGES():")
        print("=" * 80)
        messages = result.all_messages()
        for i, msg in enumerate(messages):
            print(f"\n--- Message {i} ---")
            print(f"Type: {type(msg)}")
            if hasattr(msg, 'kind'):
                print(f"Kind: {msg.kind}")

            # Check for tool calls in ModelResponse
            if hasattr(msg, 'tool_calls'):
                print(f"Tool calls: {msg.tool_calls}")

            # Check parts attribute (might contain tool returns)
            if hasattr(msg, 'parts'):
                print(f"Parts count: {len(msg.parts)}")
                for j, part in enumerate(msg.parts):
                    print(f"  Part {j} type: {type(part)}")
                    print(f"  Part {j} class: {part.__class__.__name__}")
                    if hasattr(part, 'content'):
                        print(f"  Part {j} content type: {type(part.content)}")
                        if hasattr(part.content, '__class__'):
                            print(f"  Part {j} content class: {part.content.__class__.__name__}")
                    if hasattr(part, '__dict__'):
                        print(f"  Part {j} attrs: {list(part.__dict__.keys())}")

            print(f"Attributes: {[attr for attr in dir(msg) if not attr.startswith('_')]}")

if __name__ == '__main__':
    asyncio.run(test_result_structure())
