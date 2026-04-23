"""Conversations management endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.database import Conversation, Message, get_session
from app.schemas import ConversationInfo

router = APIRouter()


@router.get("/conversations", response_model=list[ConversationInfo])
async def list_conversations(session: AsyncSession = Depends(get_session)):
    """List all conversations, most recent first."""
    result = await session.execute(
        select(
            Conversation.id,
            Conversation.title,
            Conversation.created_at,
            func.count(Message.id).label("message_count"),
        )
        .outerjoin(Message)
        .group_by(Conversation.id)
        .order_by(Conversation.updated_at.desc())
        .limit(50)
    )

    return [
        ConversationInfo(
            id=row.id,
            title=row.title,
            created_at=row.created_at,
            message_count=row.message_count,
        )
        for row in result
    ]


@router.get("/conversations/{conversation_id}/messages")
async def get_messages(
    conversation_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Get all messages in a conversation."""
    try:
        cid = UUID(conversation_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid conversation id") from exc

    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == cid)
        .order_by(Message.created_at)
    )
    messages = result.scalars().all()
    return [
        {
            "id": str(msg.id),
            "role": msg.role,
            "content": msg.content,
            "created_at": msg.created_at.isoformat(),
        }
        for msg in messages
    ]


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Delete a conversation and all its messages (browser context lives in conversation row)."""
    try:
        cid = UUID(conversation_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid conversation id") from exc

    conv = await session.get(Conversation, cid)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    await session.execute(delete(Message).where(Message.conversation_id == cid))
    await session.execute(delete(Conversation).where(Conversation.id == cid))
    await session.commit()
    return Response(status_code=204)
