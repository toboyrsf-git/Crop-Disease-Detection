"""
FastAPI Backend Service for Crop Disease Screening & Expert Escalation.
"""

import os
import io
import uuid
import base64
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse
from pydantic import BaseModel
from PIL import Image

from .database import (
    init_db, save_case, get_case, list_cases,
    save_expert_review, export_retraining_data, escalate_case
)
from .triage import evaluate_triage

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)

# Initialize database tables
init_db()

app = FastAPI(
    title="Crop Disease Screening Aid API",
    description="Photo-based screening aid prioritizing human expert follow-up for smallholder farmers.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------- Models -----------------

class TriageSubmission(BaseModel):
    crop: Optional[str] = "Unknown"
    predicted_class: str
    confidence: float
    second_class: Optional[str] = None
    second_confidence: Optional[float] = 0.0
    entropy: Optional[float] = None
    image_base64: Optional[str] = None
    farmer_notes: Optional[str] = ""
    location_coords: Optional[str] = "Rural Field"
    farmer_id: Optional[str] = "anonymous_farmer"
    model_version: Optional[str] = "v1.0.0-mobilenetv3-quantized"
    user_requested_escalation: Optional[bool] = False

class ExpertReviewSubmission(BaseModel):
    expert_id: str
    verified_class: str
    severity_rating: str  # mild, moderate, severe, critical
    prescribed_actions: str
    expert_notes: str

# ----------------- Image Helper -----------------

def compress_and_save_image(b64_str: str) -> tuple[str, str]:
    """
    Compresses image for low-bandwidth cellular networks.
    Saves high-res (max 1024px, 80% quality) and low-res thumbnail (256px).
    Returns ("", "") gracefully if payload is missing or corrupted (Bug Fix 5).
    """
    if not b64_str:
        return "", ""

    try:
        if "," in b64_str:
            b64_str = b64_str.split(",", 1)[1]

        img_bytes = base64.b64decode(b64_str)
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    except Exception as exc:
        # Bug Fix 5: Corrupted or truncated base64 payloads (dropped network packets,
        # malformed uploads) are logged and handled gracefully instead of HTTP 500.
        print(f"[WARN] compress_and_save_image: failed to decode image – {exc}")
        return "", ""

    unique_name = f"leaf_{uuid.uuid4().hex[:10]}"
    main_filename = f"{unique_name}.jpg"
    thumb_filename = f"{unique_name}_thumb.jpg"

    main_path = os.path.join(UPLOADS_DIR, main_filename)
    thumb_path = os.path.join(UPLOADS_DIR, thumb_filename)

    # Compress standard view (max 1024px)
    img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
    img.save(main_path, "JPEG", quality=80, optimize=True)

    # Save thumbnail (max 256px) for ultra-low bandwidth dashboard lists
    img.thumbnail((256, 256), Image.Resampling.LANCZOS)
    img.save(thumb_path, "JPEG", quality=60, optimize=True)

    return f"/uploads/{main_filename}", f"/uploads/{thumb_filename}"

# ----------------- Routes -----------------

@app.get("/api/health")
def health_check():
    return {"status": "ok", "service": "Crop Disease Screening Aid"}

@app.get("/api/labels")
def get_labels():
    labels_file = os.path.join(PROJECT_DIR, "ml", "labels.json")
    if os.path.exists(labels_file):
        with open(labels_file, "r", encoding="utf-8") as f:
            import json
            return json.load(f)
    return {"classes": []}

@app.get("/api/model/info")
def get_model_info():
    meta_file = os.path.join(PROJECT_DIR, "ml", "model_metadata.json")
    if os.path.exists(meta_file):
        with open(meta_file, "r", encoding="utf-8") as f:
            import json
            return json.load(f)
    return {
        "model_version": "v1.0.0-mobilenetv3-quantized",
        "triage_thresholds": {"high_confidence_min": 0.80, "medium_confidence_min": 0.50}
    }

@app.post("/api/cases")
def submit_case(payload: TriageSubmission):
    """
    Ingests photo screening from farmer device, performs confidence-based triage,
    and enqueues case if expert review is warranted.
    """
    case_id = f"CASE-{datetime.now(timezone.utc).strftime('%y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    
    # Compute confidence margin and entropy-informed triage
    triage_result = evaluate_triage(
        predicted_class=payload.predicted_class,
        top_confidence=payload.confidence,
        second_confidence=payload.second_confidence or 0.0,
        all_probabilities=None,
        user_requested_escalation=payload.user_requested_escalation
    )
    
    # Compress and store image
    main_url, thumb_url = compress_and_save_image(payload.image_base64 or "")
    
    # Prepare record
    case_record = {
        "id": case_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "crop": payload.crop,
        "predicted_class": payload.predicted_class,
        "confidence": payload.confidence,
        "second_class": payload.second_class,
        "second_confidence": payload.second_confidence,
        "entropy": triage_result["prediction_entropy"],
        "tier": triage_result["tier"],
        "urgency": triage_result["urgency"],
        "status": "pending_review" if triage_result["needs_expert_review"] else "resolved",
        "image_path": main_url,
        "image_compressed_path": thumb_url,
        "farmer_notes": payload.farmer_notes,
        "location_coords": payload.location_coords,
        "farmer_id": payload.farmer_id,
        "model_version": payload.model_version,
        "user_requested_escalation": payload.user_requested_escalation
    }
    
    save_case(case_record)
    
    return {
        "case_id": case_id,
        "triage": triage_result,
        "image_url": main_url,
        "enqueued_for_expert": triage_result["needs_expert_review"]
    }

@app.get("/api/cases")
def get_cases(status: Optional[str] = None, urgency: Optional[str] = None, limit: int = 50):
    """
    Returns prioritized case list for agronomists / extension workers.
    """
    return list_cases(status=status, urgency=urgency, limit=limit)

@app.get("/api/cases/{case_id}")
def get_case_detail(case_id: str):
    case = get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return case

@app.post("/api/cases/{case_id}/review")
def review_case(case_id: str, review: ExpertReviewSubmission):
    """
    Agronomist submits verified diagnosis, cultural recommendations, and feedback.
    """
    case = get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    review_record = {
        "case_id": case_id,
        "expert_id": review.expert_id,
        "verified_class": review.verified_class,
        "severity_rating": review.severity_rating,
        "prescribed_actions": review.prescribed_actions,
        "expert_notes": review.expert_notes
    }

    review_id = save_expert_review(review_record)
    return {
        "status": "success",
        "review_id": review_id,
        "case_id": case_id,
        "message": "Expert diagnosis saved and routed to farmer feedback channel."
    }


@app.patch("/api/cases/{case_id}/escalate")
def escalate_existing_case(case_id: str):
    """
    Bug Fix 2: Farmer escalates an already-submitted Tier-1 case for expert review
    WITHOUT creating a duplicate case record. Upgrades urgency to 'farmer_requested'
    and returns the updated status. The client sends PATCH to this endpoint instead
    of a second POST to /api/cases.
    """
    case = get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    updated = escalate_case(case_id)
    if not updated:
        return {"status": "no_change", "case_id": case_id, "message": "Case already reviewed or not found."}

    return {
        "status": "escalated",
        "case_id": case_id,
        "message": "Case promoted to agronomist review queue."
    }

@app.get("/api/export/retraining")
def get_retraining_dataset():
    """
    Exports expert-validated feedback samples for active learning and model retraining.
    """
    records = export_retraining_data()
    return {
        "total_verified_samples": len(records),
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "data": records
    }

# ----------------- Static File Mounts -----------------

# Uploaded images directory
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")

# Expert Portal redirect for URL convenience
@app.get("/expert")
def redirect_to_expert():
    return RedirectResponse(url="/expert/")

# Expert Portal
EXPERT_DIR = os.path.join(PROJECT_DIR, "expert_portal")
if os.path.exists(EXPERT_DIR):
    app.mount("/expert", StaticFiles(directory=EXPERT_DIR, html=True), name="expert")

# Client PWA (Served at root)
CLIENT_DIR = os.path.join(PROJECT_DIR, "client")
if os.path.exists(CLIENT_DIR):
    app.mount("/", StaticFiles(directory=CLIENT_DIR, html=True), name="client")
