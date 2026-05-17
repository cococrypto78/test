import asyncio
import time
from typing import Any, Optional
from anthropic import AsyncAnthropic
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from config.settings import settings
from utils.logger import logger


class BaseAgent:
    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._last_call_time: float = 0
        self._min_call_interval: float = 1.0

    async def _enforce_rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_call_time
        if elapsed < self._min_call_interval:
            await asyncio.sleep(self._min_call_interval - elapsed)
        self._last_call_time = time.monotonic()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=30),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    async def think(
        self,
        system_prompt: str,
        user_message: str,
        tools: Optional[list] = None,
        temperature: float = 0.7,
    ) -> dict:
        await self._enforce_rate_limit()
        kwargs = {
            "model": settings.claude_model,
            "max_tokens": settings.claude_max_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_message}],
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools

        logger.debug(f"[{self.agent_name}] Calling Claude API")
        response = await self.client.messages.create(**kwargs)

        result = {
            "text": "",
            "tool_calls": [],
            "stop_reason": response.stop_reason,
        }

        for block in response.content:
            if block.type == "text":
                result["text"] += block.text
            elif block.type == "tool_use":
                result["tool_calls"].append({
                    "name": block.name,
                    "input": block.input,
                    "id": block.id,
                })

        return result

    async def think_with_tools(
        self,
        system_prompt: str,
        user_message: str,
        tools: list,
        tool_executor: dict,
        max_rounds: int = 5,
    ) -> str:
        messages = [{"role": "user", "content": user_message}]
        full_response = ""

        for _ in range(max_rounds):
            await self._enforce_rate_limit()
            response = await self.client.messages.create(
                model=settings.claude_model,
                max_tokens=settings.claude_max_tokens,
                system=system_prompt,
                messages=messages,
                tools=tools,
                temperature=0.7,
            )

            assistant_content = []
            for block in response.content:
                if block.type == "text":
                    full_response += block.text
                    assistant_content.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    assistant_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })

            messages.append({"role": "assistant", "content": assistant_content})

            if response.stop_reason != "tool_use":
                break

            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    executor_fn = tool_executor.get(block.name)
                    if executor_fn:
                        tool_result = await executor_fn(**block.input)
                    else:
                        tool_result = {"error": f"Unknown tool: {block.name}"}
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(tool_result),
                    })

            messages.append({"role": "user", "content": tool_results})

        return full_response

    async def log_action(
        self,
        action: str,
        details: Optional[dict] = None,
        prospect_id: Optional[int] = None,
        session=None,
    ) -> None:
        logger.info(f"[{self.agent_name}] {action} | prospect_id={prospect_id} | {details or {}}")
        if session:
            from crm.repository import ProspectRepository
            repo = ProspectRepository(session)
            await repo.add_log(
                agent_name=self.agent_name,
                action=action,
                prospect_id=prospect_id,
                details=details,
            )
