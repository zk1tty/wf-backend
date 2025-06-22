import asyncio
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import uuid

import aiofiles
from browser_use.agent.views import ActionResult
from browser_use.browser.browser import Browser
from langchain_openai import ChatOpenAI
from supabase import Client

from workflow_use.builder.service import BuilderService
from workflow_use.controller.service import WorkflowController
from workflow_use.recorder.service import RecordingService
from workflow_use.workflow.service import Workflow

from .dependencies import supabase
from .views import (
	TaskInfo,
	WorkflowAddRequest,
	WorkflowBuildRequest,
	WorkflowBuildResponse,
	WorkflowCancelResponse,
	WorkflowDeleteStepRequest,
	WorkflowExecuteRequest,
	WorkflowMetadataUpdateRequest,
	WorkflowRecordResponse,
	WorkflowResponse,
	WorkflowStatusResponse,
	WorkflowUpdateRequest,
	WorkflowJobStatus,
)

from workflow_use.browser.custom_screensaver import patch_browser_use_screensaver

# Add job tracking at module level
workflow_jobs: Dict[str, WorkflowJobStatus] = {}

# Global task storage for tracking background executions
background_tasks: Dict[str, Dict[str, Any]] = {}

logger = logging.getLogger(__name__)

class WorkflowService:
	"""Workflow execution service."""

	def __init__(self, supabase_client: Client, app=None) -> None:
		self.supabase = supabase_client
		
		# Patch the browser-use screensaver with rebrowse logo
		patch_browser_use_screensaver(
			logo_url=None,  # Will auto-detect rebrowse.png
			logo_text="rebrowse"  # Fallback text if logo not found
		)
		
		# ---------- Core resources to fetch from local storage ----------
		self.tmp_dir: Path = Path('./tmp')
		self.log_dir: Path = self.tmp_dir / 'logs'
		self.log_dir.mkdir(exist_ok=True, parents=True)

		# LLM / workflow executor
		try:
			self.llm_instance = ChatOpenAI(model='gpt-4.1-mini')
		except Exception as exc:
			print(f'Error initializing LLM: {exc}. Ensure OPENAI_API_KEY is set.')
			self.llm_instance = None

		# Browser configuration for production/Railway
		# Browser instance will be created dynamically based on execution mode
		self.browser_instance = None  # Created per workflow execution with specific mode
		self.controller_instance = WorkflowController()
		self.recording_service = RecordingService(app=app)

		# In‑memory task tracking
		self.active_tasks: Dict[str, TaskInfo] = {}
		self.workflow_tasks: Dict[str, asyncio.Task] = {}
		self.cancel_events: Dict[str, asyncio.Event] = {}

	def _create_browser_instance(self, mode: str = "auto") -> Browser:
		"""Create browser instance with appropriate configuration for environment and mode.
		
		Args:
			mode: "cloud-run", "local-run", or "auto" (default)
				- "cloud-run": Force headless Playwright Chromium (server-side)
				- "local-run": Force local Chromium with GUI (user's installed browser)
				- "auto": Auto-detect based on environment variables
		"""
		import shutil
		from browser_use.browser.browser import BrowserProfile
		
		# Auto-detect environment if mode is "auto"
		if mode == "auto":
			is_production = os.getenv('RAILWAY_ENVIRONMENT') is not None or os.getenv('RENDER') is not None
			detected_mode = "cloud-run" if is_production else "local-run"
			print(f"[WorkflowService] Auto-detected mode: {detected_mode}")
			mode = detected_mode
		
		if mode == "cloud-run":
			# Cloud/Server configuration - headless Playwright Chromium
			print("[WorkflowService] Initializing browser in CLOUD-RUN mode (headless)")
			print(f"[WorkflowService] Display: {os.getenv('DISPLAY', 'not set')}")
			
			# Check if Playwright browsers are installed
			playwright_chromium_path = "/root/.cache/ms-playwright/chromium-1169/chrome-linux/chrome"
			if os.path.exists(playwright_chromium_path):
				print(f"[WorkflowService] Playwright Chromium found at: {playwright_chromium_path}")
			else:
				print(f"[WorkflowService] WARNING: Playwright Chromium not found at: {playwright_chromium_path}")
				print("[WorkflowService] Make sure 'playwright install chromium' was run during build")
			
			profile = BrowserProfile(
				headless=True,  # Run without GUI
				disable_security=True,  # Disable security for automation
				args=[
					'--no-sandbox',  # Required for Docker/Railway
					'--disable-dev-shm-usage',  # Overcome limited resource problems
					'--disable-gpu',  # Disable GPU hardware acceleration
					'--disable-web-security',  # Disable web security for automation
					'--disable-features=VizDisplayCompositor',  # Disable compositor
					'--disable-background-timer-throttling',  # Disable background throttling
					'--disable-backgrounding-occluded-windows',
					'--disable-renderer-backgrounding',
					'--disable-field-trial-config',
					'--disable-ipc-flooding-protection',
					'--disable-extensions',  # Disable extensions
					'--disable-plugins',  # Disable plugins
					'--disable-default-apps',  # Disable default apps
					'--disable-sync',  # Disable sync
					'--no-first-run',  # Skip first run setup
					'--no-default-browser-check',  # Skip default browser check
					'--disable-background-networking',  # Disable background networking
					'--single-process',  # Use single process (saves memory)
					'--memory-pressure-off',  # Disable memory pressure
					'--max_old_space_size=4096',  # Increase memory limit
					'--remote-debugging-port=9222',  # Enable remote debugging
				]
			)
			
			# Let browser-use/Playwright handle the executable path automatically
			return Browser(browser_profile=profile)
			
		elif mode == "local-run":
			# Local user configuration - use their installed Chromium with GUI
			print("[WorkflowService] Initializing browser in LOCAL-RUN mode (user's Chromium)")
			
			# Find user's local Chromium installation
			chromium_paths = [
				'/usr/bin/chromium-browser',
				'/usr/bin/chromium',
				'/usr/bin/google-chrome',
				'/usr/bin/google-chrome-stable',
				'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',  # macOS
			]
			
			chromium_executable = None
			for path in chromium_paths:
				if os.path.exists(path):
					chromium_executable = path
					break
			
			if not chromium_executable:
				# Try using shutil.which
				for name in ['chromium-browser', 'chromium', 'google-chrome', 'google-chrome-stable']:
					found = shutil.which(name)
					if found:
						chromium_executable = found
						break
			
			if chromium_executable:
				print(f"[WorkflowService] Using local Chromium: {chromium_executable}")
			else:
				print("[WorkflowService] WARNING: No local Chromium found, falling back to default")
				print("[WorkflowService] Make sure to run: curl -fsSL https://your-repo/install-chromium.sh | bash")
			
			# Local configuration with GUI enabled
			profile = BrowserProfile(
				headless=False,  # Enable GUI for local development
				disable_security=True,  # Still disable security for automation
				args=[
					'--disable-web-security',  # Disable web security for automation
					'--no-first-run',  # Skip first run setup
					'--disable-default-browser-check',  # Skip default browser check
					# Note: Remove --no-sandbox and other container-specific flags for local use
				]
			)
			
			return Browser(browser_profile=profile)
		
		else:
			raise ValueError(f"Invalid browser mode: {mode}. Must be 'cloud-run', 'local-run', or 'auto'")

	def _get_timestamp(self) -> str:
		"""Get current timestamp in the format used for logging."""
		return time.strftime('%Y-%m-%d %H:%M:%S') + f'.{int(time.time() * 1000) % 1000:03d}'

	async def _log_file_position(self) -> int:
		log_file = self.log_dir / 'backend.log'
		if not log_file.exists():
			async with aiofiles.open(log_file, 'w') as f:
				await f.write('')
			return 0
		return log_file.stat().st_size

	async def _read_logs_from_position(self, position: int) -> Tuple[List[str], int]:
		log_file = self.log_dir / 'backend.log'
		if not log_file.exists():
			return [], 0

		current_size = log_file.stat().st_size
		if position >= current_size:
			return [], position

		async with aiofiles.open(log_file, 'r', encoding='utf-8') as f:
			await f.seek(position)
			all_logs = await f.readlines()
			new_logs = [
				line
				for line in all_logs
				if not line.strip().startswith('INFO:')
				and not line.strip().startswith('WARNING:')
				and not line.strip().startswith('DEBUG:')
				and not line.strip().startswith('ERROR:')
			]
		return new_logs, current_size

	async def _write_log(self, log_file: Path, message: str) -> None:
		async with aiofiles.open(log_file, 'a', encoding='utf-8') as f:
			await f.write(message)

	def _sync_workflow_filename(self, file_path: Path, workflow_content: dict) -> Path:
		"""Synchronize the workflow file name with its internal name."""
		current_name = workflow_content.get('name')
		if not current_name:
			return file_path

		# Check if a file with this name already exists (excluding current file)
		name_exists = False
		for path in self.tmp_dir.iterdir():
			if (path.is_file() and not path.name.startswith('temp_recording') 
				and path != file_path 
				and path.stem == current_name):
				name_exists = True
				break

		if name_exists:
			# If name exists, update both file name and internal name
			new_filename = self._get_next_available_filename(current_name)
			new_name = Path(new_filename).stem  # Get name without extension
			workflow_content['name'] = new_name
			new_file_path = self.tmp_dir / new_filename
			file_path.rename(new_file_path)
			return new_file_path
		elif file_path.stem != current_name:
			# If name doesn't exist but file name doesn't match internal name
			new_filename = f"{current_name}.json"
			new_file_path = self.tmp_dir / new_filename
			file_path.rename(new_file_path)
			return new_file_path

		return file_path
	
	def list_workflows(self) -> List[str]:
		return [f.name for f in self.tmp_dir.iterdir() if f.is_file() and not f.name.startswith('temp_recording')]

	def get_workflow(self, name: str) -> str:
		wf_file = self.tmp_dir / name
		try:
			data = wf_file.read_text()
			workflow_content = json.loads(data)
			
			# If file name doesn't match internal name, sync them
			if workflow_content.get('name') != wf_file.stem:
				wf_file = self._sync_workflow_filename(wf_file, workflow_content)
				return json.loads(wf_file.read_text())
				
			return data
		except (FileNotFoundError, json.JSONDecodeError):
			return ""

	def update_workflow(self, request: WorkflowUpdateRequest) -> WorkflowResponse:
		workflow_filename = request.filename
		node_id = request.nodeId
		updated_step_data = request.stepData

		if not (workflow_filename and node_id is not None and updated_step_data):
			return WorkflowResponse(success=False, error='Missing required fields')

		# Search through all files in tmp_dir to find the matching workflow
		matching_file = None
		for file_path in self.tmp_dir.iterdir():
			if not file_path.is_file() or file_path.name.startswith('temp_recording'):
				continue
			try:
				workflow_content = json.loads(file_path.read_text())
				if workflow_content.get('name') == workflow_filename:
					matching_file = file_path
					break
			except (json.JSONDecodeError, KeyError):
				continue

		if not matching_file:
			return WorkflowResponse(success=False, error=f"Workflow with name '{workflow_filename}' not found")
		# Load and modify the workflow
		workflow_content = json.loads(matching_file.read_text())
		steps = workflow_content.get('steps', [])

		try:
			node_index = int(node_id)
		except ValueError:
			return WorkflowResponse(success=False, error='Invalid node ID')

		# Updating or adding a step
		if 0 <= node_index < len(steps):
			steps[node_index] = updated_step_data
		elif node_index == len(steps):  # Add new step
			steps.append(updated_step_data)
		else:
			return WorkflowResponse(success=False, error='Node index out of bounds for adding step')

		workflow_content['steps'] = steps
		matching_file.write_text(json.dumps(workflow_content, indent=2))
		return WorkflowResponse(success=True)

	def update_workflow_metadata(self, request: WorkflowMetadataUpdateRequest) -> WorkflowResponse:
		workflow_name = request.name
		updated_metadata = request.metadata

		if not (workflow_name and updated_metadata):
			return WorkflowResponse(success=False, error='Missing required fields')

		# Search through all files in tmp_dir to find the matching workflow
		matching_file = None
		for file_path in self.tmp_dir.iterdir():
			if not file_path.is_file() or file_path.name.startswith('temp_recording'):
				continue
			try:
				workflow_content = json.loads(file_path.read_text())
				if workflow_content.get('name') == workflow_name:
					matching_file = file_path
					break
			except (json.JSONDecodeError, KeyError):
				continue

		if not matching_file:
			print(f"Workflow with name '{workflow_name}' not found")
			return WorkflowResponse(success=False, error=f"Workflow with name '{workflow_name}' not found")

		workflow_content = json.loads(matching_file.read_text())
		
		# Update metadata fields directly from updated_metadata
		if 'name' in updated_metadata:
			workflow_content['name'] = updated_metadata['name']
		if 'description' in updated_metadata:
			workflow_content['description'] = updated_metadata['description']
		if 'workflow_analysis' in updated_metadata:
			workflow_content['workflow_analysis'] = updated_metadata['workflow_analysis']
		if 'version' in updated_metadata:
			workflow_content['version'] = updated_metadata['version']
		if 'input_schema' in updated_metadata:
			workflow_content['input_schema'] = updated_metadata['input_schema']

		# Only sync if the name was updated and is different from current file name
		if 'name' in updated_metadata and updated_metadata['name'] != matching_file.stem:
			matching_file = self._sync_workflow_filename(matching_file, workflow_content)

		matching_file.write_text(json.dumps(workflow_content, indent=2))
		return WorkflowResponse(success=True)
	
	def delete_step(self, request: WorkflowDeleteStepRequest) -> WorkflowResponse:
		workflow_name = request.workflowName
		step_index = request.stepIndex

		if not (workflow_name and step_index):
			return WorkflowResponse(success=False, error='Missing required fields')

		# Search through all files in tmp_dir to find the matching workflow
		matching_file = None
		for file_path in self.tmp_dir.iterdir():
			if not file_path.is_file() or file_path.name.startswith('temp_recording'):
				continue
			try:
				workflow_content = json.loads(file_path.read_text())
				if workflow_content.get('name') == workflow_name:
					matching_file = file_path
					break
			except (json.JSONDecodeError, KeyError):
				continue

		if not matching_file:
			print(f"Workflow with name '{workflow_name}' not found")
			return WorkflowResponse(success=False, error=f"Workflow with name '{workflow_name}' not found")

		if not matching_file:
			return WorkflowResponse(success=False, error="Workflow not found")

		workflow_content = json.loads(matching_file.read_text())
		steps = workflow_content.get('steps', [])

		if 0 <= step_index < len(steps):
			del steps[step_index]
			workflow_content['steps'] = steps
			matching_file.write_text(json.dumps(workflow_content, indent=2))
			return WorkflowResponse(success=True)

		return WorkflowResponse(success=False, error="Invalid step index")

	async def run_workflow_in_background(
		self,
		task_id: str,
		request: WorkflowExecuteRequest,
		cancel_event: asyncio.Event,
	) -> None:
		workflow_name = request.name
		inputs = request.inputs
		log_file = self.log_dir / 'backend.log'
		try:
			self.active_tasks[task_id] = TaskInfo(status='running', workflow=workflow_name)
			await self._write_log(log_file, f"[{self._get_timestamp()}] Starting workflow '{workflow_name}'\n")
			await self._write_log(log_file, f'[{self._get_timestamp()}] Input parameters: {json.dumps(inputs)}\n')

			if cancel_event.is_set():
				await self._write_log(log_file, f'[{self._get_timestamp()}] Workflow cancelled before execution\n')
				self.active_tasks[task_id].status = 'cancelled'
				return

			workflow_path = self.tmp_dir / workflow_name
			try:
				self.workflow_obj = Workflow.load_from_file(
					str(workflow_path), llm=self.llm_instance, browser=self.browser_instance, controller=self.controller_instance
				)
			except Exception as e:
				print(f'Error loading workflow: {e}')
				return

			await self._write_log(log_file, f'[{self._get_timestamp()}] Executing workflow...\n')

			if cancel_event.is_set():
				await self._write_log(log_file, f'[{self._get_timestamp()}] Workflow cancelled before execution\n')
				self.active_tasks[task_id].status = 'cancelled'
				return

			result = await self.workflow_obj.run(inputs, close_browser_at_end=True, cancel_event=cancel_event)

			if cancel_event.is_set():
				await self._write_log(log_file, f'[{self._get_timestamp()}] Workflow execution was cancelled\n')
				self.active_tasks[task_id].status = 'cancelled'
				return

			formatted_result = []
			for i, s in enumerate(result.step_results):
				content = None
				if isinstance(s, ActionResult):  # Handle agentic steps and agent fallback
					content = s.extracted_content
				elif hasattr(s, 'history') and s.history:  # AgentHistoryList
					# For AgentHistoryList, get the last successful result
					last_item = s.history[-1]
					last_action_result = next(
						(r for r in reversed(last_item.result) if r.extracted_content is not None),
						None,
					)
					if last_action_result:
						content = last_action_result.extracted_content

				formatted_result.append(
					{
						'step_id': i,
						'extracted_content': content,
						'status': 'completed',
					}
				)

			for step in formatted_result:
				await self._write_log(
					log_file, f'[{self._get_timestamp()}] Completed step {step["step_id"]}: {step["extracted_content"]}\n'
				)

			self.active_tasks[task_id].status = 'completed'
			self.active_tasks[task_id].result = formatted_result
			await self._write_log(
				log_file, f'[{self._get_timestamp()}] Workflow completed successfully with {len(result.step_results)} steps\n'
			)

		except asyncio.CancelledError:
			await self._write_log(log_file, f'[{self._get_timestamp()}] Workflow force‑cancelled\n')
			self.active_tasks[task_id].status = 'cancelled'
			raise
		except Exception as exc:
			await self._write_log(log_file, f'[{self._get_timestamp()}] Error: {exc}\n')
			self.active_tasks[task_id].status = 'failed'
			self.active_tasks[task_id].error = str(exc)

	def get_task_status(self, task_id: str) -> Optional[WorkflowStatusResponse]:
		task_info = self.active_tasks.get(task_id)
		if not task_info:
			return None

		return WorkflowStatusResponse(
			task_id=task_id,
			status=task_info.status,
			workflow=task_info.workflow,
			result=task_info.result,
			error=task_info.error,
		)

	async def cancel_workflow(self, task_id: str) -> WorkflowCancelResponse:
		task_info = self.active_tasks.get(task_id)
		if not task_info:
			return WorkflowCancelResponse(success=False, message='Task not found')
		if task_info.status != 'running':
			return WorkflowCancelResponse(success=False, message=f'Task is already {task_info.status}')

		task = self.workflow_tasks.get(task_id)
		cancel_event = self.cancel_events.get(task_id)

		if cancel_event:
			cancel_event.set()
		if task and not task.done():
			task.cancel()

		await self._write_log(
			self.log_dir / 'backend.log',
			f'[{self._get_timestamp()}] Workflow execution for task {task_id} cancelled by user\n',
		)

		self.active_tasks[task_id].status = 'cancelling'
		return WorkflowCancelResponse(success=True, message='Workflow cancellation requested')

	async def run_workflow_session_in_background(
		self,
		task_id: str,
		workflow_id: str,
		inputs: dict,
		cancel_event: asyncio.Event,
		owner_id: Optional[str] = None,
		mode: str = "cloud-run",
	) -> None:
		"""Execute a workflow from database using session-based authentication."""
		log_file = self.log_dir / 'backend.log'
		temp_file = None
		
		try:
			# Fetch workflow from database
			workflow_data = self.get_workflow_by_id(workflow_id)
			if not workflow_data:
				raise ValueError(f"Workflow {workflow_id} not found in database")
			
			# Verify ownership if owner_id provided
			if owner_id and workflow_data.get('owner_id') != owner_id:
				raise ValueError(f"Access denied: User {owner_id} does not own workflow {workflow_id}")
			
			workflow_name = workflow_data.get('name', f'workflow_{workflow_id}')
			
			self.active_tasks[task_id] = TaskInfo(status='running', workflow=workflow_name)
			await self._write_log(log_file, f"[{self._get_timestamp()}] Starting session workflow '{workflow_name}' (ID: {workflow_id})\n")
			await self._write_log(log_file, f'[{self._get_timestamp()}] Input parameters: {json.dumps(inputs)}\n')

			if cancel_event.is_set():
				await self._write_log(log_file, f'[{self._get_timestamp()}] Workflow cancelled before execution\n')
				self.active_tasks[task_id].status = 'cancelled'
				return

			# Create temporary workflow file
			temp_file = self.tmp_dir / f"temp_session_{task_id}_{workflow_id}.json"
			temp_file.write_text(json.dumps(workflow_data))
			
			await self._write_log(log_file, f'[{self._get_timestamp()}] Created temporary workflow file: {temp_file.name}\n')

			try:
				# Create browser instance with the specified mode
				browser_instance = self._create_browser_instance(mode=mode)
				await self._write_log(log_file, f'[{self._get_timestamp()}] Created browser instance for mode: {mode}\n')
				
				self.workflow_obj = Workflow.load_from_file(
					str(temp_file), 
					llm=self.llm_instance, 
					browser=browser_instance, 
					controller=self.controller_instance
				)
			except Exception as e:
				await self._write_log(log_file, f'[{self._get_timestamp()}] Error loading workflow: {e}\n')
				raise ValueError(f'Error loading workflow: {e}')

			await self._write_log(log_file, f'[{self._get_timestamp()}] Executing workflow...\n')

			if cancel_event.is_set():
				await self._write_log(log_file, f'[{self._get_timestamp()}] Workflow cancelled before execution\n')
				self.active_tasks[task_id].status = 'cancelled'
				return

			result = await self.workflow_obj.run(inputs, close_browser_at_end=True, cancel_event=cancel_event)

			if cancel_event.is_set():
				await self._write_log(log_file, f'[{self._get_timestamp()}] Workflow execution was cancelled\n')
				self.active_tasks[task_id].status = 'cancelled'
				return

			formatted_result = []
			for i, s in enumerate(result.step_results):
				content = None
				if isinstance(s, ActionResult):  # Handle agentic steps and agent fallback
					content = s.extracted_content
				elif hasattr(s, 'history') and s.history:  # AgentHistoryList
					# For AgentHistoryList, get the last successful result
					last_item = s.history[-1]
					last_action_result = next(
						(r for r in reversed(last_item.result) if r.extracted_content is not None),
						None,
					)
					if last_action_result:
						content = last_action_result.extracted_content

				formatted_result.append(
					{
						'step_id': i,
						'extracted_content': content,
						'status': 'completed',
					}
				)

			for step in formatted_result:
				await self._write_log(
					log_file, f'[{self._get_timestamp()}] Completed step {step["step_id"]}: {step["extracted_content"]}\n'
				)

			self.active_tasks[task_id].status = 'completed'
			self.active_tasks[task_id].result = formatted_result
			await self._write_log(
				log_file, f'[{self._get_timestamp()}] Session workflow completed successfully with {len(result.step_results)} steps\n'
			)

		except asyncio.CancelledError:
			await self._write_log(log_file, f'[{self._get_timestamp()}] Session workflow force‑cancelled\n')
			self.active_tasks[task_id].status = 'cancelled'
			raise
		except Exception as exc:
			await self._write_log(log_file, f'[{self._get_timestamp()}] Session workflow error: {exc}\n')
			self.active_tasks[task_id].status = 'failed'
			self.active_tasks[task_id].error = str(exc)
		finally:
			# Clean up temporary file
			if temp_file and temp_file.exists():
				try:
					temp_file.unlink()
					await self._write_log(log_file, f'[{self._get_timestamp()}] Cleaned up temporary file: {temp_file.name}\n')
				except Exception as e:
					await self._write_log(log_file, f'[{self._get_timestamp()}] Warning: Failed to cleanup temp file {temp_file.name}: {e}\n')

	def add_workflow(self, request: WorkflowAddRequest) -> WorkflowResponse:
		"""Add a new workflow file."""
		if not request.name or not request.content:
			return WorkflowResponse(success=False, error='Missing required fields')

		# Create new workflow file with collision handling
		try:
			workflow_file = self.tmp_dir / self._get_next_available_filename(request.name)
			workflow_file.write_text(request.content)
			return WorkflowResponse(success=True)
		except Exception as e:
			return WorkflowResponse(success=False, error=f'Error creating workflow: {str(e)}')

	def delete_workflow(self, name: str) -> WorkflowResponse:
		"""Delete a workflow file."""
		if not name:
			return WorkflowResponse(success=False, error='Missing workflow name')

		# Find and delete the workflow file
		for file_path in self.tmp_dir.iterdir():
			if not file_path.is_file() or file_path.name.startswith('temp_recording'):
				continue
			try:
				workflow_content = json.loads(file_path.read_text())
				if workflow_content.get('name') == name:
					file_path.unlink()
					return WorkflowResponse(success=True)
			except (json.JSONDecodeError, KeyError):
				continue

		return WorkflowResponse(success=False, error=f"Workflow '{name}' not found")

	async def record_workflow(self) -> WorkflowRecordResponse:
		"""Record a new workflow using the recording service."""
		try:
			workflow_data = await self.recording_service.record_workflow_using_main_server()
			return WorkflowRecordResponse(success=True, workflow=workflow_data)
		except Exception as e:
			print(f'Error recording workflow: {e}')
			return WorkflowRecordResponse(success=False, workflow=None, error=str(e))

	async def cancel_recording(self) -> WorkflowRecordResponse:
		"""Cancel an ongoing workflow recording."""
		try:
			await self.recording_service.cancel_recording()
			return WorkflowRecordResponse(success=True, workflow=None)
		except Exception as e:
			print(f'Error cancelling recording: {e}')
			return WorkflowRecordResponse(success=False, workflow=None, error=str(e))

	def _get_next_available_filename(self, base_name: str) -> str:
		"""Get the next available filename by adding incremental numbers."""
		counter = 1
		file_name = f'{base_name}.json'
		while (self.tmp_dir / file_name).exists():
			file_name = f'{base_name}{counter}.json'
			counter += 1
		return file_name

	async def build_workflow(self, request: WorkflowBuildRequest) -> WorkflowBuildResponse:
		"""Build a workflow from the edited recording."""
		try:
			if not self.llm_instance:
				return WorkflowBuildResponse(
					success=False,
					message='Failed to build workflow',
					error='LLM instance not available. Please ensure OPENAI_API_KEY is set.',
				)

			# Initialize the builder service with the LLM instance
			builder_service = BuilderService(llm=self.llm_instance)

			# Build the workflow using the builder service
			built_workflow = await builder_service.build_workflow(
				input_workflow=request.workflow,
				user_goal=request.prompt,
				use_screenshots=False,  # TODO: We don't need screenshots for now
			)

			# Set timestamps for steps that don't have them
			current_time = int(time.time() * 1000)  # Current time in milliseconds
			has_timestamp = False
			for step in built_workflow.steps:
				if hasattr(step, 'type') and step.type != 'agent' and hasattr(step, 'timestamp') and step.timestamp is not None:
					has_timestamp = True
					break
			if not has_timestamp:
				for step in built_workflow.steps:
					if hasattr(step, 'type') and step.type != 'agent' and hasattr(step, 'timestamp'):
						step.timestamp = current_time

			# Handle workflow name
			if not request.name:
				workflow_name = built_workflow.name
			else:
				built_workflow.name = request.name
				workflow_name = request.name

			# Save the built workflow to the final location with collision handling
			final_file = self.tmp_dir / self._get_next_available_filename(workflow_name)
			final_file.write_text(built_workflow.model_dump_json(indent=2))

			return WorkflowBuildResponse(success=True, message=f"Workflow '{final_file.stem}' built successfully")
		except Exception as e:
			print(f'Error building workflow: {e}')
			return WorkflowBuildResponse(success=False, message='Failed to build workflow', error=str(e))

	def get_workflow_by_id(self, workflow_id: str) -> Optional[Dict[str, Any]]:
		"""Fetch workflow from database by ID."""
		try:
			response = self.supabase.table('workflows').select('*').eq('id', workflow_id).execute()
			
			if response.data and len(response.data) > 0:
				return response.data[0]
			else:
				logger.warning(f"No workflow found with ID: {workflow_id}")
				return None
				
		except Exception as e:
			logger.error(f"Error fetching workflow {workflow_id}: {e}")
			return None


# ─── Supabase Service Helpers ────────
async def list_all_workflows(limit: int = 100):
	"""Fetch all workflows from Supabase database in read-only mode."""
	if not supabase:
		raise Exception("Supabase client not configured")
		
	return supabase.from_("workflows")           \
	               .select("*")                  \
	               .order("created_at", desc=True) \
	               .limit(limit)                 \
	               .execute().data


async def get_workflow_by_id(workflow_id: str):
	"""Get single workflow by UUID with proper error handling."""
	if not supabase:
		raise Exception("Supabase client not configured")
	
	try:
		result = supabase.from_("workflows") \
		               .select("*") \
		               .eq("id", workflow_id) \
		               .execute()
		
		# Check if any data was returned
		if not result.data or len(result.data) == 0:
			return None
			
		return result.data[0]  # Return the first (and only) result
		
	except Exception as e:
		# Log the error but don't expose internal details
		print(f"Database error retrieving workflow {workflow_id}: {e}")
		raise Exception("Failed to retrieve workflow")


def sanitize_content(content: str | None) -> str:
	"""Sanitize content to prevent database Unicode errors."""
	if not content:
		return content or ""
	
	# Remove null bytes and other problematic characters
	content = content.replace('\x00', '')  # Remove null bytes
	content = content.replace('\u0000', '')  # Remove Unicode null
	
	# Limit length to prevent overly long content
	if len(content) > 10000:
		content = content[:10000] + "... (truncated)"
	
	# Escape or remove problematic Unicode sequences
	try:
		# Test if content can be safely stored
		content.encode('utf-8')
		return content
	except UnicodeEncodeError:
		# Fallback: remove non-UTF-8 characters
		return content.encode('utf-8', 'ignore').decode('utf-8')


async def build_workflow_from_recording_data(recording_data: dict, user_goal: str, workflow_name: Optional[str] = None):
	"""Build a workflow from recording JSON data using BuilderService."""
	try:
		# Initialize the builder service with the LLM instance
		if not hasattr(build_workflow_from_recording_data, '_builder_service'):
			from langchain_openai import ChatOpenAI
			llm_instance = ChatOpenAI(model='gpt-4o')
			build_workflow_from_recording_data._builder_service = BuilderService(llm=llm_instance)
		
		builder_service = build_workflow_from_recording_data._builder_service
		
		# Validate and convert recording data to WorkflowDefinitionSchema
		from workflow_use.schema.views import WorkflowDefinitionSchema
		recording_schema = WorkflowDefinitionSchema.model_validate(recording_data)
		
		# Build the workflow using the builder service
		built_workflow = await builder_service.build_workflow(
			input_workflow=recording_schema,
			user_goal=user_goal,
			use_screenshots=False,  # Disabled for faster demo processing
			max_images=0  # No images for faster processing
		)
		
		# Use LLM-generated name first, fallback to provided name
		if not built_workflow.name or built_workflow.name.strip() == "":
			built_workflow.name = workflow_name or "New Workflow"
			
		# Set timestamps for steps that don't have them
		import time
		current_time = int(time.time() * 1000)  # Current time in milliseconds
		has_timestamp = False
		for step in built_workflow.steps:
			if hasattr(step, 'type') and step.type != 'agent' and hasattr(step, 'timestamp') and step.timestamp is not None:
				has_timestamp = True
				break
		if not has_timestamp:
			for step in built_workflow.steps:
				if hasattr(step, 'type') and step.type != 'agent' and hasattr(step, 'timestamp'):
					step.timestamp = current_time
		
		return built_workflow
		
	except Exception as e:
		print(f'Error building workflow from recording: {e}')
		raise Exception(f"Failed to build workflow: {str(e)}")


async def process_workflow_upload_async(job_id: str, recording_data: dict, user_goal: str, workflow_name: Optional[str] = None, owner_id: Optional[str] = None):
	"""Process workflow upload with improved error handling and granular progress updates."""
	import asyncio
	
	# Progress updater for granular progress during conversion
	async def update_progress_gradually(start_progress: int, end_progress: int, max_duration: float):
		"""Update progress every 10% with shorter intervals for responsiveness"""
		progress_points = list(range(start_progress + 10, end_progress, 10))  # [20, 30, 40, 50, 60, 70]
		if not progress_points:
			return
			
		# Update every 0.8 seconds for responsiveness
		update_interval = 0.8
		
		for target_progress in progress_points:
			await asyncio.sleep(update_interval)
			if job_id in workflow_jobs and workflow_jobs[job_id].progress < target_progress:
				workflow_jobs[job_id].progress = target_progress
				# Estimate remaining time based on current progress
				progress_ratio = target_progress / end_progress
				remaining_time = max(2, int(max_duration * (1 - progress_ratio)))
				workflow_jobs[job_id].estimated_remaining_seconds = remaining_time
	
	try:
		# Update job status: Starting conversion
		workflow_jobs[job_id].status = "processing"
		workflow_jobs[job_id].progress = 10
		workflow_jobs[job_id].estimated_remaining_seconds = 25
		
		# Step 1: Convert recording to workflow (this takes time)
		try:
			# Start gradual progress updates during conversion (10% → 80%)
			progress_task = asyncio.create_task(
				update_progress_gradually(start_progress=10, end_progress=80, max_duration=15)
			)
			
			# Run conversion and progress updates concurrently
			conversion_task = asyncio.create_task(build_workflow_from_recording_data(
				recording_data=recording_data,
				user_goal=user_goal,
				workflow_name=workflow_name
			))
			
			# Wait for conversion to complete
			built_workflow = await conversion_task
			
			# Cancel progress updater and set final conversion progress
			progress_task.cancel()
			try:
				await progress_task
			except asyncio.CancelledError:
				pass
			
			# Update progress: Conversion successful
			workflow_jobs[job_id].progress = 80
			workflow_jobs[job_id].estimated_remaining_seconds = 5
			
		except Exception as e:
			# Conversion failed
			workflow_jobs[job_id].status = "failed"
			workflow_jobs[job_id].error = f"Workflow conversion failed: {str(e)}"
			workflow_jobs[job_id].estimated_remaining_seconds = 0
			print(f"Workflow conversion failed for job {job_id}: {e}")
			return None
		
		# Step 2: Save to database with content sanitization
		try:
			if not supabase:
				raise Exception("Database not configured")
			
			# Gradual progress during database operations (80% → 100%)
			workflow_jobs[job_id].progress = 85
			workflow_jobs[job_id].estimated_remaining_seconds = 3
			await asyncio.sleep(0.3)  # Brief pause to make progress visible
			
			from datetime import datetime
			now = datetime.utcnow().isoformat()
			
			# Progress: Sanitizing content
			workflow_jobs[job_id].progress = 90
			workflow_jobs[job_id].estimated_remaining_seconds = 2
			await asyncio.sleep(0.2)  # Brief pause
			
			# Sanitize content before database insertion
			sanitized_steps = []
			for step in built_workflow.steps:
				step_dict = step.model_dump()
				# Remove or sanitize problematic Unicode characters
				if 'content' in step_dict and step_dict['content']:
					step_dict['content'] = sanitize_content(step_dict['content'])
				sanitized_steps.append(step_dict)
			
			# Progress: Inserting into database
			workflow_jobs[job_id].progress = 95
			workflow_jobs[job_id].estimated_remaining_seconds = 1
			await asyncio.sleep(0.2)  # Brief pause
			
			row = supabase.table("workflows").insert({
				"owner_id": owner_id,
				"name": sanitize_content(built_workflow.name),
				"version": built_workflow.version,
				"description": sanitize_content(built_workflow.description),
				"workflow_analysis": sanitize_content(built_workflow.workflow_analysis),
				"steps": sanitized_steps,
				"input_schema": [item.model_dump() for item in built_workflow.input_schema],
				"created_at": now,
				"updated_at": now
			}).execute().data[0]
			
			# Job completed successfully
			workflow_jobs[job_id].status = "completed" 
			workflow_jobs[job_id].progress = 100
			workflow_jobs[job_id].workflow_id = row["id"]
			workflow_jobs[job_id].estimated_remaining_seconds = 0
			
			return row["id"]
			
		except Exception as e:
			# Database save failed
			workflow_jobs[job_id].status = "failed"
			workflow_jobs[job_id].error = f"Database save failed: {str(e)}"
			workflow_jobs[job_id].estimated_remaining_seconds = 0
			print(f"Database save failed for job {job_id}: {e}")
			return None
		
	except Exception as e:
		# Unexpected error
		workflow_jobs[job_id].status = "failed"
		workflow_jobs[job_id].error = f"Unexpected error: {str(e)}"
		workflow_jobs[job_id].estimated_remaining_seconds = 0
		print(f"Unexpected error in job {job_id}: {e}")
		return None


async def start_workflow_upload_job(recording_data: dict, user_goal: str, workflow_name: Optional[str] = None, owner_id: Optional[str] = None) -> str:
	"""Start an async workflow upload job and return job ID."""
	job_id = str(uuid.uuid4())
	
	# Initialize job status
	workflow_jobs[job_id] = WorkflowJobStatus(
		job_id=job_id,
		status="processing",
		progress=0,
		estimated_remaining_seconds=30
	)
	
	# Start background task (fire and forget)
	import asyncio
	asyncio.create_task(process_workflow_upload_async(job_id, recording_data, user_goal, workflow_name, owner_id))
	
	return job_id


def get_workflow_job_status(job_id: str) -> Optional[WorkflowJobStatus]:
	"""Get the current status of a workflow upload job."""
	return workflow_jobs.get(job_id)
