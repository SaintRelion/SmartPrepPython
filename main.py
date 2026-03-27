from fastapi import FastAPI
from api.auth.router import router as auth_router
from api.materials.router import router as materials_router
from api.ai.router import router as ai_router
from api.review.router import router as reviewee_router
from api.analytics.router import router as analytics_router


from api.sr_libs.router import router as sr_libs_router

app = FastAPI()

app.include_router(auth_router)
app.include_router(materials_router)
app.include_router(ai_router)
app.include_router(reviewee_router)
app.include_router(analytics_router)


app.include_router(sr_libs_router)
