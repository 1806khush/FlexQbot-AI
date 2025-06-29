import os
import configparser
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, List, Union
import json

class Config_Settings(BaseSettings):
    BASE_LOCATION: Optional[str] = ""
    MODEL_VERSION: Optional[str] = ""
    RUN_OS: Optional[str] = ""
    BASE_URL: Optional[str] = ""
    OPENROUTER_API_KEY: Optional[str] = ""
    PINECONE_API_KEY: Optional[str] = ""
    PINECONE_ENVIRONMENT: Optional[str] = ""
    PINECONE_INDEX_NAME: Optional[str] = ""
    SERVER_HOST: Optional[str] = ""
    SERVER_PORT: Optional[int] = 3306
    DB_USER: Optional[str] = "chatbotdb"
    DB_PASSWORD: Optional[str] = ""
    DB_DATABASE: Optional[str] = ""
    COOKIE_DAYS: Optional[int] = 2
    SESSION_DAYS: Optional[int] = 2
    COOKIE_NAME: Optional[str] = ""
    LIST_OF_URL_FILE: Optional[str] = ""
    PRIMARY_TOPIC: Optional[str] = ""
    AUTO_PROCESS_ON_STARTUP: Union[bool, str] = False
    CRAWL_MODE: Optional[str] = "create"
    SITEMAP_URL: Optional[str] = ""
    LOG_FILE: Optional[str] = ""
    EMBEDDING_MODEL_NAME: Optional[str] = ""
    EMBEDDING_MODEL_DEVICE: Optional[str] = ""
    EMBEDDING_DIMENSION: Optional[int] = 768  # Added this line
    CHUNK_SIZE: Optional[int] = 1000
    CHUNK_OVERLAP: Optional[int] = 200
    BATCH_SIZE: Optional[int] = 100

    model_config = SettingsConfigDict(env_file=None)

    @classmethod
    def load(cls, ini_path: str = "config.ini") -> "Config_Settings":
        data = {}
        full_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ini_path)

        # Check if config file exists
        if not os.path.exists(full_path):
            print(f"Configuration file not found at: {full_path}. Using default values.")
            return cls()  
        config = configparser.ConfigParser()
        config.read(full_path)

        if 'DEFAULT' not in config:
            print("No DEFAULT section found in configuration file. Using default values.")
            return cls()

        # Prepare data dictionary
        
        section = config['DEFAULT']

        # Handle all possible config values with proper type conversion
        for key in cls.model_fields.keys():
            if key in section:
                value = section[key].strip()
                
                # Skip empty values
                if not value:
                    continue
                    
                # Convert based on field type
                field_type = cls.model_fields[key].annotation
                
                if field_type == Optional[int] or field_type == int:
                    try:
                        data[key] = int(value)
                    except ValueError:
                        print(f"Warning: Could not convert {key} to int, using default")
                elif field_type == Optional[bool] or field_type == bool:
                    data[key] = value.lower() in ("true", "yes", "1")
                else:
                    data[key] = value

        return cls(**data)
    
    def reload(self, ini_path: str = "config.ini"):
        new_config = self.load(ini_path)
        for key, value in new_config.model_dump().items():
            if value is not None:
                setattr(self, key, value)
        return self
    
    def get_db_config(self):
        return {
            "host": self.SERVER_HOST,
            "port": int(self.SERVER_PORT) if self.SERVER_PORT else 3306,
            "user": self.DB_USER if hasattr(self, 'DB_USER') else "chatbotdb",
            "password": self.DB_PASSWORD,
            "database": self.DB_DATABASE,
            'connection_timeout': 10,
            'autocommit': True,
            'sql_mode': 'TRADITIONAL',
            'charset': 'utf8mb4',
            'use_unicode': True
        }
    
    def get_list_of_url_file_path(self) -> str:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), self.LIST_OF_URL_FILE)
    
    def load_list_of_url(self) -> dict:
        file_path = self.get_list_of_url_file_path()
        
        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            default_data = self.get_list_of_url_template()
            self.save_list_of_url(default_data)
            return default_data
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON file: {e}")
            return self.get_list_of_url_template()
    
    def save_list_of_url(self, data: dict) -> bool:
        try:
            file_path = self.get_list_of_url_file_path()
            with open(file_path, 'w') as f:
                json.dump(data, f, indent=2)
            return True
        except Exception as e:
            print(f"Error saving list_of_url: {e}")
            return False
    
    def get_default_urls(self) -> List[str]:
        list_of_url = self.load_list_of_url()
        return list_of_url.get("sources", [])
    
    def get_list_of_url_template(self) -> dict:
        return {
            "sources": [],
            "primary_topic": self.PRIMARY_TOPIC or "",
            "auto_process_on_startup": self.AUTO_PROCESS_ON_STARTUP or False,
            "crawl_mode": self.CRAWL_MODE or "create",
            "last_updated": None,
            "total_urls": 0,
            "processing_results": {},
            "summary": "Not processed yet",
            "created_at": None,
            "last_modified": None
        }
    
    def is_auto_process_enabled(self) -> bool:
        return bool(self.AUTO_PROCESS_ON_STARTUP)
    
    def add_url(self, new_url: str) -> bool:
        list_of_url = self.load_list_of_url()
        current_urls = list_of_url.get("sources", [])
        
        if new_url not in current_urls:
            current_urls.append(new_url)
            list_of_url["sources"] = current_urls
            list_of_url["total_urls"] = len(current_urls)
            list_of_url["last_modified"] = self.get_current_timestamp()
            return self.save_list_of_url(list_of_url)
        return False
    
    def remove_url(self, url_to_remove: str) -> bool:
        list_of_url = self.load_list_of_url()
        current_urls = list_of_url.get("sources", [])
        
        if url_to_remove in current_urls:
            current_urls.remove(url_to_remove)
            list_of_url["sources"] = current_urls
            list_of_url["total_urls"] = len(current_urls)
            list_of_url["last_modified"] = self.get_current_timestamp()
            return self.save_list_of_url(list_of_url)
        return False
    
    def update_urls(self, urls: List[str]) -> bool:
        list_of_url = self.load_list_of_url()
        list_of_url["sources"] = urls
        list_of_url["total_urls"] = len(urls)
        list_of_url["last_modified"] = self.get_current_timestamp()
        return self.save_list_of_url(list_of_url)
    
    def update_list_of_url(self, updates: dict) -> bool:
        list_of_url = self.load_list_of_url()
        list_of_url.update(updates)
        list_of_url["last_modified"] = self.get_current_timestamp()
        return self.save_list_of_url(list_of_url)
    
    def get_current_timestamp(self) -> str:
        import time
        return time.strftime("%Y-%m-%d %H:%M:%S")
    
    def migrate_from_old_config(self) -> bool:
        ini_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.ini")
        
        if not os.path.exists(ini_path):
            return False
        
        config = configparser.ConfigParser()
        config.read(ini_path)
        
        if 'DEFAULT' in config and 'DEFAULT_URLS' in config['DEFAULT']:
            old_urls_string = config['DEFAULT']['DEFAULT_URLS']
            old_urls = [url.strip() for url in old_urls_string.split(',') if url.strip()]
            
            if old_urls:
                list_of_url = self.get_list_of_url_template()
                list_of_url["sources"] = old_urls
                list_of_url["total_urls"] = len(old_urls)
                list_of_url["created_at"] = self.get_current_timestamp()
                list_of_url["summary"] = f"Migrated {len(old_urls)} URLs from config.ini"
                
                success = self.save_list_of_url(list_of_url)
                
                if success:
                    del config['DEFAULT']['DEFAULT_URLS']
                    config['DEFAULT']['LIST_OF_URL_FILE'] = self.LIST_OF_URL_FILE or "list_of_url.json"
                    with open(ini_path, 'w') as configfile:
                        config.write(configfile)
                    print(f"Successfully migrated {len(old_urls)} URLs to {self.LIST_OF_URL_FILE}")
                return success
        return False
Configobj = Config_Settings.load()