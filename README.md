# Vision Codex

Vision Codex is an AI-powered visual code review app.

## Local development

1. Copy `.env.example` to `.env` and set `GEMINI_API_KEY`.
2. Start the API from `Backend/`:

   ```powershell
   python -m uvicorn main:app --reload --port 8080
   ```

3. Open `Frontend/index.html` in a browser. The frontend defaults to `http://localhost:8080`.

## Deployment

GitHub Pages publishes `Frontend/` through the workflow in `.github/workflows/pages.yml`.
The FastAPI backend cannot run on GitHub Pages; deploy it separately and set
`window.VISION_CODEX_API_BASE` before loading the frontend, or update the frontend
configuration to the deployed API URL. Keep `GEMINI_API_KEY` only in the backend
hosting provider's environment variables, never in frontend files or Git history.

Website: https://dibyadipto12345-pixel.github.io/Vision-Codex/
