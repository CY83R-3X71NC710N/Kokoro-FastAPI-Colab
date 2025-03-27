#!/usr/bin/env python3
"""
Google Account Configuration for Kokoro TTS Proxy

This file stores Google account credentials for the proxy to use.
The proxy will rotate through these accounts when Colab limits are hit.
"""

# List of Google accounts to use for Colab
# Each account should have a name (for identification) and login credentials
GOOGLE_ACCOUNTS = [
    # Add your accounts here, for example:
    # {
    #     "name": "Primary Account",
    #     "email": "your.email@gmail.com",
    #     "password": "your-password"
    # },
    # {
    #     "name": "Secondary Account",
    #     "email": "your.second.email@gmail.com",
    #     "password": "second-password"
    # }
]

# Flag to indicate if authentication should be attempted automatically
# Set to False if you prefer to log in manually when prompted
ENABLE_AUTO_AUTH = True

# Time in seconds to wait for manual login if auto-auth is disabled or fails
MANUAL_LOGIN_TIMEOUT = 120

# GPU type to request (options: "T4", "P100", "V100")
PREFERRED_GPU = "T4"

# Set to True to use a headless browser (no visible window)
# For debugging, it's better to set this to False
USE_HEADLESS_BROWSER = False

# Use the GitHub URL instead of the local file path for more reliable loading
# Setting to False will use the remote GitHub URL
USE_LOCAL_NOTEBOOK = False