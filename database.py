import mysql.connector
from mysql.connector import pooling
from datetime import datetime
from datetime import timedelta
from config import Configobj
import time
import threading
import uuid
db_config = Configobj.get_db_config()

class DatabaseManager:
    def __init__(self):
        self.connection_pool = None
        self._lock = threading.Lock()
        self.initialize_connection_pool()
    
    def initialize_connection_pool(self) -> bool:
        try:
            current_db_config = {
                "host": db_config['host'],
                "user": db_config['user'],
                "password": db_config['password'],
                "database": db_config['database'],
                'connection_timeout': 10,
                'autocommit': True,
                'sql_mode': 'TRADITIONAL',
                'charset': 'utf8mb4',
                'use_unicode': True,
            }
            
            if self.connection_pool:
                try:
                    self.connection_pool._remove_connections()
                except:
                    pass
                    
            self.connection_pool = pooling.MySQLConnectionPool(
                pool_name="chatbot_pool",
                pool_size=3,
                **current_db_config
            )
            print("Database connection pool created successfully")
            return True
        except Exception as e:
            print(f"Error initializing connection pool: {e}")
            return False
    
    def get_connection(self):
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if self.connection_pool:
                    conn = self.connection_pool.get_connection()
                    cursor = conn.cursor()
                    cursor.execute("SET SESSION innodb_lock_wait_timeout = 10")
                    try:
                        cursor.execute("SET SESSION transaction_isolation = 'READ-COMMITTED'")
                    except mysql.connector.Error:
                        cursor.execute("SET SESSION tx_isolation = 'READ-COMMITTED'")
                    
                    cursor.close()
                    return conn
                else:
                    current_db_config = {
                        "host": db_config['host'],
                        "user": db_config['user'],
                        "password": db_config['password'],
                        "database": db_config['database'],
                        'connection_timeout': 10,
                        'autocommit': True,
                    }
                    return mysql.connector.connect(**current_db_config)
            except Exception as e:
                print(f"Error getting database connection (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(0.5 * (attempt + 1))
                    if attempt == 1:
                        self.initialize_connection_pool()
                else:
                    raise

    def reload_database_config(self) -> bool:
        with self._lock:
            try:
                Configobj.reload()
                global db_config
                db_config = Configobj.get_db_config()
                self.initialize_connection_pool()
                print("Database configuration reloaded successfully")
                return True
            except Exception as e:
                print(f"Error reloading database configuration: {e}")
                return False
    
    def execute_sql_query(self, sqlquery, params=None, fetch_one=False, fetch_all=False, commit=False):
        conn = None
        cursor = None
        result = None
        
        try:
            conn = self.get_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(sqlquery, params or ())
            if commit:
                conn.commit()
            if fetch_one:
                result = cursor.fetchone()
            elif fetch_all:
                result = cursor.fetchall()
            else:
                result = cursor.lastrowid or True
                
        except Exception as e:
            print(f"Database sqlquery failed: {e}")
            if conn and not conn.autocommit:
                conn.rollback()
            raise
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
                
        return result
    def check_email_exists(self, email):
        return self.execute_sql_query(
            "SELECT CustomerID FROM customermaster WHERE EmailAddress = %s",
            (email,),
            fetch_one=True
        )
    
    def get_customer(self, customer_id):
        return self.execute_sql_query(
            "SELECT CustomerID FROM customermaster WHERE CustomerID = %s",
            (customer_id,),
            fetch_one=True
        )
    
    def create_customer(self, name, email, phone):
        return self.execute_sql_query(
            "INSERT INTO customermaster (FullName, EmailAddress, Phone) VALUES (%s, %s, %s)",
            (name, email, phone),
            commit=True
        )
    
    def update_customer(self, name, phone, customer_id):
        return self.execute_sql_query(
            "UPDATE customermaster SET FullName = %s, Phone = %s, LastLoginDateTime = CURRENT_TIMESTAMP WHERE CustomerID = %s",
            (name, phone, customer_id),
            commit=True
        )
    
    def get_customer_cookie(self, customer_id):
        return self.execute_sql_query(
            "SELECT CookieID FROM cookies WHERE CustomerID = %s",
            (customer_id,),
            fetch_one=True
        )
    
    def create_cookie(self, cookie_id, customer_id):
        return self.execute_sql_query(
            "INSERT INTO cookies (CookieID, CustomerID) VALUES (%s, %s)",
            (cookie_id, customer_id),
            commit=True
        )
    
    # Session management methods
    def create_session(self, customer_id, cookie_id=None):
        if cookie_id:
            return self.execute_sql_query(
                "INSERT INTO sessions (CustomerID, CookieID) VALUES (%s, %s)",
                (customer_id, cookie_id),
                commit=True
            )
        else:
            return self.execute_sql_query(
                "INSERT INTO sessions (CustomerID) VALUES (%s)",
                (customer_id,),
                commit=True
            )
    
    def get_session_info(self, session_id):
        return self.execute_sql_query(
            """SELECT s.SessionID, s.CustomerID, s.CreatedOn, s.LastActivity,
                  c.FullName, c.EmailAddress, c.Phone
               FROM sessions s 
               LEFT JOIN customermaster c ON s.CustomerID = c.CustomerID 
               WHERE s.SessionID = %s""",
            (session_id,),
            fetch_one=True
        )
    
    def update_session_activity(self, session_id):
        max_retries = 3
        for attempt in range(max_retries):
            try:
                return self.execute_sql_query(
                    "UPDATE sessions SET LastActivity = NOW() WHERE SessionID = %s",
                    (session_id,),
                    commit=True
                )
            except mysql.connector.Error as e:
                if e.errno == 1205:  
                    time.sleep(0.1 * (attempt + 1))
                    continue
                raise
        return False
    
    def get_session_info_by_customer(self, customer_id):
        return self.execute_sql_query(
            """SELECT s.SessionID, s.CustomerID, s.CreatedOn, s.LastActivity,
                  c.FullName, c.EmailAddress, c.Phone
               FROM sessions s 
               JOIN customermaster c ON s.CustomerID = c.CustomerID 
               WHERE s.CustomerID = %s
               ORDER BY s.LastActivity DESC
               LIMIT 1""",
            (customer_id,),
            fetch_one=True
        )
    
    def log_question(self, customer_id, session_id, question, conversation_mode="chatbot"):
        return self.execute_sql_query(
            """INSERT INTO conversation (ConversationText, ConversationMode, CustomerID, StaffID, SessionID, CreatedOn) 
               VALUES (%s, %s, %s, %s, %s, NOW())""",
            (question, conversation_mode, customer_id, None, session_id),
            commit=True
        )
    
    
    def log_answer(self, customer_id, session_id, answer, staff_id=1, conversation_mode="chatbot"):
        if staff_id == 1:
            final_customer_id = None 
        else:
            customer_id
        return self.execute_sql_query(
            """INSERT INTO conversation (ConversationText, ConversationMode, CustomerID, StaffID, SessionID, CreatedOn) 
               VALUES (%s, %s, %s, %s, %s, NOW())""",
            (answer, conversation_mode, final_customer_id, staff_id, session_id),
            commit=True
        )
    
    def log_chat(self, customer_id, session_id, question, answer, conversation_mode="chatbot"):
        question_id = self.log_question(customer_id, session_id, question, conversation_mode)
        answer_id = self.log_answer(customer_id, session_id, answer, 1, conversation_mode)
        return question_id and answer_id
    
    def get_session_chat_history(self, session_id):
        results = self.execute_sql_query(
            """SELECT c.ConversationID, c.ConversationText AS MessageContent, c.ConversationMode, 
                  c.CreatedOn, c.StaffID, c.CustomerID, s.FullName as StaffName, s.StaffType
               FROM conversation c
               LEFT JOIN staffmaster s ON c.StaffID = s.StaffID
               WHERE c.SessionID = %s
               ORDER BY c.CreatedOn ASC""",
            (session_id,),
            fetch_all=True
        )
        
        for result in results if results else []:
            if result['CustomerID'] is not None and result['StaffID'] is None:
                result['sender'] = 'User'
            elif result['StaffID'] == 1:
                result['sender'] = 'Bot'
            elif result['StaffID'] is not None and result['StaffID'] > 1:
                result['sender'] = f"Staff ({result['StaffName'] or 'Unknown'})"
            else:
                result['sender'] = 'System'
                
        return results 
    
    def get_last_message_for_session(self, session_id):
        return self.execute_sql_query(
            """SELECT ConversationText, CreatedOn 
               FROM conversation 
               WHERE SessionID = %s 
               ORDER BY CreatedOn DESC 
               LIMIT 1""",
            (session_id,),
            fetch_one=True
        )
    
    # Cookie management methods
    def create_cookie_for_user(self, customer_id):
        cookie_id = str(uuid.uuid4())
        success = self.execute_sql_query(
            "INSERT INTO cookies (CookieID, CustomerID) VALUES (%s, %s)",
            (cookie_id, customer_id),
            commit=True
        )
        if success:
            return cookie_id
        else:
            None
    
    def get_customer_by_cookie(self, cookie_id):
        result = self.execute_sql_query(
            "SELECT CustomerID FROM cookies WHERE CookieID = %s",
            (cookie_id,),
            fetch_one=True
        )
        if result:
            return result['CustomerID'] 
        else:
            None
    
    def validate_cookie(self, cookie_id, customer_id):
        result = self.execute_sql_query(
            "SELECT 1 FROM cookies WHERE CookieID = %s AND CustomerID = %s",
            (cookie_id, customer_id),
            fetch_one=True
        )
        return result 
    
    # Session listing methods
    def get_customer_sessions(self, customer_id, active_only=False):
        query = """SELECT s.SessionID, s.CustomerID, s.CreatedOn, s.LastActivity, 
                      COUNT(c.ConversationID) as message_count
                   FROM sessions s
                   LEFT JOIN conversation c ON s.SessionID = c.SessionID
                   WHERE s.CustomerID = %s"""
        
        params = [customer_id]
        
        if active_only:
            cutoff_time = datetime.now() - timedelta(hours=48)
            query += " AND s.LastActivity >= %s"
            params.append(cutoff_time)
            
        query += " GROUP BY s.SessionID ORDER BY s.LastActivity DESC"
        
        return self.execute_sql_query(
            query,
            tuple(params),
            fetch_all=True
        )
    
    # Staff management methods
    def create_human_staff(self, full_name, email, phone=None, company_name=None):
        return self.execute_sql_query(
            """INSERT INTO staffmaster 
               (StaffType, FullName, EmailAddress, Phone, CompanyName, HumanHandOver) 
               VALUES (1, %s, %s, %s, %s, 1)""",
            (full_name, email, phone, company_name),
            commit=True
        )
    
    def get_next_human_staff_id(self):
        result = self.execute_sql_query(
            "SELECT MAX(StaffID) as max_id FROM staffmaster WHERE StaffType = 1",
            fetch_one=True
        )
        if result and result['max_id']:
            return result['max_id'] + 1 
        else: 
            2
    