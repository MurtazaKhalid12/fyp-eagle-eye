import os
import sys
import numpy as np
from pathlib import Path
import cv2

try:
    import tensorflow as tf
    from PIL import Image
except ImportError:
    print("Missing packages. Run: pip install tensorflow pillow")
    sys.exit(1)

# Paths
REPO_ROOT   = Path(r"C:\fyp-eagle-eye")
TEST_FOLDER_H = REPO_ROOT / "sketchboard" / "dataset" / "Humans"
TEST_FOLDER_N = REPO_ROOT / "sketchboard" / "dataset" / "NonHuman"

IMG_W = IMG_H = 48

# Preprocessing
def preprocess(img_path: Path):
    # 1) Open image
    img = Image.open(img_path).convert('L')  # Convert to Grayscale ('L')

    # 2) Resize
    resized = img.resize((IMG_W, IMG_H))

    # 3) Convert to array and shape as (1, 48, 48, 1)
    img_array = np.array(resized)
    img_array = np.expand_dims(img_array, axis=-1) # Add channel dimension
    
    # 4) Normalize to int8 [-128, 127]
    inp = (img_array.astype(np.int32) - 128).astype(np.int8)

    # Reshape to (1, 48, 48, 1)
    return np.expand_dims(inp, axis=0)

interpreter = None
input_details = None
output_details = None

def init_interpreter():
    global interpreter, input_details, output_details
    model_path = REPO_ROOT / "sketchboard" / "augmented_human_model.tflite"
    interpreter = tf.lite.Interpreter(model_path=str(model_path))
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()[0]
    output_details = interpreter.get_output_details()[0]

def predict(img_path: Path):
    tensor = preprocess(img_path)
    if tensor is None:
        return None
    interpreter.set_tensor(input_details["index"], tensor)
    interpreter.invoke()
    out = interpreter.get_tensor(output_details["index"]).astype(np.int32).flatten()
    h, n = int(out[0]), int(out[1])
    is_human = (h > n) and (h > 10)
    return is_human, h, n

def run_test(folder_path, expected_human):
    images = list(folder_path.glob("*.jpg")) + list(folder_path.glob("*.jpeg")) + list(folder_path.glob("*.png"))
    
    correct = 0
    total = len(images)
    if total == 0:
        return 0, 0
        
    for img_path in images:
        result = predict(img_path)
        if not result: continue
        
        is_human, score_h, score_n = result
        
        if is_human == expected_human:
            correct += 1
        else:
            print(f"    X  {img_path.name:40s}  H={score_h:4d} N={score_n:4d}  [Expected {'Human' if expected_human else 'NonHuman'}]")
            
    return correct, total

def main():
    print("\n" + "="*60)
    print("  EagleEye — Sketchboard Test (RGB Transfer Learning)")
    print("="*60)
    
    # Init Interpreter
    init_interpreter()
    
    print("\nTesting Humans folder...")
    h_correct, h_total = run_test(TEST_FOLDER_H, expected_human=True)
    
    print("\nTesting NonHuman folder...")
    n_correct, n_total = run_test(TEST_FOLDER_N, expected_human=False)
    
    print("\n" + "="*60)
    print("  RESULTS")
    print("="*60)
    if h_total > 0: print(f"  Human accuracy    : {h_correct:4d}/{h_total:<4d} ({(h_correct/h_total)*100:.1f}%)")
    if n_total > 0: print(f"  NonHuman accuracy : {n_correct:4d}/{n_total:<4d} ({(n_correct/n_total)*100:.1f}%)")
    
    total = h_total + n_total
    correct = h_correct + n_correct
    if total > 0:
        print(f"  Overall accuracy  : {correct:4d}/{total:<4d} ({(correct/total)*100:.1f}%)")
        
    tp = h_correct
    fp = n_total - n_correct
    fn = h_total - h_correct
    
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    
    print(f"  Precision         : {precision:.3f}")
    print(f"  Recall            : {recall:.3f}")
    print(f"  F1 Score          : {f1:.3f}")
    print()

if __name__ == "__main__":
    main()
