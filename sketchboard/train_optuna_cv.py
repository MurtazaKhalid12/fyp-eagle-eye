import os
import glob
import numpy as np
import tensorflow as tf
from tensorflow.keras import layers, models
import optuna
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import accuracy_score, f1_score
from pathlib import Path
import warnings

# Suppress warnings and TF logs to keep output clean
warnings.filterwarnings("ignore")
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
tf.get_logger().setLevel('ERROR')

# --- CONFIGURATION ---
SKETCHBOARD = Path(__file__).resolve().parent
DATASET_PATH = SKETCHBOARD / "dataset"
IMG_HEIGHT, IMG_WIDTH = 48, 48
EPOCHS_PER_FOLD = 40
BATCH_SIZE = 32
N_SPLITS = 5
SEED = 123
N_TRIALS = 10 # Number of Optuna hyperparameter trials

def load_data():
    class_names = sorted(p.name for p in DATASET_PATH.iterdir() if p.is_dir())
    images, labels = [], []
    
    for label, class_name in enumerate(class_names):
        class_dir = DATASET_PATH / class_name
        paths = []
        for pattern in ("*.jpg", "*.jpeg", "*.png"):
            paths.extend(class_dir.glob(pattern))
        for p in sorted(paths):
            image_bytes = tf.io.read_file(str(p))
            img = tf.io.decode_image(image_bytes, channels=3, expand_animations=False)
            img = tf.cast(img, tf.float32)
            
            # Mimic firmware crop and resize
            shape = tf.shape(img)
            h, w = shape[0], shape[1]
            side = tf.minimum(h, w)
            offset_y, offset_x = (h - side) // 2, (w - side) // 2
            img = tf.image.crop_to_bounding_box(img, offset_y, offset_x, side, side)
            img = tf.image.resize(img, (IMG_HEIGHT, IMG_WIDTH), method="bilinear")
            
            # Grayscale matched to firmware luminance weighting
            r, g, b = img[..., 0], img[..., 1], img[..., 2]
            gray = (r * 77.0 + g * 150.0 + b * 29.0) / 256.0
            gray = tf.expand_dims(gray, axis=-1)
            
            images.append(gray.numpy())
            labels.append(label)
            
    return np.array(images), np.array(labels), class_names

# Global data loading so we don't reload every trial
print("Loading dataset into memory for fast K-Fold CV...")
X_FULL, y_FULL, CLASS_NAMES = load_data()

def build_model(trial, num_classes):
    # Optuna Hyperparameter Space
    learning_rate = trial.suggest_float("learning_rate", 1e-4, 5e-3, log=True)
    dropout_rate = trial.suggest_float("dropout_rate", 0.1, 0.4)
    base_filters = trial.suggest_categorical("base_filters", [8, 16])
    
    data_augmentation = tf.keras.Sequential([
        layers.RandomRotation(0.12),
        layers.RandomZoom(height_factor=0.18, width_factor=0.18),
    ], name="geometry_only_augmentation")

    model = models.Sequential([
        layers.Input(shape=(IMG_HEIGHT, IMG_WIDTH, 1)),
        layers.Rescaling(1.0 / 127.5, offset=-1.0),
        data_augmentation,
        
        layers.Conv2D(base_filters, 3, strides=2, padding="same", activation="relu"),
        layers.MaxPooling2D(),
        
        layers.Conv2D(base_filters * 2, 3, strides=2, padding="same", activation="relu"),
        layers.MaxPooling2D(),
        
        layers.Conv2D(base_filters * 4, 3, padding="same", activation="relu"),
        layers.GlobalAveragePooling2D(),
        
        layers.Dropout(dropout_rate),
        layers.Dense(num_classes, activation="softmax"),
    ])

    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=learning_rate),
        loss="sparse_categorical_crossentropy",
        metrics=["accuracy"]
    )
    return model

def objective(trial):
    skf = StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=SEED)
    
    fold_accs = []
    fold_f1s = []
    
    # 5-Fold Stratified Cross Validation
    for fold, (train_idx, val_idx) in enumerate(skf.split(X_FULL, y_FULL)):
        X_train, X_val = X_FULL[train_idx], X_FULL[val_idx]
        y_train, y_val = y_FULL[train_idx], y_FULL[val_idx]
        
        model = build_model(trial, len(CLASS_NAMES))
        
        # Early stopping to prevent over-training on the fold
        early_stop = tf.keras.callbacks.EarlyStopping(
            monitor="val_loss", 
            patience=6, 
            restore_best_weights=True, 
            verbose=0
        )
        
        model.fit(
            X_train, y_train,
            validation_data=(X_val, y_val),
            epochs=EPOCHS_PER_FOLD,
            batch_size=BATCH_SIZE,
            callbacks=[early_stop],
            verbose=0
        )
        
        # Predictions for metric evaluation
        y_pred_probs = model.predict(X_val, verbose=0)
        y_pred = np.argmax(y_pred_probs, axis=1)
        
        acc = accuracy_score(y_val, y_pred)
        f1 = f1_score(y_val, y_pred, average='macro')
        
        fold_accs.append(acc)
        fold_f1s.append(f1)
        
    # Calculate Mean Metrics Across All 5 Folds
    mean_acc = np.mean(fold_accs)
    mean_f1 = np.mean(fold_f1s)
    
    # Track the accuracy in Optuna as an additional user attribute
    trial.set_user_attr("mean_accuracy", float(mean_acc))
    
    print(f"[Trial {trial.number}] -> Mean Acc: {mean_acc:.4f} | Mean F1 (Macro): {mean_f1:.4f}")
    
    # We want Optuna to maximize the Macro F1 Score
    return mean_f1

if __name__ == "__main__":
    print(f"\n=== Starting Optuna + {N_SPLITS}-Fold Stratified CV ===")
    optuna.logging.set_verbosity(optuna.logging.WARNING) # Reduce spam
    
    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=N_TRIALS)
    
    print("\n=== Best Trial Found ===")
    print(f"F1 Score : {study.best_trial.value:.4f}")
    print(f"Accuracy : {study.best_trial.user_attrs.get('mean_accuracy'):.4f}")
    print("Hyperparameters: ")
    for key, value in study.best_trial.params.items():
        print(f"  {key}: {value}")
        
    print("\n--> Training final production model on the ENTIRE dataset...")
    
    # Helper functions for export
    def representative_data_gen():
        for i in range(min(100, len(X_FULL))):
            yield [tf.cast(np.expand_dims(X_FULL[i], axis=0), tf.float32)]

    def convert_to_int8_tflite(model) -> bytes:
        converter = tf.lite.TFLiteConverter.from_keras_model(model)
        converter.optimizations = [tf.lite.Optimize.DEFAULT]
        converter.representative_dataset = representative_data_gen
        converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
        converter.inference_input_type = tf.int8
        converter.inference_output_type = tf.int8
        return converter.convert()

    def hex_to_c_array(data: bytes, var_name: str) -> str:
        guard = f"{var_name.upper()}_H"
        lines = [
            "// Auto-generated by train_optuna_cv.py",
            f"#ifndef {guard}",
            f"#define {guard}",
            "",
            f"extern const unsigned char {var_name}[];",
            f"extern const unsigned int {var_name}_len;",
            "",
            f"const unsigned char {var_name}[] = {{",
        ]
        for i in range(0, len(data), 12):
            chunk = ", ".join(f"0x{b:02x}" for b in data[i : i + 12])
            lines.append(f"  {chunk},")
        lines.extend([
            "};",
            f"const unsigned int {var_name}_len = {len(data)};",
            f"#endif  // {guard}",
            ""
        ])
        return "\n".join(lines)

    final_model = build_model(study.best_trial, len(CLASS_NAMES))
    
    # Train on everything for a robust 25 epochs
    final_model.fit(X_FULL, y_FULL, epochs=25, batch_size=BATCH_SIZE, verbose=1)
    
    print("\n--> Converting to INT8 TFLite...")
    tflite_data = convert_to_int8_tflite(final_model)
    
    TFLITE_PATH = SKETCHBOARD / "model_v3.0_optuna_optimized.tflite"
    TFLITE_PATH.write_bytes(tflite_data)
    
    print("--> Generating C-Header file...")
    c_header = hex_to_c_array(tflite_data, "g_human_detect_model_data")
    HEADER_PATH = SKETCHBOARD / "human_detect_model_data_optuna.h"
    HEADER_PATH.write_text(c_header, encoding="utf-8")
    
    print(f"\n✅ All done! Model saved to {TFLITE_PATH.name} and header saved to {HEADER_PATH.name}")
