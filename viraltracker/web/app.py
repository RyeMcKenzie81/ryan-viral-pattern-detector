"""
FastAPI web dashboard for monitoring Railway cron jobs.

Provides:
- Dashboard showing last 30 cron runs
- CSV download for each run
- Log viewing
- Next scheduled run display
"""
import os
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import Request

from supabase import create_client, Client

# Initialize FastAPI
app = FastAPI(title="ViralTracker Cron Dashboard")

# Initialize Supabase client
supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_KEY")

if not supabase_url or not supabase_key:
    raise ValueError("SUPABASE_URL and SUPABASE_KEY environment variables are required")

supabase: Client = create_client(supabase_url, supabase_key)

# Templates
templates = Jinja2Templates(directory="viraltracker/web/templates")


def get_next_run_time() -> str:
    """Calculate next scheduled run (Mon-Fri 6 AM EST)."""
    now = datetime.utcnow()

    # Convert to EST (UTC-5)
    est_now = now - timedelta(hours=5)

    # Next 6 AM
    next_run = est_now.replace(hour=6, minute=0, second=0, microsecond=0)

    # If already past 6 AM today, move to tomorrow
    if est_now.hour >= 6:
        next_run += timedelta(days=1)

    # Skip weekends
    while next_run.weekday() >= 5:  # 5=Saturday, 6=Sunday
        next_run += timedelta(days=1)

    return next_run.strftime("%Y-%m-%d %I:%M %p EST")


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard showing cron run history."""
    try:
        # Fetch last 30 runs from Supabase
        response = supabase.table("cron_runs") \
            .select("*") \
            .order("run_date", desc=True) \
            .limit(30) \
            .execute()

        runs = response.data

        # Calculate next run time
        next_run = get_next_run_time()

        return templates.TemplateResponse("dashboard.html", {
            "request": request,
            "runs": runs,
            "next_run": next_run,
            "total_runs": len(runs)
        })

    except Exception as e:
        return HTMLResponse(
            content=f"<h1>Error loading dashboard</h1><p>{str(e)}</p>",
            status_code=500
        )


@app.get("/runs/{run_id}/download")
async def download_csv(run_id: str):
    """Download CSV file for a specific run."""
    try:
        # Get run info from database
        response = supabase.table("cron_runs") \
            .select("csv_storage_path, run_date") \
            .eq("id", run_id) \
            .single() \
            .execute()

        if not response.data:
            raise HTTPException(status_code=404, detail="Run not found")

        csv_path = response.data["csv_storage_path"]
        run_date = response.data["run_date"]

        if not csv_path:
            raise HTTPException(status_code=404, detail="No CSV file for this run")

        # Download from Supabase Storage
        file_data = supabase.storage.from_("cron-outputs").download(csv_path)

        # Save temporarily
        temp_path = f"/tmp/{run_id}.csv"
        with open(temp_path, "wb") as f:
            f.write(file_data)

        # Return file
        filename = f"keyword_greens_{run_date}.csv"
        return FileResponse(
            temp_path,
            media_type="text/csv",
            filename=filename
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/runs/{run_id}/logs")
async def view_logs(run_id: str):
    """View logs for a specific run."""
    try:
        # Get run info from database
        response = supabase.table("cron_runs") \
            .select("log_output, run_date, status") \
            .eq("id", run_id) \
            .single() \
            .execute()

        if not response.data:
            raise HTTPException(status_code=404, detail="Run not found")

        logs = response.data.get("log_output", "No logs available")
        run_date = response.data["run_date"]
        status = response.data["status"]

        # Return as HTML with <pre> tag
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Logs - {run_date}</title>
            <style>
                body {{
                    font-family: monospace;
                    margin: 20px;
                    background: #1e1e1e;
                    color: #d4d4d4;
                }}
                h1 {{
                    color: #4ec9b0;
                }}
                pre {{
                    background: #252526;
                    padding: 20px;
                    border-radius: 5px;
                    overflow-x: auto;
                }}
                .back {{
                    color: #4ec9b0;
                    text-decoration: none;
                }}
                .status {{
                    color: {'#4ec9b0' if status == 'completed' else '#ce9178'};
                }}
            </style>
        </head>
        <body>
            <a class="back" href="/">&larr; Back to Dashboard</a>
            <h1>Logs for {run_date}</h1>
            <p>Status: <span class="status">{status}</span></p>
            <pre>{logs}</pre>
        </body>
        </html>
        """

        return HTMLResponse(content=html_content)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    """Health check endpoint for Railway."""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@app.get("/favicon.ico")
async def favicon():
    """Redirect favicon requests."""
    return RedirectResponse(url="/static/favicon.ico", status_code=301)
