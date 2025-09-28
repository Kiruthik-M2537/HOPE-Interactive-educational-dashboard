from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.types import JSON
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import re
import random
import os

# Import the new OpenAI client interface
from openai import OpenAI

app = Flask(__name__)
CORS(app)  # Enable CORS for all origins — safe for local dev

# Database configuration
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///database.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# User model
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    points = db.Column(db.Integer, default=0)
    quiz_history = db.Column(JSON, nullable=True)  # Store quiz attempts and results

with app.app_context():
    db.create_all()


@app.route("/api/signup", methods=["POST"])
def signup():
    data = request.get_json() or {}
    username = (data.get("username") or "").strip()
    password = data.get("password")
    if not username or not password:
        return jsonify({"success": False, "error": "Missing username or password"}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({"success": False, "error": "Username already exists"}), 409
    user = User(
        username=username,
        password_hash=generate_password_hash(password),
        points=0,
        quiz_history=[]
    )
    db.session.add(user)
    db.session.commit()
    return jsonify({"success": True})


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    username = (data.get("username") or "").strip()
    password = data.get("password")
    if not username or not password:
        return jsonify({"success": False, "error": "Missing username or password"}), 400
    user = User.query.filter_by(username=username).first()
    if user and check_password_hash(user.password_hash, password):
        return jsonify({"success": True, "name": user.username})
    return jsonify({"success": False, "error": "Invalid credentials"}), 401


@app.route("/api/leaderboard", methods=["GET", "POST"])
def leaderboard():
    if request.method == "GET":
        users = User.query.order_by(User.points.desc()).limit(10).all()
        return jsonify([{"name": u.username, "points": u.points} for u in users])
    else:
        data = request.get_json() or {}
        username = (data.get("username") or "").strip()
        points = data.get("points")
        if not username or not isinstance(points, int):
            return jsonify({"success": False, "error": "Invalid data"}), 400
        user = User.query.filter_by(username=username).first()
        if not user:
            return jsonify({"success": False, "error": "User not found"}), 404
        user.points = (user.points or 0) + points
        db.session.commit()
        return jsonify({"success": True})


@app.route("/api/summarize", methods=["POST"])
def summarize():
    data = request.get_json() or {}
    notes = data.get("notes")
    if not notes or not isinstance(notes, str) or not notes.strip():
        return jsonify({"success": False, "error": "No notes provided"}), 400
    sentences = re.split(r"(?<=[.!?])\s+", notes.strip())
    summary = " ".join(sentences[:3]).strip()
    if not summary:
        summary = notes[:150]
    return jsonify({"success": True, "summary": summary})


@app.route("/api/studyplan", methods=["POST"])
def studyplan():
    data = request.get_json() or {}
    notes = data.get("notes")
    if not notes or not isinstance(notes, str) or not notes.strip():
        return jsonify({"success": False, "error": "No notes provided"}), 400
    topics = [line.strip() for line in notes.split("\n") if line.strip()]
    if not topics:
        topics = re.split(r"(?<=[.!?])\s+", notes.strip())
    plan = []
    for i, topic in enumerate(topics):
        minutes = min(30, max(8, len(topic.split()) * 2))
        plan.append({"step": i + 1, "topic": topic[:65] + ("..." if len(topic) > 65 else ""), "minutes": minutes})
    return jsonify({"success": True, "plan": plan})


@app.route("/api/studypath", methods=["POST"])
def studypath():
    data = request.get_json() or {}
    notes = data.get("notes")
    if not notes or not isinstance(notes, str) or not notes.strip():
        return jsonify({"success": False, "error": "No notes provided"}), 400
    topics = [line.strip() for line in notes.split("\n") if line.strip()]
    if not topics:
        topics = re.split(r"(?<=[.!?])\s+", notes.strip())
    preferred_order = ["Genetics", "Ecology", "Evolution", "Human Anatomy"]

    def priority(t):
        for idx, kw in enumerate(preferred_order):
            if kw.lower() in t.lower():
                return idx
        return len(preferred_order)

    sorted_topics = sorted(topics, key=priority)
    plan = []
    for i, topic in enumerate(sorted_topics):
        minutes = min(30, max(8, len(topic.split()) * 2))
        plan.append({"step": i + 1, "topic": topic[:65] + ("..." if len(topic) > 65 else ""), "minutes": minutes})
    return jsonify({"success": True, "path": plan})


@app.route("/api/quiz", methods=["POST"])
def generate_quiz():
    data = request.get_json() or {}
    notes = data.get("notes")
    username = (data.get("username") or "").strip()
    if not notes or not isinstance(notes, str) or not notes.strip():
        return jsonify({"success": False, "error": "No notes provided"}), 400
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", notes.strip()) if len(s.split()) > 5]
    all_words = set()
    for s in sentences:
        all_words.update(w for w in s.split() if len(w) > 3)
    random.shuffle(sentences)
    quiz_list = []
    for sent in sentences[:3]:
        words = sent.split()
        if len(words) < 4:
            continue
        idx = random.randint(1, len(words) - 2)
        answer = words[idx]
        question = " ".join(w if i != idx else "_____" for i, w in enumerate(words))
        distractors = [w for w in all_words if w != answer]
        if len(distractors) >= 3:
            distractors = random.sample(distractors, 3)
        options = distractors + [answer]
        random.shuffle(options)
        quiz_list.append({"question": question, "answer": answer, "options": options, "topic": "General"})
    if not quiz_list:
        return jsonify({"success": False, "error": "Cannot generate quiz"}), 400
    if username:
        user = User.query.filter_by(username=username).first()
        if user:
            if user.quiz_history is None:
                user.quiz_history = []
            user.quiz_history.append({"timestamp": datetime.utcnow().isoformat(), "results": []})
            db.session.commit()
    return jsonify({"success": True, "quiz": quiz_list})


@app.route("/api/quiz/results", methods=["POST"])
def submit_quiz():
    data = request.get_json() or {}
    username = (data.get("username") or "").strip()
    results = data.get("results")
    if not username or not isinstance(results, list):
        return jsonify({"success": False, "error": "Invalid data"}), 400
    user = User.query.filter_by(username=username).first()
    if not user:
        return jsonify({"success": False, "error": "User not found"}), 404
    if user.quiz_history is None:
        user.quiz_history = []
    if not user.quiz_history or "results" not in user.quiz_history[-1]:
        user.quiz_history.append({"timestamp": datetime.utcnow().isoformat(), "results": results})
    else:
        user.quiz_history[-1]["results"] = results
    db.session.commit()
    print(f"Stored quiz results for {username}")
    return jsonify({"success": True})


@app.route("/api/remediation", methods=["POST"])
def pseudo_remediation():
    data = request.get_json() or {}
    username = (data.get("username") or "").strip()
    if not username:
        return jsonify({"success": False, "error": "Username required"}), 400

    possible_weaknesses = [
        "Genetics", "Cell Biology", "Evolution", "Ecology",
        "Human Anatomy", "Biochemistry", "Microbiology", "Physiology"
    ]

    random.seed(username)  # deterministic per user
    count = random.randint(1, 3)
    weaknesses = random.sample(possible_weaknesses, count)

    remediation = []
    for topic in weaknesses:
        missed = random.randint(1, 5)
        remediation.append({
            "topic": topic,
            "misses": missed,
            "suggestion": f"Focus on {topic} to improve your understanding."
        })

    return jsonify({"success": True, "remediation": remediation})


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json() or {}
    message = data.get("message")
    if not message or not isinstance(message, str) or not message.strip():
        return jsonify({"success": False, "error": "No message provided"}), 400

    if not client.api_key:
        return jsonify({"success": False, "error": "OpenAI API key not configured"}), 500

    try:
        completion = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": message}],
            max_tokens=256,
            temperature=0.6,
        )
        reply = completion.choices[0].message.content.strip()
        return jsonify({"success": True, "reply": reply})

    except Exception as e:
        print(f"OpenAI API error: {e}")
        return jsonify({"success": False, "error": f"AI service error: {str(e)}"}), 500


if __name__ == "__main__":
    app.run(debug=True)
