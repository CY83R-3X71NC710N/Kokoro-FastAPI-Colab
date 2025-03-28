# Kokoro-FastAPI-Colab

A ready-to-run Google Colab notebook for deploying Kokoro text-to-speech API with GPU acceleration and public access via Cloudflare.

## Features

- One-click launch of Kokoro TTS API on Google Colab with T4 GPU
- Automatic Cloudflare tunnel creation for public access
- Compatible with SillyTavern and other applications as an OpenAI-compatible TTS endpoint
- Pre-configured with all necessary setup steps

## Quick Start

Click the button below to open this project in Google Colab with T4 GPU acceleration:

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/CY83R-3X71NC710N/Kokoro-FastAPI-Colab/blob/main/launch_kokoro.ipynb)

## Usage

1. Click the "Open In Colab" button above
2. In Colab, go to Runtime → Change runtime type and select "T4 GPU" 
3. Run the notebook
4. The notebook will set up Kokoro TTS and create a public URL via Cloudflare
5. Use the generated URL in SillyTavern or other applications

# Todo
Use ngrok static domains

## Guide for Creating a Free Custom Static Ngrok Domain, Creating a Free Account, and Getting the Auth Token

### Step 1: Create a Free Ngrok Account
1. Go to the [ngrok website](https://ngrok.com/).
2. Click on the "Sign Up" button.
3. Fill in the required information to create a free account.
4. Verify your email address if required.

### Step 2: Get Your Ngrok Auth Token
1. Log in to your ngrok account.
2. Go to the "Auth" section in the dashboard.
3. Copy your auth token from the provided field.

### Step 3: Create a Free Custom Static Ngrok Domain
1. In the ngrok dashboard, go to the "Domain" section. [ngrok domain section](https://dashboard.ngrok.com/domains)
2. Click on "New Domain".
3. Get the domain and copy it
4. Your custom static ngrok domain will be something like `your-subdomain.ngrok.io`.

### Step 4: Set Up Ngrok in the Notebook
1. In the code cell at the top of this notebook, set the `NGROK_AUTH_TOKEN` variable to your auth token.
2. Set the `NGROK_CUSTOM_DOMAIN` variable to your reserved custom domain (optional).
3. Run the notebook to start the Kokoro FastAPI server with ngrok tunnel.

## License

See the [LICENSE](LICENSE) file for details.
