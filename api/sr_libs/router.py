from fastapi import APIRouter
from api.sr_libs.api_exporter import (
    build_sr_spec,
)  # Import the function we built earlier

router = APIRouter(prefix="/sr_libs", tags=["Internal"])


@router.get("/schema")
async def get_api_schema():
    return build_sr_spec()
