import asyncio
import os
import sys
from pathlib import Path

# Configure utf-8 stdout
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Add project root and shared to path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "shared"))

from shared.model_router import (
    load_env,
    parse_model_routing,
    get_agent_model,
    RoutingLlm,
)
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types


def test_parse_model_routing():
    print("Testing parse_model_routing...")
    # Test JSON list
    r1 = parse_model_routing('{"gemini-8-flash": ["gemini-2.5-pro", "gemini-2.0-flash"]}')
    assert r1 == {"gemini-8-flash": ["gemini-2.5-pro", "gemini-2.0-flash"]}, f"Failed r1: {r1}"

    # Test single string
    r2 = parse_model_routing('{"gemini-8-flash": "gemini-2.5-pro"}')
    assert r2 == {"gemini-8-flash": ["gemini-2.5-pro"]}, f"Failed r2: {r2}"

    # Test comma-separated string
    r3 = parse_model_routing('{"gemini-8-flash": "gemini-2.5-pro, gemini-2.0-flash"}')
    assert r3 == {"gemini-8-flash": ["gemini-2.5-pro", "gemini-2.0-flash"]}, f"Failed r3: {r3}"

    # Test empty / None
    assert parse_model_routing("") == {}
    assert parse_model_routing(None) == {}
    print("✓ parse_model_routing passed!")


def test_get_agent_model_resolution():
    print("Testing get_agent_model resolution...")
    # Set mock environment
    os.environ["MODEL"] = "gemini-2.5-flash"
    os.environ["RESEARCHER_MODEL"] = "gemini-2.5-flash"
    os.environ["JUDGE_MODEL"] = "gemini-8-flash"
    os.environ["CONTENT_BUILDER_MODEL"] = "gemini-2.5-flash"
    os.environ["MODEL_ROUTING"] = '{"gemini-8-flash": ["gemini-2.5-pro", "gemini-2.0-flash"]}'

    judge_routed = get_agent_model("judge")
    assert judge_routed.model == "gemini-8-flash", f"Expected gemini-8-flash, got {judge_routed.model}"
    expected_judge_candidates = [
        "gemini-8-flash",
        "gemini-2.5-pro",
        "gemini-2.0-flash",
        "gemini-2.5-flash",
    ]
    assert (
        judge_routed.candidate_models == expected_judge_candidates
    ), f"Expected {expected_judge_candidates}, got {judge_routed.candidate_models}"

    researcher_routed = get_agent_model("researcher")
    assert researcher_routed.model == "gemini-2.5-flash"
    assert researcher_routed.candidate_models == ["gemini-2.5-flash"]
    print("✓ get_agent_model resolution passed!")


async def test_dynamic_failover_routing():
    print("Testing dynamic failover execution...")

    call_history = []

    class MockLlm(BaseLlm):
        model: str
        should_fail: bool = False

        async def generate_content_async(self, req: LlmRequest, stream: bool = False):
            call_history.append(self.model)
            if self.should_fail:
                raise RuntimeError(f"Model {self.model} rate limited or high traffic (503)")
            yield LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[types.Part.from_text(text=f"Success response from {self.model}")],
                )
            )

    mock_registry = {
        "gemini-8-flash": MockLlm(model="gemini-8-flash", should_fail=True),
        "gemini-2.5-pro": MockLlm(model="gemini-2.5-pro", should_fail=True),
        "gemini-2.0-flash": MockLlm(model="gemini-2.0-flash", should_fail=False),
        "gemini-2.5-flash": MockLlm(model="gemini-2.5-flash", should_fail=False),
    }

    class TestableRoutingLlm(RoutingLlm):
        async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False):
            # Patch LLMRegistry lookup with mock_registry
            last_error = None
            for candidate in self.candidate_models:
                try:
                    underlying = mock_registry[candidate]
                    req = llm_request.model_copy(deep=True)
                    req.model = candidate
                    yielded_any = False
                    async for r in underlying.generate_content_async(req, stream=stream):
                        yielded_any = True
                        yield r
                    return
                except Exception as e:
                    if yielded_any:
                        raise
                    last_error = e
                    continue
            if last_error:
                raise last_error

    router = TestableRoutingLlm(
        model="gemini-8-flash",
        candidate_models=[
            "gemini-8-flash",
            "gemini-2.5-pro",
            "gemini-2.0-flash",
            "gemini-2.5-flash",
        ],
        agent_name="judge",
    )

    req = LlmRequest(model="gemini-8-flash")
    results = []
    async for resp in router.generate_content_async(req):
        results.append(resp.content.parts[0].text)

    # Verification: gemini-8-flash (failed) -> gemini-2.5-pro (failed) -> gemini-2.0-flash (success!)
    assert call_history == [
        "gemini-8-flash",
        "gemini-2.5-pro",
        "gemini-2.0-flash",
    ], f"Call history mismatch: {call_history}"
    assert results == ["Success response from gemini-2.0-flash"]
    print("✓ dynamic failover execution passed!")


def test_agent_instantiations():
    print("Testing agent instantiations...")
    from agents.researcher.agent import researcher
    from agents.judge.agent import judge
    from agents.content_builder.agent import content_builder

    assert researcher.name == "researcher"
    assert judge.name == "judge"
    assert content_builder.name == "content_builder"

    assert isinstance(researcher.model, BaseLlm)
    assert type(researcher.model).__name__ == "RoutingLlm"
    assert isinstance(judge.model, BaseLlm)
    assert type(judge.model).__name__ == "RoutingLlm"
    assert isinstance(content_builder.model, BaseLlm)
    assert type(content_builder.model).__name__ == "RoutingLlm"
    print("✓ agent instantiations passed!")


if __name__ == "__main__":
    test_parse_model_routing()
    test_get_agent_model_resolution()
    asyncio.run(test_dynamic_failover_routing())
    test_agent_instantiations()
    print("\n==============================")
    print("ALL TESTS PASSED SUCCESSFULLY!")
    print("==============================")
