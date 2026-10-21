# Label Pipeline on Replit

## Run

Press **Run** to start the **Start application** workflow, or run
`bash scripts/start.sh`. Python dependencies are installed through Replit's
package manager; the startup script must not run pip against system Python.
The script builds the React frontend when needed and starts FastAPI at `0.0.0.0:5000`.
FastAPI serves both the frontend and the relative `/api` routes.
The `PORT` environment variable can override the default port.

## Configuration and data

- Set `LABELS_API_SECRET` in Replit Secrets; enter that value on the app's
  login screen. Never put the password in source code or documentation.
- The existing app uses SQLite at `data/app.db` by default.
- Blob storage uses the app's existing automatic selection: Replit Object
  Storage when available, otherwise `data/blobs/`. Health information is
  available at `/api/health`.
- Fonts download in the background at startup. Real design artwork must be
  uploaded before generating production labels.
- Keep the existing Python/FastAPI and React/Vite structure. At startup the app
  migrates a database made before the fixed half-sheet layouts (geometry v2): it
  backs it up first (`data/backups/` and `backups/` in blob storage) and logs every
  change. Review persistent database and blob storage configuration separately
  before publishing.

## Checks

Run `python -m pytest` for the existing Python tests and
`cd frontend && npm run build` for TypeScript checking and the frontend build.
Tests use temporary local data rather than the workspace database.
