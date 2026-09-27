"""
Unit tests for Crop Disease Screening Triage & Escalation System.
"""

import unittest
import sys
import os

# Add parent directory to path so imports resolve
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.triage import evaluate_triage, compute_entropy
from backend.database import init_db, save_case, get_case, save_expert_review, export_retraining_data

class TestCropScreeningTriage(unittest.TestCase):

    def setUp(self):
        init_db()

    def test_high_confidence_tier_1(self):
        """High confidence with clear margin should be Tier 1 and NOT auto-escalate."""
        result = evaluate_triage(
            predicted_class="Tomato___Early_blight",
            top_confidence=0.92,
            second_confidence=0.05,
            user_requested_escalation=False
        )
        self.assertEqual(result["tier"], "tier_1_high_confidence")
        self.assertEqual(result["urgency"], "optional_review")
        self.assertFalse(result["needs_expert_review"])
        self.assertFalse(result["auto_escalated"])
        self.assertIn("SCREENING AID ONLY", result["disclaimer"])

    def test_medium_confidence_tier_2(self):
        """Confidence between 0.50 and 0.80 should be Tier 2 and auto-escalate."""
        result = evaluate_triage(
            predicted_class="Tomato___Late_blight",
            top_confidence=0.74,
            second_confidence=0.20,
            user_requested_escalation=False
        )
        self.assertEqual(result["tier"], "tier_2_medium_confidence")
        self.assertEqual(result["urgency"], "standard_review")
        self.assertTrue(result["needs_expert_review"])
        self.assertTrue(result["auto_escalated"])

    def test_narrow_margin_ambiguity(self):
        """Even with high top confidence, narrow margin (<0.35) between top two classes triggers Tier 2."""
        result = evaluate_triage(
            predicted_class="Tomato___Early_blight",
            top_confidence=0.82,
            second_confidence=0.78,  # Margin is only 0.04
            user_requested_escalation=False
        )
        self.assertEqual(result["tier"], "tier_2_medium_confidence")
        self.assertTrue(result["needs_expert_review"])

    def test_low_confidence_ood_tier_3(self):
        """Confidence below 0.50 or Out-Of-Distribution triggers urgent Tier 3 triage."""
        result = evaluate_triage(
            predicted_class="Unknown_or_NonPlant",
            top_confidence=0.35,
            second_confidence=0.25,
            user_requested_escalation=False
        )
        self.assertEqual(result["tier"], "tier_3_low_confidence")
        self.assertEqual(result["urgency"], "urgent_review")
        self.assertTrue(result["needs_expert_review"])
        self.assertTrue(result["auto_escalated"])

    def test_entropy_calculation(self):
        """Flat probability distribution should produce normalized entropy close to 1.0."""
        # 10 equally probable classes -> high confusion
        flat_probs = [0.1] * 10
        entropy = compute_entropy(flat_probs)
        self.assertAlmostEqual(entropy, 1.0, places=2)

        # 1 dominant class -> low entropy
        sharp_probs = [0.98] + [0.002] * 10
        entropy_sharp = compute_entropy(sharp_probs)
        self.assertLess(entropy_sharp, 0.20)

    def test_database_escalation_and_review_flow(self):
        """Tests complete life cycle: Case submission -> Case lookup -> Expert review -> Retraining export."""
        case_id = f"TEST-CASE-{os.urandom(4).hex()}"
        case_data = {
            "id": case_id,
            "crop": "Tomato",
            "predicted_class": "Tomato___Early_blight",
            "confidence": 0.65,
            "second_class": "Tomato___Septoria_leaf_spot",
            "second_confidence": 0.28,
            "entropy": 0.45,
            "tier": "tier_2_medium_confidence",
            "urgency": "standard_review",
            "status": "pending_review",
            "image_path": "/uploads/test_leaf.jpg",
            "farmer_notes": "Yellow spots on lowest foliage",
            "location_coords": "Sector 4-B",
            "farmer_id": "test_farmer_99",
            "user_requested_escalation": True
        }

        # 1. Save case
        saved_id = save_case(case_data)
        self.assertEqual(saved_id, case_id)

        # 2. Fetch case
        retrieved = get_case(case_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved["status"], "pending_review")

        # 3. Expert reviews and corrects diagnosis
        review_data = {
            "case_id": case_id,
            "expert_id": "Agronomist_Sarah",
            "verified_class": "Tomato___Septoria_leaf_spot",
            "severity_rating": "moderate",
            "prescribed_actions": "Prune lower leaves, avoid evening sprinkler irrigation.",
            "expert_notes": "Concentric rings are missing central bullseye; confirmed Septoria."
        }
        review_id = save_expert_review(review_data)
        self.assertGreater(review_id, 0)

        # 4. Check that case is now resolved / reviewed
        updated_case = get_case(case_id)
        self.assertEqual(updated_case["status"], "reviewed")
        self.assertIsNotNone(updated_case["expert_review"])
        self.assertEqual(updated_case["expert_review"]["verified_class"], "Tomato___Septoria_leaf_spot")
        self.assertEqual(updated_case["expert_review"]["agreement"], 0)  # Expert corrected model

        # 5. Check active learning export includes this sample
        export_samples = export_retraining_data()
        sample_ids = [s["id"] for s in export_samples]
        self.assertIn(case_id, sample_ids)


if __name__ == "__main__":
    unittest.main()
