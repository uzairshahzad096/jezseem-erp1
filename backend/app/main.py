import logging
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.auth.router import router as auth_router
from app.calibration.router import router as calibration_router
from app.leads.router import router as leads_router
from app.crm.router import router as crm_router
from app.security.router import router as security_router
from app.companies.router import router as companies_router
from app.core.config import settings
from app.dashboard.router import router as dashboard_router
from app.exports.router import router as exports_router
from app.finance.errors import FinanceError
from app.finance.imported_vouchers import router as imported_vouchers_router
from app.finance.router import router as finance_router
from app.receivables.router import ar_router, sales_router as sales_invoice_router
from app.gatepass.router import router as gatepass_router
from app.hrms.router import router as hrms_router
from app.inventory.images import MEDIA_URL_PREFIX
from app.inventory.router import router as inventory_router
from app.partners.router import router as partners_router
from app.procurement.router import router as procurement_router
from app.sales.router import router as sales_router
from app.documents.router import router as documents_router
from app.reports.router import router as reports_router

logger = logging.getLogger("jezseem")
logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Guard: the development auth bypass must never reach production ---
if settings.AUTH_DISABLED:
    if settings.ENVIRONMENT.lower() == "production":
        raise RuntimeError(
            "AUTH_DISABLED=true with ENVIRONMENT=production. "
            "Authentication cannot be bypassed in production â€” set AUTH_DISABLED=false."
        )
    logger.warning(
        "=" * 72 + "\n"
        "  AUTH_DISABLED is ON. Every request runs as '%s' and all\n"
        "  permission checks pass. Development only â€” set AUTH_DISABLED=false\n"
        "  before this system holds real data.\n" + "=" * 72,
        settings.DEV_USER_USERNAME,
    )


@app.get("/api/v1/auth/status", tags=["auth"])
def auth_status():
    """Lets the frontend know whether it should show a login screen."""
    return {"auth_required": not settings.AUTH_DISABLED}


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """
    Turn any unhandled error into a JSON response carrying CORS headers.

    Without this, Starlette's default 500 bypasses CORSMiddleware, the browser
    blocks the response, and the frontend reports a bare "Failed to fetch" with
    no clue what broke. Per spec section 24: the user sees a reference code,
    the technical detail goes to the server log only.
    """
    reference = uuid.uuid4().hex[:8]
    logger.exception("Unhandled error [%s] on %s %s", reference, request.method, request.url.path)

    origin = request.headers.get("origin")
    headers = {}
    if origin and origin in settings.CORS_ORIGINS:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "true"

    return JSONResponse(
        status_code=500,
        headers=headers,
        content={
            "detail": (
                "Something went wrong on the server. "
                f"Quote reference {reference} when reporting this."
            ),
            "reference": reference,
        },
    )


@app.exception_handler(FinanceError)
async def finance_error_handler(request: Request, exc: FinanceError):
    """Finance services raise FinanceError, not HTTPException, because the
    posting engine is also called outside requests. Its message is written
    for the user and goes out as the detail, like an HTTPException's."""
    origin = request.headers.get("origin")
    headers = {}
    if origin and origin in settings.CORS_ORIGINS:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "true"
    return JSONResponse(status_code=exc.status_code, headers=headers, content={"detail": exc.message})


@app.get("/api/health", tags=["system"])
def health_check():
    """Liveness/readiness probe for Docker, Nginx and monitoring."""
    return {"status": "ok", "app": settings.APP_NAME, "environment": settings.ENVIRONMENT}


# --- Uploaded files ---
# Product images are served as plain static files so an <img> tag can load
# them: a browser does not attach the bearer token to an image request, so an
# authenticated route would leave every picture broken once AUTH_DISABLED is
# switched off. Filenames are item UUIDs, which are not guessable, but this
# path performs no permission check â€” anyone who can reach the API and knows
# an item's id can fetch its picture. For an internal ERP behind Nginx that is
# the intended trade; if product photos ever need to be access-controlled,
# replace this mount with an authenticated route and have the frontend load
# images through fetch() into object URLs.
Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
app.mount(MEDIA_URL_PREFIX, StaticFiles(directory=settings.UPLOAD_DIR), name="media")


app.include_router(auth_router, prefix=settings.API_V1_PREFIX)
app.include_router(companies_router, prefix=settings.API_V1_PREFIX)
app.include_router(dashboard_router, prefix=settings.API_V1_PREFIX)
app.include_router(inventory_router, prefix=settings.API_V1_PREFIX)
app.include_router(partners_router, prefix=settings.API_V1_PREFIX)
app.include_router(sales_router, prefix=settings.API_V1_PREFIX)
app.include_router(documents_router, prefix=settings.API_V1_PREFIX)
app.include_router(reports_router, prefix=settings.API_V1_PREFIX)
app.include_router(exports_router, prefix=settings.API_V1_PREFIX)
app.include_router(gatepass_router, prefix=settings.API_V1_PREFIX)
app.include_router(procurement_router, prefix=settings.API_V1_PREFIX)
app.include_router(finance_router, prefix=settings.API_V1_PREFIX)
app.include_router(imported_vouchers_router, prefix=settings.API_V1_PREFIX)
app.include_router(sales_invoice_router, prefix=settings.API_V1_PREFIX)
app.include_router(ar_router, prefix=settings.API_V1_PREFIX)
app.include_router(hrms_router, prefix=settings.API_V1_PREFIX)
app.include_router(calibration_router, prefix=settings.API_V1_PREFIX)
app.include_router(leads_router, prefix=settings.API_V1_PREFIX)
app.include_router(crm_router, prefix=settings.API_V1_PREFIX)
app.include_router(security_router, prefix=settings.API_V1_PREFIX)
