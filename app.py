from flask import Flask, flash, redirect, request, url_for
from config import Config
from extensions import db
from auth.routes import auth_bp
from dashboard.routes import dashboard_bp
from flask_migrate import Migrate
import os
from werkzeug.exceptions import RequestEntityTooLarge


app = Flask(__name__)
app.config.from_object(Config)
migrate = Migrate(app, db)
db.init_app(app)

# Register blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(dashboard_bp)


@app.errorhandler(RequestEntityTooLarge)
def handle_large_upload(error):
    max_mb = app.config.get("MAX_CONTENT_LENGTH_MB", 20)
    flash(f"Upload too large. Max allowed size is {max_mb} MB.")
    if request.path.startswith("/roadmap/new"):
        return redirect(url_for("dashboard.create_roadmap"))
    return redirect(url_for("dashboard.dashboard"))

with app.app_context():
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    if os.getenv("AUTO_CREATE_SCHEMA", "false").lower() == "true":
        db.create_all()

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
