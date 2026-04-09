"""Chat endpoint — handles user messages and streams agent responses."""

import json
from uuid import uuid4

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import run_agent_stream
from app.memory.database import Conversation, Message, get_session
from app.schemas import MessageRequest

router = APIRouter()


async def _get_or_create_conversation(
    conversation_id, session: AsyncSession
) -> Conversation:
    """Get existing conversation or create a new one."""
    if conversation_id:
        result = await session.execute(
            select(Conversation).where(Conversation.id == conversation_id)
        )
        conv = result.scalar_one_or_none()
        if conv:
            return conv

    conv = Conversation(id=uuid4())
    session.add(conv)
    await session.commit()
    return conv


async def _load_history(conversation_id, session: AsyncSession) -> list:
    """Load conversation history from DB as LangChain messages."""
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )
    messages = []
    for msg in result.scalars():
        if msg.role == "user":
            messages.append(HumanMessage(content=msg.content))
        elif msg.role == "assistant":
            messages.append(AIMessage(content=msg.content))
    return messages


@router.post("/chat")
async def chat(
    request: MessageRequest,
    session: AsyncSession = Depends(get_session),
):
    """Send a message to the agent and receive a streaming response (SSE)."""
    conv = await _get_or_create_conversation(request.conversation_id, session)
    history = await _load_history(conv.id, session)

    # Save user message
    user_msg = Message(
        conversation_id=conv.id,
        role="user",
        content=request.content,
    )
    session.add(user_msg)
    await session.commit()

    # Update conversation title from first message
    if len(history) == 0:
        conv.title = request.content[:100]
        await session.commit()

    async def event_stream():
        full_response = []
        async for event in run_agent_stream(
            user_message=request.content,
            conversation_history=history,
            conversation_id=conv.id,
        ):
            if event["event"] == "token":
                full_response.append(event["data"])

            sse_data = json.dumps(
                {
                    "event": event["event"],
                    "data": event["data"],
                    "conversation_id": str(conv.id),
                },
                ensure_ascii=False,
            )
            yield f"data: {sse_data}\n\n"

        # Save assistant response to DB
        assistant_content = "".join(full_response)
        if assistant_content:
            assistant_msg = Message(
                conversation_id=conv.id,
                role="assistant",
                content=assistant_content,
            )
            session.add(assistant_msg)
            await session.commit()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Conversation-Id": str(conv.id),
        },
    )
