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

### Environment Variables

Key environment variables for configuration:
- `JWT_SECRET`: JWT signing secret (required for production)
- `AUTH_USERNAME`: Admin username (default: admin)
- `AUTH_PASSWORD`: Admin password (plaintext, for testing)
- `AUTH_PASSWORD_HASH`: Admin password bcrypt hash (preferred)
- `DB_TYPE`: Database type (sqlite or mysql)
- `MYSQL_*`: MySQL connection parameters (when DB_TYPE=mysql)

### Database Schema Management

The application uses automatic schema migration. New database columns are added automatically when missing, with backward compatibility maintained.

## API Endpoints

Main API routes (all prefixed with /api):
- `/api/auth/*`: Authentication endpoints
- `/api/management/*`: System management and configuration
- `/api/stats/*`: Traffic statistics and analytics
- `/api/torrents/*`: Torrent data management
- `/api/migrate/*`: Cross-seed functionality

All API endpoints (except auth) require JWT authentication via Bearer token in Authorization header.