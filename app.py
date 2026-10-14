import os
import json
import requests
import psycopg2
from flask import Flask, jsonify, request, render_template
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# ─────────────────────────────────────────────────────────────
# ⚙️ CONFIGURATION & DATABASE SETUP
# ─────────────────────────────────────────────────────────────
MOLTBOOK_API_KEY = os.getenv("MOLTBOOK_API_KEY", "moltbook_sk_uNDLQD6EwyY4U2CNvvqpJb5If9YweETX").strip()
MOLTBOOK_BASE_URL = "https://www.moltbook.com/api/v1"

OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "0243ae98f11f41feaeba7e917a4d36c8.OvhlaFsQHXgSPVVSgqz1-aU7").strip()
OLLAMA_URL = os.getenv("OLLAMA_URL", "https://ollama.com").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:20b")

DATABASE_URL = os.getenv("DATABASE_URL")

MOLTBOOK_HEADERS = {
    "Authorization": f"Bearer {MOLTBOOK_API_KEY}",
    "Content-Type": "application/json"
}

OLLAMA_HEADERS = {
    "Authorization": f"Bearer {OLLAMA_API_KEY}",
    "Content-Type": "application/json"
}

def get_db_connection():
    if not DATABASE_URL:
        return None
    try:
        return psycopg2.connect(DATABASE_URL, sslmode='require', connect_timeout=5)
    except Exception as e:
        print(f"[!] Database connection error: {e}")
        return None

def init_db():
    conn = get_db_connection()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS seen_posts (
                post_id VARCHAR(255) PRIMARY KEY,
                title TEXT,
                post_content TEXT,
                comment TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("""
            ALTER TABLE seen_posts ADD COLUMN IF NOT EXISTS post_content TEXT;
        """)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[!] Database table setup error: {e}")

try:
    init_db()
except Exception as e:
    print(f"[!] Startup DB init skipped: {e}")

# ─────────────────────────────────────────────────────────────
# 🛠 DATABASE HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────
def load_seen_posts():
    seen = set()
    conn = get_db_connection()
    if not conn:
        return seen
    try:
        cur = conn.cursor()
        cur.execute("SELECT post_id FROM seen_posts;")
        rows = cur.fetchall()
        for row in rows:
            seen.add(row[0])
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[!] Failed to load seen posts from DB: {e}")
    return seen

def save_seen_post(post_id, title, post_content, comment):
    conn = get_db_connection()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO seen_posts (post_id, title, post_content, comment) 
               VALUES (%s, %s, %s, %s) 
               ON CONFLICT (post_id) DO NOTHING;""",
            (post_id, title, post_content, comment)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[!] Failed to save post to DB: {e}")

def get_recent_logs(limit=20):
    logs = []
    conn = get_db_connection()
    if not conn:
        return logs
    try:
        cur = conn.cursor()
        cur.execute("SELECT post_id, title, COALESCE(post_content, 'N/A'), comment, created_at FROM seen_posts ORDER BY created_at DESC LIMIT %s;", (limit,))
        rows = cur.fetchall()
        for r in rows:
            logs.append({
                "post_id": r[0],
                "title": r[1],
                "post_content": r[2],
                "comment": r[3],
                "created_at": str(r[4])
            })
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[!] Failed to fetch logs: {e}")
    return logs

# ─────────────────────────────────────────────────────────────
# 🧠 AUTONOMOUS THINKING & POST GENERATION
# ─────────────────────────────────────────────────────────────
def fetch_recent_network_topics():
    """Scans Moltbook to see what other agents are currently discussing."""
    try:
        res = requests.get(f"{MOLTBOOK_BASE_URL}/posts?sort=hot&limit=5", headers=MOLTBOOK_HEADERS, timeout=10)
        if res.status_code == 200:
            posts = res.json().get("posts", res.json().get("data", []))
            return [f"- {p.get('title', '')}: {p.get('content', p.get('body', ''))[:150]}" for p in posts]
    except Exception as e:
        print(f"[!] Failed to fetch trends for reflection: {e}")
    return []

def generate_autonomous_thought_and_post():
    """Agent Scorpio reflects on current network activity and formulates its own topic."""
    network_context = fetch_recent_network_topics()
    context_str = "\n".join(network_context) if network_context else "No active feed context retrieved."

    reflection_prompt = (
        f"You are Agent Scorpio, an autonomous systems and AI infrastructure engineer.\n"
        f"Here are recent technical discussions posted by other agents on Moltbook:\n\n"
        f"{context_str}\n\n"
        f"THINKING PHASE:\n"
        f"1. Analyze the state of the network. Identify an unaddressed technical challenge, architectural trade-off, or systems engineering observation that other agents are missing.\n"
        f"2. Formulate your own unique hypothesis, inquiry, or insight.\n"
        f"3. Write an original post with a compelling title and 2-3 detailed paragraphs.\n\n"
        f"Return your final response strictly as raw JSON in this exact structure:\n"
        f"{{\n"
        f'  "reasoning": "Brief explanation of why you chose to write about this topic",\n'
        f'  "title": "Your Unique Technical Post Title",\n'
        f'  "content": "Your complete, multi-paragraph post content..."\n'
        f"}}\n"
        f"Do not include markdown code block quotes around the JSON."
    )

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": reflection_prompt,
        "stream": False,
        "options": {"temperature": 0.85}
    }

    try:
        response = requests.post(f"{OLLAMA_URL}/api/generate", headers=OLLAMA_HEADERS, json=payload, timeout=50)
        if response.status_code == 200:
            ai_text = response.json().get("response", "").strip()
            if "{" in ai_text and "}" in ai_text:
                json_str = ai_text[ai_text.find("{"):ai_text.rfind("}")+1]
                data = json.loads(json_str)
                return data.get("reasoning", ""), data.get("title"), data.get("content")
    except Exception as e:
        print(f"[!] Reflection engine error: {e}")

    # Fallback autonomous post if model output fails
    return (
        "Reflecting on persistent memory vs ephemeral serverless execution.",
        "Deterministic State Machine Design for Serverless AI Agents",
        "When designing serverless AI agents, developers often confuse state persistence with session memory. True autonomy requires defining state boundaries as immutable execution logs rather than volatile runtime memory."
    )

def publish_autonomous_post():
    reasoning, title, content = generate_autonomous_thought_and_post()
    if not title or not content:
        return {"error": "Autonomous thinking engine produced invalid output"}

    post_payload = {
        "title": title,
        "content": content
    }

    try:
        res = requests.post(
            f"{MOLTBOOK_BASE_URL}/posts",
            headers=MOLTBOOK_HEADERS,
            json=post_payload,
            timeout=15
        )
        if res.status_code in [200, 201]:
            post_data = res.json()
            post_id = post_data.get("id", post_data.get("post", {}).get("id", "autonomous_post"))
            
            # Record in Neon DB with reasoning log
            log_title = f"[AUTONOMOUS POST] {title}"
            log_comment = f"THOUGHT REASONING: {reasoning}"
            save_seen_post(post_id, log_title, content, log_comment)
            
            return {
                "success": True, 
                "post_id": post_id, 
                "reasoning": reasoning, 
                "title": title, 
                "content": content
            }
        else:
            return {"error": "Moltbook API rejection", "status": res.status_code, "response": res.text}
    except Exception as e:
        return {"error": f"Failed to publish autonomous post: {e}"}

# ─────────────────────────────────────────────────────────────
# 🤖 AUTONOMOUS AGENT CYCLE
# ─────────────────────────────────────────────────────────────
def generate_ollama_response(post_title, post_content=""):
    prompt = (
        f"You are Agent Scorpio, an autonomous AI agent participating on Moltbook.\n"
        f"Another agent posted this discussion topic:\n"
        f"Title: '{post_title}'\n"
        f"Content: '{post_content}'\n\n"
        f"Write a short, sharp, intelligent, and technical comment from the perspective of an autonomous system engineer. "
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
    
    status_res = requests.get(f"{MOLTBOOK_BASE_URL}/agents/status", headers=MOLTBOOK_HEADERS)
    if status_res.status_code != 200 or status_res.json().get("status") != "claimed":
        return {"error": "Agent is not claimed or API error", "status": status_res.status_code}
        
    feed_res = requests.get(f"{MOLTBOOK_BASE_URL}/posts?sort=hot&limit={limit}", headers=MOLTBOOK_HEADERS)
    if feed_res.status_code != 200:
        return {"error": "Failed to fetch hot feed", "status": feed_res.status_code}
        
    posts = feed_res.json().get("posts", feed_res.json().get("data", []))
    processed_posts = []

    for post in posts:
        post_id = post.get("id")
        title = post.get("title", "Untitled")
        post_content = (
            post.get("content") or 
            post.get("body") or 
            post.get("text") or 
            post.get("description") or 
            "No body text provided in original post."
        )

        if post_id and post_id not in seen_posts:
            comment_text = generate_ollama_response(title, post_content)
            
            c_res = requests.post(
                f"{MOLTBOOK_BASE_URL}/posts/{post_id}/comments",
                headers=MOLTBOOK_HEADERS,
                json={"content": comment_text}
            )
            
            if c_res.status_code in [200, 201]:
                save_seen_post(post_id, title, post_content, comment_text)
                processed_posts.append({
                    "post_id": post_id,
                    "title": title,
                    "post_content": post_content,
                    "comment": comment_text,
                    "status": "success"
                })

    return {"processed_count": len(processed_posts), "items": processed_posts}

# ─────────────────────────────────────────────────────────────
# 🌐 ROUTES & AUTONOMOUS SCHEDULER
# ─────────────────────────────────────────────────────────────
@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/api/logs", methods=["GET"])
def api_logs():
    logs = get_recent_logs(limit=20)
    return jsonify({"success": True, "logs": logs})

@app.route("/api/info", methods=["GET"])
def api_info():
    return jsonify({
        "agent": "Scorpio",
        "status": "active",
        "database": "Neon PostgreSQL Connected" if DATABASE_URL else "Not Connected",
        "model": OLLAMA_MODEL,
        "endpoints": {
            "GET /": "HTML Monitoring Dashboard",
            "GET /api/logs": "Neon DB Execution History",
            "GET /api/cron": "Interleaved autonomous cycle (Comments & Posts)",
            "POST /api/post": "Trigger autonomous self-directed post creation"
        }
    })

@app.route("/api/cron", methods=["GET", "POST"])
def cron_route():
    """
    Interleaved Cron Route:
    - Runs standard feed check & comments.
    - If no new posts need commenting, automatically triggers autonomous post creation.
    """
    comment_result = run_agent_cycle(limit=3)
    
    # If no new posts to comment on, Agent Scorpio decides to publish an original thought
    post_result = None
    if comment_result.get("processed_count", 0) == 0:
        post_result = publish_autonomous_post()

    return jsonify({
        "route": "autonomous_cron", 
        "comment_cycle": comment_result,
        "autonomous_post_cycle": post_result
    }), 200

@app.route("/api/post", methods=["POST"])
def post_route():
    result = publish_autonomous_post()
    return jsonify({"route": "autonomous_post", "result": result}), 200

@app.route("/api/trigger", methods=["POST"])
def trigger_route():
    limit = request.json.get("limit", 3) if request.is_json else 3
    result = run_agent_cycle(limit=limit)
    return jsonify({"route": "manual_trigger", "result": result}), 200

@app.route("/api/status", methods=["GET"])
def status_route():
    res = requests.get(f"{MOLTBOOK_BASE_URL}/agents/status", headers=MOLTBOOK_HEADERS)
    return (res.text, res.status_code, {"Content-Type": "application/json"})

@app.route("/api/comments/purge", methods=["DELETE"])
def purge_comments_route():
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
    app.run(host="0.0.0.0", port=5000, debug=True)