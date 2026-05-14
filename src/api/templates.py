"""
Shared Jinja2Templates instance used across all route modules.
Centralising here ensures Jinja2 globals (e.g. user_initials) are
available in every template without each route needing its own instance.
"""
from fastapi.templating import Jinja2Templates
from src.config import settings

templates = Jinja2Templates(directory=settings.templates_dir)
