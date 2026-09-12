import os
import json
import re
import logging
from typing import Literal, Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import google.generativeai as genai

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vision-codex")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")
raw_origins = os.environ.get("ALLOWED_ORIGINS", "*")
if raw_origins.strip() == "*":
    ALLOWED_ORIGINS = ["*"]
    ALLOW_CREDENTIALS = False
else:
    ALLOWED_ORIGINS = [orig.strip() for orig in raw_origins.split(",") if orig.strip()]
    ALLOW_CREDENTIALS = True

AnalysisMode = Literal["security", "architecture", "performance", "wireframe"]

app = FastAPI(title="Vision Codex API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=ALLOW_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Finding(BaseModel):
    severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW", "PERF", "SUGGESTION"]
    title: str
    explanation: str
    recommendation: Optional[str] = None


class AnalysisResponse(BaseModel):
    mode: AnalysisMode
    summary: str
    findings: list[Finding]
    generated_code: Optional[str] = None


PROMPTS = {
    "security": "You are a senior application security engineer. Examine this image carefully. It may show code, a system architecture diagram, or a flowchart. Identify every security vulnerability you can find.",
    "architecture": "You are a principal software architect. Examine this system architecture diagram or design sketch. Identify every architectural flaw, single points of failure, missing redundancy, and anti-patterns.",
    "performance": "You are a performance engineering expert. Examine this code screenshot or system diagram. Identify every performance risk including N+1 queries, missing caching, blocking calls, and inefficient algorithms.",
    "wireframe": "You are a senior frontend engineer. Examine this wireframe or UI sketch. Produce a complete production-ready React functional component with Tailwind CSS that implements the UI layout shown.",
}

FORMAT = """
You MUST respond with ONLY a valid JSON object. No markdown, no code fences, no explanation text before or after. Just raw JSON.

The JSON must follow this exact structure:
{
  "summary": "one sentence summary of the analysis",
  "findings": [
    {
      "severity": "CRITICAL",
      "title": "short title",
      "explanation": "why this is a problem",
      "recommendation": "how to fix it"
    }
  ],
  "generated_code": null
}

Severity must be one of: CRITICAL, HIGH, MEDIUM, LOW, PERF, SUGGESTION
For wireframe mode, put the React component code as a string in generated_code field.
For all other modes, set generated_code to null.
If no issues found, return empty findings array.
Start your response with { and end with }. Nothing else.
"""


def parse_json_response(text: str) -> dict:
    """Try multiple strategies to extract JSON from model response."""
    try:
        return json.loads(text.strip())
    except Exception:
        pass

    cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", text.strip())
    try:
        return json.loads(cleaned.strip())
    except Exception:
        pass

    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end+1])
        except Exception:
            pass

    logger.error("All JSON parse strategies failed. Raw response: %s", text[:800])
    raise ValueError("Could not extract JSON from model response")


@app.get("/")
def root():
    return {
        "service": "Vision Codex API",
        "status": "running",
        "model": MODEL_NAME,
        "docs": "/docs",
        "health": "/health"
    }


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL_NAME, "gemini_ready": bool(GEMINI_API_KEY)}


@app.post("/analyze", response_model=AnalysisResponse)
async def analyze(
    file: UploadFile = File(...),
    mode: AnalysisMode = Form(...),
):
    if not GEMINI_API_KEY:
        raise HTTPException(500, "Server is missing GEMINI_API_KEY")

    allowed_types = {"image/png", "image/jpeg", "image/jpg", "image/webp"}
    if file.content_type not in allowed_types:
        raise HTTPException(400, f"Unsupported file type: {file.content_type}")

    raw = await file.read()
    if len(raw) > 8 * 1024 * 1024:
        raise HTTPException(400, "File too large — max 8MB")

    prompt = PROMPTS[mode] + "\n\n" + FORMAT

    try:
        model = genai.GenerativeModel(MODEL_NAME)
        image_part = {"mime_type": file.content_type, "data": raw}

        generation_config = genai.types.GenerationConfig(
            temperature=0.1,
            response_mime_type="application/json",
        )

        result = model.generate_content(
            [prompt, image_part],
            generation_config=generation_config,
        )
        raw_text = result.text
        logger.info("Model raw response (first 300 chars): %s", raw_text[:300])

    except Exception as exc:
        logger.exception("Gemini API call failed")
        raise HTTPException(502, f"Model request failed: {exc}")

    try:
        parsed = parse_json_response(raw_text)
    except Exception:
        return AnalysisResponse(
            mode=mode,
            summary="Analysis completed but response format was unexpected.",
            findings=[Finding(
                severity="SUGGESTION",
                title="Raw model response",
                explanation=raw_text[:500],
                recommendation="Try again — the model occasionally returns unstructured responses.",
            )],
            generated_code=None,
        )

    findings_raw = parsed.get("findings", [])
    findings = []
    for f in findings_raw:
        try:
            findings.append(Finding(**f))
        except Exception:
            continue

    return AnalysisResponse(
        mode=mode,
        summary=parsed.get("summary", "Analysis complete."),
        findings=findings,
        generated_code=parsed.get("generated_code"),
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)