# AURA-Med Live frontend

This directory contains the Phase 2 React + Tailwind single-page dashboard.
It talks to the FastAPI live API under `/api/v1/live` and subscribes to
`/api/v1/live/sessions/{sessionId}/events` over WebSocket.

The interface is a research/simulation view. It does not provide a diagnosis,
clinical monitoring, or medical advice. Values, quality flags, failure records,
and any future trend/trust fields are displayed from backend responses. The
frontend formats those fields for readability and does not reimplement backend
quality, trust, or classification calculations.

The dashboard is designed for high-contrast, keyboard-friendly review: status
meaning is written in text, chart lines use both color and line style, and the
chart has an expandable text data view. Completed recordings can be opened from
History and read as a stored, read-only replay after the backend restarts.

## Requirements

- Node.js `22.14.0` (pinned in `.nvmrc`)
- The FastAPI service running on `http://127.0.0.1:8000`

Set `VITE_API_BASE_URL` when the API is on another origin. Copy
`.env.example` to `.env.local` for the local default.

## Install and run

```bash
cd frontend
npm ci
npm run dev
```

Open `http://localhost:5173`. Vite proxies `/api` and WebSocket traffic to
`http://127.0.0.1:8000` during development. Start the backend separately with
the repository's documented Python command.

For a production bundle and local preview:

```bash
npm run build
npm run preview
```

The deployed host must route `/api` and WebSocket requests to the FastAPI
origin, or `VITE_API_BASE_URL` can point directly to that origin at build time.

## Test

```bash
npm test
```

The deterministic Vitest contract test drives the event flow used by the
dashboard: status → sample → missing reading → failure review. It verifies the
plain-English status mapping and confirms that omitted backend trend/trust
fields are not invented by the frontend.

There is no browser automation dependency in this compact frontend, so the
test suite does not click a real browser or open a live FastAPI process. The
manual smoke path is: create a session, start it, observe samples and the
WebSocket status, end it, open History and read-only review, expand the text
data view and technical details, then open the four export links. Check the
flow with keyboard navigation and at 200% browser zoom.
