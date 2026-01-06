
import asyncio
import os
from pydantic_ai import Agent

# Mock key
os.environ["GEMINI_API_KEY"] = "mock"
os.environ["OPENAI_API_KEY"] = "mock"

async def test_agent():
    # Create simple agent
    agent = Agent('openai:gpt-4o-mini', system_prompt="Reply with 'Hello'")
    
    # We can't actually run it without a real API key usually, but pydantic_ai validates keys.
    # If we can't run it, we can't see the result object. 
    # But maybe we can import AgentRunResult?
    
    from pydantic_ai import AgentRunResult
    print(f"AgentRunResult attributes: {dir(AgentRunResult)}")

if __name__ == "__main__":
    try:
        asyncio.run(test_agent())
    except Exception as e:
        print(f"Error: {e}")
        # Try importing result directly
        try:
             from pydantic_ai.agent import AgentRunResult
             print(f"AgentRunResult attributes (from agent module): {dir(AgentRunResult)}")
        except:
             pass
