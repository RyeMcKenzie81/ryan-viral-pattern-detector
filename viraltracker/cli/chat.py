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
        console.print("[yellow]Make sure OPENAI_API_KEY, SUPABASE_URL, SUPABASE_KEY, and GEMINI_API_KEY are set.[/yellow]")
        return

    # Welcome message
    console.print(Panel(
        f"[bold cyan]Viral Content Agent[/bold cyan]\n"
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
                response = result.output

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
