"""Sync/Backup API routes."""

import json
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.database import get_db
from app.services.sync_service import SyncService
from app.services.snapshot_service import SnapshotError, SnapshotService
from app.schemas import (
    SyncRequest, SyncResponse, BackupResponse, SnapshotCreated, SnapshotData, SnapshotInfo
)
from app.auth import get_current_store
from app.models import BackupSnapshot, Store

router = APIRouter(prefix="/sync", tags=["Sync/Backup"])


def get_service(db: AsyncSession = Depends(get_db)) -> SyncService:
    return SyncService(db)


@router.post("", response_model=SyncResponse)
async def sync_from_client(
    data: SyncRequest,
    service: SyncService = Depends(get_service),
    current_store: Store = Depends(get_current_store),
):
    """Sync data from client (localStorage) to backend — scoped to current store."""
    return await service.sync_from_client(data, store_id=current_store.id)


@router.get("/backup", response_model=BackupResponse)
async def full_backup(
    service: SyncService = Depends(get_service),
    current_store: Store = Depends(get_current_store),
):
    """Get full backup of the current store's data."""
    data = await service.full_backup(store_id=current_store.id)
    return BackupResponse(
        timestamp=datetime.utcnow(),
        version="1.0.0",
        data=data
    )


@router.post("/restore", response_model=SyncResponse)
async def restore_backup(
    data: dict,
    service: SyncService = Depends(get_service),
    current_store: Store = Depends(get_current_store),
):
    """Restore backup data into the current store (replaces this store's data).

    ไฟล์ผิดรูปจะได้ 400 และข้อมูลเดิมไม่ถูกแตะ; ถ้ากู้คืนล้มกลางทาง service
    จะย้อนข้อมูลเดิมกลับให้ แล้วส่ง 500 พร้อมข้อความอธิบาย
    """
    try:
        return await service.restore_backup(data, store_id=current_store.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ── Backup snapshots: ไฟล์สำรองของหน้าเว็บ เก็บทั้งก้อน กู้คืนได้ครบทุกฟิลด์ ──

LabelQuery = Query("", max_length=100, description="แยกร้านในหน้าเว็บ เช่น store-1")


def get_snapshot_service(db: AsyncSession = Depends(get_db)) -> SnapshotService:
    return SnapshotService(db)


def _snapshot_info(snapshot: BackupSnapshot) -> dict:
    return {
        "id": snapshot.id,
        "label": snapshot.label,
        "sha256": snapshot.sha256,
        "size_bytes": snapshot.size_bytes,
        "counts": json.loads(snapshot.counts or "{}"),
        "created_at": snapshot.created_at,
    }


def _snapshot_data(snapshot: BackupSnapshot) -> dict:
    return {**_snapshot_info(snapshot), "data": json.loads(snapshot.payload)}


@router.post("/snapshots", response_model=SnapshotCreated, status_code=201)
async def create_snapshot(
    request: Request,
    response: Response,
    label: str = LabelQuery,
    service: SnapshotService = Depends(get_snapshot_service),
    current_store: Store = Depends(get_current_store),
):
    """เก็บไฟล์สำรองของหน้าเว็บ (exportBackupJSON) — 201 ถ้าเป็นชุดใหม่, 200 ถ้าข้อมูลเหมือนชุดที่มีอยู่."""
    limit = settings.SNAPSHOT_MAX_BYTES
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise HTTPException(status_code=413, detail=f"ไฟล์สำรองใหญ่เกิน {limit:,} ไบต์")
    raw_bytes = await request.body()
    if len(raw_bytes) > limit:
        raise HTTPException(status_code=413, detail=f"ไฟล์สำรองใหญ่เกิน {limit:,} ไบต์")
    try:
        raw = raw_bytes.decode("utf-8")
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="ข้อมูลไม่ใช่ JSON ที่ถูกต้อง") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="ไฟล์สำรองต้องเป็น JSON object")

    try:
        snapshot, created = await service.create(payload, raw=raw, store_id=current_store.id, label=label)
    except SnapshotError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not created:
        response.status_code = 200
    return {**_snapshot_info(snapshot), "created": created}


@router.get("/snapshots", response_model=List[SnapshotInfo])
async def list_snapshots(
    label: Optional[str] = Query(None, max_length=100),
    service: SnapshotService = Depends(get_snapshot_service),
    current_store: Store = Depends(get_current_store),
):
    """รายการ snapshot ใหม่สุดก่อน (ไม่รวมข้อมูล)."""
    return [_snapshot_info(s) for s in await service.list(store_id=current_store.id, label=label)]


@router.get("/snapshots/latest", response_model=SnapshotData)
async def latest_snapshot(
    label: str = LabelQuery,
    service: SnapshotService = Depends(get_snapshot_service),
    current_store: Store = Depends(get_current_store),
):
    """snapshot ล่าสุดของ label นี้ พร้อมข้อมูลต้นฉบับ."""
    snapshot = await service.latest(store_id=current_store.id, label=label)
    if not snapshot:
        raise HTTPException(status_code=404, detail="ยังไม่มีข้อมูลสำรอง")
    return _snapshot_data(snapshot)


@router.get("/snapshots/{snapshot_id}", response_model=SnapshotData)
async def get_snapshot(
    snapshot_id: int,
    service: SnapshotService = Depends(get_snapshot_service),
    current_store: Store = Depends(get_current_store),
):
    snapshot = await service.get(snapshot_id, store_id=current_store.id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="ไม่พบข้อมูลสำรองนี้")
    return _snapshot_data(snapshot)


@router.api_route("/health", methods=["GET", "HEAD"])
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "database": "connected", "timestamp": datetime.utcnow().isoformat()}