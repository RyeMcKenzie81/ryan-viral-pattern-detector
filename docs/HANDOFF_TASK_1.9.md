# Task 1.9: Streamlit UI - Implementation Handoff

**Status:** READY TO START
**Date:** 2025-11-17
**Branch:** feature/pydantic-ai-agent
**Previous Task:** 1.8 (CLI Integration) - COMPLETE ✅
**Next Task:** 1.10 (FastAPI Endpoints)

---

## Overview

Task 1.9 creates a **Streamlit web interface** that provides a chat-based UI for the Pydantic AI agent. This gives non-technical users access to the same viral content analysis capabilities available through the CLI.

**What This Provides:**
- Web-based chat interface (similar to ChatGPT)
- Full access to all 3 agent tools (find_outliers, analyze_hooks, export_results)
- Project configuration via sidebar
- Quick action buttons for common queries
- Conversation history with markdown rendering
- Session state management

---

## Context: What's Already Complete

### ✅ Phase 1 Progress (Tasks 1.1-1.8)

**Services Layer (Tasks 1.1-1.4):**
- `viraltracker/services/models.py` - Pydantic models (Tweet, HookAnalysis, OutlierTweet)
- `viraltracker/services/twitter_service.py` - Database access
- `viraltracker/services/gemini_service.py` - AI hook analysis with rate limiting
- `viraltracker/services/stats_service.py` - Statistical calculations

**Agent Layer (Tasks 1.5-1.7):**
- `viraltracker/agent/dependencies.py` - AgentDependencies for typed DI
- `viraltracker/agent/tools.py` - 3 agent tools (find_outliers, analyze_hooks, export_results)
- `viraltracker/agent/agent.py` - Pydantic AI agent with dynamic system prompts

**CLI Integration (Task 1.8):**
- `viraltracker/cli/chat.py` - Interactive REPL chat command
- `viraltracker chat` command working and tested

### 📦 Available Dependencies

The agent is already fully functional and can be imported:

```python
from viraltracker.agent import agent, AgentDependencies

# Create dependencies
deps = AgentDependencies.create(
    db_path="viraltracker.db",
    project_name="yakety-pack-instagram"
)

# Run agent
result = await agent.run("Find viral tweets from today", deps=deps)
print(result.data)  # Markdown-formatted response
```

---

## Task 1.9: Implementation Specification

### Goal

Create a Streamlit app (`viraltracker/ui/app.py`) that provides:
1. **Chat interface** - Similar to ChatGPT, users type messages and get responses
2. **Sidebar settings** - Project selector, quick actions, clear chat
3. **Conversation history** - All messages displayed in chat format
4. **Markdown rendering** - Agent responses formatted nicely
5. **Session state** - Preserves conversation and settings

### File to Create

**Primary:**
- `viraltracker/ui/app.py` (~200-250 lines)

**Supporting:**
- `viraltracker/ui/__init__.py` (empty, for Python package)
- Update `requirements.txt` to add `streamlit==1.40.0`

---

## Implementation Guide

### Step 1: Streamlit App Structure

**File:** `viraltracker/ui/app.py`

```python
"""
Streamlit UI for Viraltracker Agent - Web-based chat interface.

Provides a ChatGPT-style interface for analyzing viral content using
the Pydantic AI agent. Includes project configuration, quick actions,
and conversation history.
"""

import streamlit as st
import asyncio
import os
from viraltracker.agent import agent, AgentDependencies

# Page configuration
st.set_page_config(
    page_title="Viraltracker Agent",
    page_icon="🎯",
    layout="wide"
)

# Main title
st.title("🎯 Viraltracker - Viral Content Analyzer")
st.caption("Powered by Pydantic AI")

# Initialize session state
# ... (dependencies, messages, etc.)

# Sidebar
# ... (project selector, quick actions, clear chat button)

# Display chat history
# ... (loop through messages and display)

# Chat input
# ... (handle user input, call agent, display response)

# Footer
# ... (show current project, database path)
```

### Step 2: Session State Management

Streamlit uses `st.session_state` to persist data across reruns. Initialize:

```python
# Initialize AgentDependencies in session state (only once)
if 'deps' not in st.session_state:
    st.session_state.deps = AgentDependencies.create(
        db_path=os.getenv('DB_PATH', 'viraltracker.db'),
        project_name=os.getenv('PROJECT_NAME', 'yakety-pack-instagram')
    )

# Initialize message history (list of dicts)
if 'messages' not in st.session_state:
    st.session_state.messages = []
```

**Message Format:**
```python
{
    'role': 'user',  # or 'assistant'
    'content': 'Find viral tweets from today'
}
```

### Step 3: Sidebar Implementation

```python
with st.sidebar:
    st.header("⚙️ Settings")

    # Project selector
    project = st.text_input(
        "Project Name",
        value=st.session_state.deps.project_name,
        help="Which project to analyze (e.g., yakety-pack-instagram)"
    )

    # Update project if changed
    if project != st.session_state.deps.project_name:
        st.session_state.deps.project_name = project
        st.rerun()

    st.divider()

    # Quick Actions
    st.subheader("🚀 Quick Actions")

    if st.button("🔍 Find Viral Tweets (24h)", use_container_width=True):
        st.session_state.messages.append({
            'role': 'user',
            'content': 'Find viral tweets from the last 24 hours'
        })
        st.rerun()

    if st.button("🎣 Analyze Hooks", use_container_width=True):
        st.session_state.messages.append({
            'role': 'user',
            'content': 'Analyze the hooks from recent viral tweets'
        })
        st.rerun()

    if st.button("📊 Full Report (48h)", use_container_width=True):
        st.session_state.messages.append({
            'role': 'user',
            'content': 'Generate a full report for the last 48 hours including outliers and hooks'
        })
        st.rerun()

    st.divider()

    # Clear chat button
    if st.button("🗑️ Clear Chat", use_container_width=True):
        st.session_state.messages = []
        st.rerun()
```

### Step 4: Display Chat History

```python
# Display all messages in conversation
for msg in st.session_state.messages:
    with st.chat_message(msg['role']):
        st.markdown(msg['content'])
```

**Note:** `st.chat_message()` automatically formats messages with user/assistant icons.

### Step 5: Handle Chat Input

```python
# Chat input box at bottom of page
if prompt := st.chat_input("Ask about viral content..."):
    # Add user message to history
    st.session_state.messages.append({
        'role': 'user',
        'content': prompt
    })

    # Display user message
    with st.chat_message('user'):
        st.markdown(prompt)

    # Get agent response
    with st.chat_message('assistant'):
        with st.spinner('🤖 Analyzing...'):
            try:
                # Run agent (async)
                result = asyncio.run(
                    agent.run(prompt, deps=st.session_state.deps)
                )

                response = result.data

                # Display response
                st.markdown(response)

                # Add to history
                st.session_state.messages.append({
                    'role': 'assistant',
                    'content': response
                })

            except Exception as e:
                error_msg = f"❌ **Error:** {str(e)}\n\nPlease check that:\n- Environment variables are set (OPENAI_API_KEY, SUPABASE_URL, etc.)\n- Database exists at: {st.session_state.deps.twitter.db_path}\n- Project '{st.session_state.deps.project_name}' has data"

                st.error(error_msg)

                st.session_state.messages.append({
                    'role': 'assistant',
                    'content': error_msg
                })
```

### Step 6: Footer Information

```python
# Show current configuration at bottom
st.divider()
col1, col2, col3 = st.columns(3)

with col1:
    st.caption(f"📁 **Project:** {st.session_state.deps.project_name}")

with col2:
    st.caption(f"💾 **Database:** {st.session_state.deps.twitter.db_path}")

with col3:
    st.caption(f"💬 **Messages:** {len(st.session_state.messages)}")
```

---

## Environment Variables Required

The Streamlit app needs the same environment variables as the agent:

```bash
# Required for agent
OPENAI_API_KEY=sk-...          # Or ANTHROPIC_API_KEY if using Claude
SUPABASE_URL=https://...
SUPABASE_KEY=...
GEMINI_API_KEY=...

# Optional configuration
DB_PATH=/path/to/viraltracker.db
PROJECT_NAME=yakety-pack-instagram
```

---

## Running the Streamlit App

### Local Development

```bash
# Activate virtual environment
source venv/bin/activate

# Run Streamlit app
streamlit run viraltracker/ui/app.py

# App opens at: http://localhost:8501
```

### Command Line Options

```bash
# Specify port
streamlit run viraltracker/ui/app.py --server.port 8080

# Disable watching for file changes (production)
streamlit run viraltracker/ui/app.py --server.fileWatcherType none

# Run in headless mode (server only, no browser)
streamlit run viraltracker/ui/app.py --server.headless true
```

---

## Testing Requirements

### Manual Testing Checklist

Create a testing checklist to verify the UI works correctly:

**1. App Loads:**
- [ ] Streamlit app starts without errors
- [ ] Page title shows "Viraltracker Agent"
- [ ] Chat interface is visible
- [ ] Sidebar displays correctly

**2. Session State:**
- [ ] AgentDependencies initializes on first load
- [ ] Project name shows in sidebar
- [ ] Messages list starts empty

**3. Chat Functionality:**
- [ ] Can type message in chat input
- [ ] User message appears in chat
- [ ] Agent response appears after processing
- [ ] Spinner shows while agent is thinking
- [ ] Markdown formatting renders correctly

**4. Quick Actions:**
- [ ] "Find Viral Tweets" button adds message and triggers agent
- [ ] "Analyze Hooks" button works
- [ ] "Full Report" button works
- [ ] Messages appear in chat after clicking buttons

**5. Settings:**
- [ ] Can change project name
- [ ] Project name updates in dependencies
- [ ] Page reruns when project changes

**6. Error Handling:**
- [ ] Missing API keys show helpful error message
- [ ] Database connection errors are caught
- [ ] Agent errors display in chat

**7. Clear Chat:**
- [ ] Clear button removes all messages
- [ ] Conversation history resets
- [ ] Dependencies persist (not reset)

### Automated Testing

**File:** `test_streamlit_ui.py` (~150 lines)

```python
"""
Test Streamlit UI - Basic import and configuration tests.

Note: Full UI testing requires Streamlit testing framework (not included in Phase 1).
These tests verify imports, dependencies, and basic functionality.
"""

import os

# Set test environment variables
os.environ['OPENAI_API_KEY'] = 'sk-test-key'
os.environ['SUPABASE_URL'] = 'https://test.supabase.co'
os.environ['SUPABASE_KEY'] = 'test-key'
os.environ['GEMINI_API_KEY'] = 'test-key'

def test_streamlit_import():
    """Test that streamlit can be imported."""
    import streamlit as st
    assert st is not None
    print("✓ Streamlit imports successfully")

def test_app_file_exists():
    """Test that app.py exists."""
    import os
    assert os.path.exists("viraltracker/ui/app.py")
    print("✓ viraltracker/ui/app.py exists")

def test_agent_import_in_app():
    """Test that app can import agent."""
    # Import app module
    import sys
    sys.path.insert(0, os.getcwd())

    # This will execute the app.py file
    # We can't fully test Streamlit apps without their testing framework
    # But we can verify imports work

    from viraltracker.agent import agent, AgentDependencies
    assert agent is not None
    assert AgentDependencies is not None
    print("✓ App can import agent components")

def test_dependencies_creation():
    """Test that AgentDependencies can be created."""
    from viraltracker.agent import AgentDependencies

    deps = AgentDependencies.create(
        db_path="viraltracker.db",
        project_name="test-project"
    )

    assert deps.project_name == "test-project"
    assert deps.twitter is not None
    assert deps.gemini is not None
    assert deps.stats is not None
    print("✓ AgentDependencies creation works")

def main():
    """Run all tests."""
    print("\n" + "="*80)
    print("STREAMLIT UI TEST SUITE")
    print("="*80)

    try:
        test_streamlit_import()
        test_app_file_exists()
        test_agent_import_in_app()
        test_dependencies_creation()

        print("\n" + "="*80)
        print("✓ All 4 tests PASSED")
        print("="*80)
        print("\nManual testing required:")
        print("1. Run: streamlit run viraltracker/ui/app.py")
        print("2. Test chat interface")
        print("3. Test quick actions")
        print("4. Test project settings")
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
```

---

## Success Criteria

Task 1.9 is complete when:

1. ✅ **App Runs:** `streamlit run viraltracker/ui/app.py` starts without errors
2. ✅ **Chat Works:** Can send messages and receive agent responses
3. ✅ **Tools Work:** Agent can call all 3 tools (find_outliers, analyze_hooks, export_results)
4. ✅ **Settings Work:** Can change project name and see it update
5. ✅ **Quick Actions Work:** Buttons trigger agent with pre-filled queries
6. ✅ **History Persists:** Messages stay visible throughout session
7. ✅ **Clear Works:** Clear button resets conversation
8. ✅ **Tests Pass:** All 4 automated tests pass
9. ✅ **Documentation Created:** `docs/STREAMLIT_UI_SUMMARY.md` written

---

## Documentation Requirements

After implementation, create `docs/STREAMLIT_UI_SUMMARY.md` with:

1. **Overview** - What the Streamlit UI provides
2. **File Structure** - All files created/modified
3. **Key Components** - Session state, sidebar, chat, etc.
4. **Usage Guide** - How to run and use the UI
5. **Configuration** - Environment variables, settings
6. **Testing Results** - Manual and automated test outcomes
7. **Screenshots** - (Optional but helpful) UI screenshots
8. **Known Limitations** - What's not included in Phase 1
9. **Future Enhancements** - What could be added in Phase 2
10. **Integration** - How it connects to the agent layer

---

## Architecture Diagram

```
User Browser
     │
     ↓
Streamlit App (http://localhost:8501)
     │
     ├──> Session State
     │       ├── deps (AgentDependencies)
     │       └── messages (conversation history)
     │
     ├──> Sidebar
     │       ├── Project Selector
     │       ├── Quick Actions
     │       └── Clear Chat
     │
     ├──> Chat Interface
     │       ├── Message History Display
     │       └── Chat Input Box
     │
     └──> Pydantic AI Agent
             │
             ├──> find_outliers_tool
             ├──> analyze_hooks_tool
             └──> export_results_tool
                     │
                     ↓
             AgentDependencies
                     │
                     ├──> TwitterService → Database
                     ├──> GeminiService → Gemini API
                     └──> StatsService → Calculations
```

---

## Common Issues & Solutions

### Issue 1: "ModuleNotFoundError: No module named 'streamlit'"

**Solution:** Install Streamlit
```bash
pip install streamlit==1.40.0
# Or update requirements.txt and reinstall
```

### Issue 2: "asyncio.run() cannot be called from a running event loop"

**Solution:** Streamlit runs in an event loop. Use `asyncio.run()` carefully or switch to sync wrappers if needed. The implementation above should work.

### Issue 3: Agent takes too long, UI freezes

**Solution:** This is expected in Phase 1. Phase 2 will add streaming responses to show progress in real-time. For now, the spinner shows the agent is working.

### Issue 4: Environment variables not found

**Solution:** Make sure to set environment variables before running Streamlit:
```bash
export OPENAI_API_KEY=sk-...
export SUPABASE_URL=https://...
# Then run
streamlit run viraltracker/ui/app.py
```

Or create a `.env` file and load with `python-dotenv` (already installed).

### Issue 5: Database not found

**Solution:** Ensure `viraltracker.db` exists in the project root, or set `DB_PATH` environment variable to the correct location.

---

## Phase 1 vs Phase 2 Features

### ✅ Phase 1 (Task 1.9) - Basic UI

- Single-page chat interface
- Project configuration
- Quick action buttons
- Conversation history
- Markdown rendering
- Error handling

### ⏭️ Phase 2 - Enhanced UI (Later)

- **Streaming responses** - Show agent thinking in real-time
- **Multi-page UI** - Tools catalog, database browser, history page
- **Download buttons** - Export results as JSON, CSV, Markdown
- **Charts/visualizations** - Show statistics visually
- **Advanced settings** - Model selection, threshold tuning, etc.
- **Saved sessions** - Load/save conversation history

**For Task 1.9, focus on Phase 1 features only.** Keep it simple and functional.

---

## Example User Flows

### Flow 1: Find Viral Tweets

1. User opens Streamlit app
2. Clicks "🔍 Find Viral Tweets (24h)" button in sidebar
3. Message appears in chat: "Find viral tweets from the last 24 hours"
4. Agent processes query (spinner shows progress)
5. Agent response appears with list of viral tweets
6. User can click "🎣 Analyze Hooks" to continue

### Flow 2: Custom Query

1. User types in chat input: "Show me viral tweets about parenting from this week"
2. Agent processes query
3. Agent calls `find_outliers_tool` with appropriate parameters
4. Response shows viral tweets matching query
5. User asks follow-up: "Why did these go viral?"
6. Agent calls `analyze_hooks_tool` on those tweets
7. Response shows hook types and emotional triggers

### Flow 3: Change Project

1. User clicks on project name in sidebar
2. Changes from "yakety-pack-instagram" to "competitor-project"
3. Page reruns with new project
4. All subsequent queries use new project
5. Conversation history is preserved

---

## Integration with Existing Code

### Agent (Task 1.7)
```python
from viraltracker.agent import agent, AgentDependencies

# Streamlit uses the same agent as the CLI
result = await agent.run(user_message, deps=deps)
```

### Dependencies (Task 1.5)
```python
# AgentDependencies manages all services
deps = AgentDependencies.create(
    project_name=st.session_state.project
)
```

### Tools (Task 1.6)
- `find_outliers_tool` - Called by agent when user asks for viral tweets
- `analyze_hooks_tool` - Called by agent when user asks why tweets went viral
- `export_results_tool` - Called by agent when user asks to download data

**No changes needed to existing code.** The Streamlit app is a new interface to the same agent.

---

## File Locations Summary

```
viraltracker/
├── ui/                      # NEW: Streamlit UI
│   ├── __init__.py          # NEW: Empty file for Python package
│   └── app.py               # NEW: Main Streamlit app (~200-250 lines)
│
├── agent/                   # EXISTING: Task 1.7
│   ├── __init__.py
│   ├── agent.py
│   ├── dependencies.py
│   └── tools.py
│
├── services/                # EXISTING: Tasks 1.1-1.4
│   ├── __init__.py
│   ├── models.py
│   ├── twitter_service.py
│   ├── gemini_service.py
│   └── stats_service.py
│
└── cli/                     # EXISTING: Task 1.8
    ├── __init__.py
    ├── main.py
    └── chat.py

docs/
├── STREAMLIT_UI_SUMMARY.md  # NEW: Documentation for Task 1.9
├── CLI_CHAT_SUMMARY.md      # EXISTING: Task 1.8
├── AGENT_CONFIG_SUMMARY.md  # EXISTING: Task 1.7
├── AGENT_TOOLS_SUMMARY.md   # EXISTING: Task 1.6
├── AGENT_DEPENDENCIES_SUMMARY.md  # EXISTING: Task 1.5
└── SERVICES_LAYER_SUMMARY.md      # EXISTING: Tasks 1.1-1.4

# Test files (project root)
test_streamlit_ui.py         # NEW: Task 1.9
test_cli_chat.py             # EXISTING: Task 1.8
test_agent_config.py         # EXISTING: Task 1.7
test_agent_tools.py          # EXISTING: Task 1.6
test_agent_dependencies.py   # EXISTING: Task 1.5
test_services_layer.py       # EXISTING: Tasks 1.1-1.4

requirements.txt             # UPDATE: Add streamlit==1.40.0
```

---

## Next Steps After Task 1.9

**Task 1.10:** FastAPI Endpoints (Phase 1 Final Task)

Once Task 1.9 is complete, the agent will be accessible via:
1. ✅ Direct Python import
2. ✅ CLI command (`viraltracker chat`)
3. ✅ Streamlit web UI (Task 1.9)
4. ⏭️ FastAPI REST API (Task 1.10)

**Phase 1 Completion:** After Task 1.10, all Phase 1 deliverables will be complete!

---

## Estimated Time

**Total Time for Task 1.9:** 3-4 hours

**Breakdown:**
- Streamlit app implementation: 2 hours
- Testing (manual + automated): 1 hour
- Documentation (`STREAMLIT_UI_SUMMARY.md`): 1 hour
- Bug fixes and polish: 30 minutes

---

## Key Takeaways

1. **Simple is better** - Phase 1 UI should be functional, not fancy
2. **Reuse the agent** - Don't rewrite agent logic, just call it
3. **Session state is critical** - Use `st.session_state` for deps and messages
4. **asyncio.run() works** - Even though Streamlit has event loop
5. **Test manually** - Streamlit UI testing is mostly manual in Phase 1
6. **Markdown rendering** - Agent responses already formatted in markdown
7. **Quick actions help** - Pre-filled queries make UI more accessible

---

## Questions Before Starting?

- Which port should Streamlit run on? (Default: 8501)
- Should we add authentication? (Phase 1: No, Phase 2: Yes)
- Should we add file upload? (Phase 1: No, Phase 2: Yes)
- Should we add charts? (Phase 1: No, Phase 2: Yes)

**For Phase 1, keep it simple!** Just get the chat working with the existing agent.

---

**Task 1.9: Streamlit UI - READY TO START**

*This handoff provides everything needed to implement the Streamlit web interface for the Pydantic AI agent.*
