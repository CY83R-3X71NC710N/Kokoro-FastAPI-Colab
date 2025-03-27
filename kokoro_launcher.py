#!/usr/bin/env python3
"""
Kokoro TTS API Launcher & Monitor Script

This script helps you launch the Kokoro TTS API in Google Colab and monitor its status.
It provides a simple way to get the API URL once it's ready.
"""

import webbrowser
import time
import os
import requests
import threading
import json
import argparse
from datetime import datetime

# Configuration
DEFAULT_COLAB_URL = "https://colab.research.google.com/github/remsky/Kokoro-FastAPI-Colab/blob/main/launch_kokoro.ipynb"
HISTORY_FILE = os.path.expanduser("~/.kokoro_api_history.json")

def load_history():
    """Load previous API URLs history."""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {"api_urls": []}
    return {"api_urls": []}

def save_api_url(url):
    """Save API URL to history."""
    history = load_history()
    # Add new URL with timestamp
    history["api_urls"].insert(0, {
        "url": url,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    # Keep only the last 5 URLs
    history["api_urls"] = history["api_urls"][:5]
    
    with open(HISTORY_FILE, 'w') as f:
        json.dump(history, f, indent=2)

def check_api_status(url):
    """Check if the API is responding."""
    try:
        response = requests.get(f"{url}/v1/audio/voices", timeout=5)
        if response.status_code == 200:
            return True
    except requests.exceptions.RequestException:
        pass
    return False

def monitor_clipboard():
    """
    Monitor clipboard for cloudflare URLs.
    Note: Requires pyperclip package (pip install pyperclip)
    """
    try:
        import pyperclip
    except ImportError:
        print("Clipboard monitoring requires pyperclip module.")
        print("Please install it with: pip install pyperclip")
        return
    
    print("Monitoring clipboard for Cloudflare URLs...")
    last_clipboard = ""
    
    while True:
        current_clipboard = pyperclip.paste()
        
        if current_clipboard != last_clipboard:
            last_clipboard = current_clipboard
            
            # Check if it contains a Cloudflare URL
            if "trycloudflare.com" in current_clipboard:
                if "https://" not in current_clipboard:
                    # Extract just the domain part if that's what was copied
                    url = f"https://{current_clipboard.strip()}"
                else:
                    url = current_clipboard.strip()
                
                print(f"\n🔗 Detected Cloudflare URL: {url}")
                
                # Check if API is working
                print("Checking if API is responding...")
                if check_api_status(url):
                    print(f"✅ API is up and running at: {url}")
                    print(f"TTS Endpoint: {url}/v1/audio/speech")
                    save_api_url(url)
                    print("URL saved to history for future use")
                else:
                    print("⚠️ API not responding yet. Will check again when URL changes.")
        
        time.sleep(2)

def launch_colab(open_browser=True):
    """Launch the Colab notebook."""
    url = DEFAULT_COLAB_URL
    
    print(f"🚀 Launching Kokoro TTS in Google Colab: {url}")
    
    if open_browser:
        webbrowser.open(url)
    
    print("\n📋 Important steps:")
    print("1. After Colab opens, click on 'Connect' to connect to a runtime (with GPU)")
    print("2. Run the notebook cell by clicking 'Run cell' or pressing Shift+Enter")
    print("3. Wait until you see 'Kokoro API is now available at: [URL]' message")
    print("4. Copy that URL to use as your TTS endpoint")
    
    # Display keep-alive JavaScript
    print("\n⏲️ To keep Colab running, paste this in browser console:")
    print("""function ClickConnect() {
  console.log("Clicked connect button");
  document.querySelector("colab-toolbar-button#connect").click();
}
setInterval(ClickConnect, 60000);""")

def test_api(url):
    """Test the API by generating a sample audio."""
    try:
        print(f"🔊 Testing API at {url}...")
        
        response = requests.post(
            f"{url}/v1/audio/speech",
            json={
                "model": "kokoro",
                "input": "Hello, this is a test of the Kokoro text-to-speech API!",
                "voice": "af_bella",
                "response_format": "mp3"
            },
            timeout=15  # Longer timeout for first request
        )
        
        if response.status_code == 200:
            # Save test audio
            filename = "kokoro_test.mp3"
            with open(filename, "wb") as f:
                f.write(response.content)
            print(f"✅ API test successful! Audio saved to {filename}")
            return True
        else:
            print(f"⚠️ API test failed with status code {response.status_code}")
            print(response.text[:200])
            return False
    except Exception as e:
        print(f"❌ Error testing API: {str(e)}")
        return False

def show_history():
    """Show previously saved API URLs."""
    history = load_history()
    
    if not history["api_urls"]:
        print("No previous API URLs found.")
        return
    
    print("\n📜 Previous API URLs:")
    for i, entry in enumerate(history["api_urls"], 1):
        print(f"{i}. {entry['url']} ({entry['timestamp']})")
        # Check if still active
        if check_api_status(entry['url']):
            print("   ✅ Still active!")
        else:
            print("   ❌ Not responding")

def main():
    parser = argparse.ArgumentParser(description="Kokoro TTS API Launcher & Monitor")
    parser.add_argument("--launch", action="store_true", help="Launch the Colab notebook")
    parser.add_argument("--monitor", action="store_true", help="Monitor clipboard for API URLs")
    parser.add_argument("--test", metavar="URL", help="Test the API at the specified URL")
    parser.add_argument("--history", action="store_true", help="Show previously saved API URLs")
    
    args = parser.parse_args()
    
    if args.history:
        show_history()
    
    if args.launch:
        launch_colab()
    
    if args.test:
        test_api(args.test)
    
    if args.monitor:
        monitor_clipboard()
    
    # If no arguments, show help and launch
    if not any(vars(args).values()):
        parser.print_help()
        print("\n")
        launch_decision = input("Do you want to launch Kokoro TTS in Colab? (y/n): ")
        if launch_decision.lower() in ['y', 'yes']:
            launch_colab()
            
            monitor_decision = input("Do you want to monitor clipboard for API URLs? (y/n): ")
            if monitor_decision.lower() in ['y', 'yes']:
                monitor_clipboard()

if __name__ == "__main__":
    main()