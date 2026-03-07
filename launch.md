Terminal 1 (Windows+x Admin)

cd C:\Users\skycr\Perso\0Lith\0lith-desktop
npm run tauri dev

---

Terminal 2 (PowerShell)

cd C:\Users\skycr\Perso\0Lith\0lith-desktop
.\scripts\dev-sign.ps1

---

Obsidian Bridge (PowerShell)

cd C:\Users\skycr\Perso\0Lith\0lith-obsidian-bridge
uvicorn api.main:app --reload --host 127.0.0.1 --port 8765

# Prerequisites: Ollama running on :11434 (qwen3:14b pulled)
# Optional:      docker start qdrant   (semantic search on :6333)
# Swagger UI:    http://127.0.0.1:8765/docs
# Health check:  http://127.0.0.1:8765/health
