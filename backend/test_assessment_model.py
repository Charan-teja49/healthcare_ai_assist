import io
import json
import unittest
from unittest.mock import patch

from backend.assessment_model import hypotheses


class AssessmentModelTests(unittest.TestCase):
    def test_emergency_bypasses_even_enabled_model(self):
        with (
            patch.dict("os.environ", {"OLLAMA_ASSESSMENT_ENABLED": "1"}),
            patch("backend.assessment_model.urlopen") as transport,
        ):
            self.assertIsNone(hypotheses({"symptoms": "chest pain"}, "EMERGENCY"))
            transport.assert_not_called()

    def test_remote_url_never_receives_patient_text(self):
        with (
            patch.dict(
                "os.environ",
                {
                    "OLLAMA_ASSESSMENT_ENABLED": "1",
                    "OLLAMA_URL": "https://remote.invalid",
                },
            ),
            patch("backend.assessment_model.urlopen") as transport,
        ):
            self.assertIsNone(
                hypotheses({"symptoms": "private fixture"}, "CONSULT_SOON")
            )
            transport.assert_not_called()

    def test_schema_valid_hypotheses_preserve_rank(self):
        data = {
            "response": json.dumps(
                {
                    "ranked_conditions": [
                        {
                            "name": "Cause undetermined",
                            "rationale": "Clinical examination is required.",
                            "rank": 1,
                        }
                    ]
                }
            )
        }
        with (
            patch.dict(
                "os.environ",
                {
                    "OLLAMA_ASSESSMENT_ENABLED": "1",
                    "OLLAMA_URL": "http://127.0.0.1:11434",
                },
            ),
            patch(
                "backend.assessment_model.urlopen",
                return_value=io.BytesIO(json.dumps(data).encode()),
            ),
        ):
            result = hypotheses({"symptoms": "fictional"}, "URGENT")
        self.assertEqual(result[0]["rank"], 1)

    def test_invalid_or_unavailable_model_returns_offline_fallback(self):
        with patch.dict(
            "os.environ",
            {"OLLAMA_ASSESSMENT_ENABLED": "1", "OLLAMA_URL": "http://127.0.0.1:11434"},
        ):
            for data in [
                {
                    "ranked_conditions": [
                        {
                            "name": "Cause undetermined",
                            "rationale": "Needs review",
                            "rank": 2,
                        }
                    ]
                },
                {"urgency": "SELF_CARE", "ranked_conditions": []},
            ]:
                with patch(
                    "backend.assessment_model.urlopen",
                    return_value=io.BytesIO(
                        json.dumps({"response": json.dumps(data)}).encode()
                    ),
                ):
                    self.assertIsNone(hypotheses({"symptoms": "fictional"}, "URGENT"))
            with patch("backend.assessment_model.urlopen", side_effect=TimeoutError):
                self.assertIsNone(hypotheses({}, "URGENT"))
