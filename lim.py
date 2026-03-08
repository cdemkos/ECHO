import ollama
import asyncio

async def generate_summary(prompt: str) -> str:
    response = await asyncio.to_thread(
        ollama.chat,
        model='qwen2.5:3b',  # oder phi4:mini, gemma2:2b etc.
        messages=[{'role': 'user', 'content': f"Fasse extrem knapp und ehrlich zusammen:\n\n{prompt}"}]
    )
    return response['message']['content']
