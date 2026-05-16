import sys

sys.path.append("..")

from typing import Dict, Any, Tuple, List, Optional
from langchain_core.messages import (
    AIMessage,
    SystemMessage,
    BaseMessage,
    ToolMessage,
)
import json
from src.agents.tools.prompt_templates import SYSTEM_AGENT_PROMPT, SYSTEM_ERROR_PROMPT


class Agent:
    def __init__(
        self,
        base_llm,
        tools: List[Any],
        *,
        tool_choice_required: bool = False,
        bind_tools_kwargs: Optional[Dict[str, Any]] = None,
    ):
        self.base_llm = base_llm
        self.tools = tools
        self.tools_by_name = {t.name: t for t in tools}
        self.llm_with_tools = self.base_llm.bind_tools(self.tools)

    async def _decide_tool_async(
        self, messages: List[BaseMessage]
    ) -> Tuple[Optional[str], Dict[str, Any], AIMessage, Optional[dict]]:
        msgs: List[BaseMessage] = [
            SystemMessage(content=SYSTEM_AGENT_PROMPT),
            *messages,
        ]
        ai: AIMessage = await self.llm_with_tools.ainvoke(msgs)
        tcalls = getattr(ai, "tool_calls", None)

        if not tcalls:
            return None, {}, ai, None

        call = tcalls[0]
        name = call.get("name")
        args = call.get("args") or {}

        if name not in self.tools_by_name:
            return None, {}, ai, call

        return name, args, ai, call

    async def _chatting(self, messages: List[BaseMessage]) -> Dict[str, Any]:
        reply: AIMessage = await self.base_llm.ainvoke(
            [SystemMessage(content=SYSTEM_AGENT_PROMPT), *messages]
        )
        return {"type": "text", "content": reply.content, "error": ""}

    async def chat(self, messages: List[BaseMessage]) -> Dict[str, Any]:
        from src.common.logger import get_logger

        logger = get_logger(__name__)

        logger.info(f"Agent.chat starting with {len(messages)} messages")

        logger.info("Deciding which tool to use")
        name, args, ai_msg, call = await self._decide_tool_async(messages)
        logger.info(
            f"Tool decision result: name={name}, args_keys={list(args.keys()) if args else None}"
        )

        if not name:
            logger.info("No tool selected, using direct chatting")
            result = await self._chatting(messages)
            logger.info(f"Chatting result: {result}")
            return result

        logger.info(f"Using tool: {name}")
        tool = self.tools_by_name[name]
        logger.info(f"Tool object: {tool}")

        logger.info(f"Invoking tool with args: {args}")
        result = await tool.ainvoke(args)
        logger.info(f"Tool result type: {type(result)}")
        logger.info(
            f"Tool result keys: {list(result.keys()) if isinstance(result, dict) else 'Not a dict'}"
        )
        logger.info(f"Tool result preview: {str(result)[:300]}...")

        err = result.get("error") or ""
        if err:
            logger.warning(f"Tool returned error: {err}")
            tool_err_msg = ToolMessage(
                content=json.dumps(
                    {"error": err, "tool": name, "args": args}, ensure_ascii=False
                ),
                tool_call_id=call.get("id", "tool_call_0") if call else "tool_call_0",
            )
            logger.info("Invoking LLM for error handling")
            reply: AIMessage = await self.base_llm.ainvoke(
                [
                    SystemMessage(content=SYSTEM_ERROR_PROMPT),
                    *messages,
                    ai_msg,
                    tool_err_msg,
                ]
            )
            error_result = {"type": "text", "content": reply.content, "error": err}
            logger.info(f"Error handling result: {error_result}")
            return error_result

        logger.info(f"Agent.chat completed successfully, returning: {result}")
        return result
