# CHECKPOINT: Ad Scheduler Upload Template Mode

**Date**: December 2, 2025
**Status**: ✅ Feature Complete
**Feature**: Upload new reference ad templates directly in scheduler

---

## Executive Summary

Added a third template selection mode to the Ad Scheduler that allows users to upload new reference ad templates directly when creating a scheduled job, rather than only selecting from existing templates.

---

## Implementation Details

### File Modified

**File**: `viraltracker/ui/pages/04_📅_Ad_Scheduler.py`
**Changes**: +93 lines, -5 lines

### New Template Mode

The scheduler previously had two template modes:
1. **`unused`** - Auto-selects templates not yet used for the product
2. **`specific`** - User selects from existing templates in `reference-ads` storage

Now includes a third mode:
3. **`upload`** - Upload new reference ads directly for this scheduled run

### Code Changes

#### 1. Session State Initialization (line 49-50)
```python
if 'sched_uploaded_files' not in st.session_state:
    st.session_state.sched_uploaded_files = []
```

#### 2. Upload Helper Function (lines 194-217)
```python
def upload_template_files(files: list) -> list:
    """Upload template files to reference-ads storage and return storage names."""
    import uuid
    db = get_supabase_client()
    storage_names = []

    for file in files:
        storage_name = f"{uuid.uuid4()}_{file.name}"
        try:
            file_bytes = file.read()
            file.seek(0)
            db.storage.from_("reference-ads").upload(
                storage_name, file_bytes,
                {"content-type": file.type, "upsert": "true"}
            )
            storage_names.append(storage_name)
        except Exception as e:
            st.error(f"Failed to upload {file.name}: {e}")
    return storage_names
```

#### 3. Template Mode Radio Updated (lines 696-706)
Added `'upload'` as third option with format:
- 🔄 Use Unused Templates
- 📋 Specific Templates
- 📤 Upload New - Upload reference ads for this run

#### 4. Upload Mode UI (lines 780-811)
- Multi-file uploader accepting jpg, jpeg, png, webp
- Preview grid (up to 5 columns)
- File count display
- Session state storage for upload on save

#### 5. Save Handling (lines 921-932)
```python
if template_mode == 'upload':
    with st.spinner("Uploading templates..."):
        uploaded_storage_names = upload_template_files(st.session_state.sched_uploaded_files)
    if not uploaded_storage_names:
        st.error("Failed to upload templates")
        st.stop()
    template_ids = uploaded_storage_names
    template_count = len(uploaded_storage_names)
```

#### 6. Session State Cleanup
Clears `sched_uploaded_files` on save and cancel actions.

---

## Worker Compatibility

**No worker changes required.** The scheduler worker (`viraltracker/worker/scheduler_worker.py`) already handles `template_ids` for non-`unused` modes:

```python
else:
    templates = job.get('template_ids', [])
```

Since `upload` mode stores the storage names in `template_ids`, the worker processes them identically to `specific` mode.

---

## Database Compatibility

**No database changes required.** The `scheduled_jobs` table already has:
- `template_mode TEXT` - Accepts `'upload'` as a valid value
- `template_ids TEXT[]` - Stores the uploaded file storage names

---

## User Flow

1. Navigate to Ad Scheduler
2. Click "Create Schedule"
3. Select product and configure job name/schedule
4. Choose "📤 Upload New" template mode
5. Upload one or more reference ad images
6. Preview images in grid
7. Save schedule - files upload to `reference-ads` storage
8. Job executes using uploaded templates

---

## Testing Checklist

- [x] Upload mode appears in scheduler radio options
- [x] Multi-file upload works with preview grid
- [x] Validation prevents save without uploads
- [x] Files upload to reference-ads storage on save
- [x] Job saves with correct template_ids
- [x] Session state clears after save/cancel
- [x] Code compiles without syntax errors

---

## Related Files

| File | Purpose |
|------|---------|
| `viraltracker/ui/pages/04_📅_Ad_Scheduler.py` | Main scheduler UI with upload feature |
| `viraltracker/worker/scheduler_worker.py` | Worker that processes scheduled jobs (unchanged) |
