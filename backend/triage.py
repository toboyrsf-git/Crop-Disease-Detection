"""
Confidence-Threshold Triage Engine
Implements triage logic, entropy evaluation, and escalation prioritization.
"""

import math
from typing import Dict, Any, List

# Threshold constants based on model calibration
HIGH_CONFIDENCE_THRESHOLD = 0.80
MEDIUM_CONFIDENCE_THRESHOLD = 0.50
CONFIDENCE_MARGIN_THRESHOLD = 0.35
MAX_ACCEPTABLE_ENTROPY = 0.70

def compute_entropy(probabilities: List[float]) -> float:
    """
    Computes normalized Shannon entropy across predictions.
    Entropy near 1.0 indicates high confusion / out-of-distribution sample.
    """
    n = len(probabilities)
    if n <= 1:
        return 0.0
    
    ent = 0.0
    for p in probabilities:
        if p > 1e-9:
            ent -= p * math.log(p)
    
    max_ent = math.log(n)
    return ent / max_ent if max_ent > 0 else 0.0


def evaluate_triage(
    predicted_class: str,
    top_confidence: float,
    second_confidence: float = 0.0,
    all_probabilities: List[float] = None,
    user_requested_escalation: bool = False
) -> Dict[str, Any]:
    """
    Evaluates model prediction outputs against calibrated safety thresholds.
    Never presents prediction as final diagnosis.

    Returns structured triage outcome with UI guidance and routing priority.
    """
    # --- Bug Fix 6: Normalize confidence values sent as percentages (e.g. 85.0 -> 0.85) ---
    # This prevents negative entropy and ensures all threshold comparisons are correct.
    if top_confidence > 1.0:
        top_confidence = top_confidence / 100.0
    if second_confidence > 1.0:
        second_confidence = second_confidence / 100.0
    # Clamp to [0, 1] to guard against any other out-of-range values
    top_confidence = max(0.0, min(1.0, top_confidence))
    second_confidence = max(0.0, min(1.0, second_confidence))

    margin = max(0.0, top_confidence - second_confidence)
    # Entropy fallback: use (1.0 - top_confidence) only when no probability vector is provided.
    # This produces a value in [0, 1], consistent with the normalized entropy range.
    entropy = compute_entropy(all_probabilities) if all_probabilities else (1.0 - top_confidence)
    
    # Check for Out-of-Distribution or Unknown class
    is_unknown_class = "Unknown" in predicted_class or "NonPlant" in predicted_class
    
    # Tier 3: Low Confidence / Out of Distribution / High Confusion
    if top_confidence < MEDIUM_CONFIDENCE_THRESHOLD or entropy > MAX_ACCEPTABLE_ENTROPY or is_unknown_class:
        tier = "tier_3_low_confidence"
        urgency = "urgent_review"
        ui_status = "Inconclusive / Out of Distribution"
        headline = "Screening Uncertain: Agronomist Follow-up Required"
        farmer_guidance = (
            "The model cannot reliably identify a disease in this photo. "
            "This may be due to lighting, background clutter, or rare symptoms. "
            "An agricultural extension officer has been notified to inspect your case."
        )
        needs_expert_review = True
        auto_escalate = True
        
    # Tier 2: Medium Confidence / Overlapping Symptoms
    elif top_confidence < HIGH_CONFIDENCE_THRESHOLD or margin < CONFIDENCE_MARGIN_THRESHOLD:
        tier = "tier_2_medium_confidence"
        urgency = "standard_review"
        ui_status = "Possible Match (Inconclusive)"
        headline = f"Potential signs of {predicted_class.replace('___', ' ')} detected"
        farmer_guidance = (
            "Screening indicates possible disease, but symptoms visually overlap with other conditions. "
            "Do not purchase or apply chemical pesticides yet. An expert review is recommended."
        )
        needs_expert_review = True
        auto_escalate = True
        
    # Tier 1: High Confidence Screening
    else:
        tier = "tier_1_high_confidence"
        urgency = "optional_review" if not user_requested_escalation else "farmer_requested"
        ui_status = "Screening Indicator"
        headline = f"Visual indicators match {predicted_class.replace('___', ' ')}"
        farmer_guidance = (
            "Preliminary screening matches known symptoms. Review cultural and organic field management practices below. "
            "Remember: This is a screening aid. Confirm with an agronomist before any chemical intervention."
        )
        needs_expert_review = user_requested_escalation
        auto_escalate = False

    return {
        "tier": tier,
        "urgency": urgency,
        "ui_status": ui_status,
        "headline": headline,
        "farmer_guidance": farmer_guidance,
        "top_confidence": round(top_confidence, 4),
        "second_confidence": round(second_confidence, 4),
        "confidence_margin": round(margin, 4),
        "prediction_entropy": round(entropy, 4),
        "needs_expert_review": needs_expert_review,
        "auto_escalated": auto_escalate,
        "disclaimer": (
            "⚠️ SCREENING AID ONLY: Not a certified diagnosis. "
            "Always consult an agricultural extension officer before applying pesticides."
        )
    }
