from setupdatabase import DatabaseSetupForTables
from database import DatabaseManager, db_config
import mysql.connector

def initialize_database():
    db_manager = DatabaseManager()
    conn = None
    
    try:
        temp_config = {
            "host": db_config['host'],
            "user": db_config['user'],
            "password": db_config['password']
        }
        
        conn = mysql.connector.connect(**temp_config)
        setup = DatabaseSetupForTables(conn)
        
        # Create database if not exists
        if not setup.create_database_if_not_exists():
            print("Failed to create database")
            return False
        
        # Now connect to the specific database
        conn = db_manager.get_connection()
        setup = DatabaseSetupForTables(conn)
        
        # Create tables
        if not setup.check_and_create_database():
            print("Failed to create tables")
            return False
        
        print("Database and tables initialized successfully")
        return True
        
    except Exception as e:
        print(f"Error during database initialization: {e}")
        return False
    finally:
        if conn:
            conn.close()

if __name__ == '__main__':
    initialize_database()