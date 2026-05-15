import os
import numpy as np
import tensorflow as tf
from tensorflow.keras import layers, models, applications
from pathlib import Path
import warnings
from sklearn.model_selection import train_test_split

# Suppress warnings
warnings.filterwarnings("ignore")
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

# --- CONFIGURATION ---
KD_DIR = Path(__file__).resolve().parent
SKETCHBOARD = KD_DIR.parent
DATASET_PATH = SKETCHBOARD / "dataset"
IMG_HEIGHT, IMG_WIDTH = 48, 48
BATCH_SIZE = 32
EPOCHS = 20

# --- DATASET LOADING (RGB for Teacher) ---
def load_rgb_data():
    class_names = sorted(p.name for p in DATASET_PATH.iterdir() if p.is_dir())
    images, labels = [], []
    for label, class_name in enumerate(class_names):
        class_dir = DATASET_PATH / class_name
        paths = list(class_dir.glob("*.jpg")) + list(class_dir.glob("*.jpeg")) + list(class_dir.glob("*.png"))
        for p in paths:
            img_bytes = tf.io.read_file(str(p))
            img = tf.io.decode_image(img_bytes, channels=3, expand_animations=False)
            img = tf.cast(img, tf.float32)
            
            # Crop to square and resize
            shape = tf.shape(img)
            h, w = shape[0], shape[1]
            side = tf.minimum(h, w)
            offset_y, offset_x = (h - side) // 2, (w - side) // 2
            img = tf.image.crop_to_bounding_box(img, offset_y, offset_x, side, side)
            img = tf.image.resize(img, (IMG_HEIGHT, IMG_WIDTH), method="bilinear")
            
            # MobileNetV2 expects [-1, 1] preprocessing
            img = applications.mobilenet_v2.preprocess_input(img)
            
            images.append(img.numpy())
            labels.append(label)
    return np.array(images), np.array(labels), class_names

# --- DISTILLATION CLASS ---
class Distiller(tf.keras.Model):
    def __init__(self, student, teacher):
        super(Distiller, self).__init__()
        self.teacher = teacher
        self.student = student

    def compile(self, optimizer, metrics, student_loss_fn, distillation_loss_fn, alpha=0.1, temperature=3):
        super(Distiller, self).compile(optimizer=optimizer, metrics=metrics)
        self.student_loss_fn = student_loss_fn
        self.distillation_loss_fn = distillation_loss_fn
        self.alpha = alpha
        self.temperature = temperature

    def train_step(self, data):
        x, y = data

        # Teacher needs RGB
        teacher_predictions = self.teacher(x, training=False)
        
        # Student needs Grayscale! (Convert RGB to Grayscale)
        x_gray = tf.image.rgb_to_grayscale(x)

        with tf.GradientTape() as tape:
            student_predictions = self.student(x_gray, training=True)

            student_loss = self.student_loss_fn(y, student_predictions)
            
            distillation_loss = self.distillation_loss_fn(
                tf.nn.softmax(teacher_predictions / self.temperature, axis=1),
                tf.nn.softmax(student_predictions / self.temperature, axis=1),
            ) * (self.temperature**2)

            loss = self.alpha * student_loss + (1 - self.alpha) * distillation_loss

        trainable_vars = self.student.trainable_variables
        gradients = tape.gradient(loss, trainable_vars)
        self.optimizer.apply_gradients(zip(gradients, trainable_vars))

        self.compiled_metrics.update_state(y, student_predictions)
        results = {m.name: m.result() for m in self.metrics}
        results.update({"student_loss": student_loss, "distillation_loss": distillation_loss})
        return results

    def test_step(self, data):
        x, y = data
        x_gray = tf.image.rgb_to_grayscale(x)
        y_prediction = self.student(x_gray, training=False)
        student_loss = self.student_loss_fn(y, y_prediction)
        self.compiled_metrics.update_state(y, y_prediction)
        results = {m.name: m.result() for m in self.metrics}
        results.update({"student_loss": student_loss})
        return results

# --- MODEL DEFINITIONS ---
def build_student_model(num_classes):
    """Your tiny ESP32 model (Optuna hyperparameters)."""
    base_filters = 16 
    model = models.Sequential([
        layers.Input(shape=(IMG_HEIGHT, IMG_WIDTH, 1)),
        # No Rescaling here because x_gray is already in [-1, 1] during distillation loop
        layers.RandomRotation(0.12),
        layers.RandomZoom(0.18),
        
        layers.Conv2D(base_filters, 3, strides=2, padding="same", activation="relu"),
        layers.MaxPooling2D(),
        layers.Conv2D(base_filters * 2, 3, strides=2, padding="same", activation="relu"),
        layers.MaxPooling2D(),
        layers.Conv2D(base_filters * 4, 3, padding="same", activation="relu"),
        layers.GlobalAveragePooling2D(),
        
        layers.Dropout(0.2447), # Optuna dropout
        layers.Dense(num_classes) # NO SOFTMAX, return logits for KD
    ], name="Student_ESP32_Model")
    return model

def load_teacher_logits(model_path):
    print("Loading Teacher Model from:", model_path)
    teacher = tf.keras.models.load_model(model_path)
    
    # Extract logits layer
    last_layer = teacher.layers[-1]
    
    if isinstance(last_layer, layers.Dense):
        # Create a new dense layer with linear activation
        new_dense = layers.Dense(last_layer.units, activation=None, name="logits_output")
        logits = new_dense(teacher.layers[-2].output)
        teacher_logits = tf.keras.Model(inputs=teacher.inputs, outputs=logits, name="Teacher_Logits")
        
        new_dense.set_weights(last_layer.get_weights())
        teacher_logits.trainable = False
        return teacher_logits
    else:
        raise ValueError("Unexpected last layer in teacher model.")

# --- MAIN EXECUTION ---
if __name__ == "__main__":
    print("--> Loading dataset for Knowledge Distillation...")
    X, y, CLASS_NAMES = load_rgb_data()
    X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.15, stratify=y, random_state=42)
    
    teacher_path = KD_DIR / "teacher_mobilenetv2.keras"
    teacher_logits_model = load_teacher_logits(teacher_path)
    
    student_model = build_student_model(len(CLASS_NAMES))
    
    print("\n--> Initializing Distiller...")
    distiller = Distiller(student=student_model, teacher=teacher_logits_model)
    
    distiller.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=0.003234), # Optuna LR
        metrics=[tf.keras.metrics.SparseCategoricalAccuracy(name="accuracy")],
        student_loss_fn=tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True),
        distillation_loss_fn=tf.keras.losses.KLDivergence(),
        alpha=0.1,
        temperature=4
    )
    
    print("\n--> Starting Distillation Training...")
    distiller.fit(
        X_train, y_train,
        validation_data=(X_val, y_val),
        epochs=EPOCHS,
        batch_size=BATCH_SIZE
    )
    
    # Save student in TFLite INT8 format
    print("\n--> Exporting Student Model to INT8 TFLite...")
    
    # Wrap student in Rescaling + Softmax for ESP32 deployment!
    export_model = tf.keras.Sequential([
        layers.Input(shape=(IMG_HEIGHT, IMG_WIDTH, 1)),
        layers.Rescaling(1.0 / 127.5, offset=-1.0),
        distiller.student,
        layers.Activation('softmax')
    ])
    
    def representative_data_gen():
        for i in range(min(100, len(X_train))):
            # Convert X_train from [-1, 1] back to [0, 255] float32 for TFLite quantization mapping
            x_original = (X_train[i:i+1] + 1.0) * 127.5
            x_gray = tf.image.rgb_to_grayscale(tf.convert_to_tensor(x_original, dtype=tf.float32))
            yield [x_gray]

    converter = tf.lite.TFLiteConverter.from_keras_model(export_model)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    converter.representative_dataset = representative_data_gen
    converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    converter.inference_input_type = tf.int8
    converter.inference_output_type = tf.int8
    
    tflite_model = converter.convert()
    
    tflite_path = KD_DIR / "student_distilled_model.tflite"
    with open(tflite_path, "wb") as f:
        f.write(tflite_model)
        
    print(f"✅ Distilled TFLite model saved to {tflite_path.name} ({len(tflite_model)/1024:.1f} KB)")
