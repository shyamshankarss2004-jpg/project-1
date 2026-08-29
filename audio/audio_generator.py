"""
audio/audio_generator.py
-------------------------
Developer tool for generating communication audio files using ElevenLabs TTS.

This script is NOT part of the runtime application. Run it manually in a
development environment to regenerate the WAV files in audio/communications/.

Usage:
    export ELEVENLABS_API_KEY="your_key_here"   # Linux/macOS
    set ELEVENLABS_API_KEY=your_key_here        # Windows
    python audio/audio_generator.py
"""

import os
from elevenlabs.client import ElevenLabs


def main():
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "ELEVENLABS_API_KEY environment variable is not set. "
            "Export the key before running this script."
        )

    client = ElevenLabs(api_key=api_key)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(script_dir, "communications")
    os.makedirs(output_dir, exist_ok=True)

    # Voice and model configuration
    voice_id = "S1JKkpuAQNsowB8ZvKRO"
    model_id = "eleven_turbo_v2_5"

    audio_prompts = {
        "prepare": "Get ready!",
        "exercise": "Exercise!",
        "finish": "Congratulations! You finished your workout. It has been saved in your history!",
        "ohp_wrong_1": "Keep your forearms perpendicular!",
        "squat_wrong_1": "Keep your arms in front of you!",
    }

    for file_type, text in audio_prompts.items():
        audio_stream = client.generate(text=text, voice=voice_id, model=model_id)
        output_path = os.path.join(output_dir, f"{file_type}.wav")
        with open(output_path, "wb") as f:
            for chunk in audio_stream:
                f.write(chunk)
        print(f"✅ Saved: {output_path}")


if __name__ == "__main__":
    main()
