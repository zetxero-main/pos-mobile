"""Backup snapshots — เก็บไฟล์สำรองของหน้าเว็บทั้งก้อน.

ต่างจาก /sync (แปลงข้อมูลลงตาราง) ตรงที่ไม่แปลงอะไรเลย: เก็บ JSON ต้นฉบับไว้
แล้วส่งคืนแบบเดิมทุกไบต์ จึงกู้คืนได้ครบทุกฟิลด์ แม้ฟิลด์ที่ backend ไม่รู้จัก
"""

import hashlib
import json
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import BackupSnapshot

# คีย์ที่ exportBackupJSON() ใส่เป็น list — ต้องมีอย่างน้อยหนึ่งคีย์จึงนับว่าเป็นไฟล์สำรอง
BACKUP_LIST_KEYS = ("products", "sales", "purchases", "debts", "expenses", "holdBills")
COUNT_KEYS = ("products", "sales", "debts")
# ไม่นับตอนเทียบว่าข้อมูลซ้ำ (เปลี่ยนทุกครั้งที่กดสำรอง)
VOLATILE_KEYS = ("exportedAt",)


class SnapshotError(ValueError):
    """ข้อมูลที่ส่งมาไม่ใช่ไฟล์สำรองของหน้าเว็บ."""


def validate_backup(payload: dict) -> None:
    present = [key for key in BACKUP_LIST_KEYS if key in payload]
    if not present:
        raise SnapshotError(
            "ไม่ใช่ไฟล์สำรองของ pos-mobile (ต้องมีอย่างน้อยหนึ่งใน: " + ", ".join(BACKUP_LIST_KEYS) + ")"
        )
    not_lists = [key for key in present if not isinstance(payload[key], list)]
    if not_lists:
        raise SnapshotError("ฟิลด์ต้องเป็นรายการ (list): " + ", ".join(not_lists))


def content_hash(payload: dict) -> str:
    stable = {key: value for key, value in payload.items() if key not in VOLATILE_KEYS}
    canonical = json.dumps(stable, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def summarize(payload: dict) -> dict:
    return {key: len(payload[key]) for key in COUNT_KEYS if isinstance(payload.get(key), list)}


class SnapshotService:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self, payload: dict, *, raw: str, store_id: int, label: str = ""
    ) -> tuple[BackupSnapshot, bool]:
        """เก็บ snapshot ใหม่ คืน (snapshot, created) — created=False ถ้าข้อมูลเหมือนชุดที่มีอยู่."""
        validate_backup(payload)
        digest = content_hash(payload)

        existing = await self.db.scalar(
            select(BackupSnapshot).where(
                BackupSnapshot.store_id == store_id,
                BackupSnapshot.label == label,
                BackupSnapshot.sha256 == digest,
            )
        )
        if existing:
            return existing, False

        snapshot = BackupSnapshot(
            store_id=store_id,
            label=label,
            sha256=digest,
            size_bytes=len(raw.encode("utf-8")),
            counts=json.dumps(summarize(payload)),
            payload=raw,
        )
        self.db.add(snapshot)
        await self.db.flush()
        await self._prune(store_id=store_id, label=label)
        await self.db.commit()
        await self.db.refresh(snapshot)
        return snapshot, True

    async def _prune(self, *, store_id: int, label: str) -> None:
        keep = max(1, settings.SNAPSHOT_KEEP)
        stale_ids = (
            await self.db.scalars(
                select(BackupSnapshot.id)
                .where(BackupSnapshot.store_id == store_id, BackupSnapshot.label == label)
                .order_by(BackupSnapshot.created_at.desc(), BackupSnapshot.id.desc())
                .offset(keep)
            )
        ).all()
        if stale_ids:
            await self.db.execute(delete(BackupSnapshot).where(BackupSnapshot.id.in_(stale_ids)))

    async def list(self, *, store_id: int, label: Optional[str] = None) -> list[BackupSnapshot]:
        query = select(BackupSnapshot).where(BackupSnapshot.store_id == store_id)
        if label is not None:
            query = query.where(BackupSnapshot.label == label)
        query = query.order_by(BackupSnapshot.created_at.desc(), BackupSnapshot.id.desc())
        return list((await self.db.scalars(query)).all())

    async def latest(self, *, store_id: int, label: str = "") -> Optional[BackupSnapshot]:
        return await self.db.scalar(
            select(BackupSnapshot)
            .where(BackupSnapshot.store_id == store_id, BackupSnapshot.label == label)
            .order_by(BackupSnapshot.created_at.desc(), BackupSnapshot.id.desc())
            .limit(1)
        )

    async def get(self, snapshot_id: int, *, store_id: int) -> Optional[BackupSnapshot]:
        return await self.db.scalar(
            select(BackupSnapshot).where(
                BackupSnapshot.id == snapshot_id, BackupSnapshot.store_id == store_id
            )
        )
