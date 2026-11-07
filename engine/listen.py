import sys
from pathlib import Path

import pyaudio
import numpy as np
from openwakeword.model import Model

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

import action

if __name__ == "__main__":
    raise SystemExit(action.main())

MODEL_PATH = BASE_DIR / "models" / "onyx.onnx"

SAMPLE_RATE = 16000
CHUNK_SIZE = 1280
THRESHOLD = 0.7


def main():
    print("Initializing ONYX...")

    model = Model(
        wakeword_models=[str(MODEL_PATH)],
        inference_framework="onnx"
    )

    print("Model loaded successfully!")

    audio_interface = pyaudio.PyAudio()

    stream = audio_interface.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=SAMPLE_RATE,
        input=True,
        frames_per_buffer=CHUNK_SIZE
    )

    print("\nONYX IS LISTENING...")
    print("Press CTRL+C to stop.\n")

    try:
        while True:
            audio_data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
            audio = np.frombuffer(audio_data, dtype=np.int16)

            predictions = model.predict(audio)

            for name, score in predictions.items():
                print(f"\r{name}: {score:.4f}", end="", flush=True)

                if score >= THRESHOLD:
                    print("\n[ONYX DETECTED]")
                    action.run(stream)
                    model.reset()
                    print("\nONYX IS LISTENING...\n")
                    break

    except KeyboardInterrupt:
        print("\n\nONYX shutting down...")

    finally:
        stream.stop_stream()
        stream.close()
        audio_interface.terminate()


if __name__ == "__main__":
    main()