"""Quick manual check of the configured Ollama endpoint/model:  python test_ollama.py"""
from app.services import ollama_service

print(ollama_service.status())
print(ollama_service.generate_text(None, "Say hello in one short sentence.", max_tokens=40))
