import logging

import httpx

logger = logging.getLogger(__name__)

PLATE_RECOGNIZER_URL = "https://api.platerecognizer.com/v1/plate-reader/"


async def detect_plate(image_bytes: bytes, api_token: str) -> list[dict] | None:
    """Send image to Plate Recognizer and return detection results.

    Returns list of dicts with keys: plate, confidence, region, ...
    Returns None on network/HTTP error (caller handles user-facing message).
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                PLATE_RECOGNIZER_URL,
                headers={"Authorization": f"Token {api_token}"},
                files={"upload": ("image.jpg", image_bytes, "image/jpeg")},
                data={"regions": ["ru"]},
            )
            response.raise_for_status()
            data = response.json()
            logger.info("Plate Recognizer API response: %s", data)
            return data.get("results", [])
    except Exception as e:
        logger.warning(f"Plate Recognizer API error: {e}", exc_info=True)
        return None
