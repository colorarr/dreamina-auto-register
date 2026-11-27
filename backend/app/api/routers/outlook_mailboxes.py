"""
Dreamina Auto Register - Outlook 邮箱管理 API 路由
"""
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.models.outlook_mailbox import OutlookMailbox
from app.services.mailbox_verification import parse_mailbox_import_line
from app.schemas import (
    OutlookMailboxCreate,
    OutlookMailboxBatchCreate,
    OutlookMailboxUpdate,
    OutlookMailboxResponse,
    PaginatedResponse,
    MessageResponse,
)

router = APIRouter()


@router.get("", response_model=PaginatedResponse)
async def list_outlook_mailboxes(
    page: int = 1,
    page_size: int = 50,
    db: AsyncSession = Depends(get_db)
):
    """获取 Outlook 邮箱列表（分页）"""
    # 统计总数
    count_stmt = select(func.count(OutlookMailbox.id))
    total = (await db.execute(count_stmt)).scalar() or 0

    # 查询数据
    stmt = (
        select(OutlookMailbox)
        .order_by(OutlookMailbox.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    items = result.scalars().all()

    return PaginatedResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[OutlookMailboxResponse.model_validate(item) for item in items],
    )


@router.post("/batch", response_model=MessageResponse)
async def batch_create_outlook_mailboxes(
    data: OutlookMailboxBatchCreate,
    db: AsyncSession = Depends(get_db)
):
    """批量导入邮箱池；通用 API 行格式：邮箱----HTTPS 取码地址。"""
    entries = []
    invalid = 0
    for raw in data.emails:
        if not raw.strip():
            continue
        try:
            entries.append(parse_mailbox_import_line(raw, data.provider_type))
        except ValueError:
            invalid += 1
    if not entries:
        raise HTTPException(status_code=400, detail="没有可导入的有效邮箱行")

    stmt = select(OutlookMailbox.email)
    existing = {row[0].casefold() for row in (await db.execute(stmt)).all()}
    new_mailboxes = []
    duplicate = 0
    for entry in entries:
        key = entry.email.casefold()
        if key in existing:
            duplicate += 1
            continue
        existing.add(key)
        new_mailboxes.append(OutlookMailbox(
            email=entry.email,
            provider_type=data.provider_type,
            code_url=entry.code_url,
            note=data.note,
            is_enabled=True,
            created_at=datetime.utcnow(),
        ))

    if new_mailboxes:
        db.add_all(new_mailboxes)
        await db.commit()

    added = len(new_mailboxes)
    return MessageResponse(
        message=f"成功导入 {added} 个邮箱，跳过 {duplicate} 个重复项、{invalid} 个无效项",
        success=True
    )


@router.patch("/{mailbox_id}", response_model=OutlookMailboxResponse)
async def update_outlook_mailbox(
    mailbox_id: int,
    data: OutlookMailboxUpdate,
    db: AsyncSession = Depends(get_db)
):
    """更新 Outlook 邮箱（启用/禁用、修改备注）"""
    stmt = select(OutlookMailbox).where(OutlookMailbox.id == mailbox_id)
    mailbox = (await db.execute(stmt)).scalar_one_or_none()
    if not mailbox:
        raise HTTPException(status_code=404, detail="邮箱不存在")

    if data.is_enabled is not None:
        mailbox.is_enabled = data.is_enabled
    if data.note is not None:
        mailbox.note = data.note

    await db.commit()
    await db.refresh(mailbox)
    return OutlookMailboxResponse.model_validate(mailbox)


@router.delete("/{mailbox_id}", response_model=MessageResponse)
async def delete_outlook_mailbox(
    mailbox_id: int,
    db: AsyncSession = Depends(get_db)
):
    """删除 Outlook 邮箱"""
    stmt = select(OutlookMailbox).where(OutlookMailbox.id == mailbox_id)
    mailbox = (await db.execute(stmt)).scalar_one_or_none()
    if not mailbox:
        raise HTTPException(status_code=404, detail="邮箱不存在")

    await db.delete(mailbox)
    await db.commit()
    return MessageResponse(message=f"邮箱 {mailbox.email} 已删除", success=True)
