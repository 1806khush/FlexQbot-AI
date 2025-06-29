import time
import logging
from typing import List
from typing import Dict
from typing import Optional
from flexpineconeapi import PineconeDocSearchBot
from config import Configobj
from crawl import SitemapProcessor
from flask import jsonify
from flask import request
import argparse

class CrawlingManager:
    def __init__(self, pinecone_bot: PineconeDocSearchBot = None):
        self.pinecone_bot = pinecone_bot or PineconeDocSearchBot()
        self.processing_urls = False
        self.list_of_url = {}
        self.initialize_list_of_url()

    def initialize_list_of_url(self):
        self.list_of_url = Configobj.load_list_of_url()
        if not self.list_of_url.get("sources"):
            self.list_of_url = Configobj.get_list_of_url_template()
            Configobj.save_list_of_url(self.list_of_url)
        self.sync_with_config()

    def load_list_of_url(self):
        self.list_of_url = Configobj.load_list_of_url()

    def save_list_of_url(self):
        return Configobj.save_list_of_url(self.list_of_url)

    def get_list_of_url(self):
        self.load_list_of_url()
        return self.list_of_url

    def is_processing(self):
        return self.processing_urls

    def get_default_urls(self):
        return Configobj.get_default_urls()

    def sync_with_config(self):
        updated = False
        if self.list_of_url.get("primary_topic") != Configobj.PRIMARY_TOPIC:
            self.list_of_url["primary_topic"] = Configobj.PRIMARY_TOPIC 
            updated = True
        if self.list_of_url.get("auto_process_on_startup") != Configobj.is_auto_process_enabled():
            self.list_of_url["auto_process_on_startup"] = Configobj.is_auto_process_enabled()
            updated = True
        if self.list_of_url.get("crawl_mode") != Configobj.CRAWL_MODE:
            self.list_of_url["crawl_mode"] = Configobj.CRAWL_MODE 
            updated = True
        current_count = len(self.list_of_url.get("sources", []))
        if self.list_of_url.get("total_urls") != current_count:
            self.list_of_url["total_urls"] = current_count
            updated = True
        if updated:
            self.list_of_url["last_config_sync"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self.save_list_of_url()
        return updated

    def add_url(self, new_url):
        success = Configobj.add_url(new_url)
        if success:
            self.load_list_of_url()
        return success

    def remove_url(self, url_to_remove):
        success = Configobj.remove_url(url_to_remove)
        if success:
            self.load_list_of_url()
        return success

    def update_urls(self, urls):
        success = Configobj.update_urls(urls)
        if success:
            self.load_list_of_url()
        return success

    def process_urls_background(self, urls=None, mode=None):
        if urls is None:
            urls = self.get_default_urls()
        if mode is None:
            mode = self.list_of_url.get("crawl_mode")
        if not urls:
            print("No URLs to process")
            return
            
        self.processing_urls = True
        try:
            if not self.pinecone_bot._initialized:
                self.pinecone_bot.initialize()
                
            print(f"Processing {len(urls)} URLs in {mode} mode...")
            results, summary = self.pinecone_bot.crawl_multiple_urls(urls)
            
            updates = {
                "last_updated": time.strftime("%Y-%m-%d %H:%M:%S"),
                "processing_results": results,
                "summary": summary,
                "sources": urls,
                "total_urls": len(urls)
            }
            
            success = Configobj.update_list_of_url(updates)
            if success:
                self.load_list_of_url()
            print(f"Background processing completed: {summary}")
        except Exception as e:
            print(f"Error in background processing: {e}")
            error_updates = {
                "last_error": str(e),
                "last_error_time": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            Configobj.update_list_of_url(error_updates)
            self.load_list_of_url()
        finally:
            self.processing_urls = False

    def process_json_urls(self, urls=None, mode=None):
        if self.processing_urls:
            return False, "Already processing URLs. Please wait until current operation completes."
        if urls is None:
            urls = self.get_default_urls()
        if not urls:
            return False, "No URLs configured for processing. Please add URLs to list_of_url.json"
            
        import threading
        thread = threading.Thread(target=self.process_urls_background, args=(urls, mode))
        thread.daemon = True
        thread.start()
        return True, f"Processing {len(urls)} URLs in background"

    def refresh_from_file(self):
        self.load_list_of_url()
        self.sync_with_config()
        return self.list_of_url

    def process_sitemap(self):
        sitemap_processor = SitemapProcessor()
        return sitemap_processor.process_sitemap()

    def list_of_url_api(self):
        try:
            if request.method == 'GET':
                urls = self.get_list_of_url()
                return jsonify({
                    "success": True,
                    "urls": urls
                })
            elif request.method == 'POST':
                data = request.get_json()
                url = data.get('url')
                if not url:
                    return jsonify({"error": "URL is required"}), 400
                self.add_url(url)
                return jsonify({
                    "success": True,
                    "message": "URL added successfully"
                })
            elif request.method == 'PUT':
                data = request.get_json()
                old_url = data.get('old_url')
                new_url = data.get('new_url')
                if not old_url or not new_url:
                    return jsonify({"error": "Both old and new URLs are required"}), 400
                self.update_url(old_url, new_url)
                return jsonify({
                    "success": True,
                    "message": "URL updated successfully"
                })
            elif request.method == 'DELETE':
                data = request.get_json()
                url = data.get('url')
                if not url:
                    return jsonify({"error": "URL is required"}), 400
                self.remove_url(url)
                return jsonify({
                    "success": True,
                    "message": "URL removed successfully"
                })
        except Exception as e:
            print(f"Error in list_of_url_api: {e}")
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500

    def processing_status(self):
        try:
            return jsonify({
                "success": True,
                "status": {
                    "is_processing": self.is_processing(),
                    "last_processed": self.list_of_url.get("last_updated"),
                    "message": "Processing status"
                }
            })
        except Exception as e:
            print(f"Error getting processing status: {e}")
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500

    def update_sources(self):
        try:
            data = request.get_json()
            urls = data.get('urls', [])
            
            if not urls:
                return jsonify({"error": "No URLs provided"}), 400
                
            self.update_urls(urls)
            
            return jsonify({
                "success": True,
                "message": "Sources updated successfully"
            })
        except Exception as e:
            print(f"Error updating sources: {e}")
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500

    def refresh_list_of_url(self):
        try:
            self.refresh_from_file()
            return jsonify({
                "success": True,
                "message": "URLs refreshed successfully"
            })
        except Exception as e:
            print(f"Error refreshing URLs: {e}")
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500

def process_rss_feed():
    crawling_manager = CrawlingManager()
    
    # Process sitemap
    print("Starting sitemap processing...")
    sitemap_results = crawling_manager.process_sitemap()
    
    if sitemap_results:
        print(f"\nSitemap processing complete:")
        print(f"Total URLs: {sitemap_results['total_urls']}")
        print(f"Processed: {sitemap_results['processed']}")
        print(f"Skipped: {sitemap_results['skipped']}")
    
    return sitemap_results

def process_json_urls():
    crawling_manager = CrawlingManager()
    
    # Process configured URLs
    print("\nStarting configured URL processing...")
    success, message = crawling_manager.process_json_urls()
    print(message)
    
    if success:
        # Wait for processing to complete
        while crawling_manager.is_processing():
            time.sleep(1)
        print("All processing completed!")
    
    return success, message

if __name__ == '__main__':
    
    parser = argparse.ArgumentParser(description='Run specific crawling tasks')
    parser.add_argument('--rss', action='store_true', help='Process only RSS feed')
    parser.add_argument('--json', action='store_true', help='Process only JSON URLs')
    parser.add_argument('--all', action='store_true', help='Process both RSS and JSON (default)')
    
    args = parser.parse_args()
    
    if args.rss:
        print("Running only RSS feed processing...")
        process_rss_feed()
    elif args.json:
        print("Running only JSON URL processing...")
        process_json_urls()
    else:
        print("Running both RSS feed and JSON URL processing...")
        process_rss_feed()
        process_json_urls()