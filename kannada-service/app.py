from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from ai4bharat.transliteration import XlitEngine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("kannada-service")

app = FastAPI(title="Naatify Kannada Transliteration")

engine = None


class TransliterationRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50000)


@app.on_event("startup")
def load_model():
    global engine
    logger.info("Loading Kannada transliteration model...")
    engine = XlitEngine("kn", beam_width=5, rescore=False)
    logger.info("Kannada transliteration model loaded")


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": engine is not None}


@app.post("/transliterate")
def transliterate(request: TransliterationRequest):
    if engine is None:
        raise HTTPException(status_code=503, detail="Model is not loaded")

    if not request.text.strip():
        raise HTTPException(status_code=422, detail="Text cannot be empty")

    try:
        # Sentence-level inference preserves line and stanza breaks.
        lines = request.text.splitlines()
        output = []

        for line in lines:
            if not line.strip():
                output.append(line)
                continue

            result = engine.translit_sentence(line)
            converted = result.get("kn", "")
            output.append(converted if converted else line)

        return {
            "original_text": request.text,
            "kannada_text": "\n".join(output),
            "review_status": "needs_review",
        }
    except Exception:
        logger.exception("Kannada transliteration failed")
        raise HTTPException(
            status_code=500,
            detail="Kannada transliteration failed",
        )
