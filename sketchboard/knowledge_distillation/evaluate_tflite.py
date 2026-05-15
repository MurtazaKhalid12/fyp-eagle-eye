import os
import numpy as np
import tensorflow as tf
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
from pathlib import Path

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

KD_DIR = Path(__file__).resolve().parent
SKETCHBOARD = KD_DIR.parent
DATASET_PATH = SKETCHBOARD / "dataset"
IMG_HEIGHT, IMG_WIDTH = 48, 48

def load_data():
    class_names = sorted(p.name for p in DATASET_PATH.iterdir() if p.is_dir())
    images, labels = [], []
    for label, class_name in enumerate(class_names):
        class_dir = DATASET_PATH / class_name
        paths = list(class_dir.glob("*.jpg")) + list(class_dir.glob("*.jpeg")) + list(class_dir.glob("*.png"))
        for p in paths:
            img_bytes = tf.io.read_file(str(p))
            img = tf.io.decode_image(img_bytes, channels=1, expand_animations=False) # Grayscale directly!
            img = tf.cast(img, tf.float32)
            
            shape = tf.shape(img)
            h, w = shape[0], shape[1]
            side = tf.minimum(h, w)
            offset_y, offset_x = (h - side) // 2, (w - side) // 2
            img = tf.image.crop_to_bounding_box(img, offset_y, offset_x, side, side)
            img = tf.image.resize(img, (IMG_HEIGHT, IMG_WIDTH), method="bilinear")
            
            images.append(img.numpy()) # [0, 255] range
            labels.append(label)
    return np.array(images), np.array(labels), class_names

print("Loading dataset...")
X, y, CLASS_NAMES = load_data()
_, X_val, _, y_val = train_test_split(X, y, test_size=0.15, stratify=y, random_state=42)

tflite_path = KD_DIR / "kd_optuna_best_student.tflite"
interpreter = tf.lite.Interpreter(model_path=str(tflite_path))
interpreter.allocate_tensors()

input_details = interpreter.get_input_details()[0]
output_details = interpreter.get_output_details()[0]

input_scale, input_zero_point = input_details['quantization']
output_scale, output_zero_point = output_details['quantization']

y_pred = []
for i in range(len(X_val)):
    img = X_val[i:i+1] # Shape (1, 48, 48, 1) in [0, 255] float32
    
    # Quantize to INT8
    if input_scale != 0.0:
        img = img / input_scale + input_zero_point
    img = np.clip(img, -128, 127).astype(np.int8)
    
    interpreter.set_tensor(input_details['index'], img)
    interpreter.invoke()
    
    output_data = interpreter.get_tensor(output_details['index'])[0]
    
    y_pred.append(np.argmax(output_data))

print("\nClassification Report on Validation Set (TFLite INT8 Student Model):")
print(classification_report(y_val, y_pred, target_names=CLASS_NAMES, digits=4))
