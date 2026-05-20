import os
import time


ENV = os.getenv("APP_ENV", "development")
APP_VERSION = os.getenv("APP_VERSION", "0.1.0")
APP_STARTED_AT = time.time()
SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "0").lower() in {"1", "true", "yes"}
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")
UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "storage/uploads")
LOG_FOLDER = os.getenv("LOG_FOLDER", "storage/logs")
CACHE_FOLDER = os.getenv("CACHE_FOLDER", "storage/cache")
DEBUG_LOGS = os.getenv("DEBUG_LOGS", "0").lower() in {"1", "true", "yes"}
DEBUG_PNCP = os.getenv("DEBUG_PNCP", "0").lower() in {"1", "true", "yes"}
DEBUG_IA = os.getenv("DEBUG_IA", "0").lower() in {"1", "true", "yes"}
OPENAI_DISABLE_MINUTES = int(os.getenv("OPENAI_DISABLE_MINUTES", "10"))
PNCP_MAX_WORKERS = int(os.getenv("PNCP_MAX_WORKERS", "3"))
PNCP_BACKOFF_MAX_SECONDS = float(os.getenv("PNCP_BACKOFF_MAX_SECONDS", "8"))
PNCP_DEBUG_PAYLOADS = os.getenv("PNCP_DEBUG_PAYLOADS", "1").lower() in {"1", "true", "yes"}
PNCP_DEBUG_FOLDER = os.getenv("PNCP_DEBUG_FOLDER", "storage/debug/pncp")
PNCP_MAX_CONTRATACOES = int(os.getenv("PNCP_MAX_CONTRATACOES", "60"))
PNCP_MAX_ITENS_PRE_SCORE = int(os.getenv("PNCP_MAX_ITENS_PRE_SCORE", "180"))
PNCP_MAX_ITENS_SCORE = int(os.getenv("PNCP_MAX_ITENS_SCORE", "80"))
SEARCH_MAX_SCORE_CANDIDATES = int(os.getenv("SEARCH_MAX_SCORE_CANDIDATES", "50"))
SEARCH_MIN_RESULTS_BEFORE_EXPANSION = int(os.getenv("SEARCH_MIN_RESULTS_BEFORE_EXPANSION", "20"))
