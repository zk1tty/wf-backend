import asyncio
from pathlib import Path

# Ensure langchain-openai is installed and OPENAI_API_KEY is set
from langchain_openai import ChatOpenAI

from workflow_use.builder.service import BuilderService
from workflow_use.workflow.service import Workflow

# Instantiate the LLM and the service directly
llm_instance = ChatOpenAI(model='gpt-4o')  # Or your preferred model
builder_service = BuilderService(llm=llm_instance)


async def test_run_workflow():
	"""
	Tests that the workflow is built correctly from a JSON file path.
	"""
	path = Path(__file__).parent / 'tmp' / 'recording.workflow.json'

	workflow = Workflow.load_from_file(path)
	result = await workflow.run({'model': '12'})
	print(result)


if __name__ == '__main__':
	asyncio.run(test_run_workflow())
