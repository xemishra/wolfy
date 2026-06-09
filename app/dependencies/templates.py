from fastapi.templating import Jinja2Templates

from app.core.paths import TEMPLATES_DIR
from app.utils.text import name_initial

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["initial"] = name_initial
