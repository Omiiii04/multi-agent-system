import pathlib
from google.adk.agents import Agent
from google.adk.skills import load_skill_from_dir
from google.adk.tools.skill_toolset import SkillToolset
from model_router import get_agent_model

model = get_agent_model("content_builder")

# Load local skill folder
skill_dir = pathlib.Path(__file__).parent / "skills"
content_builder_skill = load_skill_from_dir(skill_dir)

# Wrap the local skill in a SkillToolset
content_builder_toolset = SkillToolset(skills=[content_builder_skill])

content_builder = Agent(
    name="content_builder",
    model=model,
    tools=[content_builder_toolset],
)

root_agent = content_builder
