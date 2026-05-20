import logging
import logging.config
from pathlib import Path

from config.runtime_settings import LOG_FOLDER


LOG_DIRS = {
    "app": Path(LOG_FOLDER) / "app",
    "pesquisa": Path(LOG_FOLDER) / "pesquisa",
    "pncp": Path(LOG_FOLDER) / "pncp",
    "ia": Path(LOG_FOLDER) / "ia",
    "errors": Path(LOG_FOLDER) / "errors",
}


def garantir_diretorios_logs():
    for diretorio in LOG_DIRS.values():
        diretorio.mkdir(parents=True, exist_ok=True)


def setup_logging(debug=False):
    garantir_diretorios_logs()
    level = "DEBUG" if debug else "INFO"
    formato = "%(asctime)s %(levelname)s [%(name)s] %(message)s"

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": formato,
                    "datefmt": "%Y-%m-%d %H:%M:%S",
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "level": level,
                },
                "app_file": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "filename": str(LOG_DIRS["app"] / "app.log"),
                    "maxBytes": 2_000_000,
                    "backupCount": 5,
                    "encoding": "utf-8",
                    "formatter": "default",
                    "level": level,
                },
                "pesquisa_file": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "filename": str(LOG_DIRS["pesquisa"] / "pesquisa.log"),
                    "maxBytes": 2_000_000,
                    "backupCount": 5,
                    "encoding": "utf-8",
                    "formatter": "default",
                    "level": level,
                },
                "pncp_file": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "filename": str(LOG_DIRS["pncp"] / "pncp.log"),
                    "maxBytes": 2_000_000,
                    "backupCount": 5,
                    "encoding": "utf-8",
                    "formatter": "default",
                    "level": level,
                },
                "ia_file": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "filename": str(LOG_DIRS["ia"] / "ia.log"),
                    "maxBytes": 2_000_000,
                    "backupCount": 5,
                    "encoding": "utf-8",
                    "formatter": "default",
                    "level": level,
                },
                "errors_file": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "filename": str(LOG_DIRS["errors"] / "errors.log"),
                    "maxBytes": 2_000_000,
                    "backupCount": 10,
                    "encoding": "utf-8",
                    "formatter": "default",
                    "level": "ERROR",
                },
            },
            "root": {
                "handlers": ["console", "app_file", "errors_file"],
                "level": level,
            },
            "loggers": {
                "app": {
                    "handlers": ["console", "app_file", "errors_file"],
                    "level": level,
                    "propagate": False,
                },
                "pesquisa": {
                    "handlers": ["console", "pesquisa_file", "errors_file"],
                    "level": level,
                    "propagate": False,
                },
                "pncp": {
                    "handlers": ["console", "pncp_file", "errors_file"],
                    "level": level,
                    "propagate": False,
                },
                "ia": {
                    "handlers": ["console", "ia_file", "errors_file"],
                    "level": level,
                    "propagate": False,
                },
                "errors": {
                    "handlers": ["console", "errors_file"],
                    "level": "ERROR",
                    "propagate": False,
                },
                "werkzeug": {
                    "handlers": ["console", "app_file"],
                    "level": "WARNING" if not debug else "INFO",
                    "propagate": False,
                },
            },
        }
    )

