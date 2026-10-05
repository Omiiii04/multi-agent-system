import pathlib
from google.adk.agents import Agent
from google.adk.skills import load_skill_from_dir
from google.adk.tools.skill_toolset import SkillToolset
from model_router import get_agent_model

model = get_agent_model("researcher")

skill_dir = pathlib.Path(__file__).parent / "skills"
researcher_skill = load_skill_from_dir(skill_dir)

researcher_toolset = SkillToolset(skills=[researcher_skill])

researcher = Agent(
    name="researcher",
    model=model,
    tools=[researcher_toolset],
)

root_agent = researcher
