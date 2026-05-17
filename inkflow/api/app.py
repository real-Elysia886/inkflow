"""FastAPI application factory."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from inkflow.api.routers import llm, skill, world, distill, pipeline, projects, outline, workbench
from inkflow.api.ws_manager import ws_manager

WEB_DIR = Path(__file__).parent.parent / "web"
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"


async def _periodic_ws_cleanup():
    """Periodically clean up expired WebSocket message buffers."""
    while True:
        await asyncio.sleep(300)  # every 5 minutes
        ws_manager.cleanup_expired_buffers()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Bind ws_manager to the actual serving event loop at startup."""
    loop = asyncio.get_running_loop()
    ws_manager.set_loop(loop)
    cleanup_task = asyncio.create_task(_periodic_ws_cleanup())
    yield
    cleanup_task.cancel()


def create_app() -> FastAPI:
    app = FastAPI(
        title="inkflow",
        description="AI-powered multi-agent novel writing framework",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount static files
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Register API routers
    app.include_router(llm.router)
    app.include_router(skill.router)
    app.include_router(world.router)
    app.include_router(distill.router)
    app.include_router(pipeline.router)
    app.include_router(projects.router)
    app.include_router(outline.router)
    app.include_router(workbench.router)

    # Page routes
    from fastapi.responses import HTMLResponse
    from fastapi.requests import Request

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return templates.TemplateResponse(request=request, name="index.html")

    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        """Lightweight liveness probe. Does not touch disk or LLM providers."""
        return {"ok": True, "version": app.version}

    return app
