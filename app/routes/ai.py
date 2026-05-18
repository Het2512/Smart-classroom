from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required
from app.models import Note
from app.extensions import db
import os
import PyPDF2
from openai import OpenAI
import json

ai_bp = Blueprint('ai', __name__)

def get_nvidia_client():
    """Return an OpenAI-compatible client pointed at NVIDIA NIM."""
    return OpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=os.getenv('NVIDIA_API_KEY')
    )

# ── Model config ────────────────────────────────────────────────────────────
# meta/llama-3.1-8b-instruct  → fastest, great for summarize/quiz/chat
# nvidia/llama-3.1-nemotron-nano-8b-v1 → NVIDIA-tuned alternative
# meta/llama-3.3-70b-instruct → highest quality but slow
FAST_MODEL = "meta/llama-3.1-8b-instruct"

def ai_generate(prompt: str) -> str:
    """Call NVIDIA NIM AI and return the response text."""
    try:
        client = get_nvidia_client()
        response = client.chat.completions.create(
            model=FAST_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.6,
            max_tokens=800,
        )
        return response.choices[0].message.content or ""
    except Exception as e:
        return f"AI Error: {str(e)}"

def extract_pdf_text(filepath):
    text = ""
    with open(filepath, 'rb') as f:
        reader = PyPDF2.PdfReader(f)
        for page in reader.pages:
            text += page.extract_text() or ""
    return text[:8000]

@ai_bp.route('/summarize/<int:note_id>')
@login_required
def summarize(note_id):
    note     = db.get_or_404(Note, note_id)
    filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], note.filename)
    text     = extract_pdf_text(filepath)
    summary  = ai_generate(
        f"Summarize the following educational content clearly and concisely for a student. "
        f"Use bullet points where appropriate and highlight key concepts:\n\n{text}"
    )
    return render_template('summarize.html', note=note, summary=summary)

@ai_bp.route('/summarize_ajax/<int:note_id>', methods=['POST'])
@login_required
def summarize_ajax(note_id):
    """AJAX endpoint — returns JSON summary so the student page can show a loading spinner."""
    note     = db.get_or_404(Note, note_id)
    filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], note.filename)
    text     = extract_pdf_text(filepath)
    summary  = ai_generate(
        f"Summarize the following educational content clearly and concisely for a student. "
        f"Use bullet points where appropriate and highlight key concepts:\n\n{text}"
    )
    return jsonify({'title': note.title, 'summary': summary})

@ai_bp.route('/quiz/<int:note_id>')
@login_required
def quiz(note_id):
    note     = db.get_or_404(Note, note_id)
    filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], note.filename)
    text     = extract_pdf_text(filepath)
    prompt   = f"""Generate exactly 5 multiple choice questions from this content.
Return ONLY valid JSON array, no other text:
[
  {{
    "question": "Question text here?",
    "options": ["A. option1", "B. option2", "C. option3", "D. option4"],
    "answer": "A"
  }}
]

Content: {text}"""
    raw       = ai_generate(prompt) or ""
    questions = []
    try:
        start = raw.find('[')
        end   = raw.rfind(']') + 1
        if start != -1 and end > start:
            questions = json.loads(raw[start:end])
    except Exception:
        pass
    return render_template('quiz.html', note=note, questions=questions)

@ai_bp.route('/chat', methods=['GET', 'POST'])
@login_required
def chat():
    if request.method == 'POST':
        data     = request.get_json(silent=True) or {}
        question = data.get('question', '')
        answer   = ai_generate(
            f"You are a helpful study assistant for students. Answer this doubt clearly and simply: {question}"
        )
        return jsonify({'answer': answer})
    return render_template('chat.html')
