"""
Gemini 2.5 Pro commentary client.
Generates a 2-sentence live race strategy insight per lap.
API key stored in Secrets Manager: f1-mlops/gemini-api-key
Cached at module level — refreshes every session (cold start).
"""
import json
import logging
import time
import boto3
import google.generativeai as genai

logger = logging.getLogger(__name__)

_api_key_cache: dict = {}   # {"key": str, "fetched_at": float}
_KEY_TTL = 3600             # re-fetch after 1 hour


def _get_api_key() -> str:
    now = time.time()
    if _api_key_cache.get("key") and now - _api_key_cache.get("fetched_at", 0) < _KEY_TTL:
        return _api_key_cache["key"]
    client = boto3.client("secretsmanager", region_name="us-east-1")
    resp = client.get_secret_value(SecretId="f1-mlops/gemini-api-key")
    key = json.loads(resp["SecretString"])["api_key"]
    _api_key_cache["key"] = key
    _api_key_cache["fetched_at"] = now
    return key


def generate_race_commentary(predictions: list, safety_car: bool, session_key: str) -> str:
    """
    Generate a 2-sentence race strategy commentary using Gemini 2.5 Pro.
    Uses top-3 highest-probability predictions as context.

    Returns a commentary string, or "" on failure (non-blocking).
    """
    if not predictions:
        return ""
    try:
        key = _get_api_key()
        genai.configure(api_key=key)
        model = genai.GenerativeModel("gemini-2.5-pro")

        top = sorted(predictions, key=lambda p: p.get("pitstop_probability", 0), reverse=True)[:3]

        driver_lines = []
        for p in top:
            driver = p.get("driver_name", p.get("driver", "Unknown"))
            team = p.get("team", "")
            prob = p.get("pitstop_probability", 0) * 100
            tyre = p.get("tyre_compound", "?")
            age = p.get("tyre_age", "?")
            pos = p.get("position", "?")
            driver_lines.append(
                f"  P{pos} {driver} ({team}): {prob:.0f}% pitstop probability, "
                f"{tyre} tyres aged {age} laps"
            )

        sc_note = " Safety car is currently deployed." if safety_car else ""
        prompt = (
            f"You are an F1 race strategist providing live commentary during session {session_key}.{sc_note}\n"
            f"Current pitstop predictions:\n" + "\n".join(driver_lines) + "\n\n"
            "In exactly 2 sentences, give sharp tactical commentary: who is most likely to pit and why, "
            "and what the strategic implication is for the race. Be specific and direct, as if speaking live on TV."
        )

        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                max_output_tokens=120,
                temperature=0.7,
            ),
        )
        return response.text.strip()
    except Exception as e:
        logger.warning(f"Gemini commentary failed (non-critical): {e}")
        return ""
