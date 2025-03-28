#!/usr/bin/env python3
"""
Detect Cloudflare URL from Kokoro-FastAPI-Colab

This script helps launch the Kokoro-FastAPI-Colab notebook in Google Colab
and automatically detects the Cloudflare URL that's generated for public access.
"""

import argparse
import re
import subprocess
import sys
import time
import webbrowser
from urllib.parse import quote

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Launch Kokoro-FastAPI-Colab and detect Cloudflare URL")
    parser.add_argument("--no-browser", action="store_true", help="Don't open browser automatically")
    parser.add_argument("--timeout", type=int, default=600, help="Timeout in seconds for URL detection (default: 600)")
    return parser.parse_args()

def get_colab_url():
    """Generate the Colab URL with the predefined GitHub username."""
    base_url = "https://colab.research.google.com/github/"
    github_username = "CY83R-3X71NC710N"
    notebook_path = f"{github_username}/Kokoro-FastAPI-Colab/blob/main/launch_kokoro.ipynb"
    params = "?accelerator=gpu&colab=true"
    return f"{base_url}{notebook_path}{params}"

def open_colab_in_browser(url):
    """Open the Colab URL in the default web browser."""
    print(f"\nOpening Google Colab in your browser...")
    print(f"URL: {url}")
    print("\nPlease:")
    print("1. Sign in to your Google account if prompted")
    print("2. Select 'Runtime' > 'Run all' from the Colab menu")
    print("3. Leave this terminal running to detect the Cloudflare URL")
    
    try:
        webbrowser.open(url)
        return True
    except Exception as e:
        print(f"Error opening browser: {e}")
        print(f"Please manually open this URL in your browser: {url}")
        return False

def monitor_colab_output():
    """
    Monitor for clipboard changes or user input to detect Cloudflare URL.
    
    This is a simplified version as we can't actually monitor Colab output 
    from a local terminal. Instead, we'll prompt the user to copy and paste
    the Cloudflare URL when they see it.
    """
    print("\n" + "="*80)
    print("WAITING FOR CLOUDFLARE URL")
    print("="*80)
    print("\nWhen you see a URL like 'https://xxxx-xxxx-xxxx-xxxx.trycloudflare.com' in Colab,")
    print("copy it and paste it here, or type it manually.")
    print("\nPress Ctrl+C at any time to exit.")
    
    try:
        while True:
            user_input = input("\nEnter the Cloudflare URL (or press Enter to check clipboard): ").strip()
            
            if user_input:
                # Check if the input looks like a Cloudflare URL
                if re.search(r'https?://.*\.trycloudflare\.com', user_input):
                    return user_input
                else:
                    print("That doesn't look like a Cloudflare URL. Please try again.")
            
            # Give some time before prompting again
            time.sleep(2)
            
    except KeyboardInterrupt:
        print("\nMonitoring stopped by user.")
        return None

def main():
    """Main function to run the script."""
    args = parse_arguments()
    
    # Generate the Colab URL with hardcoded GitHub username
    colab_url = get_colab_url()
    
    if not args.no_browser:
        open_colab_in_browser(colab_url)
    else:
        print(f"\nColab URL (open this in your browser):\n{colab_url}")
    
    # Monitor for the Cloudflare URL
    print(f"\nMonitoring for Cloudflare URL (timeout: {args.timeout} seconds)...")
    cloudflare_url = monitor_colab_output()
    
    if cloudflare_url:
        print("\n" + "="*80)
        print(f"CLOUDFLARE URL DETECTED: {cloudflare_url}")
        print("="*80)
        print("\nYou can now use this URL with SillyTavern or other applications.")
        print("Keep the Colab notebook running to maintain the connection.")
    else:
        print("\nNo Cloudflare URL detected before timeout or operation was cancelled.")

if __name__ == "__main__":
    main()