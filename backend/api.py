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

# Include routers
app.include_router(local_wf_router)
app.include_router(db_wf_router)

# Optional standalone runner
if __name__ == '__main__':
	uvicorn.run('api:app', host='127.0.0.1', port=8000, log_level='info')
