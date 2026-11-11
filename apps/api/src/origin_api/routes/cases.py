"""Cases: one investigation each; uploads are added to a case."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from origin_api import ratelimit
from origin_api.routes.assets import asset_out
from origin_api.schemas import AssetBrief, AssetOut, CaseIn, CaseOut, UploadRejectedOut
from origin_api.state import Session, State
from origin_core.db.models import Asset, AuditEvent, Case
from origin_core.enums import Actor
from origin_core.hashing import sha256_hex
from origin_core.ingest.service import IngestLimits, ingest_upload
from origin_core.ingest.validate import RejectReason, UploadRejected

router = APIRouter(prefix="/cases", tags=["cases"])

UPLOAD_CHUNK = 1 << 20


def _case_out(case: Case, assets: list[Asset]) -> CaseOut:
    return CaseOut(
        id=case.id,
        title=case.title,
        notes=case.notes,
        created_at=case.created_at,
        assets=[
            AssetBrief(
                id=a.id,
                original_filename=a.original_filename,
                width=a.width,
                height=a.height,
                c2pa_state=a.c2pa_state,
                created_at=a.created_at,
            )
            for a in assets
        ],
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_case(body: CaseIn, session: Session) -> CaseOut:
    case = Case(title=body.title.strip(), notes=body.notes)
    session.add(case)
    await session.flush()
    session.add(
        AuditEvent(
            case_id=case.id,
            actor=Actor.ANALYST,
            action="case.created",
            subject_type="case",
            subject_id=case.id,
            detail={"title": case.title},
        )
    )
    await session.commit()
    await session.refresh(case)
    return _case_out(case, [])


@router.get("")
async def list_cases(session: Session, limit: int = 50) -> list[CaseOut]:
    cases = (
        (
            await session.execute(
                select(Case).order_by(Case.created_at.desc()).limit(min(limit, 200))
            )
        )
        .scalars()
        .all()
    )
    return [_case_out(case, []) for case in cases]


async def _case_or_404(session: Session, case_id: uuid.UUID) -> Case:
    case = await session.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    return case


@router.get("/{case_id}")
async def get_case(case_id: uuid.UUID, session: Session) -> CaseOut:
    case = await _case_or_404(session, case_id)
    assets = (
        (
            await session.execute(
                select(Asset).where(Asset.case_id == case_id).order_by(Asset.created_at)
            )
        )
        .scalars()
        .all()
    )
    return _case_out(case, list(assets))


async def _read_capped(file: UploadFile, max_bytes: int) -> bytes:
    """Read at most max_bytes + 1 so an oversized upload is refused without buffering it all."""
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(UPLOAD_CHUNK):
        chunks.append(chunk)
        total += len(chunk)
        if total > max_bytes:
            break
    return b"".join(chunks)


@router.post(
    "/{case_id}/assets",
    status_code=status.HTTP_201_CREATED,
    response_model=AssetOut,
    dependencies=[Depends(ratelimit.uploads)],
    responses={
        200: {"model": AssetOut, "description": "Identical image already in this case"},
        413: {"model": UploadRejectedOut},
        422: {"model": UploadRejectedOut},
        429: {"description": "Too many uploads from this client; see Retry-After"},
    },
)
async def upload_asset(
    case_id: uuid.UUID, file: UploadFile, state: State, session: Session
) -> AssetOut | JSONResponse:
    """Add an image to a case: validated by content, stored, fingerprinted, and checked for
    metadata and Content Credentials. The image is not sent to any third party here."""
    await _case_or_404(session, case_id)
    settings = state.settings
    data = await _read_capped(file, settings.upload_max_bytes)
    try:
        result = await ingest_upload(
            session,
            state.blobs,
            case_id=case_id,
            data=data,
            filename=file.filename,
            limits=IngestLimits(settings.upload_max_bytes, settings.upload_max_pixels),
            exiftool=settings.exiftool_path,
        )
        await session.commit()
    except UploadRejected as exc:
        code = 413 if exc.reason is RejectReason.TOO_LARGE else 422
        body = UploadRejectedOut(reason=exc.reason.value, message=exc.message)
        return JSONResponse(status_code=code, content=body.model_dump())
    except IntegrityError:
        # The same bytes were uploaded concurrently; the other request created the asset.
        await session.rollback()
        return await upload_asset_existing(case_id, data, session)

    out = await asset_out(session, result.asset)
    if result.created:
        return out
    return JSONResponse(status_code=200, content=out.model_dump(mode="json"))


async def upload_asset_existing(case_id: uuid.UUID, data: bytes, session: Session) -> JSONResponse:
    asset = (
        await session.execute(
            select(Asset).where(Asset.case_id == case_id, Asset.sha256 == sha256_hex(data))
        )
    ).scalar_one()
    out = await asset_out(session, asset)
    return JSONResponse(status_code=200, content=out.model_dump(mode="json"))
