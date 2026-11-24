from urdunlp import normalize, transliterate_to_roman


def transliterate_urdu(text: str) -> dict:
    """Transliterate Urdu text while preserving the original OCR output."""
    if not isinstance(text, str) or not text.strip():
        return {
            "original_urdu": text if isinstance(text, str) else "",
            "normalized_urdu": "",
            "roman_urdu": "",
            "review_status": "needs_review",
        }

    # Process each line separately to preserve verse and stanza boundaries.
    normalized_lines = []
    roman_lines = []

    for line in text.splitlines():
        if not line.strip():
            normalized_lines.append(line)
            roman_lines.append(line)
            continue

        normalized_line = normalize(line)
        roman_line = transliterate_to_roman(normalized_line)

        normalized_lines.append(normalized_line)
        roman_lines.append(roman_line)

    normalized = "\n".join(normalized_lines)
    roman = "\n".join(roman_lines)

    return {
        "original_urdu": text,
        "normalized_urdu": normalized,
        "roman_urdu": roman,
        "review_status": "needs_review",
    }
