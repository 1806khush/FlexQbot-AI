from flask import Flask
from flask import render_template
from flask import jsonify
from flask import request
from flask import redirect
from flask import url_for
from flask import session
from flask_cors import CORS
import os
import json
import re
import threading
import time
import uuid
import numpy as np
from datetime import datetime
from datetime import timedelta
from config import Configobj
from database import DatabaseManager
from flexpineconeapi import PineconeDocSearchBot
import requests
from textblob import TextBlob
import nltk

db_manager = DatabaseManager()

class Initialize_flex_chatbot:
    def __init__(self):
        self.pinecone_bot = None
        self.llm = None
        self.setup_chatbot()
        self.last_response_id = None
        self.last_question = None
        self.user_mood = "neutral"

    def setup_chatbot(self):
        print("Entered setup_chatbot , APP.PY")
        os.environ["PINECONE_API_KEY"] = Configobj.PINECONE_API_KEY
        os.environ["OPENROUTER_API_KEY"] = Configobj.OPENROUTER_API_KEY
        
        # Initialize Pinecone without the embedding_dimension parameter
        self.pinecone_bot = PineconeDocSearchBot(
            api_key=Configobj.PINECONE_API_KEY,
            index_name=Configobj.PINECONE_INDEX_NAME
        )
        
        self.llm = OpenrouterLLM(
            api_key=Configobj.OPENROUTER_API_KEY,
            temperature=0.4,
            max_tokens=1000
        )

    def is_general_message(self, message):
        general_phrases = [
            r'^hi\b', r'^hello\b', r'^hey\b', r'thanks', r'thank you', 
            r'^good\s(morning|afternoon|evening)\b', r'^bye\b', r'^goodbye\b'
        ]
        message_lower = message.lower().strip()
        return any(re.search(pattern, message_lower) for pattern in general_phrases)

    def analyze_sentiment(self, text):
        """Analyze text sentiment and return mood with more nuanced detection"""
        analysis = TextBlob(text)
        polarity = analysis.sentiment.polarity
        
        # More nuanced sentiment detection
        if polarity < -0.7:
            return "angry"
        elif polarity < -0.3:
            return "frustrated"
        elif polarity < 0:
            return "slightly_upset"
        elif polarity > 0.7:
            return "excited"
        elif polarity > 0.3:
            return "happy"
        else:
            return "neutral"

    def adjust_tone_based_on_mood(self, response):
        """Adjust response tone based on user mood without losing content"""
        if not response:
            return response
            
        if self.user_mood == "angry":
            return f"I sincerely apologize for any frustration you're experiencing. Let me help clarify:\n\n{response}\n\nPlease let me know if this resolves your concern or if there's anything else I can assist with."
        elif self.user_mood == "frustrated":
            return f"I understand this situation might be frustrating. Here's a detailed explanation:\n\n{response}\n\nDoes this help address your concern?"
        elif self.user_mood == "happy":
            return f"Great! Here's the information you requested:\n\n{response}"
        elif self.user_mood == "excited":
            return f"That's wonderful to hear! Here are the details:\n\n{response}"
        else:
            return response

    def _build_context_from_search(self, search_results):
        """Build more comprehensive context from search results"""
        documents = []
        sources = set()
        
        if 'matches' in search_results:
            for match in search_results['matches']:
                if 'metadata' in match:
                    doc_content = match['metadata'].get('text', '')
                    source_url = match['metadata'].get('source_url', '')
                    
                    if len(doc_content) > 100:  # Only include substantial content
                        documents.append({
                            'content': doc_content,
                            'score': match.get('score', 0),
                            'source_url': source_url
                        })
                        if source_url:
                            sources.add(source_url)
        
        context_parts = []
        if documents:
            # Sort by score and include more context
            documents_sorted = sorted(documents, key=lambda x: x['score'], reverse=True)
            for doc in documents_sorted[:5]:  # Include more documents for context
                context_entry = f"Relevant Information (confidence: {doc['score']:.2f}):\n{doc['content'][:800]}"
                if doc['source_url']:
                    context_entry += f"\nSource: {doc['source_url']}"
                context_parts.append(context_entry)
        
        return "\n\n---\n".join(context_parts)
    def _extract_sources_from_context(self, context):
        """Extract and clean sources from context"""
        sources = set()
        if not context:
            return []
        
        # Look for source URLs in the context
        url_pattern = re.compile(r'Source:\s*(https?://[^\s]+)')
        for line in context.split('\n'):
            match = url_pattern.search(line)
            if match:
                source = match.group(1).strip()
                # Clean up the URL by removing any trailing characters that might have been included
                source = re.sub(r'[.,;:)\]]+$', '', source)
                if source:  # Only add non-empty sources
                    sources.add(source)
        
        return list(sources)

    def process_chat_message(self, input_text, is_feedback=False, previous_response_id=None):
        if not input_text.strip():
            return "Please enter a question."
        
        try:
            # Store the question for feedback handling
            if not is_feedback:
                self.last_question = input_text
            
            # Analyze user sentiment with more context
            self.user_mood = self.analyze_sentiment(input_text)
            
            # Skip source processing for general messages but still provide good responses
            if self.is_general_message(input_text):
                response = self.llm.generate_response(
                    input_text, 
                    context="",
                    system_message="You are a friendly and helpful support assistant. Respond to greetings and general questions in a warm, professional manner."
                )
                return self.adjust_tone_based_on_mood(response)
            
            # Get context - more comprehensive for feedback cases
            context = ""
            sources = []
            if is_feedback and previous_response_id:
                original_context = db_manager.get_response_context(previous_response_id)
                if original_context:
                    context = original_context
                    search_results = None
                else:
                    search_results = self.pinecone_bot.search(input_text, top_k=15)  # More results for feedback
                    context = self._build_context_from_search(search_results)
                    sources = self._extract_sources_from_context(context)
            else:
                search_results = self.pinecone_bot.search(input_text, top_k=10)
                context = self._build_context_from_search(search_results)
                sources = self._extract_sources_from_context(context)
            
            # Generate response with clear instructions for completeness
            system_message = """
            You are a technical support assistant for QODBC. Provide detailed, step-by-step answers to user questions.
            Include all relevant information from the context. If a process has multiple steps, number them clearly.
            For technical issues, explain both what to do and why it works.
            If the question is unclear, ask for clarification before attempting to answer.
            """
            
            if is_feedback:
                system_message += """
                IMPORTANT: The user was not satisfied with a previous answer. 
                Provide a more comprehensive response with additional details and explanations.
                Address any potential misunderstandings from the previous answer.
                """
            
            answer = self.llm.generate_response(input_text, context, system_message)
            
            # Ensure answer is complete before adjusting tone
            if not answer or len(answer) < 20:  # If answer seems too short
                answer = self.llm.generate_response(
                    "The previous response was too brief. Please provide a more detailed answer to: " + input_text,
                    context,
                    system_message + "\nThe previous answer was too short. Expand with more details and examples."
                )
            
            # Adjust tone based on mood without losing content
            answer = self.adjust_tone_based_on_mood(answer)
            
            # Add sources if they exist and it's not a general message
            if sources and not self.is_general_message(input_text):
                # Remove any existing sources section to avoid duplication
                answer = re.sub(r'\n\nSources?:.*', '', answer, flags=re.DOTALL)
                # Add the top 3 most relevant sources
                sources_text = "\n\nSources:\n" + "\n".join(sources[:3])
                answer += sources_text
            
            return answer
        except Exception as e:
            print(f"Error during chat processing: {e}")
            return "I apologize, but I encountered an issue while processing your question. Please try again or ask in a different way."
        
class OpenrouterLLM:
    def __init__(self, api_key, temperature=0.4, max_tokens=1000):
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.BASE_URL = Configobj.BASE_URL
        self.retry_count = 2
        self.timeout = 30
        self.model_name = Configobj.MODEL_VERSION

    def generate_response(self, prompt: str, context: str = "", system_message: str = None) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://QODBC-chatbot.com",
            "X-Title": "QODBC Chatbot"
        }
        
        if not system_message:
            system_message = """You are a helpful technical support assistant for QODBC. 
            Provide complete, detailed answers with explanations. 
            If a process has multiple steps, list them clearly.
            For technical issues, explain both what to do and why it works."""

        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": prompt}
        ]
        
        if context:
            messages.insert(1, {"role": "assistant", "content": f"Context: {context}"})

        data = {
            "model": self.model_name,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": 0.9,
            "frequency_penalty": 0.1,
            "presence_penalty": 0.1
        }
        
        last_error = None
        for attempt in range(self.retry_count + 1):
            try:
                response = requests.post(
                    self.BASE_URL,
                    headers=headers,
                    json=data,
                    timeout=self.timeout
                )
                
                if response.status_code == 429:
                    retry_after = int(response.headers.get('Retry-After', 5))
                    time.sleep(retry_after)
                    continue
                    
                response.raise_for_status()
                response_json = response.json()
                
                if 'error' in response_json:
                    error_msg = response_json['error'].get('message', 'Unknown API error')
                    raise ValueError(f"API Error: {error_msg}")
                
                content = response_json["choices"][0]["message"]["content"]
                
                if len(content.split()) < 10 and attempt < self.retry_count:
                    print("Response too short, retrying with adjusted parameters...")
                    data['temperature'] = min(0.7, data['temperature'] + 0.1)
                    data['max_tokens'] = min(2000, data['max_tokens'] + 200)
                    continue
                    
                return content
                
            except requests.exceptions.RequestException as e:
                last_error = e
                print(f"Attempt {attempt + 1} failed: {str(e)}")
                if attempt == self.retry_count:
                    break
                time.sleep(1 + attempt)
            except Exception as e:
                last_error = e
                print(f"Attempt {attempt + 1} failed: {str(e)}")
                if attempt == self.retry_count:
                    break
                time.sleep(1 + attempt)
        
        error_msg = str(last_error) if last_error else "Unknown error"
        return f"I apologize, but I encountered an error: {error_msg}. Please try rephrasing your question."

class CookieController:
    COOKIE_NAME = Configobj.COOKIE_NAME
    COOKIE_MAX_AGE = Configobj.COOKIE_DAYS * 24 * 60 * 60

    @staticmethod
    def set_user_cookie(response, cookie_id):
        response.set_cookie(
            CookieController.COOKIE_NAME,
            value=cookie_id,
            max_age=CookieController.COOKIE_MAX_AGE,
            httponly=True,
            samesite='Lax'
        )

    @staticmethod
    def get_cookie_from_request(request):
        return request.cookies.get(CookieController.COOKIE_NAME)

    @staticmethod
    def validate_cookie(cookie_id, customer_id):
        return db_manager.validate_cookie(cookie_id, customer_id)

    @staticmethod
    def create_cookie_for_user(customer_id):
        return db_manager.create_cookie_for_user(customer_id)

    @staticmethod
    def get_customer_by_cookie(cookie_id):
        return db_manager.get_customer_by_cookie(cookie_id)

class BrowserSession:
    @staticmethod
    def create_new_session():
        session_id = str(uuid.uuid4())
        session.permanent = True
        session['session_id'] = session_id
        session['session_created'] = datetime.now().isoformat()
        session['is_new_session'] = True
        return session_id

    @staticmethod
    def is_session_valid():
        if 'session_id' not in session or 'session_created' not in session:
            return False
        try:
            created_time = datetime.fromisoformat(session['session_created'])
            return (datetime.now() - created_time) <= timedelta(days=Configobj.SESSION_DAYS)
        except Exception as e:
            print(f"Error validating session: {e}")
            return False

    @staticmethod
    def is_user_logged_in():
        return (BrowserSession.is_session_valid() and 
                'db_session_id' in session and 
                'user_id' in session and 
                session.get('user_id') is not None and
                'user_logged_in' in session and
                session.get('user_logged_in'))

    @staticmethod
    def get_or_create_session():
        if BrowserSession.is_session_valid():
            session['is_new_session'] = False
            session.permanent = True
            return session.get('session_id')
        else:
            session.clear()
            session.permanent = True
            return BrowserSession.create_new_session()

    @staticmethod
    def update_session_data(user_id, db_session_id, name, email, phone):
        session.permanent = True
        session.update({
            'user_id': user_id,
            'db_session_id': db_session_id,
            'user_name': name,
            'user_email': email,
            'user_phone': phone,
            'last_updated': datetime.now().isoformat(),
            'user_logged_in': True
        })

    @staticmethod
    def clear_session():
        session.clear()

    @staticmethod
    def get_session_info():
        if not BrowserSession.is_session_valid():
            return None
        return {
            'session_id': session.get('session_id'),
            'session_created': session.get('session_created'),
            'user_id': session.get('user_id'),
            'db_session_id': session.get('db_session_id'),
            'user_name': session.get('user_name'),
            'user_email': session.get('user_email'),
            'is_new_session': session.get('is_new_session', False),
            'user_logged_in': session.get('user_logged_in', False),
            'last_updated': session.get('last_updated')
        }

class FlaskApp:
    def __init__(self):
        self.app = Flask(__name__)
        CORS(self.app)
        session_days = Configobj.SESSION_DAYS if hasattr(Configobj, 'SESSION_DAYS') else 2
        self.app.permanent_session_lifetime = timedelta(days=session_days)
        self.app.secret_key = os.urandom(24)
        self.app.config.update(
            SESSION_COOKIE_SECURE=False,
            SESSION_COOKIE_HTTPONLY=True,
            SESSION_COOKIE_SAMESITE='Lax',
            SESSION_PERMANENT=True,
            SESSION_COOKIE_MAX_AGE=session_days * 24 * 60 * 60
        )
        self.chatbot_manager = Initialize_flex_chatbot()
        self.register_routes()

    def register_routes(self):
        print("Entered register_routes , APP.PY")
        routes = [
            ("/", "index", self.index, ["GET"]),
            ("/settings.html", "settings", self.settings_page, ["GET"]),
            ("/chatbot", "chatbot", self.chatbot_route, ["GET"]),
            ("/signup", "signup", self.signup, ["GET"]),
            ("/submit-form", "submit_form", self.submit_form, ["POST"]),
            ("/get_chat_history", "get_chat_history", self.get_chat_history, ["GET"]),
            ("/get", "chat", self.chat, ["GET", "POST"]),
            ("/config/sync", "config_sync", self.config_sync, ["POST"]),
            ("/config/reload", "config_reload", self.config_reload, ["POST"]),
            ("/session/info", "session_info", self.session_info, ["GET"]),
            ("/session/clear", "clear_session", self.clear_session_route, ["POST"]),
            ("/session/retrieve", "retrieve_session", self.retrieve_session, ["POST"]),
            ("/recent_conversations", "recent_conversations", self.recent_conversations, ["GET"]),
            ("/create_staff", "create_staff", self.create_staff, ["POST"]),
            ("/get_next_staff_id", "get_next_staff_id", self.get_next_staff_id, ["GET"]),
            ("/get_customer_sessions", "get_customer_sessions", self.get_customer_sessions, ["GET"]),
            ("/session/update", "session_update", self.session_update, ["POST"]),
            ("/handle_feedback", "handle_feedback", self.handle_feedback, ["POST"])
        ]
        for route, endpoint, handler, methods in routes:
            self.app.add_url_rule(route, endpoint, handler, methods=methods)
    def session_update(self):
        try:
            if not BrowserSession.is_user_logged_in():
                return jsonify({"error": "User not logged in"}), 401
                
            data = request.get_json()
            if not data:
                return jsonify({"error": "No data provided"}), 400
                
            name = data.get('name')
            email = data.get('email')
            phone = data.get('phone', '')
            
            if not name or not email:
                return jsonify({"error": "Name and email are required"}), 400
                
            # Validate email format
            if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
                return jsonify({"error": "Please enter a valid email address"}), 400

            user_id = session.get('user_id')
            if not user_id:
                return jsonify({"error": "User ID not found in session"}), 400
                
            # Update database
            success = db_manager.update_customer(name, phone, user_id)
            
            if success:
                # Update session data
                BrowserSession.update_session_data(
                    user_id,
                    session.get('db_session_id'),
                    name,
                    email,
                    phone
                )
                return jsonify({"success": True})
            else:
                return jsonify({"error": "Failed to update database"}), 500
                
        except Exception as e:
            print(f"Error updating session: {e}")
            return jsonify({"error": str(e)}), 500
        
    def settings_page(self):
        return render_template('settings.html')
    def index(self):
        return redirect(url_for('recent_conversations'))

    def recent_conversations(self):
        if not BrowserSession.is_user_logged_in():
            return redirect(url_for('signup'))
        
        user_id = session.get('user_id')
        sessions = db_manager.get_customer_sessions(user_id)
        sessions_with_last_message = []
        
        for i in sessions:
            try:
                last_message = db_manager.get_last_message_for_session(i['SessionID'])
                session_data = {
                    'session_id': i['SessionID'],
                    'created_at': i['CreatedOn'],
                    'last_activity': i['LastActivity'],
                    'message_count': i.get('message_count', 0),
                    'last_message': last_message['ConversationText'] if last_message and last_message.get('ConversationText') else None,
                    'last_message_time': last_message['CreatedOn'] if last_message else None
                }
                sessions_with_last_message.append(session_data)
            except Exception as e:
                print(f"Error processing session {i['SessionID']}: {e}")
                session_data = {
                    'session_id': i['SessionID'],
                    'created_at': i['CreatedOn'],
                    'last_activity': i['LastActivity'],
                    'message_count': i.get('message_count', 0),
                    'last_message': None,
                    'last_message_time': None
                }
                sessions_with_last_message.append(session_data)
        
        return render_template('recent_conversations.html', 
                            sessions=sessions_with_last_message,
                            user_name=session.get('user_name', ''),
                            show_signup_modal=False)

    def signup(self):
        session_id = BrowserSession.get_or_create_session()
        if BrowserSession.is_user_logged_in():
            return redirect(url_for('recent_conversations'))
        
        redirect_target = session.pop('redirect_after_signup', None) or url_for('recent_conversations')
        
        return render_template('signup.html', 
                            session_info=BrowserSession.get_session_info(),
                            redirect_target=redirect_target)

    def chatbot_route(self):
        if not BrowserSession.is_user_logged_in():
            session['redirect_after_signup'] = url_for('chatbot')
            return redirect(url_for('signup'))
        
        cookie_id = CookieController.get_cookie_from_request(request)
        if cookie_id and not CookieController.get_customer_by_cookie(cookie_id):
            response = redirect(url_for('signup'))
            response.set_cookie(
                CookieController.COOKIE_NAME,
                value='',
                max_age=0,
                expires=0
            )
            BrowserSession.clear_session()
            return response

        user_id = session.get('user_id')
        db_session_id = session.get('db_session_id')
        user_name = session.get('user_name', '')
        
        viewing_session_id = request.args.get('session_id')
        if viewing_session_id:
            try:
                sessions = db_manager.get_customer_sessions(user_id)
                session_ids = [str(sess['SessionID']) for sess in sessions]
                
                if str(viewing_session_id) in session_ids:
                    session['db_session_id'] = viewing_session_id
                    chat_history = db_manager.get_session_chat_history(viewing_session_id)
                    for chat in chat_history:
                        if isinstance(chat.get('CreatedOn'), datetime):
                            chat['CreatedOn'] = chat['CreatedOn'].strftime('%Y-%m-%d %H:%M:%S')
                    return render_template('index.html', 
                                        user_name=user_name,
                                        chat_history=chat_history,
                                        session_info=BrowserSession.get_session_info(),
                                        viewing_past_conversation=True)
                else:
                    return redirect(url_for('chatbot'))
            except Exception as e:
                print(f"Error verifying session ownership: {e}")
                return redirect(url_for('chatbot'))
        
        chat_history = []
        if db_session_id:
            try:
                chat_history = db_manager.get_session_chat_history(db_session_id)
                for chat in chat_history:
                    if isinstance(chat.get('CreatedOn'), datetime):
                        chat['CreatedOn'] = chat['CreatedOn'].strftime('%Y-%m-%d %H:%M:%S')
            except Exception as e:
                print(f"Error loading chat history: {e}")
        
        return render_template('index.html', 
                            user_name=user_name,
                            chat_history=chat_history,
                            session_info=BrowserSession.get_session_info(),
                            viewing_past_conversation=False)

    def submit_form(self):
        try:
            session_id = BrowserSession.get_or_create_session()
            data = request.get_json() or request.form
            name = data.get('name')
            email = data.get('email')
            phone = data.get('phone', '')          
            
            if not name or not email:
                return jsonify({"error": "Name and email are required"}), 400
              
            existing_user = db_manager.check_email_exists(email)
            is_returning_user = bool(existing_user)
            conn = db_manager.get_connection()
            cursor = conn.cursor(dictionary=True)
            
            try:
                if not is_returning_user:
                    cursor.execute(
                        "INSERT INTO customermaster (FullName, EmailAddress, Phone) VALUES (%s, %s, %s)",
                        (name, email, phone)
                    )
                    user_id = cursor.lastrowid
                    cookie_id = str(uuid.uuid4())
                    cursor.execute(
                        "INSERT INTO cookies (CookieID, CustomerID) VALUES (%s, %s)",
                        (cookie_id, user_id)
                    )
                    cursor.execute(
                        "INSERT INTO sessions (CustomerID, CookieID) VALUES (%s, %s)",
                        (user_id, cookie_id)
                    )
                    db_session_id = cursor.lastrowid
                else:
                    user_id = existing_user['CustomerID']
                    cursor.execute(
                        "UPDATE customermaster SET FullName = %s, Phone = %s, LastLoginDateTime = CURRENT_TIMESTAMP WHERE CustomerID = %s",
                        (name, phone, user_id)
                    )
                    cursor.execute(
                        "SELECT CookieID FROM cookies WHERE CustomerID = %s",
                        (user_id,)
                    )
                    existing_cookie = cursor.fetchone()
                    cookie_id = existing_cookie['CookieID'] if existing_cookie else str(uuid.uuid4())
                    
                    if not existing_cookie:
                        cursor.execute(
                            "INSERT INTO cookies (CookieID, CustomerID) VALUES (%s, %s)",
                            (cookie_id, user_id)
                        )
                    cursor.execute(
                        "INSERT INTO sessions (CustomerID, CookieID) VALUES (%s, %s)",
                        (user_id, cookie_id)
                    )
                    db_session_id = cursor.lastrowid
                
                conn.commit()
                BrowserSession.update_session_data(user_id, db_session_id, name, email, phone)
                
                redirect_target = data.get('redirect_target', url_for('recent_conversations'))
                
                response = jsonify({
                    "message": "Contact information saved successfully", 
                    "user_id": user_id,
                    "db_session_id": db_session_id,
                    "session_id": session_id,
                    "is_returning_user": is_returning_user,
                    "is_new_session": session.get('is_new_session', False),
                    "redirect_to": redirect_target
                })
                
                CookieController.set_user_cookie(response, cookie_id)
                return response, 200

            except Exception as e:
                conn.rollback()
                raise e
            finally:
                cursor.close()
                conn.close()

        except Exception as e:
            print(f"Error saving contact data: {e}")
            if "Duplicate entry" in str(e) and "email" in str(e):
                return jsonify({"error": "This email address is already registered"}), 400
            return jsonify({"error": "Failed to save contact information"}), 500

    def retrieve_session(self):
        try:
            session_id = BrowserSession.get_or_create_session()
            session_info = BrowserSession.get_session_info()

            if session_info:
                user_data = {}
                if session_info.get('db_session_id'):
                    try:
                        chat_history = db_manager.get_session_chat_history(session_info['db_session_id'])
                        user_data['chat_count'] = len(chat_history)
                    except Exception as e:
                        print(f"Error getting chat history: {e}")
                        user_data['chat_count'] = 0

                return jsonify({
                    "success": True,
                    "message": "Session retrieved successfully",
                    "session_info": session_info,
                    "user_data": user_data,
                    "user_logged_in": BrowserSession.is_user_logged_in(),
                    "should_redirect_to_chatbot": BrowserSession.is_user_logged_in(),
                    "timestamp": datetime.now().isoformat()
                })
            else:
                return jsonify({
                    "success": False,
                    "message": "No valid session found",
                    "should_redirect_to_signup": True,
                    "timestamp": datetime.now().isoformat()
                }), 200
        except Exception as e:
            print(f"Error retrieving session: {e}")
            return jsonify({
                "success": False,
                "message": "Error retrieving session",
                "error": str(e)
            }), 500

    def clear_session_route(self):
        try:
            BrowserSession.clear_session()
            response = jsonify({
                "success": True,
                "message": "Session cleared successfully"
            })
            response.set_cookie(
                CookieController.COOKIE_NAME,
                value='',
                max_age=0,
                expires=0
            )
            return response
        except Exception as e:
            print(f"Error clearing session: {e}")
            return jsonify({
                "success": False,
                "message": "Error clearing session",
                "error": str(e)
            }), 500

    def session_info(self):
        session_info = BrowserSession.get_session_info()
        if session_info:
            return jsonify({
                "success": True,
                "session_info": session_info,
                "user_logged_in": BrowserSession.is_user_logged_in()
            })
        else:
            return jsonify({
                "success": False,
                "message": "No active session"
            }), 404

    def chat(self):
        if request.method == 'GET':
            return redirect(url_for('chatbot'))
        
        if not BrowserSession.is_user_logged_in():
            return jsonify({"error": "User not logged in"}), 401
            
        try:
            if request.is_json:
                data = request.get_json()
            else:
                data = request.form
                
            message = data.get('message') or data.get('msg')
            user_id = session.get('user_id')
            db_session_id = session.get('db_session_id')
            
            if not message:
                return jsonify({"error": "Message is required"}), 400
                
            # Log the question and get message ID
            message_id = db_manager.log_question(user_id, db_session_id, message)
            
            # Process the message
            response = self.chatbot_manager.process_chat_message(message)
            
            # Log the answer and get response ID
            response_id = db_manager.log_answer(user_id, db_session_id, response)
            
            # Store the last response ID for reactions
            self.chatbot_manager.last_response_id = response_id
            self.chatbot_manager.last_question = message
            
            db_manager.update_session_activity(db_session_id)
            
            return jsonify({
                "response": response,
                "session_id": db_session_id,
                "response_id": response_id
            })
        except Exception as e:
            print(f"Error in chat endpoint: {e}")
            return jsonify({"error": "Error processing message"}), 500

    def handle_feedback(self):
        if not BrowserSession.is_user_logged_in():
            return jsonify({"error": "User not logged in"}), 401
            
        try:
            data = request.get_json()
            reaction = data.get('reaction')
            response_id = data.get('response_id')
            user_id = session.get('user_id')
            db_session_id = session.get('db_session_id')
            
            if not reaction or not response_id:
                return jsonify({"error": "Reaction and response ID are required"}), 400
            
            # Log the reaction to the database
            db_manager.log_reaction(
                user_id,
                db_session_id,
                response_id,
                reaction
            )
            
            # Handle thumbs down - regenerate response
            if reaction == "thumbs_down":
                original_question = self.chatbot_manager.last_question
                if not original_question:
                    return jsonify({"error": "No question found to regenerate answer for"}), 400
                
                # Regenerate response with feedback consideration
                new_response = self.chatbot_manager.process_chat_message(
                    original_question,
                    is_feedback=True,
                    previous_response_id=response_id
                )
                
                # Log the new answer
                new_response_id = db_manager.log_answer(user_id, db_session_id, new_response)
                
                # Update last response ID
                self.chatbot_manager.last_response_id = new_response_id
                
                return jsonify({
                    "success": True,
                    "regenerated": True,
                    "new_response": new_response,
                    "new_response_id": new_response_id
                })
            
            return jsonify({"success": True})
        except Exception as e:
            print(f"Error handling feedback: {e}")
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500

    def get_chat_history(self):
        if not BrowserSession.is_user_logged_in():
            return jsonify({"error": "User not logged in"}), 401
            
        try:
            db_session_id = session.get('db_session_id')
            if not db_session_id:
                return jsonify({"error": "No active session"}), 400
                
            chat_history = db_manager.get_session_chat_history(db_session_id)
            
            formatted_history = []
            for message in chat_history:
                message_dict = dict(message)
                if isinstance(message_dict.get('CreatedOn'), datetime):
                    message_dict['CreatedOn'] = message_dict['CreatedOn'].strftime('%Y-%m-%d %H:%M:%S')
                formatted_history.append(message_dict)
                
            return jsonify({
                "success": True,
                "chat_history": formatted_history
            })
        except Exception as e:
            print(f"Error getting chat history: {e}")
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500

    def config_sync(self):
        try:
            Configobj.sync()
            return jsonify({
                "success": True,
                "message": "Configuration synced successfully"
            })
        except Exception as e:
            print(f"Error syncing config: {e}")
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500

    def config_reload(self):
        try:
            Configobj.reload()
            db_manager.reload_database_config()
            return jsonify({
                "success": True,
                "message": "Configuration reloaded successfully"
            })
        except Exception as e:
            print(f"Error reloading config: {e}")
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500

    def create_staff(self):
        try:
            if not BrowserSession.is_user_logged_in():
                return jsonify({"error": "User not logged in"}), 401
                
            data = request.get_json()
            full_name = data.get('full_name')
            email = data.get('email')
            phone = data.get('phone')
            company_name = data.get('company_name')
            
            if not full_name or not email:
                return jsonify({"error": "Full name and email are required"}), 400
                
            staff_id = db_manager.create_human_staff(full_name, email, phone, company_name)
            
            return jsonify({
                "success": True,
                "message": "Staff member created successfully",
                "staff_id": staff_id
            })
        except Exception as e:
            print(f"Error creating staff: {e}")
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500

    def get_next_staff_id(self):
        try:
            next_id = db_manager.get_next_human_staff_id()
            return jsonify({
                "success": True,
                "next_staff_id": next_id
            })
        except Exception as e:
            print(f"Error getting next staff ID: {e}")
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500

    def get_customer_sessions(self):
        try:
            if not BrowserSession.is_user_logged_in():
                return jsonify({"error": "User not logged in"}), 401
                
            user_id = session.get('user_id')
            active_only = request.args.get('active_only', 'false').lower() == 'true'
            
            sessions = db_manager.get_customer_sessions(user_id, active_only)
            
            formatted_sessions = []
            for sess in sessions:
                session_dict = dict(sess)
                if isinstance(session_dict.get('CreatedOn'), datetime):
                    session_dict['CreatedOn'] = session_dict['CreatedOn'].strftime('%Y-%m-%d %H:%M:%S')
                if isinstance(session_dict.get('LastActivity'), datetime):
                    session_dict['LastActivity'] = session_dict['LastActivity'].strftime('%Y-%m-%d %H:%M:%S')
                formatted_sessions.append(session_dict)
                
            return jsonify({
                "success": True,
                "sessions": formatted_sessions
            })
        except Exception as e:
            print(f"Error getting customer sessions: {e}")
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500

    def run(self, host=None, port=None):
        host = Configobj.SERVER_HOST
        port = Configobj.SERVER_PORT
        self.app.run(host=host, port=port, debug=True, use_reloader=False)

if __name__ == '__main__':
    flask_app = FlaskApp()
    flask_app.run()