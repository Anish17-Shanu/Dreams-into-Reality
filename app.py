"""Dreams into Reality application created by Anish Kumar."""

from flask import Flask, flash, redirect, request, url_for
from config import Config
from extensions import db
from auth.routes import auth_bp
from dashboard.routes import dashboard_bp
from flask_migrate import Migrate
import os
from werkzeug.exceptions import RequestEntityTooLarge
from sqlalchemy import inspect, text


def _default_sql_literal(value):
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    escaped = str(value).replace("'", "''")
    return f"'{escaped}'"


def _build_add_column_sql(engine, table_name, column):
    preparer = engine.dialect.identifier_preparer
    quoted_table = preparer.quote(table_name)
    quoted_column = preparer.quote(column.name)
    column_type = column.type.compile(dialect=engine.dialect)
    default_sql = ""

    if column.default is not None and getattr(column.default, "is_scalar", False):
        default_sql = f" DEFAULT {_default_sql_literal(column.default.arg)}"

    return f"ALTER TABLE {quoted_table} ADD COLUMN {quoted_column} {column_type}{default_sql}"


def ensure_schema():
    db.create_all()

    engine = db.engine
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    for table in db.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue

        existing_columns = {column["name"] for column in inspector.get_columns(table.name)}
        missing_columns = [column for column in table.columns if column.name not in existing_columns]
        if not missing_columns:
            continue

        with engine.begin() as connection:
            for column in missing_columns:
                connection.execute(text(_build_add_column_sql(engine, table.name, column)))


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
    if os.getenv("AUTO_CREATE_SCHEMA", "true").lower() == "true":
        ensure_schema()

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
