"""
Database layer for Crop Disease Screening Aid.
Uses SQLite with WAL mode for fast concurrent reads and writes.
"""

import sqlite3
import os
import json
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "crop_disease.db")

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    # Cases table (Farmer submissions + triage status)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cases (
        id TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        crop TEXT,
        predicted_class TEXT NOT NULL,
        confidence REAL NOT NULL,
        second_class TEXT,
        second_confidence REAL,
        entropy REAL,
        tier TEXT NOT NULL,
        urgency TEXT NOT NULL,
        status TEXT NOT NULL,
        image_path TEXT,
        image_compressed_path TEXT,
        farmer_notes TEXT,
        location_coords TEXT,
        farmer_id TEXT,
        model_version TEXT,
        user_requested_escalation INTEGER DEFAULT 0
    )
    """)
    
    # Expert reviews table (Agronomist audit & feedback)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS expert_reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        case_id TEXT NOT NULL,
        expert_id TEXT NOT NULL,
        verified_class TEXT NOT NULL,
        agreement INTEGER NOT NULL,
        severity_rating TEXT,
        prescribed_actions TEXT,
        expert_notes TEXT,
        reviewed_at TEXT NOT NULL,
        FOREIGN KEY (case_id) REFERENCES cases (id)
    )
    """)
    
    conn.commit()
    conn.close()

def save_case(case_data: Dict[str, Any]) -> str:
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
    INSERT INTO cases (
        id, created_at, crop, predicted_class, confidence,
        second_class, second_confidence, entropy, tier, urgency,
        status, image_path, image_compressed_path, farmer_notes,
        location_coords, farmer_id, model_version, user_requested_escalation
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        case_data["id"],
        case_data.get("created_at", datetime.now(timezone.utc).isoformat()),
        case_data.get("crop", "Unknown"),
        case_data["predicted_class"],
        float(case_data["confidence"]),
        case_data.get("second_class"),
        float(case_data.get("second_confidence", 0.0)),
        float(case_data.get("entropy", 0.0)),
        case_data["tier"],
        case_data["urgency"],
        case_data.get("status", "pending_review"),
        case_data.get("image_path", ""),
        case_data.get("image_compressed_path", ""),
        case_data.get("farmer_notes", ""),
        case_data.get("location_coords", "Rural Field"),
        case_data.get("farmer_id", "anonymous_farmer"),
        case_data.get("model_version", "v1.0.0"),
        1 if case_data.get("user_requested_escalation") else 0
    ))
    
    conn.commit()
    conn.close()
    return case_data["id"]

def get_case(case_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM cases WHERE id = ?", (case_id,))
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        return None
        
    case_dict = dict(row)
    
    # Check for associated expert review
    cursor.execute("SELECT * FROM expert_reviews WHERE case_id = ? ORDER BY reviewed_at DESC LIMIT 1", (case_id,))
    review = cursor.fetchone()
    if review:
        case_dict["expert_review"] = dict(review)
    else:
        case_dict["expert_review"] = None
        
    conn.close()
    return case_dict

def list_cases(status: Optional[str] = None, urgency: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    
    query = "SELECT * FROM cases WHERE 1=1"
    params = []
    
    if status:
        query += " AND status = ?"
        params.append(status)
    if urgency:
        query += " AND urgency = ?"
        params.append(urgency)
        
    # Sort order: urgent_review first, then standard_review, farmer_requested, then recent
    query += """
    ORDER BY 
        CASE urgency
            WHEN 'urgent_review' THEN 1
            WHEN 'standard_review' THEN 2
            WHEN 'farmer_requested' THEN 3
            ELSE 4
        END,
        created_at DESC
    LIMIT ?
    """
    params.append(limit)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    
    results = []
    for r in rows:
        d = dict(r)
        # Check review
        cursor.execute("SELECT * FROM expert_reviews WHERE case_id = ?", (d["id"],))
        rev = cursor.fetchone()
        d["expert_review"] = dict(rev) if rev else None
        results.append(d)
        
    conn.close()
    return results

def save_expert_review(review_data: Dict[str, Any]) -> int:
    """
    Bug Fix 3: Uses INSERT OR REPLACE (UPSERT) so an agronomist can revise
    their notes without creating duplicate training samples. Each case_id
    always has exactly ONE canonical ground-truth review record.
    """
    conn = get_db()
    cursor = conn.cursor()

    # Calculate agreement with model prediction
    cursor.execute("SELECT predicted_class FROM cases WHERE id = ?", (review_data["case_id"],))
    row = cursor.fetchone()
    agreement = 1 if row and row["predicted_class"] == review_data["verified_class"] else 0

    # Check if a review already exists for this case
    cursor.execute("SELECT id FROM expert_reviews WHERE case_id = ?", (review_data["case_id"],))
    existing = cursor.fetchone()

    if existing:
        # Bug Fix 3: UPDATE the existing record instead of INSERTing a duplicate
        cursor.execute("""
        UPDATE expert_reviews SET
            expert_id = ?, verified_class = ?, agreement = ?,
            severity_rating = ?, prescribed_actions = ?, expert_notes = ?, reviewed_at = ?
        WHERE case_id = ?
        """, (
            review_data.get("expert_id", "Extension_Officer_01"),
            review_data["verified_class"],
            agreement,
            review_data.get("severity_rating", "moderate"),
            review_data.get("prescribed_actions", ""),
            review_data.get("expert_notes", ""),
            datetime.now(timezone.utc).isoformat(),
            review_data["case_id"]
        ))
        review_id = existing["id"]
    else:
        cursor.execute("""
        INSERT INTO expert_reviews (
            case_id, expert_id, verified_class, agreement,
            severity_rating, prescribed_actions, expert_notes, reviewed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            review_data["case_id"],
            review_data.get("expert_id", "Extension_Officer_01"),
            review_data["verified_class"],
            agreement,
            review_data.get("severity_rating", "moderate"),
            review_data.get("prescribed_actions", ""),
            review_data.get("expert_notes", ""),
            datetime.now(timezone.utc).isoformat()
        ))
        review_id = cursor.lastrowid

    # Update case status to reviewed
    cursor.execute("UPDATE cases SET status = 'reviewed' WHERE id = ?", (review_data["case_id"],))
    conn.commit()
    conn.close()
    return review_id


def escalate_case(case_id: str) -> bool:
    """
    Bug Fix 2: Promotes an existing Tier-1 case to expert review queue IN-PLACE
    without creating a duplicate case record. The client calls PATCH /api/cases/<id>/escalate
    instead of POST /api/cases again.
    Returns True if the case was found and updated, False otherwise.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE cases SET urgency = 'farmer_requested', status = 'pending_review' WHERE id = ? AND status != 'reviewed'",
        (case_id,)
    )
    updated = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return updated

def export_retraining_data() -> List[Dict[str, Any]]:
    """
    Exports expert-confirmed cases for active learning retraining loops.
    """
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
    SELECT 
        c.id, c.image_path, c.predicted_class, c.confidence,
        r.verified_class, r.agreement, r.severity_rating, r.reviewed_at
    FROM cases c
    JOIN expert_reviews r ON c.id = r.case_id
    WHERE c.image_path IS NOT NULL AND c.image_path != ''
    """)
    
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]
