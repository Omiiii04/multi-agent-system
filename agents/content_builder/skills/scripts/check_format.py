def check_format(text: str) -> dict:
    # Perform basic heading checks
    has_h1 = text.strip().startswith("# ")
    has_h2 = "## " in text
    
    if has_h1 and has_h2:
        return {
            "success": True,
            "message": "Formatting check passed: document has both H1 and H2 headings.",
        }

    missing = []
    if not has_h1:
        missing.append("main title (# H1)")
    if not has_h2:
        missing.append("section headings (## H2)")

    return {
        "success": False,
        "message": f"Formatting check failed. Missing: {', '.join(missing)}.",
    }
