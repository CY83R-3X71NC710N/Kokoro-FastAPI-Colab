#!/usr/bin/env python3
"""
Kokoro TTS API Proxy Server

This script serves as a proxy that:
1. Receives requests to /v1/audio/speech
2. Checks if a Kokoro TTS instance is active
3. If not, launches a new Colab notebook automatically
4. Forwards the request to the active TTS instance
5. Returns the response to the client
"""

import os
import json
import time
import uuid
import threading
import webbrowser
import logging
import random
from datetime import datetime, timedelta
from urllib.parse import urlparse

from flask import Flask, request, jsonify, redirect, render_template_string, Response
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import TimeoutException, WebDriverException, NoSuchElementException

# Import configuration
try:
    import config
except ImportError:
    # Default configuration if config.py doesn't exist
    class config:
        GOOGLE_ACCOUNTS = []
        ENABLE_AUTO_AUTH = True
        MANUAL_LOGIN_TIMEOUT = 120
        PREFERRED_GPU = "T4"
        USE_HEADLESS_BROWSER = False
        USE_LOCAL_NOTEBOOK = True

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("kokoro_proxy.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configuration
REMOTE_COLAB_URL = "https://colab.research.google.com/github/remsky/Kokoro-FastAPI-Colab/blob/main/launch_kokoro.ipynb"
LOCAL_COLAB_URL = "file:///workspaces/Kokoro-FastAPI-Colab/launch_kokoro.ipynb"

# Use local or remote URL based on configuration
DEFAULT_COLAB_URL = LOCAL_COLAB_URL if hasattr(config, 'USE_LOCAL_NOTEBOOK') and config.USE_LOCAL_NOTEBOOK else REMOTE_COLAB_URL

MAX_INSTANCE_AGE_HOURS = 8  # Max age of a Colab instance before creating a new one
HISTORY_FILE = os.path.expanduser("~/.kokoro_proxy_history.json")
KEEP_ALIVE_INTERVAL = 50 * 60  # 50 minutes in seconds
PROXY_PORT = 8080  # Port for the proxy server

# Global state
active_instances = []
launch_lock = threading.Lock()
is_launching = False
currently_used_account = None

app = Flask(__name__)

class ColabInstance:
    def __init__(self, cloudflare_url=None):
        self.id = str(uuid.uuid4())[:8]
        self.cloudflare_url = cloudflare_url
        self.created_at = datetime.now()
        self.last_used_at = datetime.now()
        self.status = "initializing" if not cloudflare_url else "active"
        self.google_account = None
    
    def to_dict(self):
        return {
            "id": self.id,
            "cloudflare_url": self.cloudflare_url,
            "created_at": self.created_at.isoformat(),
            "last_used_at": self.last_used_at.isoformat(),
            "status": self.status,
            "age_hours": self.age_hours(),
            "google_account": self.google_account
        }
    
    def age_hours(self):
        return (datetime.now() - self.created_at).total_seconds() / 3600
    
    def is_expired(self):
        return self.age_hours() > MAX_INSTANCE_AGE_HOURS
    
    def update_last_used(self):
        self.last_used_at = datetime.now()
    
    def is_active(self):
        if not self.cloudflare_url:
            return False
        
        # Check if instance is responsive
        try:
            response = requests.get(
                f"{self.cloudflare_url}/v1/audio/voices", 
                timeout=5
            )
            return response.status_code == 200
        except requests.RequestException:
            logger.warning(f"Instance {self.id} at {self.cloudflare_url} is not responsive")
            return False

def load_history():
    """Load previous instances history."""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                data = json.load(f)
                
                # Convert dictionary data to ColabInstance objects
                instances = []
                for instance_data in data.get("instances", []):
                    instance = ColabInstance(instance_data.get("cloudflare_url"))
                    instance.id = instance_data.get("id")
                    instance.created_at = datetime.fromisoformat(instance_data.get("created_at"))
                    instance.last_used_at = datetime.fromisoformat(instance_data.get("last_used_at"))
                    instance.status = instance_data.get("status")
                    instance.google_account = instance_data.get("google_account")
                    instances.append(instance)
                
                return instances
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"Error loading history: {e}")
            return []
    return []

def save_history(instances):
    """Save instances to history file."""
    with open(HISTORY_FILE, 'w') as f:
        # Convert ColabInstance objects to dictionaries
        instances_data = [instance.to_dict() for instance in instances]
        json.dump({"instances": instances_data}, f, indent=2)

def find_active_instance():
    """Find an active instance or return None."""
    for instance in active_instances:
        if instance.is_active():
            instance.update_last_used()
            return instance
    return None

def select_google_account(available_accounts):
    """
    Select a Google account to use for the next Colab instance.
    Implements a simple rotation strategy.
    """
    global currently_used_account
    
    if not available_accounts:
        logger.warning("No Google accounts configured. Manual login will be required.")
        return None
    
    # If we haven't used an account yet, use the first one
    if currently_used_account is None:
        selected_account = available_accounts[0]
        logger.info(f"Selected initial Google account: {selected_account['name']}")
    else:
        # Find the index of the current account
        current_index = -1
        for i, account in enumerate(available_accounts):
            if account['email'] == currently_used_account['email']:
                current_index = i
                break
        
        # Move to the next account in rotation
        if current_index >= 0 and current_index < len(available_accounts) - 1:
            selected_account = available_accounts[current_index + 1]
        else:
            # Wrap around to the first account
            selected_account = available_accounts[0]
        
        logger.info(f"Rotating to next Google account: {selected_account['name']}")
    
    currently_used_account = selected_account
    return selected_account

def google_login(driver, wait, account):
    """
    Handle Google login process.
    Returns True if login successful, False otherwise.
    """
    try:
        logger.info(f"Attempting to log in with Google account: {account['name']}")
        
        # Look for sign-in button
        try:
            # Try to find "Sign in" button (this appears if not logged in)
            sign_in_buttons = driver.find_elements(By.XPATH, "//paper-button[contains(text(), 'Sign in')]")
            if sign_in_buttons:
                logger.info("Found Sign in button, clicking...")
                sign_in_buttons[0].click()
                time.sleep(2)
        except Exception as e:
            logger.warning(f"No sign-in button found, might already be logged in: {e}")
        
        # Check if already logged in with this account
        try:
            # Look for account identifier that shows we're already logged in
            account_elements = driver.find_elements(By.XPATH, f"//*[contains(text(), '{account['email']}')]")
            if account_elements:
                logger.info(f"Already logged in with {account['email']}")
                return True
        except:
            pass
        
        # Look for email input field
        try:
            email_input = wait.until(EC.presence_of_element_located((By.NAME, "identifier")))
            email_input.clear()
            email_input.send_keys(account['email'])
            email_input.send_keys(Keys.RETURN)
            logger.info("Entered email address")
            time.sleep(2)
        except Exception as e:
            logger.warning(f"Could not enter email: {e}")
            # Try alternative email field
            try:
                email_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='email']")))
                email_input.clear()
                email_input.send_keys(account['email'])
                email_input.send_keys(Keys.RETURN)
                logger.info("Entered email address (alternative method)")
                time.sleep(2)
            except Exception as e2:
                logger.error(f"Could not enter email (both methods failed): {e2}")
                return False
        
        # Look for password input field
        try:
            password_input = wait.until(EC.presence_of_element_located((By.NAME, "password")))
            password_input.clear()
            password_input.send_keys(account['password'])
            password_input.send_keys(Keys.RETURN)
            logger.info("Entered password")
            time.sleep(3)
        except Exception as e:
            logger.warning(f"Could not enter password: {e}")
            # Try alternative password field
            try:
                password_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='password']")))
                password_input.clear()
                password_input.send_keys(account['password'])
                password_input.send_keys(Keys.RETURN)
                logger.info("Entered password (alternative method)")
                time.sleep(3)
            except Exception as e2:
                logger.error(f"Could not enter password (both methods failed): {e2}")
                return False
        
        # Check for 2FA or additional verification
        try:
            # Wait a bit to see if we're asked for verification
            time.sleep(5)
            
            # Check for "Verify it's you" text
            verify_elements = driver.find_elements(By.XPATH, "//*[contains(text(), 'Verify it')]")
            if verify_elements:
                logger.warning("2FA or additional verification required. Manual intervention needed.")
                
                # Wait for manual verification
                logger.info(f"Waiting {config.MANUAL_LOGIN_TIMEOUT} seconds for manual verification...")
                time.sleep(config.MANUAL_LOGIN_TIMEOUT)
                
                # If we're still on a login page, it failed
                if "signin" in driver.current_url or "accounts.google.com" in driver.current_url:
                    logger.error("Still on login page after timeout. Manual verification failed.")
                    return False
        except:
            pass
        
        # Check if we're successfully logged in
        try:
            # Wait for the colab page to load
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "colab-connect-button")))
            logger.info("Successfully logged in and returned to Colab")
            return True
        except Exception as e:
            logger.error(f"Failed to verify successful login: {e}")
            return False
        
    except Exception as e:
        logger.error(f"Unexpected error during Google login: {e}")
        return False

def select_t4_gpu(driver, wait):
    """
    Specifically select T4 GPU in Colab runtime options.
    Returns: 
    - True if successful
    - False if failed but other GPUs might be available
    - "unavailable" if T4 GPU is unavailable (quota exceeded)
    """
    try:
        logger.info("Attempting to select T4 GPU...")
        
        # First, click the Runtime type dropdown
        try:
            # First click "Runtime" menu
            runtime_menu = wait.until(EC.element_to_be_clickable((By.XPATH, "//div[contains(text(), 'Runtime')]")))
            runtime_menu.click()
            time.sleep(1)
            
            # Then click "Change runtime type"
            change_runtime = wait.until(EC.element_to_be_clickable((By.XPATH, "//div[contains(text(), 'Change runtime type')]")))
            change_runtime.click()
            logger.info("Clicked 'Change runtime type'")
            time.sleep(2)
        except Exception as e:
            logger.warning(f"Could not access runtime change menu: {e}")
            return False
        
        # Check for GPU quota exceeded messages
        try:
            quota_exceeded_messages = driver.find_elements(
                By.XPATH, 
                "//*[contains(text(), 'GPU unavailable') or contains(text(), 'exceeded your quota') or contains(text(), 'not available')]"
            )
            if quota_exceeded_messages:
                logger.warning(f"Detected GPU quota exceeded message: {quota_exceeded_messages[0].text}")
                
                # Try to close dialog
                try:
                    close_buttons = driver.find_elements(By.XPATH, "//button[contains(text(), 'Cancel')]")
                    if close_buttons:
                        close_buttons[0].click()
                except:
                    pass
                    
                return "unavailable"
        except:
            pass
            
        # Select GPU from hardware accelerator dropdown
        try:
            # Wait for dialog to appear
            wait.until(EC.presence_of_element_located((By.XPATH, "//div[contains(text(), 'Hardware accelerator')]")))
            
            # Click on hardware accelerator dropdown
            hardware_dropdown = wait.until(EC.element_to_be_clickable((By.XPATH, "//div[contains(@class, 'md-select-value')]")))
            hardware_dropdown.click()
            time.sleep(1)
            
            # Select GPU option
            gpu_option = wait.until(EC.element_to_be_clickable((By.XPATH, "//md-option/div[contains(text(), 'GPU')]")))
            gpu_option.click()
            logger.info("Selected GPU hardware accelerator")
            time.sleep(1)
            
            # Look for T4 specific options if available
            try:
                # Some Colab versions let you choose the GPU type
                gpu_type_dropdown = driver.find_elements(By.XPATH, "//div[contains(text(), 'GPU type')]")
                if gpu_type_dropdown:
                    gpu_type_dropdown[0].click()
                    time.sleep(1)
                    
                    # Try to select T4
                    t4_option = driver.find_elements(By.XPATH, "//div[contains(text(), 'T4')]")
                    if t4_option:
                        t4_option[0].click()
                        logger.info("Specifically selected T4 GPU")
                    else:
                        logger.warning("T4 GPU option not found in dropdown")
            except:
                logger.info("GPU type selector not available, using default GPU")
                
            # Check for T4 unavailable message after selection
            try:
                unavailable_messages = driver.find_elements(
                    By.XPATH, 
                    "//*[contains(text(), 'T4 unavailable') or contains(text(), 'exceeded your quota') or contains(text(), 'not available')]"
                )
                if unavailable_messages:
                    logger.warning(f"T4 GPU is unavailable: {unavailable_messages[0].text}")
                    
                    # Try to close dialog
                    try:
                        close_buttons = driver.find_elements(By.XPATH, "//button[contains(text(), 'Cancel')]")
                        if close_buttons:
                            close_buttons[0].click()
                    except:
                        pass
                        
                    return "unavailable"
            except:
                pass
                
            # Click Save button
            save_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Save')]")))
            save_button.click()
            logger.info("Saved runtime configuration")
            time.sleep(2)
            
            return True
        except Exception as e:
            logger.error(f"Error selecting GPU: {e}")
            
            # Try to close dialog if open
            try:
                close_buttons = driver.find_elements(By.XPATH, "//button[contains(text(), 'Cancel')]")
                if close_buttons:
                    close_buttons[0].click()
            except:
                pass
                
            return False
    except Exception as e:
        logger.error(f"Unexpected error configuring GPU: {e}")
        return False

def launch_colab_automated(google_account_name=None):
    """
    Launch Colab notebook automatically using Selenium.
    This function handles:
    1. Opening Colab in Chrome
    2. Google account login if needed
    3. Selecting a runtime with T4 GPU
    4. Running the notebook
    5. Extracting the Cloudflare URL
    6. Keeping the notebook alive
    """
    global is_launching
    
    with launch_lock:
        if is_launching:
            logger.info("Launch already in progress, waiting...")
            return None
        is_launching = True
    
    try:
        logger.info("Setting up Chrome driver for automated Colab launch")
        chrome_options = Options()
        
        # Configure browser based on settings
        if config.USE_HEADLESS_BROWSER:
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--window-size=1920,1080")
        else:
            # For debugging, it's better to see the browser
            chrome_options.add_argument("--start-maximized")
        
        driver = webdriver.Chrome(ChromeDriverManager().install(), options=chrome_options)
        wait = WebDriverWait(driver, 60)  # 1 minute timeout for operations
        
        # Create a new instance to track
        instance = ColabInstance()
        active_instances.append(instance)
        
        # Select an account to use
        account = None
        if config.GOOGLE_ACCOUNTS:
            if google_account_name:
                # Use specified account
                for acc in config.GOOGLE_ACCOUNTS:
                    if acc['name'] == google_account_name or acc['email'] == google_account_name:
                        account = acc
                        break
                
                if not account:
                    logger.warning(f"Specified account '{google_account_name}' not found in config. Using account selection strategy.")
            
            # If no account specified or not found, use selection strategy
            if not account:
                account = select_google_account(config.GOOGLE_ACCOUNTS)
        
        if account:
            instance.google_account = account['name']
        save_history(active_instances)
        
        # Navigate to Colab
        logger.info(f"Opening Colab URL: {DEFAULT_COLAB_URL}")
        driver.get(DEFAULT_COLAB_URL)
        
        # Wait for page to load
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "colab-connect-button")))
        logger.info("Colab page loaded")
        
        # Handle Google login if needed
        login_success = False
        
        if account and config.ENABLE_AUTO_AUTH:
            # Attempt automatic login
            login_success = google_login(driver, wait, account)
            if login_success:
                logger.info(f"Successfully logged in with account: {account['name']}")
            else:
                logger.warning(f"Auto-login failed for account: {account['name']}")
                
                # If auto-login failed, wait for manual login
                logger.info(f"Waiting {config.MANUAL_LOGIN_TIMEOUT} seconds for manual login...")
                time.sleep(config.MANUAL_LOGIN_TIMEOUT)
        else:
            # No account configured or auto-auth disabled, wait for manual login
            logger.info(f"No account configured or auto-auth disabled. Waiting {config.MANUAL_LOGIN_TIMEOUT} seconds for manual login...")
            time.sleep(config.MANUAL_LOGIN_TIMEOUT)
        
        # Select T4 GPU if configured
        if config.PREFERRED_GPU == "T4":
            gpu_configured = select_t4_gpu(driver, wait)
            if gpu_configured == True:
                logger.info("Successfully configured T4 GPU")
            elif gpu_configured == "unavailable":
                logger.warning("T4 GPU is unavailable due to quota limits for this account")
                
                # If we have multiple accounts, try with a different one
                if len(config.GOOGLE_ACCOUNTS) > 1 and account:
                    logger.info("T4 GPU unavailable - will retry with a different Google account")
                    
                    # Mark this attempt as failed
                    with launch_lock:
                        is_launching = False
                    
                    # Clean up
                    instance.status = "error"
                    save_history(active_instances)
                    driver.quit()
                    
                    # Get next account (excluding current one)
                    current_email = account['email']
                    next_accounts = [acc for acc in config.GOOGLE_ACCOUNTS if acc['email'] != current_email]
                    if next_accounts:
                        next_account = next_accounts[0]['name']
                        logger.info(f"Retrying with account: {next_account}")
                        
                        # Launch with next account
                        return launch_colab_automated(next_account)
                    else:
                        logger.warning("No more accounts available to try")
            else:
                logger.warning("Failed to explicitly configure T4 GPU, will try Connect button")
        
        # Look for and click the "Connect" button
        try:
            logger.info("Looking for Connect button...")
            connect_button = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "colab-connect-button"))
            )
            connect_button.click()
            logger.info("Clicked Connect button")
            
            # Wait for the runtime to start connecting
            logger.info("Waiting for runtime to connect...")
            time.sleep(10)  # Give it time to connect or show dialog
            
            # Check for disconnected notification and try again if needed
            disconnected_warnings = driver.find_elements(By.XPATH, "//div[contains(text(), 'Disconnected')]")
            if disconnected_warnings:
                logger.warning("Disconnected warning detected, trying to reconnect")
                connect_buttons = driver.find_elements(By.CSS_SELECTOR, "colab-connect-button")
                if connect_buttons:
                    connect_buttons[0].click()
                    logger.info("Clicked Connect button again")
                    time.sleep(5)
            
            # Check for T4 GPU related messages
            t4_unavailable = driver.find_elements(By.XPATH, "//*[contains(text(), 'T4 GPU') and (contains(text(), 'unavailable') or contains(text(), 'exceeded') or contains(text(), 'limited'))]")
            
            # Check for resource limit errors
            resource_warnings = driver.find_elements(By.XPATH, "//*[contains(text(), 'resource limits') or contains(text(), 'quota')]")
            quota_warnings = driver.find_elements(By.XPATH, "//*[contains(text(), 'quota') and contains(text(), 'exceeded')]")
            gpu_unavailable = driver.find_elements(By.XPATH, "//*[contains(text(), 'GPU') and contains(text(), 'unavailable')]")
            
            # If we detect any GPU limit or quota issues, switch accounts
            if t4_unavailable or resource_warnings or quota_warnings or gpu_unavailable:
                limit_message = ""
                if t4_unavailable and t4_unavailable[0].text:
                    limit_message = t4_unavailable[0].text
                elif gpu_unavailable and gpu_unavailable[0].text:
                    limit_message = gpu_unavailable[0].text
                elif resource_warnings and resource_warnings[0].text:
                    limit_message = resource_warnings[0].text
                elif quota_warnings and quota_warnings[0].text:
                    limit_message = quota_warnings[0].text
                
                logger.warning(f"T4 GPU limit detected: {limit_message}")
                
                # If we have other accounts, try with a different one
                if len(config.GOOGLE_ACCOUNTS) > 1 and account:
                    logger.info("T4 GPU limit reached - will retry with a different Google account")
                    
                    # Mark this attempt as failed
                    with launch_lock:
                        is_launching = False
                    
                    # Clean up
                    instance.status = "error" 
                    save_history(active_instances)
                    driver.quit()
                    
                    # Get next account (excluding current one)
                    current_email = account['email']
                    next_accounts = [acc for acc in config.GOOGLE_ACCOUNTS if acc['email'] != current_email]
                    if next_accounts:
                        next_account = next_accounts[0]['name']
                        logger.info(f"Retrying with account: {next_account}")
                        
                        # Launch with next account
                        return launch_colab_automated(next_account)
                    else:
                        logger.warning("No more accounts available to try")
            
            # Wait for runtime initialization to complete
            logger.info("Waiting for runtime to initialize...")
            try:
                wait.until(EC.invisibility_of_element_located((By.XPATH, "//div[contains(text(), 'Initializing')]")))
                logger.info("Runtime initialized")
            except TimeoutException:
                logger.warning("Timeout while waiting for runtime initialization. Continuing anyway.")
                
        except (TimeoutException, WebDriverException) as e:
            logger.error(f"Error connecting to runtime: {e}")
            instance.status = "error"
            save_history(active_instances)
            driver.quit()
            with launch_lock:
                is_launching = False
            return None
        
        # Run the notebook cell
        try:
            # Find the run cell button and click it
            run_button = wait.until(
                EC.element_to_be_clickable((By.XPATH, "//paper-icon-button[@icon='colab:play-arrow']"))
            )
            run_button.click()
            logger.info("Clicked Run button")
            
            # Inject keep-alive script
            logger.info("Injecting keep-alive script...")
            keep_alive_script = """
            function ClickConnect() {
              console.log("Clicked connect button");
              document.querySelector("colab-toolbar-button#connect").click();
            }
            setInterval(ClickConnect, 60000);
            """
            driver.execute_script(keep_alive_script)
            logger.info("Keep-alive script injected")
            
            # Wait for the Cloudflare URL to appear in the output
            logger.info("Waiting for Cloudflare URL to appear...")
            cloudflare_element = None
            max_attempts = 60  # 5 minutes (5 seconds per attempt)
            
            for attempt in range(max_attempts):
                try:
                    # Look for output containing Cloudflare URL
                    outputs = driver.find_elements(By.CSS_SELECTOR, ".outputview-content")
                    for output in outputs:
                        text = output.text
                        if "trycloudflare.com" in text and "Kokoro API is now available at:" in text:
                            cloudflare_element = output
                            break
                    
                    if cloudflare_element:
                        break
                        
                    logger.info(f"Waiting for Cloudflare URL (attempt {attempt+1}/{max_attempts})...")
                    time.sleep(5)
                except Exception as e:
                    logger.warning(f"Error checking for Cloudflare URL: {e}")
                    time.sleep(5)
            
            if cloudflare_element:
                # Extract the Cloudflare URL
                output_text = cloudflare_element.text
                lines = output_text.split('\n')
                cloudflare_url = None
                
                for line in lines:
                    if "Kokoro API is now available at:" in line:
                        parts = line.split("Kokoro API is now available at:")
                        if len(parts) > 1:
                            cloudflare_url = parts[1].strip()
                            break
                
                if cloudflare_url:
                    logger.info(f"Found Cloudflare URL: {cloudflare_url}")
                    instance.cloudflare_url = cloudflare_url
                    instance.status = "active"
                    save_history(active_instances)
                    
                    # Keep the browser open to maintain the Colab session
                    # The browser will continue running in the background
                    
                    with launch_lock:
                        is_launching = False
                    
                    # Start a keep-alive thread for Colab
                    threading.Thread(
                        target=keep_colab_alive,
                        args=(driver, instance),
                        daemon=True
                    ).start()
                    
                    return instance
                else:
                    logger.error("Cloudflare URL not found in output")
            else:
                logger.error("Timeout waiting for Cloudflare URL")
            
        except Exception as e:
            logger.error(f"Error running notebook: {e}")
        
        # If we get here, something went wrong
        instance.status = "error"
        save_history(active_instances)
        driver.quit()
        
    except Exception as e:
        logger.error(f"Unexpected error launching Colab: {e}")
    
    with launch_lock:
        is_launching = False
    
    return None

def keep_colab_alive(driver, instance):
    """Keep the Colab notebook running by periodically interacting with it."""
    logger.info(f"Starting keep-alive thread for instance {instance.id}")
    
    try:
        while instance.status == "active" and not instance.is_expired():
            time.sleep(KEEP_ALIVE_INTERVAL)
            
            # Check if instance is still active
            if not instance.is_active():
                logger.warning(f"Instance {instance.id} no longer responding, marking as inactive")
                instance.status = "inactive"
                save_history(active_instances)
                break
            
            # Refresh the page to keep it active
            try:
                logger.info(f"Performing keep-alive action for instance {instance.id}")
                driver.refresh()
                time.sleep(5)
                
                # Click connect button if needed
                try:
                    connect_buttons = driver.find_elements(By.CSS_SELECTOR, "colab-toolbar-button#connect")
                    if connect_buttons:
                        connect_buttons[0].click()
                        logger.info("Clicked reconnect button during keep-alive")
                except:
                    pass
                
                # Re-inject keep-alive script
                keep_alive_script = """
                function ClickConnect() {
                  console.log("Clicked connect button");
                  document.querySelector("colab-toolbar-button#connect").click();
                }
                setInterval(ClickConnect, 60000);
                """
                driver.execute_script(keep_alive_script)
                
            except Exception as e:
                logger.error(f"Error during keep-alive: {e}")
                instance.status = "error"
                save_history(active_instances)
                break
    except Exception as e:
        logger.error(f"Keep-alive thread error: {e}")
    finally:
        logger.info(f"Keep-alive thread for instance {instance.id} terminated")
        try:
            driver.quit()
        except:
            pass

def get_or_create_instance():
    """Get an active instance or create a new one if needed."""
    # First check for an active instance
    instance = find_active_instance()
    if instance:
        logger.info(f"Using existing instance {instance.id} at {instance.cloudflare_url}")
        return instance
    
    # No active instance, launch a new one
    logger.info("No active instance found, launching a new one")
    
    # Get all available Google accounts from history
    accounts = set()
    for instance in load_history():
        if instance.google_account:
            accounts.add(instance.google_account)
    
    # Use the first account for now
    # In a more sophisticated version, we could rotate through accounts
    selected_account = next(iter(accounts)) if accounts else None
    
    return launch_colab_automated(selected_account)

# API Routes
@app.route('/')
def index():
    """Home page with status and management UI."""
    instances = [instance.to_dict() for instance in active_instances]
    
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Kokoro TTS Proxy</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                max-width: 1000px;
                margin: 0 auto;
                padding: 20px;
                line-height: 1.6;
            }
            h1, h2 {
                color: #2c3e50;
            }
            .container {
                background-color: #f9f9f9;
                border-radius: 8px;
                padding: 20px;
                margin-top: 20px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }
            table {
                width: 100%;
                border-collapse: collapse;
                margin: 20px 0;
            }
            th, td {
                border: 1px solid #ddd;
                padding: 10px;
                text-align: left;
            }
            th {
                background-color: #f2f2f2;
            }
            tr:nth-child(even) {
                background-color: #f9f9f9;
            }
            .btn {
                display: inline-block;
                padding: 8px 16px;
                background-color: #3498db;
                color: white;
                border: none;
                border-radius: 4px;
                cursor: pointer;
                text-decoration: none;
                margin-right: 10px;
            }
            .btn:hover {
                background-color: #2980b9;
            }
            .status-active {
                color: green;
                font-weight: bold;
            }
            .status-error, .status-inactive {
                color: red;
            }
            .status-initializing {
                color: orange;
            }
        </style>
    </head>
    <body>
        <h1>Kokoro TTS Proxy Status</h1>
        
        <div class="container">
            <h2>Active Instances</h2>
            {% if instances %}
            <table>
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Status</th>
                        <th>URL</th>
                        <th>Age (hours)</th>
                        <th>Last Used</th>
                        <th>Google Account</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {% for instance in instances %}
                    <tr>
                        <td>{{ instance.id }}</td>
                        <td class="status-{{ instance.status }}">{{ instance.status }}</td>
                        <td>{{ instance.cloudflare_url }}</td>
                        <td>{{ "%.2f"|format(instance.age_hours) }}</td>
                        <td>{{ instance.last_used_at }}</td>
                        <td>{{ instance.google_account or 'Unknown' }}</td>
                        <td>
                            <a href="{{ instance.cloudflare_url }}/docs" target="_blank" class="btn">API Docs</a>
                            <a href="{{ instance.cloudflare_url }}/web" target="_blank" class="btn">Web UI</a>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            {% else %}
            <p>No active instances found.</p>
            {% endif %}
            
            <a href="/launch" class="btn">Launch New Instance</a>
        </div>
        
        <div class="container">
            <h2>API Usage</h2>
            <p>The proxy will automatically route requests to the active Kokoro TTS instance.</p>
            <p>Example TTS endpoint: <code>http://localhost:{{ port }}/v1/audio/speech</code></p>
            <p>This endpoint is API-compatible with the original Kokoro TTS endpoint.</p>
        </div>
    </body>
    </html>
    """
    
    return render_template_string(
        html, 
        instances=instances,
        port=PROXY_PORT
    )

@app.route('/launch')
def launch_new():
    """Launch a new Colab instance."""
    threading.Thread(
        target=launch_colab_automated,
        daemon=True
    ).start()
    
    return redirect('/')

@app.route('/v1/audio/speech', methods=['POST'])
def proxy_speech():
    """Proxy the TTS request to an active Kokoro instance."""
    instance = get_or_create_instance()
    
    if not instance:
        return jsonify({
            "error": "No active TTS instance available and failed to create a new one"
        }), 500
    
    # Forward the request to the active instance
    try:
        logger.info(f"Forwarding TTS request to {instance.cloudflare_url}")
        
        # Clone the original request
        headers = {key: value for key, value in request.headers if key != 'Host'}
        data = request.get_data()
        
        # Forward the request
        response = requests.post(
            f"{instance.cloudflare_url}/v1/audio/speech",
            headers=headers,
            data=data,
            timeout=60  # Longer timeout for TTS generation
        )
        
        # Update last used timestamp
        instance.update_last_used()
        
        # Return the response from the TTS service
        return Response(
            response.content,
            status=response.status_code,
            content_type=response.headers.get('Content-Type', 'application/octet-stream')
        )
        
    except requests.RequestException as e:
        logger.error(f"Error forwarding request: {e}")
        return jsonify({
            "error": f"Error communicating with TTS service: {str(e)}"
        }), 500

# Proxy other API endpoints as needed
@app.route('/v1/audio/voices', methods=['GET'])
def proxy_voices():
    """Proxy the voices request to an active Kokoro instance."""
    instance = get_or_create_instance()
    
    if not instance:
        return jsonify({
            "error": "No active TTS instance available and failed to create a new one"
        }), 500
    
    # Forward the request to the active instance
    try:
        logger.info(f"Forwarding voices request to {instance.cloudflare_url}")
        
        # Forward the request
        response = requests.get(
            f"{instance.cloudflare_url}/v1/audio/voices",
            timeout=10
        )
        
        # Update last used timestamp
        instance.update_last_used()
        
        # Return the response from the TTS service
        return Response(
            response.content,
            status=response.status_code,
            content_type=response.headers.get('Content-Type', 'application/json')
        )
        
    except requests.RequestException as e:
        logger.error(f"Error forwarding request: {e}")
        return jsonify({
            "error": f"Error communicating with TTS service: {str(e)}"
        }), 500

# Main entry point
def main():
    global active_instances
    
    # Load existing instances from history
    active_instances = load_history()
    logger.info(f"Loaded {len(active_instances)} instances from history")
    
    # Validate existing instances
    valid_instances = []
    for instance in active_instances:
        if instance.status == "active" and instance.is_active() and not instance.is_expired():
            logger.info(f"Found valid active instance: {instance.id} at {instance.cloudflare_url}")
            valid_instances.append(instance)
        else:
            logger.info(f"Marking instance as inactive: {instance.id}")
            instance.status = "inactive"
            valid_instances.append(instance)
    
    active_instances = valid_instances
    save_history(active_instances)
    
    # Start the Flask app
    logger.info(f"Starting proxy server on port {PROXY_PORT}")
    app.run(host='0.0.0.0', port=PROXY_PORT, debug=False)

if __name__ == "__main__":
    main()