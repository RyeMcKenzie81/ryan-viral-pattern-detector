# Handoff: Task 1.8 - CLI Integration (Pydantic AI Chat Command)

**Date:** 2025-11-17
**Branch:** feature/pydantic-ai-agent
**Previous Task:** 1.7 (Agent Configuration) - COMPLETE ✅
**Next Task:** 1.8 (CLI Integration) - START HERE

---

## Current Status

✅ **Tasks 1.1-1.7 COMPLETE** (7/10 tasks)
- Services Layer (Tasks 1.1-1.4) ✅
- Agent Dependencies (Task 1.5) ✅
- Agent Tools (Task 1.6) ✅
- Agent Configuration (Task 1.7) ✅

⏭️ **Task 1.8 NEXT:** CLI Integration

---

## What's Been Completed

### Task 1.7: Agent Configuration ✅

**Files Created:**
1. `viraltracker/agent/agent.py` (~150 lines)
   - Pydantic AI agent with OpenAI GPT-4o
   - 3 tools registered (find_outliers, analyze_hooks, export_results)
   - Dynamic system prompt (adapts to project name)
   - Retry logic: 2 retries

2. `test_agent_config.py` (~450 lines)
   - 8 comprehensive tests
   - Tests agent initialization, tool registration, system prompt
   - All tests pass ✅

3. `viraltracker/agent/__init__.py` (updated)
   - Exports: `agent`, `AgentDependencies`

4. `docs/AGENT_CONFIG_SUMMARY.md` (~600 lines)
   - Complete architecture documentation
   - Usage examples for CLI, Streamlit, FastAPI
   - Test results

**Agent is Production-Ready:**
```python
from viraltracker.agent import agent, AgentDependencies

# Create dependencies
deps = AgentDependencies.create(project_name="yakety-pack-instagram")

# Run agent
result = await agent.run("Show me viral tweets from today", deps=deps)
print(result.data)
```

---

## Task 1.8: CLI Integration

### Goal
Create a new CLI command `viraltracker chat` that provides an interactive conversational interface using the Pydantic AI agent.

### Requirements

**1. New CLI Command**
```bash
viraltracker chat --project yakety-pack-instagram
```

**2. Features to Implement:**
- Interactive chat loop (REPL-style)
- Conversation history (maintain context across messages)
- Pretty output formatting (use `rich` library)
- Graceful error handling
- Exit commands: `quit`, `exit`, `q`
- Clear/reset command: `clear`, `reset`
- Help command: `help`, `?`

**3. User Experience:**
```
$ viraltracker chat --project yakety-pack-instagram

🤖 Viral Content Agent (yakety-pack-instagram)
Type your message or 'help' for commands. 'quit' to exit.

You: Show me viral tweets from today
Agent: I'll find viral tweets from the last 24 hours...

[Agent uses find_outliers_tool and returns results]

You: Why did they go viral?
Agent: Let me analyze the hooks...

[Agent uses analyze_hooks_tool and returns patterns]

You: quit
Goodbye!
```

---

## Implementation Specifications

### File to Create

**`viraltracker/cli/chat.py`** (~200-250 lines)

### Structure

```python
"""
CLI Chat Command - Interactive Pydantic AI chat interface.

Provides a conversational REPL for analyzing viral content using
the Pydantic AI agent with full tool access.
"""

import asyncio
import click
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

from ..agent import agent, AgentDependencies


@click.command()
@click.option(
    '--project',
    default='yakety-pack-instagram',
    help='Project name (default: yakety-pack-instagram)'
)
@click.option(
    '--model',
    default='openai:gpt-4o',
    help='Model to use (default: openai:gpt-4o)'
)
def chat(project: str, model: str):
    """
    Interactive chat with the viral content analysis agent.

    Start a conversational session to analyze viral tweets, understand
    hooks, and generate insights using natural language.

    Examples:
        viraltracker chat
        viraltracker chat --project my-project
        viraltracker chat --model anthropic:claude-3-5-sonnet-20241022
    """
    # Run async chat loop
    asyncio.run(run_chat_loop(project, model))


async def run_chat_loop(project: str, model: str):
    """
    Main chat loop - handles user input and agent responses.

    Args:
        project: Project name for analysis
        model: Model to use for agent
    """
    console = Console()

    # Initialize dependencies
    try:
        deps = AgentDependencies.create(project_name=project)
    except Exception as e:
        console.print(f"[red]Error initializing agent: {e}[/red]")
        return

    # Welcome message
    console.print(Panel(
        f"[bold cyan]🤖 Viral Content Agent[/bold cyan]\n"
        f"Project: {project}\n"
        f"Model: {model}\n\n"
        f"Type your message or 'help' for commands. 'quit' to exit.",
        title="Welcome",
        border_style="cyan"
    ))

    # Chat loop
    conversation_history = []  # For maintaining context

    while True:
        # Get user input
        try:
            user_input = Prompt.ask("\n[bold green]You[/bold green]")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Goodbye![/yellow]")
            break

        # Handle commands
        if user_input.lower() in ['quit', 'exit', 'q']:
            console.print("[yellow]Goodbye![/yellow]")
            break

        if user_input.lower() in ['help', '?']:
            show_help(console)
            continue

        if user_input.lower() in ['clear', 'reset']:
            conversation_history = []
            console.clear()
            console.print("[cyan]Conversation history cleared.[/cyan]")
            continue

        if not user_input.strip():
            continue

        # Show thinking indicator
        with console.status("[cyan]Agent is thinking...[/cyan]"):
            try:
                # Run agent
                result = await agent.run(user_input, deps=deps)
                response = result.data

                # Add to history
                conversation_history.append({
                    'user': user_input,
                    'agent': response
                })

                # Display response
                console.print(f"\n[bold cyan]Agent[/bold cyan]:")
                console.print(Panel(
                    Markdown(response),
                    border_style="cyan"
                ))

            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")
                console.print("[yellow]Try rephrasing your question or check your API keys.[/yellow]")


def show_help(console: Console):
    """Display help information."""
    help_text = """
**Available Commands:**

- `help` or `?` - Show this help message
- `clear` or `reset` - Clear conversation history
- `quit`, `exit`, or `q` - Exit the chat

**Example Questions:**

- "Show me viral tweets from today"
- "Find outliers from the last 48 hours"
- "Why did those tweets go viral?"
- "Analyze hooks for top performers"
- "Give me a full report for the last week"
- "Export results as markdown"

**Tips:**

- Be specific about time ranges (e.g., "last 24 hours", "past week")
- Ask follow-up questions to dig deeper
- The agent has access to your tweet database via tools
    """
    console.print(Panel(
        Markdown(help_text),
        title="Help",
        border_style="yellow"
    ))
```

---

## Integration Steps

### 1. Update `viraltracker/cli/main.py`

Add the chat command to the CLI:

```python
from .chat import chat

# In the CLI group, add:
cli.add_command(chat)
```

### 2. Install Dependencies (if needed)

Check `requirements.txt` includes:
```
rich>=13.0.0
```

If not, add it and run:
```bash
pip install rich
```

### 3. Test the Command

```bash
# Test help
viraltracker chat --help

# Test interactive mode
viraltracker chat --project yakety-pack-instagram

# Test with different model
viraltracker chat --model anthropic:claude-3-5-sonnet-20241022
```

---

## Testing Requirements

Create `test_cli_chat.py` (~150-200 lines):

**Tests to Include:**
1. Test chat command exists
2. Test help text display
3. Test conversation loop (mocked)
4. Test error handling (invalid project, API errors)
5. Test commands (help, clear, quit)
6. Test agent integration (mocked agent.run)

**Example Test:**
```python
def test_chat_command_exists():
    """Test that chat command is registered."""
    from viraltracker.cli.main import cli

    # Check command exists
    assert 'chat' in cli.commands

    # Check help text
    result = runner.invoke(cli, ['chat', '--help'])
    assert result.exit_code == 0
    assert 'Interactive chat' in result.output
```

---

## Documentation Requirements

Create `docs/CLI_CHAT_SUMMARY.md` (~400-500 lines):

**Sections:**
1. Overview
2. Installation & Setup
3. Usage Examples
4. Command Reference
5. Advanced Features (conversation history, model switching)
6. Troubleshooting
7. Screenshots/Examples

---

## Key Files Reference

**Existing Files (use these):**
- `viraltracker/agent/agent.py` - The Pydantic AI agent ✅
- `viraltracker/agent/dependencies.py` - AgentDependencies ✅
- `viraltracker/cli/main.py` - Main CLI entry point (update this)

**New Files (create these):**
- `viraltracker/cli/chat.py` - Chat command implementation
- `test_cli_chat.py` - Test suite
- `docs/CLI_CHAT_SUMMARY.md` - Documentation

**Existing CLI Structure:**
```
viraltracker/cli/
├── __init__.py
├── main.py          # Update: add chat command
├── twitter.py       # Existing Twitter commands
└── chat.py          # NEW: chat command
```

---

## Verification Commands

```bash
cd /Users/ryemckenzie/projects/viraltracker
git branch  # Should show: * feature/pydantic-ai-agent

# Verify agent is importable
python -c "from viraltracker.agent import agent, AgentDependencies; print('✓ Agent imports successfully')"

# Run previous tests
python test_agent_config.py  # Should pass ✅

# After completing Task 1.8
viraltracker chat --help
viraltracker chat --project yakety-pack-instagram
python test_cli_chat.py
```

---

## Success Criteria

Task 1.8 is complete when:

- ✅ `viraltracker chat` command exists and is functional
- ✅ Interactive chat loop works (REPL-style)
- ✅ Agent responds to queries using tools
- ✅ Commands work (help, clear, quit)
- ✅ Error handling is graceful
- ✅ Output is pretty-formatted (Rich library)
- ✅ Tests pass (test_cli_chat.py)
- ✅ Documentation complete (docs/CLI_CHAT_SUMMARY.md)

---

## Important Notes

1. **Environment Variables:**
   - Ensure `OPENAI_API_KEY` is set (or model-specific key)
   - Ensure `SUPABASE_URL` and `SUPABASE_KEY` are set
   - Ensure `GEMINI_API_KEY` is set

2. **Async/Await:**
   - The agent is async (`await agent.run()`)
   - Use `asyncio.run()` to run the async chat loop from the synchronous Click command

3. **Rich Library:**
   - Use `Console` for output
   - Use `Markdown()` for formatting agent responses
   - Use `Panel()` for structured output
   - Use `Prompt` for user input

4. **Error Handling:**
   - Catch API errors gracefully
   - Show helpful error messages
   - Don't crash on invalid input

5. **Conversation History:**
   - Store messages in a list
   - Can be used later for context (future enhancement)
   - Clear with `clear` command

---

## Migration Plan Reference

From `docs/PYDANTIC_AI_MIGRATION_PLAN.md`:

**Task 1.8 Location:** Lines 867-920

**Estimated Time:** 3-4 hours

**Dependencies:**
- Task 1.7 (Agent Configuration) ✅
- `rich` library for pretty output
- Click for CLI framework

---

## Next Steps After Task 1.8

**Task 1.9:** Streamlit UI (simple web interface)
**Task 1.10:** FastAPI endpoints (REST API)

Once CLI integration is complete, the agent will be accessible via:
1. ✅ Direct Python import
2. ✅ CLI command (`viraltracker chat`)
3. ⏭️ Streamlit UI (Task 1.9)
4. ⏭️ FastAPI (Task 1.10)

---

## Quick Start Commands

```bash
# 1. Ensure you're on the right branch
git branch  # Should show: * feature/pydantic-ai-agent

# 2. Verify agent is working
python -c "import os; os.environ['OPENAI_API_KEY']='test'; from viraltracker.agent import agent; print('Agent loaded')"

# 3. Check existing CLI structure
ls -la viraltracker/cli/

# 4. Start implementing
# - Create viraltracker/cli/chat.py
# - Update viraltracker/cli/main.py
# - Create test_cli_chat.py
# - Create docs/CLI_CHAT_SUMMARY.md

# 5. Test as you go
viraltracker chat --help
python test_cli_chat.py
```

---

## Handoff Checklist

Before starting Task 1.8, verify:

- ✅ Task 1.7 is complete
- ✅ Agent is importable: `from viraltracker.agent import agent`
- ✅ Tests pass: `python test_agent_config.py`
- ✅ Documentation exists: `docs/AGENT_CONFIG_SUMMARY.md`
- ✅ You're on branch: `feature/pydantic-ai-agent`
- ✅ Environment variables are set (OPENAI_API_KEY, SUPABASE_*, GEMINI_API_KEY)

**Ready to start Task 1.8!** 🚀

---

**Instructions:**
1. Copy this entire document
2. Start a new Claude Code session
3. Paste as your first message
4. Claude will pick up and implement Task 1.8

---

**Contact:**
- Branch: `feature/pydantic-ai-agent`
- Base: `main`
- Docs: `docs/PYDANTIC_AI_MIGRATION_PLAN.md`
- Previous Task Summary: `docs/AGENT_CONFIG_SUMMARY.md`
