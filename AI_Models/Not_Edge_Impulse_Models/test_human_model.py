import tensorflow as tf
import numpy as np
import pathlib
import os
import random
from PIL import Image

# --- CONFIGURATION ---
MODEL_PATH = "human_detection_model.tflite"
DATASET_PATH = "../../Human_Detection_Dataset"  # Relative to this script's location
IMG_SIZE = (96, 96)

def main():
    if not os.path.exists(MODEL_PATH):
        print(f"❌ Model file '{MODEL_PATH}' not found!")
        return

    # 1. Load TFLite Model
    print(f"Loading model: {MODEL_PATH}")
    interpreter = tf.lite.Interpreter(model_path=MODEL_PATH)
    interpreter.allocate_tensors()

    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()

    input_shape = input_details[0]['shape']
    print(f"Model Input Shape: {input_shape}")
    
    # 2. Get Test Images
    categories = ['Humans', 'NonHuman']
    try:
        test_images = []
        for cat in categories:
            folder = os.path.join(DATASET_PATH, cat)
            files = [f for f in os.listdir(folder) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
            # Pick 2 random images from each category
            picked = random.sample(files, min(2, len(files)))
            for p in picked:
                test_images.append((os.path.join(folder, p), cat))
    except Exception as e:
        print(f"⚠️ Could not load images from dataset: {e}")
        return

    if not test_images:
        print("❌ No images found to test.")
        return

    print("\n--- Starting Test ---")
    correct_count = 0
    total_count = len(test_images)

    for img_path, actual_label in test_images:
        try:
            # 3. Preprocess Image
            img = Image.open(img_path).convert('L') # Convert to Grayscale
            img = img.resize(IMG_SIZE)
            img_array = np.array(img, dtype=np.uint8) # Keep as uint8 for quantized input
            
            # Add batch dimension: (1, 96, 96, 1)
            input_data = np.expand_dims(img_array, axis=0) # Batch dim
            input_data = np.expand_dims(input_data, axis=-1) # Channel dim
            
            # 4. Run Inference
            interpreter.set_tensor(input_details[0]['index'], input_data)
            interpreter.invoke()
            
            # 5. Process Output
            output_data = interpreter.get_tensor(output_details[0]['index'])
            
            # The output is int8 (-128 to 127). We can interpret this directly or dequantize.
            # Simplified: Higher value means higher confidence.
            # Assuming output index 0 = Humans, 1 = NonHuman (based on alphabetical order in training usually)
            # Let's check raw scores.
            human_score_raw = output_data[0][0]
            non_human_score_raw = output_data[0][1]
            
            # Basic prediction logic: precise quantization handling can be complex,
            # but usually max score wins.
            predicted_label = "Humans" if human_score_raw > non_human_score_raw else "NonHuman"
            
            is_correct = (predicted_label == actual_label)
            if is_correct: correct_count += 1
            
            marker = "✅" if is_correct else "❌"
            print(f"{marker} Actual: {actual_label} | Pred: {predicted_label} | Scores: [H:{human_score_raw}, NH:{non_human_score_raw}] | File: {os.path.basename(img_path)}")

        except Exception as e:
            print(f"❌ Error processing image {img_path}: {e}")

    print(f"\n--- Accuracy: {correct_count}/{total_count} ({correct_count/total_count*100:.1f}%) ---")
    print("Note: Scores are varying int8 values from the quantized model.")

if __name__ == "__main__":
    main()
