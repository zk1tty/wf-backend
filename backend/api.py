import asyncio
import sys
import os

import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.routers import get_service, local_wf_router, db_wf_router

# Set event loop policy for Windows
if sys.platform == 'win32':
	asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

app = FastAPI(title='Rebrowse Service')

# ─── CORS ────────
origins = [
    "https://app.rebrowse.me",         # production UI
    "http://localhost:5173",           # local Vite dev
    "http://localhost:3000",           # React dev server
    "http://localhost:8080",           # Alternative dev server
    "http://127.0.0.1:5173",           # local Vite dev (127.0.0.1)
    "http://127.0.0.1:3000",           # React dev server (127.0.0.1)
    "http://127.0.0.1:8080",           # Alternative dev server (127.0.0.1)
    "chrome-extension://<EXT_ID>",     # Chrome extension
]
origin_regex = r"https:\/\/.*\.vercel\.app"   # Vercel preview URLs

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=origin_regex,
    allow_credentials=True,
    allow_methods=["*"],  # Allow all HTTP methods (GET, POST, PATCH, DELETE, PUT, OPTIONS)
    allow_headers=["*"],
)
#-----

# Initialize service with app instance
service = get_service(app=app)

# Health check endpoint for Railway
@app.get("/health")
async def health_check():
	"""Health check endpoint for Railway deployment monitoring."""
	try:
		# Basic health checks
		health_status = {
			"status": "healthy",
			"service": "rebrowse-backend",
			"llm_available": service.llm_instance is not None,
			"browser_available": service.browser_instance is not None,
			"tmp_dir_exists": service.tmp_dir.exists(),
		}
		
		# Check if we can create a simple file (filesystem test)
		test_file = service.tmp_dir / "health_check.txt"
		try:
			test_file.write_text("health_check")
			test_file.unlink()  # Clean up
			health_status["filesystem_writable"] = True
		except Exception:
			health_status["filesystem_writable"] = False
		
		return health_status
		
	except Exception as e:
		raise HTTPException(status_code=503, detail=f"Service unhealthy: {str(e)}")

@app.get("/test-browser")
async def test_browser():
	"""Test browser functionality for Railway deployment."""
	import os
	import shutil
	from browser_use.browser.browser import Browser, BrowserProfile
	
	try:
		# Environment info
		env_info = {
			"environment": "production" if os.getenv('RAILWAY_ENVIRONMENT') else "development",
			"display": os.getenv('DISPLAY', 'not set'),
			"railway_env": os.getenv('RAILWAY_ENVIRONMENT', 'not set'),
		}
		
		# Check for Chromium executable
		chromium_paths = [
			'/usr/bin/chromium-browser',
			'/usr/bin/chromium',
			'/usr/bin/google-chrome',
			'/usr/bin/google-chrome-stable',
		]
		
		chromium_info = {}
		for path in chromium_paths:
			exists = os.path.exists(path) if path else False
			executable = shutil.which(path) if path else None
			chromium_info[path] = {
				"exists": exists,
				"executable": executable is not None,
				"path": executable
			}
		
		# Try to create and test browser
		browser_test = {"status": "unknown", "error": None}
		
		try:
			# Find working Chromium
			chromium_executable = None
			for name in ['chromium-browser', 'chromium', 'google-chrome']:
				found = shutil.which(name)
				if found:
					chromium_executable = found
					break
			
			if not chromium_executable:
				chromium_executable = 'chromium-browser'  # Fallback
			
			# Create test browser profile
			profile = BrowserProfile(
				headless=True,
				disable_security=True,
				args=[
					'--no-sandbox',
					'--disable-dev-shm-usage',
					'--disable-gpu',
					'--single-process',
					'--disable-web-security',
					'--no-first-run',
					'--disable-extensions'
				]
			)
			
			# Test browser creation
			test_browser = Browser(browser_profile=profile)
			
			# Try to start browser
			await test_browser.start()
			
			# Try to navigate to a simple page
			page = await test_browser.get_current_page()
			await page.goto("data:text/html,<html><body><h1>Browser Test</h1></body></html>")
			
			# Get page title
			title = await page.title()
			
			# Close browser
			await test_browser.close()
			
			browser_test = {
				"status": "success",
				"chromium_path": chromium_executable,
				"page_title": title,
				"message": "Browser test completed successfully"
			}
			
		except Exception as e:
			browser_test = {
				"status": "failed",
				"error": str(e),
				"message": "Browser test failed"
			}
		
		return {
			"environment": env_info,
			"chromium_detection": chromium_info,
			"browser_test": browser_test,
			"timestamp": os.popen('date').read().strip()
		}
		
	except Exception as e:
		raise HTTPException(status_code=500, detail=f"Browser test failed: {str(e)}")

# Include routers
app.include_router(local_wf_router)
app.include_router(db_wf_router)

# Optional standalone runner
if __name__ == '__main__':
	uvicorn.run('api:app', host='127.0.0.1', port=8000, log_level='info')
