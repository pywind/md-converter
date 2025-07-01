from fastapi import APIRouter

router = APIRouter()

@router.get("/health")
async def health_check():
    """
    Perform a health check on the API.
    """
    return {"status": "ok"}