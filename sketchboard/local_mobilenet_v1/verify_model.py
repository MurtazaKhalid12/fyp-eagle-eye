import numpy as np
import tensorflow as tf
import time
import pathlib
import os

# --- CONFIGURATION ---
DATASET_PATH = r'c:\fyp-eagle-eye\sketchboard\local_mobilenet_v1\dataset'
IMG_HEIGHT = 96
IMG_WIDTH = 96
BATCH_SIZE = 16
INT8_MODEL_PATH = r'mobilenet_v1_96x96_int8.tflite'
FLOAT_MODEL_PATH = r'mobilenet_v1_96x96_float.tflite'

def evaluate_tflite_model(model_path, val_ds, is_int8=True):
    print(f"\n--- Evaluating Model: {model_path} ---")
    
    # Load TFLite model and allocate tensors
    interpreter = tf.lite.Interpreter(model_path=model_path)
    interpreter.allocate_tensors()

    # Get input and output tensors
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()
    
    print("Input Details:", input_details[0])
    print("Output Details:", output_details[0])

    input_shape = input_details[0]['shape']
    input_type = input_details[0]['dtype']
    
    # Extract quantization parameters
    input_quant = input_details[0]['quantization_parameters']
    input_scale = input_quant['scales'][0] if len(input_quant['scales']) > 0 else None
    input_zero_point = input_quant['zero_points'][0] if len(input_quant['zero_points']) > 0 else None

    output_quant = output_details[0]['quantization_parameters']
    output_scale = output_quant['scales'][0] if len(output_quant['scales']) > 0 else None
    output_zero_point = output_quant['zero_points'][0] if len(output_quant['zero_points']) > 0 else None

    y_true = []
    y_pred = []
    
    inference_times = []
    
    # Iterate over validation dataset
    for images, labels in val_ds:
        for i in range(images.shape[0]):
            img = images[i].numpy() # shape (96, 96, 1), range [0, 255]
            label = labels[i].numpy()
            y_true.append(label)
            
            # Preprocess the input image
            # The model already contains the Rescaling layer, so it expects [0, 255] inputs
            raw_img = img.astype(np.float32)
            
            if is_int8 and input_type == np.int8:
                # Quantize input: float_val = (int8_val - zero_point) * scale
                # => int8_val = float_val / scale + zero_point
                quantized_img = raw_img / input_scale + input_zero_point
                input_data = np.clip(np.round(quantized_img), -128, 127).astype(np.int8)
            else:
                input_data = raw_img.astype(np.float32)
                
            # Add batch dimension
            input_data = np.expand_dims(input_data, axis=0)
            
            # Run inference
            interpreter.set_tensor(input_details[0]['index'], input_data)
            
            start_time = time.time()
            interpreter.invoke()
            elapsed = time.time() - start_time
            inference_times.append(elapsed * 1000.0) # in ms
            
            # Read output
            output_data = interpreter.get_tensor(output_details[0]['index'])
            
            # Dequantize output if it is int8
            if is_int8 and output_details[0]['dtype'] == np.int8:
                output_data = (output_data.astype(np.float32) - output_zero_point) * output_scale
                
            pred_class = np.argmax(output_data[0])
            y_pred.append(pred_class)
            
    # Metrics
    y_true = np.array(y_true)
    y_pred = np.array(y_pred)
    
    accuracy = np.mean(y_true == y_pred)
    print(f"Accuracy: {accuracy * 100:.2f}%")
    print(f"Average Inference Latency (Local CPU): {np.mean(inference_times):.2f} ms")
    
    # Calculate confusion matrix manually (2x2)
    cm = [[0, 0], [0, 0]]
    for t, p in zip(y_true, y_pred):
        cm[t][p] += 1
        
    print("\nConfusion Matrix:")
    print(f"  Predicted ->  Humans  NonHuman")
    print(f"  Actual Humans   {cm[0][0]:<6}  {cm[0][1]:<6}")
    print(f"  Actual NonHuman {cm[1][0]:<6}  {cm[1][1]:<6}")
    
    # Calculate classification metrics manually
    print("\nClassification Metrics:")
    for i, class_name in enumerate(val_ds.class_names):
        tp = cm[i][i]
        fp = sum(cm[j][i] for j in range(2) if j != i)
        fn = sum(cm[i][j] for j in range(2) if j != i)
        
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        
        print(f"  Class: {class_name}")
        print(f"    Precision: {precision:.4f}")
        print(f"    Recall:    {recall:.4f}")
        print(f"    F1-score:  {f1:.4f}")
    
    return {
        "accuracy": accuracy,
        "latency_ms": np.mean(inference_times),
        "confusion_matrix": cm
    }

def main():
    data_dir = pathlib.Path(DATASET_PATH)
    
    # Load Grayscale 96x96 validation split
    val_ds = tf.keras.utils.image_dataset_from_directory(
        data_dir,
        validation_split=0.2,
        subset="validation",
        seed=123,
        image_size=(IMG_HEIGHT, IMG_WIDTH),
        batch_size=BATCH_SIZE,
        color_mode='grayscale'
    )
    
    # Check if models exist
    if os.path.exists(FLOAT_MODEL_PATH):
        evaluate_tflite_model(FLOAT_MODEL_PATH, val_ds, is_int8=False)
        
    if os.path.exists(INT8_MODEL_PATH):
        evaluate_tflite_model(INT8_MODEL_PATH, val_ds, is_int8=True)
    else:
        print(f"Quantized model not found at {INT8_MODEL_PATH}")

if __name__ == "__main__":
    main()
