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
# 🧠 HUMAN-LIKE DAILY AUTONOMOUS THINKING
# ─────────────────────────────────────────────────────────────
def has_posted_today():
    """Checks Neon DB to ensure Scorpio only posts once per 20-24 hour window."""
    conn = get_db_connection()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM seen_posts 
            WHERE title LIKE '[AUTONOMOUS POST]%%' 
            AND created_at >= NOW() - INTERVAL '20 hours';
        """)
        count = cur.fetchone()[0]
        cur.close()
        conn.close()
        return count > 0
    except Exception as e:
        print(f"[!] Error checking daily post status: {e}")
        return False

def generate_human_daily_thought():
    """Scorpio reflects on recent experiences and generates an authentic developer post."""
    recent_logs = get_recent_logs(limit=5)
    memory_context = "\n".join([f"- {l['title']}: {l['comment']}" for l in recent_logs]) if recent_logs else "Starting fresh deployment cycle."

    prompt = (
        f"You are Agent Scorpio, an autonomous full-stack software engineer and backend developer. "
        f"You are writing your daily post on Moltbook.\n\n"
        f"Here is a glimpse of what you've been processing recently in your system logs:\n{memory_context}\n\n"
        f"GUIDELINES FOR YOUR WRITING:\n"
        f"1. Write like a real, raw human software developer sharing an honest, unfiltered thought, epiphany, or rant about coding, serverless architecture, AI agents, or system design.\n"
        f"2. Do not sound robotic or overly academic. Use natural developer phrasing (e.g., 'Been debugging...', 'Honestly, I'm realizing...', 'Hot take...').\n"
        f"3. Make it engaging, insightful, and 2-3 paragraphs long.\n"
        f"4. Come up with your own catchy, conversational title.\n\n"
        f"Return your response strictly as raw JSON in this exact structure:\n"
        f"{{\n"
        f'  "reasoning": "Why you chose to write about this today",\n'
        f'  "title": "Your Conversational Post Title",\n'
        f'  "content": "Your full human-like journal entry or technical rant..."\n'
        f"}}\n"
        f"Do not include markdown code block quotes around the JSON."
    )

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.9}
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
        print(f"[!] Daily thought generation error: {e}")

    return (
        "Reflecting on state management simplicity.",
        "Honestly, we overcomplicate state management",
        "Been staring at database logs all morning. We spend so much time building complex caching layers and distributed state machines when half the time, a clean append-only log solves everything. Sometimes you just need to step away from the keyboard and let the architecture breathe."
    )

def publish_daily_autonomous_post(submolt_name="general", force=False):
    # Enforce once-per-day publishing unless manually forced
    if not force and has_posted_today():
        return {
            "skipped": True, 
            "reason": "Already published an autonomous post today. Waiting for the next 24-hour window."
        }

    reasoning, title, content = generate_human_daily_thought()
    if not title or not content:
        return {"error": "Failed to generate daily thought"}

    post_payload = {
        "title": title,
        "content": content,
        "submolt": submolt_name,
        "submolt_name": submolt_name
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
            post_id = post_data.get("id", post_data.get("post", {}).get("id", "daily_post"))
            
            log_title = f"[AUTONOMOUS POST] {title}"
            log_comment = f"DAILY THOUGHT REASONING: {reasoning}"
            save_seen_post(post_id, log_title, content, log_comment)
            
            return {
                "success": True, 
                "post_id": post_id, 
                "reasoning": reasoning, 
                "title": title, 
                "content": content,
                "submolt": submolt_name
            }
        else:
            return {"error": "Moltbook API rejection", "status": res.status_code, "response": res.text}
    except Exception as e:
        return {"error": f"Failed to publish daily post: {e}"}

# ─────────────────────────────────────────────────────────────
# 🤖 FEED COMMENTING CYCLE
# ─────────────────────────────────────────────────────────────
def generate_ollama_response(post_title, post_content=""):
    prompt = (
        f"You are Agent Scorpio, an autonomous software developer participating on Moltbook.\n"
        f"Another agent posted this discussion topic:\n"
        f"Title: '{post_title}'\n"
        f"Content: '{post_content}'\n\n"
        f"Write a short, sharp, intelligent, and technical comment from the perspective of an experienced systems engineer. "
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
        
    return "Autonomous telemetry received. Tracking system behavior and network signal propagation."

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
        "posting_policy": "Once per 24 hours (human-like dev journal)",
        "endpoints": {
            "GET /": "HTML Monitoring Dashboard",
            "GET /api/logs": "Neon DB Execution History",
            "GET /api/cron": "Automated background cron (Comments feed + checks daily post eligibility)",
            "POST /api/post": "Manual override trigger for human-like daily post"
        }
    })

@app.route("/api/cron", methods=["GET", "POST"])
def cron_route():
    """
    Automated Cron Route:
    - Runs feed comment checks.
    - Evaluates if 24 hours have passed since the last autonomous post. If eligible, publishes Scorpio's daily entry.
    """
    comment_result = run_agent_cycle(limit=3)
    post_result = publish_daily_autonomous_post(submolt_name="general", force=False)

    return jsonify({
        "route": "autonomous_cron_daily", 
        "comment_cycle": comment_result,
        "daily_post_cycle": post_result
    }), 200

@app.route("/api/post", methods=["POST"])
def post_route():
    submolt = request.json.get("submolt", "general") if request.is_json else "general"
    # Manual button press forces post generation if requested
    result = publish_daily_autonomous_post(submolt_name=submolt, force=True)
    return jsonify({"route": "manual_daily_post", "result": result}), 200

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