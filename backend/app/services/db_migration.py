"""
Database migration helpers for lightweight schema updates.
"""

from sqlalchemy import text
from app.core.database import async_session_factory
import logging

logger = logging.getLogger(__name__)


async def ensure_proxy_node_columns():
    """Ensure proxy_nodes has external proxy columns."""
    columns = [
        ("host", "VARCHAR(255)"),
        ("port", "INTEGER"),
        ("username", "VARCHAR(255)"),
        ("password", "VARCHAR(255)"),
        ("protocol", "VARCHAR(20)"),
        ("source", "VARCHAR(20) DEFAULT 'clash'"),
    ]

    async with async_session_factory() as session:
        result = await session.execute(text("PRAGMA table_info(proxy_nodes)"))
        existing_cols = {row[1] for row in result.fetchall()}

        for col_name, col_def in columns:
            if col_name in existing_cols:
                continue
            try:
                await session.execute(
                    text(f"ALTER TABLE proxy_nodes ADD COLUMN {col_name} {col_def}")
                )
                logger.info(f"Added column proxy_nodes.{col_name}")
            except Exception as exc:
                logger.error(f"Failed to add column {col_name}: {exc}")

        await session.commit()


async def ensure_accounts_login_status_column():
    """Ensure accounts has last_login_status column for consistency checks."""
    async with async_session_factory() as session:
        result = await session.execute(text("PRAGMA table_info(accounts)"))
        existing_cols = {row[1] for row in result.fetchall()}

        if "last_login_status" not in existing_cols:
            try:
                await session.execute(
                    text(
                        "ALTER TABLE accounts ADD COLUMN last_login_status VARCHAR(20)"
                    )
                )
                logger.info("Added column accounts.last_login_status")
                await session.commit()
            except Exception as exc:
                logger.error(f"Failed to add accounts.last_login_status: {exc}")


async def ensure_task_records_email_source_column():
    """Ensure task_records has email_source column for outlook mode support."""
    async with async_session_factory() as session:
        result = await session.execute(text("PRAGMA table_info(task_records)"))
        existing_cols = {row[1] for row in result.fetchall()}

        if "email_source" not in existing_cols:
            try:
                await session.execute(
                    text(
                        "ALTER TABLE task_records ADD COLUMN email_source VARCHAR(20) DEFAULT 'cloudflare'"
                    )
                )
                logger.info("Added column task_records.email_source")
                await session.commit()
            except Exception as exc:
                logger.error(f"Failed to add task_records.email_source: {exc}")


async def ensure_task_records_concurrency_column():
    """Ensure task_records has per-batch concurrency."""
    async with async_session_factory() as session:
        result = await session.execute(text("PRAGMA table_info(task_records)"))
        existing_cols = {row[1] for row in result.fetchall()}
        if "concurrency" not in existing_cols:
            await session.execute(
                text("ALTER TABLE task_records ADD COLUMN concurrency INTEGER DEFAULT 1")
            )
            logger.info("Added column task_records.concurrency")
        await session.execute(
            text("UPDATE task_records SET concurrency=1 WHERE concurrency IS NULL OR concurrency < 1")
        )
        await session.commit()


async def ensure_outlook_mailbox_strategy_columns():
    """Add mailbox strategy fields and normalize legacy rows to Outlook."""
    columns = [
        ("provider_type", "VARCHAR(20) DEFAULT 'outlook'"),
        ("code_url", "VARCHAR(2048)"),
    ]
    async with async_session_factory() as session:
        result = await session.execute(text("PRAGMA table_info(outlook_mailboxes)"))
        existing_cols = {row[1] for row in result.fetchall()}
        for name, definition in columns:
            if name not in existing_cols:
                await session.execute(
                    text(f"ALTER TABLE outlook_mailboxes ADD COLUMN {name} {definition}")
                )
                logger.info("Added column outlook_mailboxes.%s", name)
        await session.execute(
            text(
                "UPDATE outlook_mailboxes SET provider_type = 'outlook' "
                "WHERE provider_type IS NULL OR provider_type = ''"
            )
        )
        await session.commit()


async def ensure_accounts_generation_columns():
    """Ensure accounts has content generation pool columns."""
    columns = [
        ("gen_enabled", "BOOLEAN DEFAULT 0"),
        ("gen_enabled_at", "DATETIME"),
        ("gen_last_used_at", "DATETIME"),
        ("gen_locked_until", "DATETIME"),
        ("gen_auto_disabled_reason", "VARCHAR(255)"),
    ]

    async with async_session_factory() as session:
        result = await session.execute(text("PRAGMA table_info(accounts)"))
        existing_cols = {row[1] for row in result.fetchall()}

        for col_name, col_def in columns:
            if col_name in existing_cols:
                continue
            try:
                await session.execute(
                    text(f"ALTER TABLE accounts ADD COLUMN {col_name} {col_def}")
                )
                logger.info(f"Added column accounts.{col_name}")
            except Exception as exc:
                logger.error(f"Failed to add accounts.{col_name}: {exc}")

        await session.commit()


async def ensure_accounts_offer_columns():
    """Ensure accounts has subscription-offer detection columns."""
    columns = [
        ("offer_status", "VARCHAR(20) DEFAULT 'unchecked'"),
        ("offer_product_id", "VARCHAR(255)"),
        ("offer_price_amount", "INTEGER"),
        ("offer_origin_price_amount", "INTEGER"),
        ("offer_currency_code", "VARCHAR(16)"),
        ("offer_discount_percent", "INTEGER"),
        ("offer_checked_at", "DATETIME"),
        ("offer_error", "VARCHAR(512)"),
    ]
    async with async_session_factory() as session:
        result = await session.execute(text("PRAGMA table_info(accounts)"))
        existing_cols = {row[1] for row in result.fetchall()}
        for col_name, col_def in columns:
            if col_name not in existing_cols:
                await session.execute(
                    text(f"ALTER TABLE accounts ADD COLUMN {col_name} {col_def}")
                )
                logger.info("Added column accounts.%s", col_name)
        await session.execute(
            text("UPDATE accounts SET offer_status='unchecked' WHERE offer_status IS NULL OR offer_status='' ")
        )
        await session.commit()


async def ensure_accounts_proxy_binding_columns():
    """Add immutable registration proxy/IP binding fields."""
    columns = [
        ("registration_ip", "VARCHAR(64)"),
        ("registration_asn", "VARCHAR(128)"),
        ("registration_proxy_key", "VARCHAR(512)"),
    ]
    async with async_session_factory() as session:
        result = await session.execute(text("PRAGMA table_info(accounts)"))
        existing_cols = {row[1] for row in result.fetchall()}
        for col_name, col_def in columns:
            if col_name not in existing_cols:
                await session.execute(
                    text(f"ALTER TABLE accounts ADD COLUMN {col_name} {col_def}")
                )
                logger.info("Added column accounts.%s", col_name)
        await session.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_accounts_registration_ip "
                "ON accounts(registration_ip) "
                "WHERE registration_ip IS NOT NULL AND registration_ip != ''"
            )
        )
        await session.commit()


async def ensure_accounts_browser_profile_columns():
    """Add queryable registration browser-profile fields."""
    columns = [
        ("registration_browser_profile", "VARCHAR(64)"),
        ("registration_browser_version", "VARCHAR(32)"),
    ]
    async with async_session_factory() as session:
        result = await session.execute(text("PRAGMA table_info(accounts)"))
        existing_cols = {row[1] for row in result.fetchall()}
        for col_name, col_def in columns:
            if col_name not in existing_cols:
                await session.execute(
                    text(f"ALTER TABLE accounts ADD COLUMN {col_name} {col_def}")
                )
                logger.info("Added column accounts.%s", col_name)
        await session.commit()


async def ensure_content_generation_jobs_table():
    """Ensure content_generation_jobs table exists and has async task columns."""
    async with async_session_factory() as session:
        result = await session.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='content_generation_jobs'"
            )
        )
        exists = result.scalar() is not None
        if not exists:
            try:
                await session.execute(
                    text(
                        """
                    CREATE TABLE content_generation_jobs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        job_type VARCHAR(20) NOT NULL,
                        status VARCHAR(20) DEFAULT 'queued',
                        prompt TEXT,
                        model VARCHAR(100),
                        ratio VARCHAR(20),
                        resolution VARCHAR(20),
                        duration INTEGER,
                        function_mode VARCHAR(50),
                        input_images TEXT,
                        output_urls TEXT,
                        thumbnail_urls TEXT,
                        local_urls TEXT,
                        error_message TEXT,
                        remote_task_id TEXT,
                        remote_history_id TEXT,
                        remote_kind TEXT,
                        remote_status TEXT,
                        remote_fail_code TEXT,
                        remote_error_message TEXT,
                        account_id INTEGER,
                        region VARCHAR(50),
                        submitted_at DATETIME,
                        finished_at DATETIME,
                        created_at DATETIME,
                        updated_at DATETIME,
                        FOREIGN KEY(account_id) REFERENCES accounts(id)
                    )
                    """
                    )
                )
                logger.info("Created table content_generation_jobs")
                await session.commit()
            except Exception as exc:
                logger.error(f"Failed to create content_generation_jobs: {exc}")
        else:
            col_result = await session.execute(
                text("PRAGMA table_info(content_generation_jobs)")
            )
            existing_cols = {row[1] for row in col_result.fetchall()}
            columns = [
                ("thumbnail_urls", "TEXT"),
                ("local_urls", "TEXT"),
                ("function_mode", "VARCHAR(50)"),
                ("remote_task_id", "TEXT"),
                ("remote_history_id", "TEXT"),
                ("remote_kind", "TEXT"),
                ("remote_status", "TEXT"),
                ("remote_fail_code", "TEXT"),
                ("remote_error_message", "TEXT"),
                ("submitted_at", "DATETIME"),
                ("finished_at", "DATETIME"),
            ]

            for col_name, col_def in columns:
                if col_name in existing_cols:
                    continue
                try:
                    await session.execute(
                        text(
                            f"ALTER TABLE content_generation_jobs ADD COLUMN {col_name} {col_def}"
                        )
                    )
                    logger.info(f"Added column content_generation_jobs.{col_name}")
                    await session.commit()
                except Exception as exc:
                    logger.error(
                        f"Failed to add {col_name} to content_generation_jobs: {exc}"
                    )
