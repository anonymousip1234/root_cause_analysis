"""LLM synthesis client — thin wrapper for language phrasing only.

The LLM is called ONLY to polish language in report sections.
All reasoning, evidence association, and hypothesis ranking is done
by the deterministic engine BEFORE this is called.

If LLM is disabled (default), the engine's own text is used as-is.
"""

from pathlib import Path

from aiqe_rca.config import settings

PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_system_prompt() -> str:
    """Load the system prompt for LLM synthesis."""
    return (PROMPTS_DIR / "system.txt").read_text(encoding="utf-8")


def _load_section_prompt(section_name: str) -> str | None:
    """Load a section-specific prompt template, if it exists."""
    path = PROMPTS_DIR / f"section_{section_name}.txt"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def synthesize_text(
    section_name: str,
    raw_content: str,
    context: dict | None = None,
) -> str:
    """Optionally rephrase section content via LLM.

    If LLM is disabled (settings.llm_enabled == False), returns raw_content unchanged.
    If enabled, calls the configured LLM API with temperature=0 for deterministic output.

    Args:
        section_name: Key identifying the section (e.g., "executive_summary").
        raw_content: The engine-generated text to rephrase.
        context: Optional context variables for prompt template.

    Returns:
        Polished text (or raw_content if LLM disabled).
    """
    if not settings.llm_enabled:
        return raw_content

    if not settings.llm_api_key:
        return raw_content

    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.llm_api_key)

        system_prompt = _load_system_prompt()
        section_prompt = _load_section_prompt(section_name)

        if section_prompt and context:
            user_message = section_prompt.format(**context)
        else:
            user_message = (
                f"Rephrase the following {section_name} section text into clear, "
                f"engineer-friendly language. Do not add new information. "
                f"Preserve all evidence references and uncertainty language.\n\n"
                f"{raw_content}"
            )

        response = client.chat.completions.create(
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            max_tokens=1000,
        )

        result = response.choices[0].message.content
        return result.strip() if result else raw_content

    except Exception:
        # LLM failure is non-fatal — fall back to engine text
        return raw_content
