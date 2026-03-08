import ollama
import asyncio

async def generate_summary(prompt: str, model: str = 'qwen2.5:3b') -> str:
    try:
        response = await asyncio.to_thread(
            ollama.chat,
            model=model,
            messages=[{
                'role': 'user',
                'content': f"Fasse extrem knapp, ehrlich und strukturiert zusammen:\n\n{prompt}"
            }],
            options={'temperature': 0.4}
        )
        return response['message']['content'].strip()
    except Exception as e:
        return f"[LLM-Fehler: {str(e)}]"
