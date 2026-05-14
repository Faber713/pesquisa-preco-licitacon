from flask import Blueprint, current_app, render_template

from auth.decorators import login_required

main_bp = Blueprint("main", __name__)


@main_bp.get("/")
@login_required
def index():
    return render_template(
        "index.html",
        app_name=current_app.config["APP_NAME"],
        status="Flask carregado com sucesso",
    )
