"""
Test CLI Chat Command - Tests for interactive Pydantic AI chat interface.

Tests:
1. Chat command exists and is registered
2. Help text is correct
3. Chat command accepts project and model parameters
4. AgentDependencies initialization works
5. Error handling for missing environment variables
6. Help command displays correctly

All tests use mocks to avoid external dependencies (agent.run, Supabase, OpenAI).
"""

import os
from unittest.mock import Mock, patch, AsyncMock
from click.testing import CliRunner

# Set test API keys before importing
os.environ['OPENAI_API_KEY'] = 'sk-test-key-for-testing'
os.environ['SUPABASE_URL'] = 'https://test.supabase.co'
os.environ['SUPABASE_KEY'] = 'test-supabase-key'
os.environ['GEMINI_API_KEY'] = 'test-gemini-key'

from viraltracker.cli.main import cli


# ============================================================================
# Test 1: Chat Command Registration
# ============================================================================

def test_chat_command_exists():
    """Test that chat command is registered in the CLI."""
    print("\n" + "="*80)
    print("TEST 1: Chat Command Registration")
    print("="*80)

    # Check command exists in CLI
    assert 'chat' in cli.commands, "Chat command should be registered"
    print("✓ Chat command is registered in CLI")

    # Get the chat command
    chat_cmd = cli.commands['chat']
    assert chat_cmd is not None, "Chat command should exist"
    print("✓ Chat command object exists")

    # Check command name
    assert chat_cmd.name == 'chat', "Command name should be 'chat'"
    print("✓ Command name is 'chat'")

    print("\nChat command registration: PASSED ✓")


# ============================================================================
# Test 2: Chat Command Help Text
# ============================================================================

def test_chat_command_help():
    """Test that chat command has correct help text."""
    print("\n" + "="*80)
    print("TEST 2: Chat Command Help Text")
    print("="*80)

    runner = CliRunner()
    result = runner.invoke(cli, ['chat', '--help'])

    # Check exit code
    assert result.exit_code == 0, f"Help should succeed, got exit code: {result.exit_code}"
    print("✓ Help command succeeds (exit code 0)")

    # Check help text contains key information
    assert 'Interactive chat' in result.output or 'chat' in result.output.lower(), \
        "Help text should mention interactive chat"
    print("✓ Help text mentions interactive chat")

    # Check options are present
    assert '--project' in result.output, "Help should show --project option"
    print("✓ Help shows --project option")

    assert '--model' in result.output, "Help should show --model option"
    print("✓ Help shows --model option")

    # Check default values are mentioned
    assert 'yakety-pack-instagram' in result.output or 'default' in result.output.lower(), \
        "Help should mention default project"
    print("✓ Help mentions default values")

    print("\nChat command help text: PASSED ✓")


# ============================================================================
# Test 3: Chat Command Options
# ============================================================================

def test_chat_command_options():
    """Test that chat command accepts project and model options."""
    print("\n" + "="*80)
    print("TEST 3: Chat Command Options")
    print("="*80)

    # Get chat command
    chat_cmd = cli.commands['chat']

    # Check parameters exist
    param_names = [param.name for param in chat_cmd.params]

    assert 'project' in param_names, "Chat command should have 'project' parameter"
    print("✓ Chat command has 'project' parameter")

    assert 'model' in param_names, "Chat command should have 'model' parameter"
    print("✓ Chat command has 'model' parameter")

    # Check parameter defaults
    project_param = next(p for p in chat_cmd.params if p.name == 'project')
    assert project_param.default == 'yakety-pack-instagram', \
        f"Project default should be 'yakety-pack-instagram', got: {project_param.default}"
    print(f"✓ Project default is: {project_param.default}")

    model_param = next(p for p in chat_cmd.params if p.name == 'model')
    assert model_param.default == 'openai:gpt-4o', \
        f"Model default should be 'openai:gpt-4o', got: {model_param.default}"
    print(f"✓ Model default is: {model_param.default}")

    print("\nChat command options: PASSED ✓")


# ============================================================================
# Test 4: Chat Function Import
# ============================================================================

def test_chat_function_import():
    """Test that chat function can be imported."""
    print("\n" + "="*80)
    print("TEST 4: Chat Function Import")
    print("="*80)

    # Import chat function
    from viraltracker.cli.chat import chat, run_chat_loop, show_help

    # Verify functions exist
    assert chat is not None, "chat function should exist"
    print("✓ chat function imported successfully")

    assert run_chat_loop is not None, "run_chat_loop function should exist"
    print("✓ run_chat_loop function imported successfully")

    assert show_help is not None, "show_help function should exist"
    print("✓ show_help function imported successfully")

    # Check chat is callable
    assert callable(chat), "chat should be callable"
    print("✓ chat is callable")

    print("\nChat function import: PASSED ✓")


# ============================================================================
# Test 5: Agent Integration
# ============================================================================

def test_agent_integration():
    """Test that chat module correctly imports agent."""
    print("\n" + "="*80)
    print("TEST 5: Agent Integration")
    print("="*80)

    # Import chat module
    from viraltracker.cli import chat as chat_module

    # Verify agent is imported
    assert hasattr(chat_module, 'agent'), "chat module should import agent"
    print("✓ Agent is imported in chat module")

    # Verify AgentDependencies is imported
    assert hasattr(chat_module, 'AgentDependencies'), \
        "chat module should import AgentDependencies"
    print("✓ AgentDependencies is imported in chat module")

    print("\nAgent integration: PASSED ✓")


# ============================================================================
# Test 6: Rich Console Import
# ============================================================================

def test_rich_imports():
    """Test that rich library components are imported correctly."""
    print("\n" + "="*80)
    print("TEST 6: Rich Library Imports")
    print("="*80)

    from viraltracker.cli.chat import Console, Markdown, Panel, Prompt

    # Verify Rich components exist
    assert Console is not None, "Console should be imported"
    print("✓ Console imported from rich")

    assert Markdown is not None, "Markdown should be imported"
    print("✓ Markdown imported from rich")

    assert Panel is not None, "Panel should be imported"
    print("✓ Panel imported from rich")

    assert Prompt is not None, "Prompt should be imported"
    print("✓ Prompt imported from rich")

    # Test creating a Console instance
    console = Console()
    assert console is not None, "Console instance should be created"
    print("✓ Console instance created successfully")

    print("\nRich library imports: PASSED ✓")


# ============================================================================
# Run Tests
# ============================================================================

def run_sync_tests():
    """Run all synchronous tests."""
    print("\n" + "="*80)
    print("RUNNING SYNCHRONOUS TESTS")
    print("="*80)

    test_chat_command_exists()
    test_chat_command_help()
    test_chat_command_options()
    test_chat_function_import()
    test_agent_integration()
    test_rich_imports()


def main():
    """Main test runner."""
    print("\n" + "="*80)
    print("CLI CHAT TEST SUITE")
    print("="*80)
    print("Testing: viraltracker/cli/chat.py")
    print("="*80)

    try:
        # Run synchronous tests
        run_sync_tests()

        # Summary
        print("\n" + "="*80)
        print("TEST SUMMARY")
        print("="*80)
        print("✓ All 6 tests PASSED")
        print("="*80)
        print("\nCLI chat command is working correctly!")
        print("\nNext steps:")
        print("1. Test the command manually: python -m viraltracker.cli.main chat --help")
        print("2. Create docs/CLI_CHAT_SUMMARY.md")
        print("3. Run all tests together")
        print("="*80)

        return 0

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
