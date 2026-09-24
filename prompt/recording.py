"""Small helpers for storing the exact text supplied to an LLM."""

from sqlalchemy.ext.asyncio import AsyncSession

from models import Prompt


def render_prompt_snapshot(system_instructions: str, user_prompt: str) -> str:
    """Keep both model-facing message parts in one readable text snapshot."""

    return (
        "SYSTEM INSTRUCTIONS\n"
        f"{system_instructions}\n\n"
        "USER PROMPT\n"
        f"{user_prompt}"
    )


async def record_prompt(
    db: AsyncSession,
    *,
    name: str,
    prompt_type: str,
    system_instructions: str,
    user_prompt: str,
) -> Prompt:
    """Create and flush one immutable snapshot before its model call."""

    prompt = Prompt(
        prm_name=name,
        prm_type=prompt_type,
        prm_version=1,
        prm_prompt_text=render_prompt_snapshot(
            system_instructions,
            user_prompt,
        ),
    )
    db.add(prompt)
    await db.flush()
    return prompt
