import tensorflow as tf
from sklearn.metrics import classification_report, accuracy_score
import numpy as np
import pathlib

DATASET_PATH = './dataset'
IMG_HEIGHT = 48
IMG_WIDTH = 48
BATCH_SIZE = 32

data_dir = pathlib.Path(DATASET_PATH)

val_ds = tf.keras.utils.image_dataset_from_directory(
    data_dir,
    validation_split=0.2,
    subset="validation",
    seed=123,
    image_size=(IMG_HEIGHT, IMG_WIDTH),
    batch_size=1, # batch size 1 for easier tflite inference
    color_mode='grayscale'
)

class_names = val_ds.class_names

interpreter = tf.lite.Interpreter(model_path="tiny_human_model.tflite")
interpreter.allocate_tensors()

input_details = interpreter.get_input_details()[0]
output_details = interpreter.get_output_details()[0]

input_scale, input_zero_point = input_details['quantization']
output_scale, output_zero_point = output_details['quantization']

y_true = []
y_pred = []

for images, labels in val_ds:
    img = images.numpy()
    
    # Quantize input to int8
    if input_scale != 0.0:
        img_quant = (img / input_scale) + input_zero_point
        img_quant = np.clip(img_quant, -128, 127).astype(np.int8)
    else:
        img_quant = img.astype(np.int8)
        
    interpreter.set_tensor(input_details['index'], img_quant)
    interpreter.invoke()
    
    output_data = interpreter.get_tensor(output_details['index'])[0]
    
    # prediction
    pred_label = np.argmax(output_data)
    
    y_true.append(labels.numpy()[0])
    y_pred.append(pred_label)

print("Classification Report:")
print(classification_report(y_true, y_pred, target_names=class_names, digits=4))
print("Accuracy:", accuracy_score(y_true, y_pred))
