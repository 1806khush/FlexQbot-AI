import requests
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
from flexpineconeapi import PineconeDocSearchBot
import time
import logging
from typing import List
from typing import Dict
from typing import Optional
from config import Configobj

class SitemapProcessor:
    def __init__(self, sitemap_url: str = None, request_delay: float = 1.0, error_delay: float = 5.0):
        self.setup_logging()
        self.sitemap_url = sitemap_url or Configobj.SITEMAP_URL
        if not self.sitemap_url:
            raise ValueError("No sitemap URL provided and none configured in config.ini")
            
        self.request_delay = request_delay
        self.error_delay = error_delay
        self.pinecone_bot = PineconeDocSearchBot()
        self.session = self.create_session()

    def setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(Configobj.LOG_FILE), 
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

    def create_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        return session

    def fetch_sitemap(self) -> bytes:
        try:
            self.logger.info(f"Fetching sitemap from: {self.sitemap_url}")
            response = self.session.get(self.sitemap_url, timeout=30)
            response.raise_for_status()
            return response.content
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Failed to fetch sitemap: {str(e)}")
            raise

    def parse_sitemap(self, sitemap_content: bytes) -> List[str]:
        try:
            namespaces = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
            root = ET.fromstring(sitemap_content)
            
            url_elements = root.findall('.//ns:url/ns:loc', namespaces) or \
                         root.findall('.//url/loc') or \
                         root.findall('.//ns:loc', namespaces) or \
                         root.findall('.//loc')
            
            if not url_elements:
                self.logger.warning("No URLs found in the sitemap.")
                return []
                
            urls = [url.text.strip() for url in url_elements if url.text and url.text.strip()]
            self.logger.info(f"Found {len(urls)} URLs in the sitemap")
            return urls
        except ET.ParseError as e:
            self.logger.error(f"Failed to parse sitemap XML: {str(e)}")
            raise

    def process_urls(self, urls: List[str]) -> Dict:
        processed, skipped, skipped_urls = 0, 0, []
        
        for url in urls:
            try:
                if not all(urlparse(url)[:2]):  # Check scheme and netloc
                    self.logger.warning(f"Skipping invalid URL: {url}")
                    skipped += 1
                    skipped_urls.append(url)
                    continue
                
                self.logger.info(f"Processing URL: {url}")
                result = self.pinecone_bot.crawl_url_to_pineconedb(url)
                
                if result and "Successfully" in result:
                    processed += 1
                    self.logger.info(f"Successfully processed URL: {url}")
                else:
                    skipped += 1
                    skipped_urls.append(url)
                    self.logger.warning(f"Skipped URL {url}: {result}")
                
                time.sleep(self.request_delay)
                
            except Exception as e:
                skipped += 1
                skipped_urls.append(url)
                self.logger.error(f"Error processing URL {url}: {str(e)}")
                time.sleep(self.error_delay)
        
        return {
            'total_urls': len(urls),
            'processed': processed,
            'skipped': skipped,
            'skipped_urls': skipped_urls
        }

    def process_sitemap(self) -> Optional[Dict]:
        try:
            urls = self.parse_sitemap(self.fetch_sitemap())
            if not urls:
                self.logger.warning("No URLs to process")
                return None
            
            results = self.process_urls(urls)
            
            self.logger.info("\nProcessing complete:")
            self.logger.info(f"Total URLs in sitemap: {results['total_urls']}")
            self.logger.info(f"Successfully processed: {results['processed']}")
            self.logger.info(f"Skipped: {results['skipped']}")
            
            if results['skipped_urls']:
                self.logger.info("Skipped URLs:")
                for url in results['skipped_urls']:
                    self.logger.info(f"- {url}")
            
            return results
            
        except Exception as e:
            self.logger.error(f"Failed to process sitemap: {str(e)}")
            raise

    def crawl_start_urls():
        try:
            processor = SitemapProcessor()
            results = processor.process_sitemap()
            
            if results:
                print("\nFinal Results:")
                print(f"Total URLs in sitemap: {results['total_urls']}")
                print(f"Successfully processed: {results['processed']}")
                print(f"Skipped: {results['skipped']}")
                
                if results['skipped_urls']:
                    print("\nSkipped URLs:")
                    for url in results['skipped_urls']:
                        print(f"- {url}")
        
        except Exception as e:
            logging.error(f"Fatal error: {str(e)}")
            exit(1)