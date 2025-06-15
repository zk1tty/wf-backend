# Test Suite

This directory contains all test scripts for the wf-backend project. All tests have been configured with robust path handling to work from this subdirectory.

## Available Tests

### 🎮 Custom Screensaver Test
**File:** `test_custom_screensaver.py`
**Purpose:** Test the rebrowse custom DVD screensaver functionality
**Usage:**
```bash
cd test
python test_custom_screensaver.py
```
**Features Tested:**
- Auto-detection of rebrowse.png logo
- Purple gradient background
- Bouncing animation with physics
- Color-changing effects on bounce
- Sparkle particle effects

### 🌐 Session Execution Test
**File:** `test_session_execution.py`
**Purpose:** Test session-based workflow execution endpoints
**Usage:**
```bash
cd test
python test_session_execution.py
```
**Features Tested:**
- Health check endpoint
- Session token validation
- Workflow execution endpoint
- Background task management

### 🖥️ Browser Local Test
**File:** `test_browser_local.py`
**Purpose:** Comprehensive browser functionality testing
**Usage:**
```bash
cd test
python test_browser_local.py
```
**Features Tested:**
- System requirements check
- Basic browser functionality
- Headless browser configuration
- Real website navigation
- Production readiness validation

### 🔐 JWT Token Tests
**File:** `test-jwt-local.py`
**Purpose:** Test JWT token validation locally
**Usage:**
```bash
cd test
python test-jwt-local.py
```
**Features Tested:**
- JWT token decoding
- Signature verification
- API authentication

**File:** `test-fresh-token.py`
**Purpose:** Interactive test for fresh JWT tokens from Chrome extension
**Usage:**
```bash
cd test
python test-fresh-token.py
```
**Features Tested:**
- Interactive token input
- Token expiration checking
- Live API testing

## Running Tests

### From Test Directory
```bash
cd test
python <test_file_name>.py
```

### From Project Root
```bash
python test/<test_file_name>.py
```

## Path Handling

All test files use robust path handling with:
- `Path(__file__).parent.parent` to find project root
- `sys.path.insert(0, str(project_root))` for imports
- Automatic detection of configuration files (`.env`, `rebrowse.png`)

This ensures tests work correctly regardless of where they're run from.

## Prerequisites

- Python 3.11+
- All project dependencies installed (`pip install -r requirements.txt`)
- For browser tests: Chromium/Chrome installed
- For API tests: Backend server running on localhost:8000
- For JWT tests: Valid `.env` file with `SUPABASE_JWT_SECRET`

## Test Results

All tests provide detailed output with:
- ✅ Success indicators
- ❌ Failure indicators  
- 📋 Summary reports
- 💡 Troubleshooting tips 