"""LangGraph ReAct agent graph — the core reasoning loop.

Architecture:
                  ┌───────────────┐
   user message → │  agent_node   │ ← LLM decides: answer or use tool?
                  └───────┬───────┘
                          │
                    ┌─────▼─────┐
                    │  router   │ ← has tool calls? / max iterations?
                    └─────┬─────┘
                   /             \\
            tool_calls          no tool_calls
                 /                     \\
     ┌──────────▼──────────┐     ┌─────▼─────┐
     │    tools_node       │     │    END     │
     │  (execute tools)    │     └───────────┘
     └──────────┬──────────┘
                │
                └──→ back to agent_node (loop)
"""

from typing import AsyncGenerator, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, StateGraph

from app.agent.llm import get_primary_llm
from app.agent.prompts import SYSTEM_PROMPT
from app.agent.state import AgentState
from app.tools.registry import get_all_tools


def _build_graph() -> StateGraph:
    """Build and compile the ReAct agent graph."""

    tools = get_all_tools()
    tools_by_name = {tool.name: tool for tool in tools}

    # Bind tools to the LLM so it can emit tool_calls
    llm = get_primary_llm().bind_tools(tools)

    # ---- Nodes ----

    async def agent_node(state: AgentState) -> AgentState:
        """Call the LLM with the current message history."""
        # Inject system prompt if not already present
        messages = state.messages
        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=SYSTEM_PROMPT)] + messages

        response = await llm.ainvoke(messages)
        state.messages.append(response)
        state.iteration += 1
        return state

    async def tools_node(state: AgentState) -> AgentState:
        """Execute tool calls from the last AI message."""
        last_message: AIMessage = state.messages[-1]

        for tool_call in last_message.tool_calls:
            tool = tools_by_name.get(tool_call["name"])
            if tool is None:
                result = f"Error: tool '{tool_call['name']}' not found."
            else:
                try:
                    result = await tool.ainvoke(tool_call["args"])
                except Exception as e:
                    result = f"Error executing {tool_call['name']}: {e}"

            state.messages.append(
                ToolMessage(content=str(result), tool_call_id=tool_call["id"])
            )
            state.tool_calls_log.append(
                {
                    "tool_name": tool_call["name"],
                    "tool_input": tool_call["args"],
                    "tool_output": str(result)[:2000],
                }
            )

        return state

    # ---- Router ----

    def router(state: AgentState) -> Literal["tools_node", "__end__"]:
        """Decide whether to call tools or finish."""
        last = state.messages[-1]

        # Safety: cap iterations
        if state.iteration >= state.max_iterations:
            return END

        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools_node"
        return END

    # ---- Build graph ----

    graph = StateGraph(AgentState)
    graph.add_node("agent_node", agent_node)
    graph.add_node("tools_node", tools_node)

    graph.set_entry_point("agent_node")
    graph.add_conditional_edges("agent_node", router)
    graph.add_edge("tools_node", "agent_node")  # loop back

    return graph.compile()


# Singleton compiled graph
agent_graph = _build_graph()


async def run_agent(
    user_message: str,
    conversation_history: list | None = None,
    conversation_id=None,
) -> AgentState:
    """Run the agent to completion and return the final state."""
    messages = list(conversation_history or [])
    messages.append(HumanMessage(content=user_message))

    initial_state = AgentState(
        messages=messages,
        conversation_id=conversation_id,
    )

    final_state = await agent_graph.ainvoke(initial_state)
    return final_state


async def run_agent_stream(
    user_message: str,
    conversation_history: list | None = None,
    conversation_id=None,
) -> AsyncGenerator[dict, None]:
    """Run the agent with streaming — yields events as they happen."""
    messages = list(conversation_history or [])
    messages.append(HumanMessage(content=user_message))

    initial_state = AgentState(
        messages=messages,
        conversation_id=conversation_id,
    )

    async for event in agent_graph.astream_events(initial_state, version="v2"):
        kind = event["event"]

        if kind == "on_chat_model_stream":
            chunk = event["data"]["chunk"]
            content = chunk.content
            if content:
                # Claude returns list of content blocks, OpenAI returns str
                if isinstance(content, list):
                    text = "".join(
                        block.get("text", "") if isinstance(block, dict) else str(block)
                        for block in content
                    )
                else:
                    text = str(content)
                if text:
                    yield {"event": "token", "data": text}

        elif kind == "on_tool_start":
            yield {
                "event": "tool_start",
                "data": event["name"],
            }

        elif kind == "on_tool_end":
            output = event.get("data", {})
            if hasattr(output, "content"):
                text = str(output.content)
            else:
                text = str(output)
            yield {
                "event": "tool_end",
                "data": text[:1000],
            }

    yield {"event": "done", "data": ""}
