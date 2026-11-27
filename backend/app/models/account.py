"""
Dreamina Auto Register - 账号模型
"""

from datetime import datetime, date
from typing import Optional
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Date,
    DateTime,
    ForeignKey,
    Boolean,
)
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.core.timezone import get_beijing_time


class Account(Base):
    """注册账号表"""

    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 账号信息
    email = Column(
        String(255), unique=True, index=True, nullable=False, comment="邮箱地址"
    )
    password = Column(String(255), nullable=False, comment="Dreamina 密码")
    domain_id = Column(Integer, ForeignKey("email_domains.id"), comment="所属域名ID")

    # 核心目标：SessionId
    session_id = Column(String(512), comment="Dreamina sessionId")
    full_cookie = Column(Text, comment="完整 Cookie JSON")
    all_tokens = Column(Text, comment="所有提取到的 token JSON")
    browser_state_path = Column(String(512), comment="浏览器登录态文件路径")
    fingerprint_json = Column(Text, comment="浏览器指纹 JSON（登录时复用）")
    registration_browser_profile = Column(String(64), index=True, comment="注册浏览器画像")
    registration_browser_version = Column(String(32), comment="注册浏览器版本")

    # 状态
    status = Column(
        String(20),
        default="pending",
        index=True,
        comment="状态: pending/registering/success/failed/banned",
    )
    failure_reason = Column(String(512), comment="失败原因")
    last_login_status = Column(String(20), comment="最近一次注册结果: success/failed")

    # 注册信息
    birth_date = Column(Date, comment="出生日期")
    proxy_node_name = Column(String(255), comment="使用的代理节点名称")
    registration_ip = Column(String(64), unique=True, index=True, comment="注册期间唯一出口IP")
    registration_asn = Column(String(128), index=True, comment="注册出口 IP 的 ASN")
    registration_proxy_key = Column(String(512), comment="注册期间固定代理标识")
    region = Column(String(50), comment="账号所属区域")
    screenshot_path = Column(String(512), comment="截图路径")

    # 积分与健康状态
    credits_total = Column(Integer, default=0, comment="总积分")
    credits_gift = Column(Integer, default=0, comment="赠送积分")
    credits_purchase = Column(Integer, default=0, comment="购买积分")
    credits_vip = Column(Integer, default=0, comment="VIP积分")
    health_status = Column(
        String(20),
        default="unknown",
        comment="健康状态: healthy/expired/banned/unknown",
    )
    last_credit_check_at = Column(DateTime, comment="最近积分检查时间")
    last_checkin_at = Column(DateTime, comment="最近签到时间")

    # 账号优惠资格（Dreamina 订阅价格表协议检测）
    offer_status = Column(
        String(20), default="unchecked", comment="优惠状态: unchecked/checking/eligible/ineligible/error"
    )
    offer_product_id = Column(String(255), comment="命中的优惠商品ID")
    offer_price_amount = Column(Integer, comment="优惠价（最小货币单位）")
    offer_origin_price_amount = Column(Integer, comment="原价（最小货币单位）")
    offer_currency_code = Column(String(16), comment="优惠币种")
    offer_discount_percent = Column(Integer, comment="折扣百分比")
    offer_checked_at = Column(DateTime, comment="最近优惠检测时间")
    offer_error = Column(String(512), comment="优惠检测错误")

    # 验证状态
    is_valid = Column(
        String(20), default="unverified", comment="验证状态: valid/invalid/unverified"
    )
    last_verified_at = Column(DateTime, comment="最近验证时间")

    # 内容生成池
    gen_enabled = Column(Boolean, default=False, comment="内容生成池启用状态")
    gen_enabled_at = Column(DateTime, comment="内容生成池启用时间")
    gen_last_used_at = Column(DateTime, comment="内容生成池最近使用时间")
    gen_locked_until = Column(DateTime, comment="内容生成池锁定截止时间")
    gen_auto_disabled_reason = Column(String(255), comment="内容生成池自动停用原因")

    # 任务关联
    task_id = Column(
        String(36), ForeignKey("task_records.task_id"), comment="关联任务ID"
    )
    retry_count = Column(Integer, default=0, comment="重试次数")

    # 时间戳
    created_at = Column(DateTime, default=get_beijing_time, comment="创建时间")
    updated_at = Column(
        DateTime,
        default=get_beijing_time,
        onupdate=get_beijing_time,
        comment="更新时间",
    )

    # 关系
    domain = relationship("EmailDomain", back_populates="accounts")
    task = relationship(
        "TaskRecord",
        back_populates="accounts",
        primaryjoin="Account.task_id==TaskRecord.task_id",
        foreign_keys="Account.task_id",
    )

    def __repr__(self):
        return f"<Account(id={self.id}, email={self.email}, status={self.status})>"
