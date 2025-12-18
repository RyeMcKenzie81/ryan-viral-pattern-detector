# Checkpoint: Google SDK Migration + Logfire Enablement

**Date:** 2025-12-18
**Status:** Complete

## Overview

Successfully migrated from the deprecated `google-generativeai` SDK to the new `google-genai` SDK, which unblocked logfire observability by resolving a protobuf version conflict.

## Problem

The old Google SDK (`google-generativeai`) required `protobuf<5.0`, while OpenTelemetry (required by logfire) needed `protobuf>=5.0`. This created a dependency conflict that prevented logfire from being installed.

## Solution

### 1. SDK Migration

Migrated 6 files from the old SDK to the new unified `google-genai` SDK:

| File | Changes |
|------|---------|
| `viraltracker/core/config.py` | Updated `_generate_exemplars()` |
| `viraltracker/generation/hook_analyzer.py` | Updated imports and generate_content calls |
| `viraltracker/generation/content_generator.py` | Updated imports and initialization |
| `viraltracker/core/embeddings.py` | Updated to `gemini-embedding-001` with `output_dimensionality=768` |
| `viraltracker/generation/comment_generator.py` | Updated safety settings to new list format |
| `viraltracker/services/gemini_service.py` | Full migration including image generation |

### 2. Key API Changes

**Initialization:**
```python
# OLD
import google.generativeai as genai
genai.configure(api_key=api_key)
model = genai.GenerativeModel(model_name)

# NEW
from google import genai
from google.genai import types
client = genai.Client(api_key=api_key)
```

**Generate Content:**
```python
# OLD
response = model.generate_content(prompt)

# NEW
response = client.models.generate_content(
    model=model_name,
    contents=[prompt]
)
```

**Embeddings:**
```python
# OLD
result = genai.embed_content(model="text-embedding-004", content=batch, task_type="RETRIEVAL_DOCUMENT")

# NEW - IMPORTANT: Use output_dimensionality=768 for backward compatibility
result = client.models.embed_content(
    model="gemini-embedding-001",
    contents=batch,
    config=types.EmbedContentConfig(
        task_type="RETRIEVAL_DOCUMENT",
        output_dimensionality=768  # Match existing cached embeddings
    )
)
# Access: result.embeddings[0].values (not result['embedding'])
```

**Safety Settings:**
```python
# OLD
from google.generativeai.types import HarmCategory, HarmBlockThreshold
safety_settings = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
}

# NEW
safety_settings = [
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
        threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
    ),
]
```

### 3. Critical Bug Fix: FinishReason.STOP

The new SDK returns enum values for `finish_reason` instead of integers. `FinishReason.STOP` is the **normal successful completion**, not an error.

**Fixed in `gemini_service.py`:**
```python
# OLD (broken)
if candidate.finish_reason not in (None, 1):  # 1 was STOP in old SDK

# NEW (fixed)
if candidate.finish_reason not in (
    None,
    types.FinishReason.STOP,      # Normal completion
    types.FinishReason.MAX_TOKENS  # Hit token limit (usually OK)
):
```

### 4. Logfire Integration with Streamlit

**Key learnings:**
- `@st.cache_resource` decorator MUST come AFTER `st.set_page_config()`
- Railway only captures stderr from Streamlit, not stdout
- Use `logging.basicConfig(force=True)` to override Streamlit's logging config

**Working pattern in `app.py`:**
```python
st.set_page_config(...)  # MUST BE FIRST

@st.cache_resource
def init_observability():
    token = os.environ.get("LOGFIRE_TOKEN")
    if not token:
        return {"status": "skipped", "reason": "LOGFIRE_TOKEN not set"}

    try:
        import logfire

        logfire.configure(
            token=token,
            service_name="viraltracker",
            environment=os.environ.get("LOGFIRE_ENVIRONMENT", "production"),
            send_to_logfire=True,
            console=False,
        )

        logging.basicConfig(
            level=logging.INFO,
            handlers=[
                logfire.LogfireLoggingHandler(),
                logging.StreamHandler(sys.stderr),
            ],
            force=True,  # Override Streamlit's config
        )

        logfire.instrument_pydantic()
        return {"status": "success", "environment": env}
    except Exception as e:
        return {"status": "error", "reason": str(e)}

_logfire_status = init_observability()
```

### 5. Requirements Changes

**Removed:**
- `google-ai-generativelanguage==0.6.6`
- `google-generativeai==0.7.2`

**Updated:**
- `protobuf==5.29.5` (was 4.x)

**Added:**
- `logfire==4.14.2`
- `logfire-api==4.14.2`
- `opentelemetry-api==1.38.0`
- `opentelemetry-sdk==1.38.0`
- `opentelemetry-proto==1.38.0`
- `opentelemetry-exporter-otlp-proto-common==1.38.0`
- `opentelemetry-exporter-otlp-proto-http==1.38.0`
- `opentelemetry-instrumentation==0.59b0`
- `opentelemetry-instrumentation-httpx==0.59b0`
- `opentelemetry-semantic-conventions==0.59b0`
- `opentelemetry-util-http==0.59b0`

## Railway Environment Variables

Required for logfire:
- `LOGFIRE_TOKEN` - Write token from Logfire dashboard
- `LOGFIRE_ENVIRONMENT` - e.g., "production"

Note: `LOGFIRE_PROJECT_NAME` is deprecated - project is determined by the token.

## Files Modified

- `requirements.txt`
- `viraltracker/core/config.py`
- `viraltracker/core/embeddings.py`
- `viraltracker/core/observability.py`
- `viraltracker/generation/hook_analyzer.py`
- `viraltracker/generation/content_generator.py`
- `viraltracker/generation/comment_generator.py`
- `viraltracker/services/gemini_service.py`
- `viraltracker/ui/app.py`
- `Dockerfile` (added cache bust ARG)

## Verification

1. **Ad Creator works** - No more `FinishReason.STOP` errors
2. **Logfire dashboard** - Shows traces at https://logfire.pydantic.dev/
3. **Railway logs** - Now show all service initialization and HTTP requests

## Commits

- `00e2035` - feat: Migrate from deprecated google-generativeai to google-genai SDK
- `27c936c` - fix: Fix FinishReason.STOP false positive in Gemini SDK migration
- `7c065cd` - fix: Move logfire init after st.set_page_config
- `e5852c6` - chore: Clean up logfire init - remove debug prints and fix deprecation
