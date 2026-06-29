"""DealFlow360 API - FastAPI application factory."""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import Base, engine
from .routers import auth, catalog, operations, portal, quotations, reports
from .services.workflow import WorkflowError


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    if settings.seed_on_start:
        from .seed import seed_if_empty
        seed_if_empty()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="DealFlow360 API", version=settings.version, lifespan=lifespan,
                  description="B2B quote-to-cash: CPQ, risk-based approvals, negotiation, split fulfilment, "
                              "invoicing and subscription billing.",
                  docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
                       allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(WorkflowError)
    async def workflow_error(_: Request, err: WorkflowError):
        return JSONResponse(status_code=err.status_code, content={"detail": err.message})

    @app.get("/api/health", tags=["system"])
    def health():
        return {"status": "ok", "service": settings.app_name, "version": settings.version}

    for module in (auth, catalog, quotations, operations, reports, portal):
        app.include_router(module.router, prefix="/api")

    # Single-process deployment: serve the built frontend when it exists.
    if settings.frontend_dist.is_dir():
        app.mount("/", StaticFiles(directory=settings.frontend_dist, html=True), name="frontend")
    return app


app = create_app()
