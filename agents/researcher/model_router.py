# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Dynamic model routing with fallback support for ADK agents.

Allows configuring per-agent models and fallback routing dictionaries in .env.
If a configured model is unavailable (e.g. high traffic, 429 quota, 503 unavailable),
it automatically fails over to the models specified in the routing dictionary,
and finally to the default fallback model.
"""

import ast
import json
import logging
import os
from pathlib import Path
from typing import AsyncGenerator, List, Dict, Optional

from google.adk.models.base_llm import BaseLlm, BaseLlmConnection
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.models.registry import LLMRegistry

logger = logging.getLogger(__name__)

DEFAULT_FALLBACK_MODEL = "gemini-2.5-flash"


def load_env() -> None:
    """Load key-value pairs from .env into os.environ if not already present."""
    current = Path(__file__).resolve().parent
    # Search in current, parent, and parent's parent directory
    search_paths = [current, current.parent, current.parent.parent]
    for p in search_paths:
        env_file = p / ".env"
        if env_file.exists():
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key and key not in os.environ:
                        os.environ[key] = val
            break


def parse_model_routing(raw: Optional[str]) -> Dict[str, List[str]]:
    """Parse the MODEL_ROUTING configuration string into a dict of model lists.

    Supports JSON format as well as Python literal dict format.
    Values can be lists of strings or comma-separated strings.

    Example input:
        '{"gemini-8-flash": ["gemini-2.5-pro", "gemini-2.0-flash"]}'
    """
    if not raw or not raw.strip():
        return {}

    raw = raw.strip()
    data = None
    try:
        data = json.loads(raw)
    except Exception:
        try:
            data = ast.literal_eval(raw)
        except Exception:
            logger.warning("Could not parse MODEL_ROUTING config: %s", raw)
            return {}

    if not isinstance(data, dict):
        return {}

    result: Dict[str, List[str]] = {}
    for k, v in data.items():
        key = str(k).strip()
        if isinstance(v, list):
            result[key] = [str(m).strip() for m in v if str(m).strip()]
        elif isinstance(v, str):
            result[key] = [m.strip() for m in v.split(",") if m.strip()]
    return result


class RoutingLlm(BaseLlm):
    """ADK BaseLlm implementation that dynamically routes requests across candidate models."""

    model: str
    candidate_models: List[str] = []
    agent_name: str = ""

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        """Attempt content generation with candidate models in priority order.

        If a model fails (e.g. high traffic, 429 quota, 503 unavailable),
        it routes to the next candidate model in the sequence.
        """
        last_error: Optional[Exception] = None
        candidates = self.candidate_models if self.candidate_models else [self.model]

        for i, candidate in enumerate(candidates):
            logger.info(
                "[%s] Invoking model '%s' (candidate %d/%d)...",
                self.agent_name,
                candidate,
                i + 1,
                len(candidates),
            )
            yielded_any = False
            try:
                underlying_llm = LLMRegistry.new_llm(candidate)
                candidate_request = llm_request.model_copy(deep=True)
                candidate_request.model = candidate

                async for response in underlying_llm.generate_content_async(
                    candidate_request, stream=stream
                ):
                    yielded_any = True
                    yield response

                # Successful generation, return immediately
                return

            except Exception as e:
                last_error = e
                if yielded_any:
                    # Chunks were already delivered to consumer; cannot safely restart stream
                    logger.error(
                        "[%s] Error occurred after streaming started on model '%s': %s",
                        self.agent_name,
                        candidate,
                        e,
                    )
                    raise

                logger.warning(
                    "[%s] Model '%s' unavailable or encountered error: %s. "
                    "Routing to next fallback option...",
                    self.agent_name,
                    candidate,
                    e,
                )
                continue

        logger.error(
            "[%s] All candidate models (%s) failed for agent.",
            self.agent_name,
            candidates,
        )
        if last_error:
            raise last_error
        raise RuntimeError(f"No available models for agent '{self.agent_name}'.")

    def connect(self, llm_request: LlmRequest) -> BaseLlmConnection:
        """Create a live connection to the primary LLM."""
        underlying_llm = LLMRegistry.new_llm(self.model)
        return underlying_llm.connect(llm_request)


def get_agent_model(agent_name: str) -> RoutingLlm:
    """Resolve and construct the routed model for a specific agent based on .env configuration.

    Order of priority:
    1. Primary model configured for this agent (e.g. RESEARCHER_MODEL, JUDGE_MODEL)
    2. Route models defined in MODEL_ROUTING dictionary for this model or agent
    3. Global fallback model (MODEL, default gemini-2.5-flash)

    Args:
        agent_name: Name of the agent (e.g. 'researcher', 'judge', 'content_builder').

    Returns:
        A RoutingLlm configured with the candidate models sequence.
    """
    load_env()

    # 1. Resolve agent's configured primary model
    env_var_name = f"{agent_name.upper()}_MODEL"
    default_model = os.environ.get("MODEL", DEFAULT_FALLBACK_MODEL)
    configured_model = os.environ.get(env_var_name) or default_model

    # 2. Resolve fallback routes from MODEL_ROUTING dictionary
    routing_dict = parse_model_routing(os.environ.get("MODEL_ROUTING", "{}"))

    # Check routing by model name (e.g. 'gemini-8-flash') and agent name (e.g. 'judge')
    model_routes = routing_dict.get(configured_model, [])
    agent_routes = routing_dict.get(agent_name.lower(), [])

    # 3. Assemble candidate models list with deduplication while preserving order
    candidate_models: List[str] = []
    seen = set()

    for m in [configured_model] + model_routes + agent_routes + [default_model]:
        m_clean = m.strip()
        if m_clean and m_clean not in seen:
            candidate_models.append(m_clean)
            seen.add(m_clean)

    logger.info(
        "Agent '%s' configured with model '%s' and candidate route: %s",
        agent_name,
        configured_model,
        candidate_models,
    )

    return RoutingLlm(
        model=configured_model,
        candidate_models=candidate_models,
        agent_name=agent_name,
    )
