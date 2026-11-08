"""Blueprint registration for SmartWaste 2.0."""

from modules.authentication.routes import bp as auth_bp
from modules.complaints.routes import bp as complaints_bp
from modules.public.routes import bp as public_bp
from modules.admin.routes import bp as admin_bp
from modules.analytics.routes import bp as analytics_bp

ALL_BLUEPRINTS = (public_bp, auth_bp, complaints_bp, admin_bp, analytics_bp)


def register_blueprints(app):
    for blueprint in ALL_BLUEPRINTS:
        app.register_blueprint(blueprint)
