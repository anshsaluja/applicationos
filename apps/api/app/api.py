from fastapi import APIRouter
from pydantic import BaseModel

from .domain.evaluator import evaluate_requirements
from .domain.models import Requirement

router = APIRouter(prefix="/v1")


class EvaluateRequest(BaseModel):
    requirements: list[Requirement]


class EvaluateResponse(BaseModel):
    requirements: list[Requirement]
    missing_count: int
    inconsistent_count: int


@router.post("/requirements/evaluate", response_model=EvaluateResponse, tags=["requirements"])
def evaluate(payload: EvaluateRequest) -> EvaluateResponse:
    result = evaluate_requirements(payload.requirements)
    return EvaluateResponse(
        requirements=result.requirements,
        missing_count=result.missing_count,
        inconsistent_count=result.inconsistent_count,
    )
