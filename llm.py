# llm.py – Ollama LLM-Anbindung
#
# Wichtige Änderung gegenüber vorheriger Version:
#   generate_summary() wirft jetzt eine Exception statt einen Fehlertext
#   zurückzugeben. Dadurch kann der Aufrufer entscheiden was zu tun ist,
#   und Fehler-Strings werden NIEMALS als Notizen gespeichert.

import asyncio
import logging
import os

import ollama

log = logging.getLogger(__name__)

DEFAULT_MODEL = os.getenv("ECHO_MODEL", "qwen2.5:3b")

SYSTEM_PROMPT = (
    "Du bist ein persönlicher, ehrlicher Assistent für Reflexion und Gedankenorganisation. "
    "Du analysierst Gedanken präzise, nennst Muster direkt beim Namen und vermeidest Schönfärberei. "
    "Antworte immer auf Deutsch, strukturiert und knapp."
)


class LLMError(Exception):
    """Wird geworfen wenn Ollama nicht erreichbar ist oder einen Fehler zurückgibt."""
    pass


async def generate_summary(
    prompt:          str,
    model:           str = DEFAULT_MODEL,
    timeout_seconds: int = 60,
) -> str:
    """
    Sendet prompt an Ollama und gibt die Antwort zurück.
    Wirft LLMError wenn Ollama nicht erreichbar ist oder ein Timeout eintritt.
    Gibt NIEMALS einen Fehler-String zurück — der Aufrufer muss den Fehler behandeln.
    """
    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(
                ollama.chat,
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": prompt},
                ],
                options={"temperature": 0.35},
            ),
            timeout=timeout_seconds,
        )
        result = response["message"]["content"].strip()
        if not result:
            raise LLMError("Ollama hat eine leere Antwort zurückgegeben.")
        return result

    except asyncio.TimeoutError:
        raise LLMError(
            f"Timeout nach {timeout_seconds}s — "
            f"Läuft 'ollama serve' und ist '{model}' geladen?"
        )
    except LLMError:
        raise
    except Exception as e:
        raise LLMError(f"Ollama-Fehler: {e}") from e


async def check_ollama_available(model: str = DEFAULT_MODEL) -> bool:
    """Prüft ob Ollama läuft und das gewünschte Modell verfügbar ist."""
    try:
        result = await asyncio.to_thread(ollama.list)
        # ollama >= 0.4: ListResponse-Objekt; < 0.4: Dict
        if hasattr(result, "models"):
            names = [getattr(m, "model", None) or getattr(m, "name", "") for m in result.models]
        elif isinstance(result, dict):
            names = [m.get("name", "") or m.get("model", "") for m in result.get("models", [])]
        else:
            names = []
        base = model.split(":")[0]
        return any(base in n for n in names)
    except Exception:
        return False
