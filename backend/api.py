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

# Add CORS middleware
origins = [
    "https://app.rebrowse.me",       # Vercel UI
    "https://rebrowse.me",           # landing page if it ever calls API
    "chrome-extension://*"    # extension pages - replace <EXT_ID> with actual extension ID
]

# Allow any localhost address for development
if os.environ.get('ENV') == 'dev':
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_origin_regex="https?://(localhost|127\\.0\\.0\\.1)(:\\d+)?",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else: # prod
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Initialize service with app instance
service = get_service(app=app)

# Include routers
app.include_router(local_wf_router)
app.include_router(db_wf_router)

# Optional standalone runner
if __name__ == '__main__':
	uvicorn.run('api:app', host='127.0.0.1', port=8000, log_level='info')
