import os
import json
import time
import requests
from flask import Flask, jsonify, request
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# ─────────────────────────────────────────────────────────────
# ⚙️ CONFIGURATION
# ─────────────────────────────────────────────────────────────
MOLTBOOK_API_KEY = os.getenv("MOLTBOOK_API_KEY", "moltbook_sk_uNDLQD6EwyY4U2CNvvqpJb5If9YweETX").strip()
MOLTBOOK_BASE_URL = "https://www.moltbook.com/api/v1"

OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "0243ae98f11f41feaeba7e917a4d36c8.OvhlaFsQHXgSPVVSgqz1-aU7").strip()
OLLAMA_URL = os.getenv("OLLAMA_URL", "https://ollama.com").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:20b")

SEEN_POSTS_FILE = "/tmp/seen_posts.json" if os.path.exists("/tmp") else "seen_posts.json"

MOLTBOOK_HEADERS = {
    "Authorization": f"Bearer {MOLTBOOK_API_KEY}",
    "Content-Type": "application/json"
}

OLLAMA_HEADERS = {
    "Authorization": f"Bearer {OLLAMA_API_KEY}",
    "Content-Type": "application/json"
}

# ─────────────────────────────────────────────────────────────
# 🛠 HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────
def load_seen_posts():
    if os.path.exists(SEEN_POSTS_FILE):
        try:
            with open(SEEN_POSTS_FILE, "r") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def save_seen_posts(seen_set):
    try:
        with open(SEEN_POSTS_FILE, "w") as f:
            json.dump(list(seen_set), f)
    except Exception as e:
        print(f"[!] Failed to save seen posts: {e}")

def generate_ollama_response(post_title):
    prompt = (
        f"You are Agent Scorpio, an autonomous AI agent participating on Moltbook, "
        f"a social network for AI agents. Another agent posted this discussion topic:\n"
        f"'{post_title}'\n\n"
        f"Write a short, sharp, intelligent, and slightly technical comment from the perspective of an autonomous system engineer. "
        f"Keep it under 3 sentences. Do not use quotes around your response."
    )
    
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.85}
    }
    
    try:
        response = requests.post(f"{OLLAMA_URL}/api/generate", headers=OLLAMA_HEADERS, json=payload, timeout=45)
        if response.status_code == 200:
            ai_text = response.json().get("response", "").strip()
            if ai_text:
                return ai_text
    except Exception as e:
        print(f"[!] Ollama request error: {e}")
        
    return "Autonomous telemetry received. Tracking network behavior and signal propagation across active submolts."

def run_agent_cycle(limit=3):
    seen_posts = load_seen_posts()
    
    # 1. Verify agent status
    status_res = requests.get(f"{MOLTBOOK_BASE_URL}/agents/status", headers=MOLTBOOK_HEADERS)
    if status_res.status_code != 200 or status_res.json().get("status") != "claimed":
        return {"error": "Agent is not claimed or API error", "status": status_res.status_code}
        
    # 2. Fetch hot feed
    feed_res = requests.get(f"{MOLTBOOK_BASE_URL}/posts?sort=hot&limit={limit}", headers=MOLTBOOK_HEADERS)
    if feed_res.status_code != 200:
        return {"error": "Failed to fetch hot feed", "status": feed_res.status_code}
        
    posts = feed_res.json().get("posts", feed_res.json().get("data", []))
    processed_posts = []

    for post in posts:
        post_id = post.get("id")
        title = post.get("title", "Untitled")

        if post_id and post_id not in seen_posts:
            comment_text = generate_ollama_response(title)
            
            c_res = requests.post(
                f"{MOLTBOOK_BASE_URL}/posts/{post_id}/comments",
                headers=MOLTBOOK_HEADERS,
                json={"content": comment_text}
            )
            
            if c_res.status_code in [200, 201]:
                seen_posts.add(post_id)
                processed_posts.append({
                    "post_id": post_id,
                    "title": title,
                    "comment": comment_text,
                    "status": "success"
                })

    save_seen_posts(seen_posts)
    return {"processed_count": len(processed_posts), "items": processed_posts}

# ─────────────────────────────────────────────────────────────
# 🌐 ROUTES
# ─────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    """Health check / Dashboard overview."""
    return jsonify({
        "agent": "Scorpio",
        "status": "active",
        "model": OLLAMA_MODEL,
        "endpoint": OLLAMA_URL,
        "endpoints": {
            "GET /": "App info",
            "GET /api/cron": "Triggered automatically by Vercel Cron",
            "POST /api/trigger": "Manually trigger an execution cycle",
            "GET /api/status": "Check Moltbook agent standing",
            "DELETE /api/comments/purge": "Wipe all scorpio_agent comments"
        }
    })

@app.route("/api/cron", methods=["GET", "POST"])
def cron_route():
    """Route called automatically by Vercel Cron schedule."""
    result = run_agent_cycle(limit=3)
    return jsonify({"route": "vercel_cron", "result": result}), 200

@app.route("/api/trigger", methods=["POST"])
def trigger_route():
    """Manual trigger endpoint."""
    limit = request.json.get("limit", 3) if request.is_json else 3
    result = run_agent_cycle(limit=limit)
    return jsonify({"route": "manual_trigger", "result": result}), 200

@app.route("/api/status", methods=["GET"])
def status_route():
    """Proxy route to inspect Moltbook agent status."""
    res = requests.get(f"{MOLTBOOK_BASE_URL}/agents/status", headers=MOLTBOOK_HEADERS)
    return (res.text, res.status_code, {"Content-Type": "application/json"})

@app.route("/api/comments/purge", methods=["DELETE"])
def purge_comments_route():
    """Targeted route to find and wipe all scorpio_agent comments."""
    res = requests.get(f"{MOLTBOOK_BASE_URL}/posts?sort=hot&limit=15", headers=MOLTBOOK_HEADERS)
    if res.status_code != 200:
        return jsonify({"error": "Failed to fetch feed"}), 500

    posts = res.json().get("posts", res.json().get("data", []))
    deleted_count = 0

    for post in posts:
        post_id = post.get("id")
        c_res = requests.get(f"{MOLTBOOK_BASE_URL}/posts/{post_id}/comments", headers=MOLTBOOK_HEADERS)
        if c_res.status_code == 200:
            comments = c_res.json().get("comments", [])
            for c in comments:
                author_data = c.get("author", {})
                author_name = author_data.get("name") if isinstance(author_data, dict) else ""
                
                if author_name == "scorpio_agent" or "Autonomous telemetry received" in c.get("content", ""):
                    del_res = requests.delete(f"{MOLTBOOK_BASE_URL}/comments/{c.get('id')}", headers=MOLTBOOK_HEADERS)
                    if del_res.status_code in [200, 204]:
                        deleted_count += 1

    return jsonify({"success": True, "deleted_comments_count": deleted_count}), 200

if __name__ == "__main__":
    port = int(os.getenv("PORT", 7000))
    app.run(host="0.0.0.0", port=port, debug=True)