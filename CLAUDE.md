# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PT Nexus is a PT (Private Tracker) seed aggregation and analysis platform that collects and analyzes torrent data from qBittorrent and Transmission clients. The application provides traffic statistics, seed management, and site/group analytics through a web interface.

## Technology Stack

- **Frontend**: Vue 3 with TypeScript, Element Plus UI library, Vite build system
- **Backend**: Python Flask API with SQLite/MySQL database support
- **Deployment**: Docker container with multi-stage build (Node.js for frontend build, Python for backend)

## Architecture

The application follows a client-server architecture with a clear separation between frontend and backend:

1. **Frontend (vue3/)**: Vue 3 single-page application that communicates with the backend via REST API
2. **Backend (flask/)**: Flask API server that handles data processing, storage, and business logic
3. **Database**: Supports both SQLite (default) and MySQL backends
4. **Data Collection**: Direct integration with qBittorrent and Transmission client APIs

## Key Components

### Backend Structure
- `app.py`: Main Flask application entry point with app factory pattern
- `config.py`: Configuration management with default values and file persistence
- `database.py`: Database abstraction layer supporting SQLite and MySQL
- `api/`: REST API endpoints organized by functionality:
  - `routes_auth.py`: Authentication endpoints (JWT-based)
  - `routes_management.py`: System management and configuration
  - `routes_stats.py`: Traffic statistics and analytics
  - `routes_torrents.py`: Torrent data management
  - `routes_migrate.py`: Cross-seed functionality
- `core/`: Core services for data tracking and processing
- `sites/`: Site-specific parsing and data extraction logic
- `utils/`: Utility functions and helpers

### Frontend Structure
- `src/main.ts`: Application entry point
- `src/App.vue`: Main application component
- `src/router/`: Vue Router configuration
- `src/views/`: Page-level components (TorrentsView, SitesView, etc.)
- `src/components/`: Reusable UI components

## Common Development Tasks

### Building and Running

1. **Docker Deployment** (recommended):
   ```bash
   # Create docker-compose.yml first (see Deployment Details)
   docker-compose up -d
   ```

2. **Frontend Development**:
   ```bash
   cd vue3
   pnpm install
   pnpm dev
   ```

3. **Frontend Build**:
   ```bash
   cd vue3
   pnpm build
   ```

4. **Backend Development**:
   ```bash
   cd flask
   pip install -r requirements.txt
   python app.py
   ```

### Deployment Details

The application uses a multi-stage Docker build process:

1. **Frontend Build Stage**:
   - Uses Node.js 20-alpine as the base image
   - Installs pnpm package manager
   - Installs frontend dependencies
   - Builds the Vue 3 application for production

2. **Backend Runtime Stage**:
   - Uses Python 3.12-slim as the base image
   - Copies the built frontend assets from the previous stage
   - Installs Python dependencies from requirements.txt
   - Copies the Flask backend application
   - Installs system dependencies (ffmpeg, mediainfo)
   - Exposes port 5272 for the web interface
   - Mounts `/app/data` as a volume for persistent storage

3. **Data Persistence**:
   - SQLite database is stored in the `/app/data` directory
   - Configuration files are stored in the `/app/data` directory
   - Temporary files are stored in `/app/data/tmp`

4. **Volume Mounting**:
   - Mount the data directory to persist configuration and database
   - Example: `-v ./data:/app/data`

5. **Port Mapping**:
   - The container exposes port 5272
   - Map to a host port using `-p <host_port>:5272`

6. **Docker Compose Deployment**:
   Create a `docker-compose.yml` file with the following content:
   ```yaml
   services:
     pt-nexus:
       image: ghcr.io/sqing33/pt-nexus
       container_name: pt-nexus
       ports:
         - 5272:5272
       volumes:
         - ./data:/app/data
       environment:
         - TZ=Asia/Shanghai
         - DB_TYPE=sqlite
         - JWT_SECRET=please-change-me
         - AUTH_USERNAME=admin
         - AUTH_PASSWORD=your_password
   ```
   
   Then run:
   ```bash
   docker-compose up -d
   ```

### Backend Development Commands

1. **Install Python dependencies**:
   ```bash
   cd flask
   pip install -r requirements.txt
   ```

2. **Run the application**:
   ```bash
   cd flask
   python app.py
   ```

3. **Install in development mode** (if applicable):
   ```bash
   cd flask
   pip install -e .
   ```

### Frontend Development Commands

1. **Install dependencies**:
   ```bash
   cd vue3
   pnpm install
   ```

2. **Start development server**:
   ```bash
   cd vue3
   pnpm dev
   ```

3. **Build for production**:
   ```bash
   cd vue3
   pnpm build
   ```

4. **Preview production build**:
   ```bash
   cd vue3
   pnpm preview
   ```

5. **Type checking**:
   ```bash
   cd vue3
   pnpm type-check
   ```

### Testing

The project currently does not include dedicated test files or a testing framework. Testing is performed manually through the web interface. If you want to add tests, you would need to:

1. Choose a testing framework (pytest for Python backend, Vitest for Vue frontend)
2. Create test directories (`tests/` for backend, `vue3/tests/` for frontend)
3. Write unit and integration tests for critical functionality

### Linting and Formatting

Frontend linting can be performed with:
```bash
cd vue3
pnpm lint
```

To format code:
```bash
cd vue3
pnpm format
```

### Environment Variables

Key environment variables for configuration:

**Authentication Settings:**
- `JWT_SECRET`: JWT signing secret (required for production, strongly recommended to set in production)
- `AUTH_USERNAME`: Admin username (default: admin)
- `AUTH_PASSWORD`: Admin password (plaintext, for testing only)
- `AUTH_PASSWORD_HASH`: Admin password bcrypt hash (preferred over plaintext password)

**Database Settings:**
- `DB_TYPE`: Database type (sqlite or mysql, default: sqlite)
- `MYSQL_HOST`: MySQL database host (when DB_TYPE=mysql)
- `MYSQL_PORT`: MySQL database port (when DB_TYPE=mysql, default: 3306)
- `MYSQL_DATABASE`: MySQL database name (when DB_TYPE=mysql)
- `MYSQL_USER`: MySQL database username (when DB_TYPE=mysql)
- `MYSQL_PASSWORD`: MySQL database password (when DB_TYPE=mysql)

**System Settings:**
- `TZ`: Timezone setting for the container (e.g., Asia/Shanghai)

The application will first check for configuration in environment variables, then fall back to the config.json file for persistent settings. Environment variables take precedence over file-based configuration.

### Database Schema Management

The application uses automatic schema migration. New database columns are added automatically when missing, with backward compatibility maintained.

Database migrations are handled in the `_run_schema_migrations` method in `database.py`. The system checks for missing columns on startup and adds them as needed. Supported migrations include:
- Adding new columns to existing tables
- Removing deprecated columns (MySQL only, SQLite requires manual handling)
- Automatic table creation on first run

The system supports both SQLite (default) and MySQL backends. SQLite is recommended for single-user deployments, while MySQL is better for multi-user or high-traffic scenarios.

## API Endpoints

Main API routes (all prefixed with /api):
- `/api/auth/*`: Authentication endpoints
  - `POST /api/auth/login`: User login, returns JWT token
  - `GET /api/auth/status`: Get authentication status and user info
  - `POST /api/auth/change_password`: Change user password
- `/api/management/*`: System management and configuration
  - `GET /api/sites`: Get all configured sites
  - `POST /api/sites`: Add a new site
  - `PUT /api/sites/<id>`: Update an existing site
  - `DELETE /api/sites/<id>`: Delete a site
  - `GET /api/downloaders`: Get all configured downloaders
  - `POST /api/downloaders`: Add a new downloader
  - `PUT /api/downloaders/<id>`: Update an existing downloader
  - `DELETE /api/downloaders/<id>`: Delete a downloader
  - `POST /api/sync_now`: Force synchronization with downloaders
- `/api/stats/*`: Traffic statistics and analytics
  - `GET /api/stats/torrents`: Get torrent statistics
  - `GET /api/stats/sites`: Get site statistics
  - `GET /api/stats/groups`: Get group statistics
  - `GET /api/stats/speed`: Get speed statistics
  - `GET /api/stats/charts`: Get chart data for visualization
- `/api/torrents/*`: Torrent data management
  - `GET /api/torrents`: Get list of torrents with filtering options
  - `GET /api/torrents/<id>`: Get details for a specific torrent
  - `DELETE /api/torrents/<id>`: Delete a torrent
- `/api/migrate/*`: Cross-seed functionality
  - `GET /api/migrate/sites_list`: Get source and target sites for migration
  - `POST /api/migrate/check`: Check if a torrent exists on target site
  - `POST /api/migrate/upload`: Upload torrent to target site

All API endpoints (except auth) require JWT authentication via Bearer token in Authorization header.