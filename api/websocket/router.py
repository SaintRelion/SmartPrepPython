from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from utils.connection import manager

router = APIRouter(tags=["Websocket"])


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@router.post("/notify-update")
async def notify_update():
    await manager.broadcast("REFRESH_MATERIALS")
    return {"status": "success"}
