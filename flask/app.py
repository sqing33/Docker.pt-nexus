# run.py

import logging
from flask import Flask
from flask_cors import CORS

from config import get_db_config
from database import DatabaseManager, reconcile_historical_data
from services import start_data_tracker
from routes import api_bp, initialize_routes

# --- Global Logging Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [PID:%(process)d] - %(levelname)s - %(message)s')


def create_app():
    """Creates and configures the Flask application instance."""
    app = Flask(__name__)

    # Enable CORS for all API routes
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # 1. Configure and initialize the database
    db_config = get_db_config()
    db_manager = DatabaseManager(db_config)
    db_manager.init_db()
    reconcile_historical_data(db_manager)

    # 2. Inject the database manager into the routes and register the API blueprint
    initialize_routes(db_manager)
    app.register_blueprint(api_bp)

    # 3. Start the background data tracking service
    start_data_tracker(db_manager)

    logging.info("Application setup complete. Ready to serve requests.")
    return app


if __name__ == '__main__':
    flask_app = create_app()
    logging.info("Starting Flask development server as a pure API backend...")

    # use_reloader=False prevents the app from initializing twice in debug mode
    flask_app.run(host='0.0.0.0', port=5272, debug=True, use_reloader=False)
