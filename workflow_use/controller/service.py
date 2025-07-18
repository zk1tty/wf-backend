import asyncio
import logging
import pyperclip

from browser_use import Browser
from browser_use.agent.views import ActionResult
from browser_use.controller.service import Controller
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import PromptTemplate
from playwright.async_api import Page

from workflow_use.controller.utils import get_best_element_handle, truncate_selector
from workflow_use.controller.views import (
	ClickElementDeterministicAction,
	InputTextDeterministicAction,
	KeyPressDeterministicAction,
	NavigationAction,
	PageExtractionAction,
	ScrollDeterministicAction,
	SelectDropdownOptionDeterministicAction,
	ClipboardCopyAction,
	ClipboardPasteAction,
)

logger = logging.getLogger(__name__)

DEFAULT_ACTION_TIMEOUT_MS = 1000

# List of default actions from browser_use.controller.service.Controller to disable
# todo: come up with a better way to filter out the actions (filter IN the actions would be much nicer in this case)
DISABLED_DEFAULT_ACTIONS = [
	'done',
	'search_google',
	'go_to_url',  # I am using this action from the main controller to avoid duplication
	'go_back',
	'wait',
	'click_element_by_index',
	'input_text',
	'save_pdf',
	'switch_tab',
	'open_tab',
	'close_tab',
	'extract_content',
	'scroll_down',
	'scroll_up',
	'send_keys',
	'scroll_to_text',
	'get_dropdown_options',
	'select_dropdown_option',
	'drag_drop',
	'get_sheet_contents',
	'select_cell_or_range',
	'get_range_contents',
	'clear_selected_range',
	'input_selected_cell_text',
	'update_range_contents',
]


class WorkflowController(Controller):
	def __init__(self, *args, **kwargs):
		# Pass the list of actions to exclude to the base class constructor
		super().__init__(*args, exclude_actions=DISABLED_DEFAULT_ACTIONS, **kwargs)
		self.__register_actions()

	def __register_actions(self):
		# Navigate to URL ------------------------------------------------------------
		@self.registry.action('Manually navigate to URL', param_model=NavigationAction)
		async def navigation(params: NavigationAction, browser_session: Browser) -> ActionResult:
			"""Navigate to the given URL with explicit rrweb re-injection support."""
			page = await browser_session.get_current_page()
			
			# Navigate to the URL
			logger.info(f"🔗 Navigating to: {params.url}")
			await page.goto(params.url, timeout=30000)
			
			# FIXED: Use domcontentloaded instead of networkidle for dynamic sites like Amazon
			try:
				await page.wait_for_load_state('domcontentloaded', timeout=10000)
				# Additional wait for dynamic content without networkidle
				await asyncio.sleep(3)
			except Exception as e:
				logger.warning(f"Load state wait failed: {e}, continuing anyway")
			
			# NEW: Check if RRWebRecorder is attached and perform explicit re-injection
			rrweb_recorder = getattr(browser_session, '_rrweb_recorder', None)
			
			if rrweb_recorder and hasattr(rrweb_recorder, 'reinject_after_navigation'):
				logger.info(f"🎬 Performing explicit rrweb re-injection after navigation to: {params.url}")
				try:
					success = await rrweb_recorder.reinject_after_navigation(params.url)
					if success:
						msg = f'🔗 Navigated to URL with rrweb re-injection: {params.url}'
						logger.info(f"✅ rrweb re-injection successful for: {params.url}")
					else:
						msg = f'🔗 Navigated to URL (rrweb re-injection failed): {params.url}'
						logger.warning(f"⚠️ rrweb re-injection failed for: {params.url}")
				except Exception as e:
					msg = f'🔗 Navigated to URL (rrweb re-injection error): {params.url}'
					logger.error(f"❌ rrweb re-injection error for {params.url}: {e}")
			else:
				# Standard navigation without rrweb
				msg = f'🔗 Navigated to URL: {params.url}'

			logger.info(msg)
			return ActionResult(extracted_content=msg, include_in_memory=True)

		# Click element by CSS selector --------------------------------------------------

		@self.registry.action(
			'Click element by all available selectors',
			param_model=ClickElementDeterministicAction,
		)
		async def click(params: ClickElementDeterministicAction, browser_session: Browser) -> ActionResult:
			"""Click the first element matching *params.cssSelector* with fallback mechanisms."""
			page = await browser_session.get_current_page()
			original_selector = params.cssSelector

			try:
				locator, selector_used = await get_best_element_handle(
					page,
					params.cssSelector,
					params,
					timeout_ms=DEFAULT_ACTION_TIMEOUT_MS,
				)
				await locator.click(force=True)

				msg = f'🖱️  Clicked element with CSS selector: {truncate_selector(selector_used)} (original: {truncate_selector(original_selector)})'
				logger.info(msg)
				return ActionResult(extracted_content=msg, include_in_memory=True)
			except Exception as e:
				error_msg = f'Failed to click element. Original selector: {truncate_selector(original_selector)}. Error: {str(e)}'
				logger.error(error_msg)
				raise Exception(error_msg)

		# Input text into element --------------------------------------------------------
		@self.registry.action(
			'Input text into an element by all available selectors',
			param_model=InputTextDeterministicAction,
		)
		async def input(
			params: InputTextDeterministicAction,
			browser_session: Browser,
			has_sensitive_data: bool = False,
		) -> ActionResult:
			"""Fill text into the element located with *params.cssSelector*."""
			page = await browser_session.get_current_page()
			original_selector = params.cssSelector

			try:
				locator, selector_used = await get_best_element_handle(
					page,
					params.cssSelector,
					params,
					timeout_ms=DEFAULT_ACTION_TIMEOUT_MS,
				)

				# Check if it's a SELECT element
				is_select = await locator.evaluate('(el) => el.tagName === "SELECT"')
				if is_select:
					return ActionResult(
						extracted_content='Ignored input into select element',
						include_in_memory=True,
					)

				# Add a small delay and click to ensure the element is focused
				await locator.fill(params.value)
				await asyncio.sleep(0.5)
				await locator.click(force=True)
				await asyncio.sleep(0.5)

				msg = f'⌨️  Input "{params.value}" into element with CSS selector: {truncate_selector(selector_used)} (original: {truncate_selector(original_selector)})'
				logger.info(msg)
				return ActionResult(extracted_content=msg, include_in_memory=True)
			except Exception as e:
				error_msg = f'Failed to input text. Original selector: {truncate_selector(original_selector)}. Error: {str(e)}'
				logger.error(error_msg)
				raise Exception(error_msg)

		# Select dropdown option ---------------------------------------------------------
		@self.registry.action(
			'Select dropdown option by all available selectors and visible text',
			param_model=SelectDropdownOptionDeterministicAction,
		)
		async def select_change(params: SelectDropdownOptionDeterministicAction, browser_session: Browser) -> ActionResult:
			"""Select dropdown option whose visible text equals *params.value*."""
			page = await browser_session.get_current_page()
			original_selector = params.cssSelector

			try:
				locator, selector_used = await get_best_element_handle(
					page,
					params.cssSelector,
					params,
					timeout_ms=DEFAULT_ACTION_TIMEOUT_MS,
				)

				await locator.select_option(label=params.selectedText)

				msg = f'Selected option "{params.selectedText}" in dropdown {truncate_selector(selector_used)} (original: {truncate_selector(original_selector)})'
				logger.info(msg)
				return ActionResult(extracted_content=msg, include_in_memory=True)
			except Exception as e:
				error_msg = f'Failed to select option. Original selector: {truncate_selector(original_selector)}. Error: {str(e)}'
				logger.error(error_msg)
				raise Exception(error_msg)

		# Key press action ------------------------------------------------------------
		@self.registry.action(
			'Press key on element by all available selectors',
			param_model=KeyPressDeterministicAction,
		)
		async def key_press(params: KeyPressDeterministicAction, browser_session: Browser) -> ActionResult:
			"""Press *params.key* on the element identified by *params.cssSelector*."""
			page = await browser_session.get_current_page()
			original_selector = params.cssSelector

			try:
				locator, selector_used = await get_best_element_handle(page, params.cssSelector, params, timeout_ms=5000)

				await locator.press(params.key)

				msg = f"🔑  Pressed key '{params.key}' on element with CSS selector: {truncate_selector(selector_used)} (original: {truncate_selector(original_selector)})"
				logger.info(msg)
				return ActionResult(extracted_content=msg, include_in_memory=True)
			except Exception as e:
				error_msg = f'Failed to press key. Original selector: {truncate_selector(original_selector)}. Error: {str(e)}'
				logger.error(error_msg)
				raise Exception(error_msg)

		# Scroll action --------------------------------------------------------------
		@self.registry.action('Scroll page', param_model=ScrollDeterministicAction)
		async def scroll(params: ScrollDeterministicAction, browser_session: Browser) -> ActionResult:
			"""Scroll the page by the given x/y pixel offsets."""
			page = await browser_session.get_current_page()
			await page.evaluate(f'window.scrollBy({params.scrollX}, {params.scrollY});')
			msg = f'📜  Scrolled page by (x={params.scrollX}, y={params.scrollY})'
			logger.info(msg)
			return ActionResult(extracted_content=msg, include_in_memory=True)

			# Extract content ------------------------------------------------------------

		@self.registry.action(
			'Extract page content to retrieve specific information from the page, e.g. all company names, a specific description, all information about, links with companies in structured format or simply links',
			param_model=PageExtractionAction,
		)
		async def extract_page_content(
			params: PageExtractionAction, browser_session: Browser, page_extraction_llm: BaseChatModel
		):
			page = await browser_session.get_current_page()
			import markdownify

			strip = ['a', 'img']

			content = markdownify.markdownify(await page.content(), strip=strip)

			# manually append iframe text into the content so it's readable by the LLM (includes cross-origin iframes)
			for iframe in page.frames:
				if iframe.url != page.url and not iframe.url.startswith('data:'):
					content += f'\n\nIFRAME {iframe.url}:\n'
					content += markdownify.markdownify(await iframe.content())

			prompt = 'Your task is to extract the content of the page. You will be given a page and a goal and you should extract all relevant information around this goal from the page. If the goal is vague, summarize the page. Respond in json format. Extraction goal: {goal}, Page: {page}'
			template = PromptTemplate(input_variables=['goal', 'page'], template=prompt)
			try:
				output = await page_extraction_llm.ainvoke(template.format(goal=params.goal, page=content))
				msg = f'📄  Extracted from page\n: {output.content}\n'
				logger.info(msg)
				return ActionResult(extracted_content=msg, include_in_memory=True)
			except Exception as e:
				logger.debug(f'Error extracting content: {e}')
				msg = f'📄  Extracted from page\n: {content}\n'
				logger.info(msg)
				return ActionResult(extracted_content=msg)

		# === CLIPBOARD OPERATIONS (Simplified with pyperclip) ===

		@self.registry.action(
			'Copy content to clipboard from element',
			param_model=ClipboardCopyAction,
		)
		async def clipboard_copy(params: ClipboardCopyAction, browser_session: Browser) -> ActionResult:
			"""Copy content to system clipboard using pyperclip."""
			page = await browser_session.get_current_page()
			
			try:
				content_to_copy = params.content
				
				# If CSS selector is provided, get content from that element
				if params.cssSelector:
					try:
						locator, selector_used = await get_best_element_handle(
							page, params.cssSelector, params, timeout_ms=DEFAULT_ACTION_TIMEOUT_MS
						)
						# Get text content or value from the element
						element_content = await locator.evaluate('(el) => el.value || el.textContent || el.innerText')
						if element_content:
							content_to_copy = element_content
					except Exception as e:
						logger.warning(f'Could not get content from element {params.cssSelector}: {e}')
				
				# Copy to system clipboard using pyperclip
				pyperclip.copy(content_to_copy)
				
				msg = f'📋  Copied to clipboard: {content_to_copy[:100]}{"..." if len(content_to_copy) > 100 else ""}'
				logger.info(msg)
				return ActionResult(extracted_content=msg, include_in_memory=True)
				
			except Exception as e:
				error_msg = f'Failed to copy to clipboard: {str(e)}'
				logger.error(error_msg)
				raise Exception(error_msg)

		@self.registry.action(
			'Paste content from clipboard to specified element',
			param_model=ClipboardPasteAction,
		)
		async def clipboard_paste(params: ClipboardPasteAction, browser_session: Browser) -> ActionResult:
			"""Paste content from system clipboard to the specified element."""
			page = await browser_session.get_current_page()
			
			try:
				# Get content from system clipboard
				clipboard_content = pyperclip.paste()
				
				# Use provided content or clipboard content
				content_to_paste = params.content if params.content else clipboard_content
				
				# Get the target element
				locator, selector_used = await get_best_element_handle(
					page, params.cssSelector, params, timeout_ms=DEFAULT_ACTION_TIMEOUT_MS
				)
				
				# Focus the element and type the content
				await locator.focus()
				await asyncio.sleep(0.2)
				await locator.fill('')  # Clear existing content
				await page.keyboard.type(content_to_paste)
				
				msg = f'📋  Pasted to element {truncate_selector(selector_used)}: {content_to_paste[:100]}{"..." if len(content_to_paste) > 100 else ""}'
				logger.info(msg)
				return ActionResult(extracted_content=msg, include_in_memory=True)
				
			except Exception as e:
				error_msg = f'Failed to paste from clipboard: {str(e)}'
				logger.error(error_msg)
				raise Exception(error_msg)
