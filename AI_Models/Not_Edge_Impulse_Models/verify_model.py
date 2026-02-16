"""Quick test: verify INT8 TFLite model scores on validation images"""
import tensorflow as tf
import numpy as np
import pathlib

DATASET_PATH = '../../Human_Detection_Dataset/Human_Detection_Dataset'
MODEL_PATH = 'tiny_human_model_color.tflite'

def main():
    # Load model
    print(f"Loading: {MODEL_PATH}")
    interp = tf.lite.Interpreter(model_path=MODEL_PATH)
    interp.allocate_tensors()
    
    inp = interp.get_input_details()
    out = interp.get_output_details()
    
    print(f"Input:  {inp[0]['shape']}, {inp[0]['dtype']}")
    print(f"Output: {out[0]['shape']}, {out[0]['dtype']}")
    print(f"Input quant:  scale={inp[0]['quantization'][0]:.6f}, zp={inp[0]['quantization'][1]}")
    print(f"Output quant: scale={out[0]['quantization'][0]:.6f}, zp={out[0]['quantization'][1]}")
    
    # Load validation data
    data_dir = pathlib.Path(DATASET_PATH)
    val_ds = tf.keras.utils.image_dataset_from_directory(
        data_dir,
        validation_split=0.2,
        subset="validation",
        seed=123,
        image_size=(48, 48),
        batch_size=32,
        color_mode='rgb'
    )
    
    class_names = val_ds.class_names
    print(f"\nClasses: {class_names}")
    print(f"  output[0] = '{class_names[0]}'")
    print(f"  output[1] = '{class_names[1]}'")
    
    # Test
    correct = 0
    total = 0
    scores = {name: [] for name in class_names}
    
    for images, labels in val_ds:
        for i in range(images.shape[0]):
            img = tf.cast(images[i], tf.float32).numpy()
            img_int8 = (img - 128).astype(np.int8)
            img_int8 = np.expand_dims(img_int8, 0)
            
            interp.set_tensor(inp[0]['index'], img_int8)
            interp.invoke()
            
            result = interp.get_tensor(out[0]['index'])
            pred = np.argmax(result[0])
            actual = int(labels[i].numpy())
            
            scores[class_names[actual]].append(
                (int(result[0][0]), int(result[0][1]))
            )
            
            if pred == actual:
                correct += 1
            total += 1
    
    acc = correct / total
    print(f"\n{'='*50}")
    print(f"INT8 Accuracy: {acc:.3f} ({acc*100:.1f}%)")
    print(f"{'='*50}")
    
    # Score distribution
    for name in class_names:
        s = scores[name]
        if s:
            s0 = [x[0] for x in s]
            s1 = [x[1] for x in s]
            print(f"\nWhen actual = {name} ({len(s)} images):")
            print(f"  {class_names[0]:>10} score: min={min(s0):>4}, max={max(s0):>4}, avg={np.mean(s0):>6.1f}")
            print(f"  {class_names[1]:>10} score: min={min(s1):>4}, max={max(s1):>4}, avg={np.mean(s1):>6.1f}")
            
            # Show some individual scores
            print(f"  Sample scores (output[0], output[1]):")
            for j in range(min(5, len(s))):
                print(f"    [{s[j][0]:>4}, {s[j][1]:>4}] -> {'✅ Correct' if np.argmax(s[j]) == class_names.index(name) else '❌ Wrong'}")
    
    # Threshold analysis
    human_idx = 0 if 'Human' in class_names[0] else 1
    h_present = [s[human_idx] for s in scores[class_names[human_idx]]]
    h_absent = [s[human_idx] for s in scores[class_names[1-human_idx]]]
    
    print(f"\n{'='*50}")
    print(f"THRESHOLD ANALYSIS")
    print(f"{'='*50}")
    print(f"Human score when HUMAN present:    min={min(h_present):>4}, max={max(h_present):>4}, avg={np.mean(h_present):>6.1f}")
    print(f"Human score when HUMAN absent:     min={min(h_absent):>4}, max={max(h_absent):>4}, avg={np.mean(h_absent):>6.1f}")
    
    gap = min(h_present) - max(h_absent)
    threshold = (min(h_present) + max(h_absent)) // 2
    print(f"Gap: {gap}")
    print(f"Recommended threshold: {threshold}")
    
    if gap > 30:
        print("✅ Excellent separation!")
    elif gap > 10:
        print("✅ Good separation")  
    elif gap > 0:
        print("⚠️ Tight but workable")
    else:
        print("❌ Classes OVERLAP - model unreliable!")

if __name__ == "__main__":
    main()
