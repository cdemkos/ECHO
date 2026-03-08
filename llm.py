import ollama
import asyncio

async def generate_summary(prompt: str, model: str = 'qwen2.5:3b') -> str:
    try:
        response = await asyncio.to_thread(
            ollama.chat,
            model=model,
            messages=[{
                'role': 'user',
                'content': prompt
            }],
            options={'temperature': 0.35}  # etwas deterministischer
        )
        return response['message']['content'].strip()
    except Exception as e:
        return f"[LLM-Fehler: {str(e)}. Bitte überprüfe, ob Ollama läuft und das Modell '{model}' gezogen wurde.]"
