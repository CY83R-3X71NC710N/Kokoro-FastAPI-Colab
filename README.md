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

## License

See the [LICENSE](LICENSE) file for details.
