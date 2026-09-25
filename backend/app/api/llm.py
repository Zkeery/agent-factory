"""LLM 画像与 PRD 草稿对比（§5.3 第一切片）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.auth import get_current_user, require_api_key
from app.core.config import settings
from app.core.errors import AppError
from app.models import User
from app.schemas import (
    ComparePrdOut,
    ComparePrdRequest,
    ComparePrdVariantOut,
    LlmProfileOut,
    LlmProfilesOut,
)
from app.services import llm

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])


@router.get("/llm/profiles", response_model=LlmProfilesOut)
def get_llm_profiles(user: User = Depends(get_current_user)):
    data = llm.list_llm_profiles()
    return LlmProfilesOut(
        default_provider=data["default_provider"],
        profiles=[LlmProfileOut(**p) for p in data["profiles"]],
    )


@router.post("/llm/compare-prd", response_model=ComparePrdOut)
def compare_prd(body: ComparePrdRequest, user: User = Depends(get_current_user)):
    """同一 idea 串行产出 mock（及可用时 deepseek）PRD 草稿；不创建 Run、不写盘。"""
    decisions = [
        {"code": d.code, "question": d.question, "answer": d.answer}
        for d in body.decisions
    ]
    variants: list[ComparePrdVariantOut] = []

    try:
        mock_client = llm.get_llm("mock")
        prd = mock_client.generate_prd(body.idea, decisions)
        variants.append(
            ComparePrdVariantOut(
                provider="mock",
                model="mock",
                prd=prd if isinstance(prd, dict) else {"raw": str(prd)},
                prompt_tokens=int(getattr(mock_client, "prompt_tokens", 0) or 0),
                completion_tokens=int(getattr(mock_client, "completion_tokens", 0) or 0),
                error=None,
            )
        )
    except Exception as exc:  # noqa: BLE001
        variants.append(
            ComparePrdVariantOut(provider="mock", model="mock", prd=None, error=str(exc)[:200])
        )

    if settings.llm_api_key.strip():
        try:
            real = llm.get_llm("deepseek")
            prd = real.generate_prd(body.idea, decisions)
            variants.append(
                ComparePrdVariantOut(
                    provider="deepseek",
                    model=settings.llm_model,
                    prd=prd if isinstance(prd, dict) else {"raw": str(prd)},
                    prompt_tokens=int(getattr(real, "prompt_tokens", 0) or 0),
                    completion_tokens=int(getattr(real, "completion_tokens", 0) or 0),
                    error=None,
                )
            )
        except AppError as exc:
            variants.append(
                ComparePrdVariantOut(
                    provider="deepseek",
                    model=settings.llm_model,
                    prd=None,
                    error=exc.message,
                )
            )
        except Exception as exc:  # noqa: BLE001
            variants.append(
                ComparePrdVariantOut(
                    provider="deepseek",
                    model=settings.llm_model,
                    prd=None,
                    error=str(exc)[:200],
                )
            )

    return ComparePrdOut(variants=variants)
