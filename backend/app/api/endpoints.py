"""Endpoint profile management, connection tests, model discovery."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_profile_or_404
from app.db.session import get_db
from app.models import EndpointProfile
from app.schemas import (
    ConnectionTestResult,
    EndpointProfileCreate,
    EndpointProfileResponse,
    EndpointProfileUpdate,
    FetchModelsResult,
)
from app.services import crud
from app.services.connection import fetch_models, test_connection

router = APIRouter(prefix="/api/endpoints", tags=["endpoints"])


def _to_response(profile: EndpointProfile) -> EndpointProfileResponse:
    masked = "••••••••" if profile.has_api_key else None
    return EndpointProfileResponse(
        id=profile.id,
        name=profile.name,
        base_url=profile.base_url,
        default_model=profile.default_model,
        request_timeout=profile.request_timeout,
        verify_tls=profile.verify_tls,
        custom_headers=profile.custom_headers or {},
        extra_body_params=profile.extra_body_params or {},
        enabled=profile.enabled,
        notes=profile.notes,
        has_api_key=profile.has_api_key,
        api_key_storage=profile.api_key_storage,
        api_key_env_var=profile.api_key_env_var,
        input_price_per_1m=profile.input_price_per_1m,
        output_price_per_1m=profile.output_price_per_1m,
        masked_api_key=masked,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


@router.get("", response_model=list[EndpointProfileResponse])
def list_profiles(session: Session = Depends(get_db)):
    rows = session.execute(
        select(EndpointProfile).order_by(EndpointProfile.name)
    ).scalars().all()
    return [_to_response(p) for p in rows]


@router.post("", response_model=EndpointProfileResponse, status_code=201)
def create_profile(payload: EndpointProfileCreate, session: Session = Depends(get_db)):
    data = payload.model_dump(exclude_unset=True)
    profile = crud.create_endpoint_profile(session, data)
    session.commit()
    return _to_response(profile)


@router.get("/{profile_id}", response_model=EndpointProfileResponse)
def get_profile(profile_id: str, session: Session = Depends(get_db)):
    return _to_response(get_profile_or_404(session, profile_id))


@router.put("/{profile_id}", response_model=EndpointProfileResponse)
def update_profile(profile_id: str, payload: EndpointProfileUpdate, session: Session = Depends(get_db)):
    profile = get_profile_or_404(session, profile_id)
    crud.update_endpoint_profile(session, profile, payload.model_dump(exclude_unset=True))
    session.commit()
    return _to_response(profile)


@router.delete("/{profile_id}", status_code=204)
def delete_profile(profile_id: str, session: Session = Depends(get_db)):
    profile = get_profile_or_404(session, profile_id)
    from app.core.secrets import delete_api_key

    delete_api_key(profile.id)
    session.delete(profile)
    session.commit()


@router.post("/{profile_id}/duplicate", response_model=EndpointProfileResponse)
def duplicate_profile(profile_id: str, session: Session = Depends(get_db)):
    profile = get_profile_or_404(session, profile_id)
    new = crud.duplicate_endpoint_profile(session, profile)
    session.commit()
    return _to_response(new)


@router.post("/{profile_id}/test", response_model=ConnectionTestResult)
async def test_profile(profile_id: str, session: Session = Depends(get_db)):
    profile = get_profile_or_404(session, profile_id)
    return await test_connection(profile)


@router.post("/{profile_id}/models", response_model=FetchModelsResult)
async def fetch_profile_models(profile_id: str, session: Session = Depends(get_db)):
    profile = get_profile_or_404(session, profile_id)
    return await fetch_models(profile)
