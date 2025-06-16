# Rebrowse Workflow — FastAPI service

- ENV: `dev` or `prod`
- venv installation
    ```
    # Init venv
    uv venv --python 3.11
    source .venv/bin/activate

    # Manage Python packages with a pip-compatible interface
    uv pip install -r requirements.txt

    # Run uvicorn
    ENV=dev uvicorn backend.api:app --reload
    ```


If you get issue like `ModuleNotFoundError: No module named 'supabase`?

- instalation help command
    ```
    # Check which Python is being used
    which python

    # Check Python version
    python --version

    # Check installed packages (in uv environment)
    uv pip list

    # Check specific package
    uv pip list | grep supabase
    ```

This is the python package for Workflow Use. It is used to create and execute workflows.

Currently only used to reserve the pypi package name.

## Public API endopint

📊 API | Endpoints | Available
--|--|--
Method | Endpoint | Description
POST |	/workflows/{id}/execute/session	| Execute workflow with session auth
GET	| /workflows/tasks/{task_id}/status	| Check execution status
POST |	/workflows/tasks/{task_id}/cancel	| Cancel workflow execution
GET	| /workflows/logs/{task_id}	| Get execution logs
GET	| /health	Health check for | monitoring

## Auth ENdpoint

📊 | Authentication | API
--|--|--
Method | Endpoint | Description
GET | /auth/validate | Validate session token


## Browser instance 

Environment	| Browser Type	| GUI | Use Case | Triggered When
--|--|--|--|--
Local Development | Standard Browser | ✅ Yes | Development, Testing | RAILWAY_ENVIRONMENT not set
Railway Production | Headless Chromium | ❌ No | Production, Automation | RAILWAY_ENVIRONMENT=production
Render Production | Headless Chromium | ❌ No | Production, Automation | RENDER=true
Manual Production | Headless Chromium | ❌ No | Testing Production Config | Set env var manually

### 🖥️ Local Browser (Development Mode)

- 🖼️ GUI Enabled: Opens visible browser windows
- 🎯 Full Features: All browser features available
- 🔧 Easy Debugging: Can see what's happening visually
- 💻 Local Chromium: Uses your system's installed browser

```bash
# Local development
python -m uvicorn backend.api:app --reload

# Local testing
python test_browser_local.py

# CLI usage
python cli.py run-workflow workflow.json
```

### ☁️ Remote Headless Browser (Production Mode)

Characteristics:
- 🚫 No GUI: Runs completely headless
- ⚡ Optimized: Memory and CPU efficient
- 🔒 Container-Safe: Works in Docker/Railway containers
- 🎯 Production-Ready: Stable for server environments


When Triggered:
- ✅ Deployed on Railway (sets RAILWAY_ENVIRONMENT=production)
- ✅ Deployed on Render (sets RENDER=true)
- ✅ Any environment with these variables set

Config
```python
profile = BrowserProfile(
    headless=True,  # No GUI
    disable_security=True,
    args=[
        '--no-sandbox',
        '--disable-dev-shm-usage',
        '--disable-gpu',
        '--single-process',
        # ... many optimization flags
    ]
)
return Browser(browser_profile=profile)
```