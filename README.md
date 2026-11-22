# HelloCret: English script to vertical clip

A Google Colab prototype that accepts one English script, generates narration with Chatterbox, illustrates sentence-sized beats with locally drawn cartoon scenes, overlays word-by-word captions, and exports a vertical MP4.

## First-version behavior

- One script field and one Generate action; no per-video style or voice controls.
- Chatterbox runs on CUDA when a Colab GPU is available.
- The same Chatterbox model speaker is used on each run. Its default speaker is not documented as a guaranteed US-male preset. For a verifiable fixed male-US voice, add a licensed reference WAV once and configure it as the optional Chatterbox audio prompt.
- Scenes are procedural 2D/2.5D drawings. No external image/video-generation service or API key is used. This is an illustrated approximation, not a visual clone of the reference video's 3D scenes.
- Caption timing is estimated per spoken sentence from word length and sentence audio duration. It is not phoneme-level forced alignment, so word-level synchronization is approximate.
- Output is 720x1280 at 30 fps. Rendering runs in Colab. Chatterbox uses the GPU; H.264 GPU encoding is used only if available, otherwise FFmpeg uses CPU encoding.

Colab free sessions can disconnect and are not an always-on service. Start a notebook session for each batch.

## Run in Colab

1. Open `notebooks/hellocret_colab.ipynb` in Google Colab.
2. Select a T4 GPU runtime if available.
3. Run the setup cell and then the interface cell.
4. Paste an English script in the only text field and click Generate. The full pipeline runs without additional prompts.
5. Download the MP4 shown in the output area.

The first run downloads Chatterbox. Model availability and first-run latency depend on the Colab session. Automated repository tests cover validation, timing helpers, and local frame rendering; they do not prove a live model download or T4 render.

## Local smoke tests

`PYTHONPATH=src python -m unittest discover -s tests -v`

Only use a voice reference recording you have permission to use.
