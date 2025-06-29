import mysql.connector
from mysql.connector import Error
from config import Configobj

# Global db_config
db_config = Configobj.get_db_config()

class DatabaseSetupForTables:
    def __init__(self, db_connection):
        self.conn = db_connection
        self.db_name = db_config['database']
    
    def create_database_if_not_exists(self) -> bool:
        try:
            print(f"Attempting to connect to MySQL server to create database '{self.db_name}'")
            cursor = self.conn.cursor()
            
            print(f"Executing CREATE DATABASE IF NOT EXISTS for '{self.db_name}'")
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {db_config['database']}")
            self.conn.commit()
            
            print(f"Successfully created/verified database '{self.db_name}'")
            cursor.close()
            self.conn.close()
            return True
        except Exception as e:
            print(f"[ERROR] Failed to create database '{self.db_name}': {e}")
            return False
    
    def check_table_exists(self, table_name):
        cursor = self.conn.cursor()
        try:
            print(f"Executing query to check if table '{table_name}' exists")
            cursor.execute(f"""
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_schema = %s AND table_name = %s
            """, (self.db_name, table_name))
            exists = cursor.fetchone()[0] == 1
            print(f"Table '{table_name}' exists: {exists}")
            return exists
        except Error as e:
            print(f"[ERROR] Failed to check if table '{table_name}' exists: {e}")
            return False
        finally:
            cursor.close()
    
    def check_and_create_database(self):
        cursor = None
        try:
            # Check and create customermaster table
            if not self.check_table_exists("customermaster"):
                print("customermaster table doesn't exist - creating now")
                cursor = self.conn.cursor()
                cursor.execute("""CREATE TABLE customermaster (
                    CustomerID INT AUTO_INCREMENT PRIMARY KEY,
                    FullName VARCHAR(100) NOT NULL,
                    EmailAddress VARCHAR(100) NOT NULL UNIQUE,
                    Phone VARCHAR(20),
                    CreatedOn TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    LastLoginDateTime TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    Languages VARCHAR(50),
                    Browser VARCHAR(100),
                    Timezone VARCHAR(50),
                    Platform VARCHAR(50),
                    CompanyName VARCHAR(100),
                    INDEX idx_email (EmailAddress),
                    INDEX idx_created_on (CreatedOn)
                ) ENGINE=InnoDB""")
                print("[SUCCESS] Created customermaster table with all columns and indexes")
            
            # Create staffmaster table
            if not self.check_table_exists("staffmaster"):
                print("staffmaster table doesn't exist - creating now")
                cursor = self.conn.cursor()
                cursor.execute("""CREATE TABLE staffmaster (
                    StaffID INT AUTO_INCREMENT PRIMARY KEY,
                    StaffType TINYINT NOT NULL DEFAULT 0 COMMENT '1 FOR STAFF, 0 FOR BOT',
                    FullName VARCHAR(100) NOT NULL,
                    EmailAddress VARCHAR(100) NOT NULL UNIQUE,
                    Phone VARCHAR(20),
                    CompanyName VARCHAR(100),
                    CreatedOn TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    LastLoginDateTime TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    Languages VARCHAR(50),
                    Browser VARCHAR(100),
                    Timezone VARCHAR(50),
                    Platform VARCHAR(50),
                    HumanHandOver TINYINT NOT NULL DEFAULT 0 COMMENT '0 FOR BOT, 1 FOR STAFF',
                    INDEX idx_staff_email (EmailAddress),
                    INDEX idx_staff_type (StaffType),
                    INDEX idx_handover (HumanHandOver)
                ) ENGINE=InnoDB""")

                print("[SUCCESS] Created staffmaster table with all columns and indexes")
                
                # Insert the default bot record
                print("Inserting default bot record into staffmaster")
                cursor.execute("""INSERT IGNORE INTO staffmaster 
                    (StaffID, StaffType, FullName, EmailAddress, CompanyName, HumanHandOver) 
                    VALUES (1, 0, 'AI Chatbot', 'bot@system.local', 'System', 0)""")
                
                print("[SUCCESS] Inserted default bot record into staffmaster")
            
            # Create cookies table
            if not self.check_table_exists("cookies"):
                print("cookies table doesn't exist - creating now")
                cursor.execute("""CREATE TABLE cookies (
                    CookieID VARCHAR(36) PRIMARY KEY COMMENT 'GUID/UUID format',
                    CustomerID INT NOT NULL,
                    CreatedOn TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (CustomerID) REFERENCES customermaster(CustomerID) ON DELETE CASCADE,
                    INDEX idx_customer_cookie (CustomerID)
                ) ENGINE=InnoDB""")

                print("[SUCCESS] Created cookies table with all columns, foreign key, and indexes")
            
            # Create sessions table
            if not self.check_table_exists("sessions"):
                print("sessions table doesn't exist - creating now")
                cursor.execute("""CREATE TABLE sessions (
                    SessionID INT AUTO_INCREMENT PRIMARY KEY,
                    CustomerID INT NOT NULL,
                    CookieID VARCHAR(36) NULL COMMENT 'Reference to cookie if available',
                    CreatedOn TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    LastActivity TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    FOREIGN KEY (CustomerID) REFERENCES customermaster(CustomerID) ON DELETE CASCADE,
                    FOREIGN KEY (CookieID) REFERENCES cookies(CookieID) ON DELETE SET NULL,
                    INDEX idx_customer_session (CustomerID),
                    INDEX idx_session_created (CreatedOn),
                    INDEX idx_last_activity (LastActivity),
                    INDEX idx_cookie (CookieID)
                ) ENGINE=InnoDB""")
                print("[SUCCESS] Created sessions table with all columns, foreign keys, and indexes")
            
            # Createcconversation table
            if not self.check_table_exists("conversation"):
                print("conversation table doesn't exist - creating now")
                cursor.execute("""CREATE TABLE conversation (
                    ConversationID INT AUTO_INCREMENT PRIMARY KEY,
                    ConversationText TEXT NOT NULL COMMENT 'Message content (question or answer)',
                    ConversationMode VARCHAR(50) DEFAULT 'chatbot',
                    CustomerID INT NULL COMMENT 'NULL for chatbot answers, CustomerID for user questions',
                    StaffID INT NULL COMMENT 'NULL for user questions, 1 for bot answers, >1 for human staff answers',
                    SessionID INT,
                    CreatedOn TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (CustomerID) REFERENCES customermaster(CustomerID) ON DELETE CASCADE,
                    FOREIGN KEY (StaffID) REFERENCES staffmaster(StaffID) ON DELETE SET NULL,
                    FOREIGN KEY (SessionID) REFERENCES sessions(SessionID) ON DELETE SET NULL,
                    INDEX idx_conversation_customer (CustomerID),
                    INDEX idx_conversation_staff (StaffID),
                    INDEX idx_conversation_session (SessionID),
                    INDEX idx_conversation_created (CreatedOn),
                    INDEX idx_conversation_mode (ConversationMode)
                ) ENGINE=InnoDB""")

                print("[SUCCESS] Created conversation table with all columns, foreign keys, and indexes")
            
            self.conn.commit()
            print("All table creation operations completed successfully")
            return True
            
        except Error as e:
            print(f"[ERROR] Failed during table creation: {e}")
            self.conn.rollback()
            return False
        finally:
            if cursor:
                cursor.close()
            print("Exiting check_and_create_database()")