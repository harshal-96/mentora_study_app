from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import google.generativeai as genai
import json
import re
from typing import List, Optional
import sqlite3
import hashlib
from datetime import datetime
from dotenv import load_dotenv
import os

load_dotenv()

genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# Initialize FastAPI
app = FastAPI(title="AI Study Buddy API")

# CORS setup for FlutterFlow
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure Gemini

model = genai.GenerativeModel("gemini-1.5-flash")

# Database setup
def init_db():
    conn = sqlite3.connect('study_buddy.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            name TEXT,
            subjects TEXT,
            level INTEGER DEFAULT 1,
            xp INTEGER DEFAULT 0
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS quiz_history (
            id TEXT PRIMARY KEY,
            user_id TEXT,
            subject TEXT,
            score INTEGER,
            total_questions INTEGER,
            timestamp TEXT
        )
    ''')
    
    conn.commit()
    conn.close()

# Initialize database
init_db()

# Request/Response Models
class ChatRequest(BaseModel):
    message: str
    user_id: str
    subject: Optional[str] = None

class QuizRequest(BaseModel):
    subject: str
    topic: str
    difficulty: str
    num_questions: int
    user_id: str

class User(BaseModel):
    name: str
    subjects: List[str]
    grade_level: str

class QuizSubmission(BaseModel):
    user_id: str
    quiz_id: str
    answers: List[str]
    subject: str

# API Endpoints

@app.post("/api/chat")
async def chat_with_ai(request: ChatRequest):
    try:
        # Create context-aware prompt
        system_prompt = f"""
        You are an AI Study Buddy, a helpful and encouraging tutor. 
        Subject context: {request.subject or 'General'}
        
        Rules:
        - Give clear, step-by-step explanations
        - Use simple language appropriate for students
        - Be encouraging and supportive
        - If it's a math problem, show each step
        - If it's a concept, use analogies and examples
        - Keep responses under 200 words for mobile
        
        Student question: {request.message}
        """
        
        response = model.generate_content(system_prompt)
        
        return {
            "response": response.text,
            "timestamp": datetime.now().isoformat()
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/generate-quiz")
async def generate_quiz(request: QuizRequest):
    try:
        prompt = f"""
        Create a {request.difficulty} level quiz about {request.topic} in {request.subject}.
        Generate exactly {request.num_questions} multiple choice questions.
        
        Format your response as a valid JSON array with this structure:
        [
            {{
                "question": "Question text here?",
                "options": ["A) Option 1", "B) Option 2", "C) Option 3", "D) Option 4"],
                "correct_answer": "A",
                "explanation": "Brief explanation of why this is correct"
            }}
        ]
        
        Make questions practical and educational. Ensure JSON is valid.
        """
        
        response = model.generate_content(prompt)
        
        # Extract JSON from response
        json_match = re.search(r'\[.*\]', response.text, re.DOTALL)
        if json_match:
            quiz_data = json.loads(json_match.group())
        else:
            # Fallback if JSON extraction fails
            quiz_data = [
                {
                    "question": f"Sample question about {request.topic}?",
                    "options": ["A) Option 1", "B) Option 2", "C) Option 3", "D) Option 4"],
                    "correct_answer": "A",
                    "explanation": "This is a sample explanation."
                }
            ]
        
        quiz_id = hashlib.md5(f"{request.user_id}{datetime.now()}".encode()).hexdigest()
        
        return {
            "quiz_id": quiz_id,
            "questions": quiz_data,
            "subject": request.subject,
            "topic": request.topic,
            "difficulty": request.difficulty
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/submit-quiz")
async def submit_quiz(submission: QuizSubmission):
    try:
        # For demo purposes, calculate a random-ish score
        # In real app, you'd compare with correct answers
        score = min(90, max(60, hash(submission.user_id) % 40 + 60))
        
        # Save to database
        conn = sqlite3.connect('study_buddy.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO quiz_history (id, user_id, subject, score, total_questions, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (submission.quiz_id, submission.user_id, submission.subject, 
              score, len(submission.answers), datetime.now().isoformat()))
        
        conn.commit()
        conn.close()
        
        return {
            "score": score,
            "total_questions": len(submission.answers),
            "percentage": score,
            "message": "Great job!" if score >= 80 else "Keep practicing!",
            "xp_earned": score // 10
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/create-user")
async def create_user(user: User):
    try:
        user_id = hashlib.md5(f"{user.name}{datetime.now()}".encode()).hexdigest()
        
        conn = sqlite3.connect('study_buddy.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO users (id, name, subjects, level, xp)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, user.name, json.dumps(user.subjects), 1, 0))
        
        conn.commit()
        conn.close()
        
        return {
            "user_id": user_id,
            "message": "User created successfully"
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/user-stats/{user_id}")
async def get_user_stats(user_id: str):
    try:
        conn = sqlite3.connect('study_buddy.db')
        cursor = conn.cursor()
        
        # Get user info
        cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
        user_data = cursor.fetchone()
        
        # Get quiz history
        cursor.execute('''
            SELECT subject, AVG(score) as avg_score, COUNT(*) as quiz_count
            FROM quiz_history WHERE user_id = ?
            GROUP BY subject
        ''', (user_id,))
        subject_stats = cursor.fetchall()
        
        conn.close()
        
        if not user_data:
            raise HTTPException(status_code=404, detail="User not found")
        
        return {
            "user_id": user_data[0],
            "name": user_data[1],
            "level": user_data[3],
            "xp": user_data[4],
            "subject_stats": [
                {"subject": stat[0], "average_score": stat[1], "quiz_count": stat[2]}
                for stat in subject_stats
            ]
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Health check
@app.get("/")
async def root():
    return {"message": "AI Study Buddy API is running!"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)