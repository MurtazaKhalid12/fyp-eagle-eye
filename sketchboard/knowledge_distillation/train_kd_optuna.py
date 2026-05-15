import os
import numpy as np
import tensorflow as tf
from tensorflow.keras import layers, models, applications
from pathlib import Path
import warnings
from sklearn.model_selection import train_test_split
from sklearn.metrics import f1_score
import optuna

warnings.filterwarnings("ignore")
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

KD_DIR = Path(__file__).resolve().parent
SKETCHBOARD = KD_DIR.parent
DATASET_PATH = SKETCHBOARD / "dataset"
IMG_HEIGHT, IMG_WIDTH = 48, 48
BATCH_SIZE = 32
EPOCHS = 15 # Shorter epochs for Optuna trials

# --- DATASET LOADING ---
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
            
            shape = tf.shape(img)
            h, w = shape[0], shape[1]
            side = tf.minimum(h, w)
            offset_y, offset_x = (h - side) // 2, (w - side) // 2
            img = tf.image.crop_to_bounding_box(img, offset_y, offset_x, side, side)
            img = tf.image.resize(img, (IMG_HEIGHT, IMG_WIDTH), method="bilinear")
            img = applications.mobilenet_v2.preprocess_input(img)
            
            images.append(img.numpy())
            labels.append(label)
    return np.array(images), np.array(labels), class_names

# --- DISTILLER CLASS ---
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
        teacher_predictions = self.teacher(x, training=False)
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

# --- ARCHITECTURE ---
def build_student_model(num_classes):
    base_filters = 16 
    model = models.Sequential([
        layers.Input(shape=(IMG_HEIGHT, IMG_WIDTH, 1)),
        layers.RandomRotation(0.12),
        layers.RandomZoom(0.18),
        
        layers.Conv2D(base_filters, 3, strides=2, padding="same", activation="relu"),
        layers.MaxPooling2D(),
        layers.Conv2D(base_filters * 2, 3, strides=2, padding="same", activation="relu"),
        layers.MaxPooling2D(),
        layers.Conv2D(base_filters * 4, 3, padding="same", activation="relu"),
        layers.GlobalAveragePooling2D(),
        
        layers.Dropout(0.2447),
        layers.Dense(num_classes)
    ], name="Student_ESP32_Model")
    return model

def load_teacher_logits(model_path):
    teacher = tf.keras.models.load_model(model_path)
    last_layer = teacher.layers[-1]
    new_dense = layers.Dense(last_layer.units, activation=None, name="logits_output")
    logits = new_dense(teacher.layers[-2].output)
    teacher_logits = tf.keras.Model(inputs=teacher.inputs, outputs=logits, name="Teacher_Logits")
    new_dense.set_weights(last_layer.get_weights())
    teacher_logits.trainable = False
    return teacher_logits

print("--> Loading dataset...")
X, y, CLASS_NAMES = load_rgb_data()
X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.15, stratify=y, random_state=42)

teacher_path = KD_DIR / "teacher_mobilenetv2.keras"
print("--> Loading Teacher...")
teacher_logits_model = load_teacher_logits(teacher_path)

def objective(trial):
    # Suggest hyperparameters
    alpha = trial.suggest_float("alpha", 0.1, 0.9)
    temperature = trial.suggest_float("temperature", 1.0, 10.0)
    learning_rate = trial.suggest_float("learning_rate", 1e-4, 1e-2, log=True)
    
    print(f"\n[Trial {trial.number}] alpha: {alpha:.3f}, temp: {temperature:.1f}, lr: {learning_rate:.4f}")
    
    student_model = build_student_model(len(CLASS_NAMES))
    distiller = Distiller(student=student_model, teacher=teacher_logits_model)
    
    distiller.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=learning_rate),
        metrics=[tf.keras.metrics.SparseCategoricalAccuracy(name="accuracy")],
        student_loss_fn=tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True),
        distillation_loss_fn=tf.keras.losses.KLDivergence(),
        alpha=alpha,
        temperature=temperature
    )
    
    distiller.fit(
        X_train, y_train,
        validation_data=(X_val, y_val),
        epochs=EPOCHS,
        batch_size=BATCH_SIZE,
        verbose=0 # Keep logs clean
    )
    
    # Evaluate Macro F1 on validation set
    y_pred_probs = distiller.student.predict(tf.image.rgb_to_grayscale(X_val), verbose=0)
    y_pred = np.argmax(y_pred_probs, axis=1)
    f1 = f1_score(y_val, y_pred, average='macro')
    
    print(f"--> F1 Score: {f1:.4f}")
    return f1

if __name__ == "__main__":
    print("\n=== Starting Optuna KD Search ===")
    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=10) # 10 trials to keep it relatively fast
    
    print("\n=== Best Trial Found ===")
    best_trial = study.best_trial
    print(f"F1 Score : {best_trial.value:.4f}")
    print("Hyperparameters: ")
    for key, value in best_trial.params.items():
        print(f"  {key}: {value}")
        
    print("\n--> Retraining final production model on ENTIRE dataset...")
    
    student_model = build_student_model(len(CLASS_NAMES))
    distiller = Distiller(student=student_model, teacher=teacher_logits_model)
    
    distiller.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=best_trial.params["learning_rate"]),
        metrics=[tf.keras.metrics.SparseCategoricalAccuracy(name="accuracy")],
        student_loss_fn=tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True),
        distillation_loss_fn=tf.keras.losses.KLDivergence(),
        alpha=best_trial.params["alpha"],
        temperature=best_trial.params["temperature"]
    )
    
    distiller.fit(X, y, epochs=25, batch_size=BATCH_SIZE, verbose=1)
    
    print("\n--> Exporting to INT8 TFLite...")
    export_model = tf.keras.Sequential([
        layers.Input(shape=(IMG_HEIGHT, IMG_WIDTH, 1)),
        layers.Rescaling(1.0 / 127.5, offset=-1.0),
        distiller.student,
        layers.Activation('softmax')
    ])
    
    def representative_data_gen():
        for i in range(min(100, len(X))):
            x_original = (X[i:i+1] + 1.0) * 127.5
            x_gray = tf.image.rgb_to_grayscale(tf.convert_to_tensor(x_original, dtype=tf.float32))
            yield [x_gray]

    converter = tf.lite.TFLiteConverter.from_keras_model(export_model)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    converter.representative_dataset = representative_data_gen
    converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    converter.inference_input_type = tf.int8
    converter.inference_output_type = tf.int8
    
    tflite_model = converter.convert()
    
    tflite_path = KD_DIR / "kd_optuna_best_student.tflite"
    with open(tflite_path, "wb") as f:
        f.write(tflite_model)
        
    print(f"Done! Saved to {tflite_path.name}")
