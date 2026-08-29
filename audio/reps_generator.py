"""
audio/reps_generator.py
------------------------
Developer tool for generating rep-count audio files using ElevenLabs TTS.

Generates audio/reps/rep_1.wav … rep_20.wav (spoken numbers 1–20).
This script is NOT part of the runtime application. Run it manually in a
development environment when new rep sounds are needed.

Usage:
    export ELEVENLABS_API_KEY="your_key_here"   # Linux/macOS
    set ELEVENLABS_API_KEY=your_key_here        # Windows
    python audio/reps_generator.py
"""

import os
import shutil
from elevenlabs.client import ElevenLabs

_ENGLISH_NUMBERS = [
    "One!", "Two!", "Three!", "Four!", "Five!",
    "Six!", "Seven!", "Eight!", "Nine!", "Ten!",
    "Eleven!", "Twelve!", "Thirteen!", "Fourteen!", "Fifteen!",
    "Sixteen!", "Seventeen!", "Eighteen!", "Nineteen!", "Twenty!",
]


def main():
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "ELEVENLABS_API_KEY environment variable is not set. "
            "Export the key before running this script."
        )

    client = ElevenLabs(api_key=api_key)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    reps_dir = os.path.join(script_dir, "reps")

    # Clear and recreate the output folder
    if os.path.exists(reps_dir):
        shutil.rmtree(reps_dir)
    os.makedirs(reps_dir)

    voice_id = "S1JKkpuAQNsowB8ZvKRO"
    model_id = "eleven_turbo_v2_5"

    for i, text in enumerate(_ENGLISH_NUMBERS, start=1):
        audio_stream = client.generate(text=text, voice=voice_id, model=model_id)
        output_path = os.path.join(reps_dir, f"rep_{i}.wav")
        with open(output_path, "wb") as f:
            for chunk in audio_stream:
                f.write(chunk)
        print(f"✅ Saved: {output_path}")


if __name__ == "__main__":
    main()
