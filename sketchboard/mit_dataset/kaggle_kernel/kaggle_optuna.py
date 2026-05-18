import os
import optuna
import tensorflow as tf
from tensorflow.keras import layers
import numpy as np

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

input_base = "/kaggle/input"
try:
    dataset_dir = os.listdir(input_base)[0]
    DATASET_PATH = os.path.join(input_base, dataset_dir)
except Exception as e:
    DATASET_PATH = "/kaggle/input/fyp-eagle-eye-merged-data"

print(f"Loading merged dataset from: {DATASET_PATH}")

IMG_HEIGHT = 48
IMG_WIDTH = 48
BATCH_SIZE = 32

train_ds = tf.keras.utils.image_dataset_from_directory(
    DATASET_PATH,
    validation_split=0.2,
    subset="training",
    seed=123,
    color_mode="grayscale",
    image_size=(IMG_HEIGHT, IMG_WIDTH),
    batch_size=BATCH_SIZE
)

val_ds = tf.keras.utils.image_dataset_from_directory(
    DATASET_PATH,
    validation_split=0.2,
    subset="validation",
    seed=123,
    color_mode="grayscale",
    image_size=(IMG_HEIGHT, IMG_WIDTH),
    batch_size=BATCH_SIZE
)

normalization_layer = layers.Rescaling(1./127.5, offset=-1)
AUTOTUNE = tf.data.AUTOTUNE

# Cache the dataset to RAM so trials are lightning fast
train_ds = train_ds.map(lambda x, y: (normalization_layer(x), y)).cache().shuffle(1000).prefetch(buffer_size=AUTOTUNE)
val_ds = val_ds.map(lambda x, y: (normalization_layer(x), y)).cache().prefetch(buffer_size=AUTOTUNE)

def objective(trial):
    # Suggest hyperparameters
    dropout_rate = trial.suggest_float("dropout_rate", 0.1, 0.6)
    learning_rate = trial.suggest_float("learning_rate", 1e-4, 5e-3, log=True)
    rotation_factor = trial.suggest_float("rotation_factor", 0.05, 0.25)
    
    # Build Model
    data_augmentation = tf.keras.Sequential([
        layers.RandomFlip("horizontal"),
        layers.RandomRotation(rotation_factor),
        layers.RandomZoom(rotation_factor),
    ])

    inputs = tf.keras.Input(shape=(IMG_HEIGHT, IMG_WIDTH, 1))
    x = data_augmentation(inputs)

    base_model = tf.keras.applications.MobileNet(
        input_shape=(IMG_HEIGHT, IMG_WIDTH, 1),
        alpha=0.25,
        include_top=False,
        weights=None,
        pooling=None
    )

    x = base_model(x)
    x = layers.GlobalAveragePooling2D()(x)
    x = layers.Dropout(dropout_rate)(x)
    outputs = layers.Dense(2, activation='softmax')(x)

    model = tf.keras.Model(inputs, outputs)

    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=learning_rate),
        loss='sparse_categorical_crossentropy',
        metrics=['accuracy']
    )

    # Train for 15 epochs per trial to quickly gauge potential
    history = model.fit(
        train_ds,
        validation_data=val_ds,
        epochs=15,
        verbose=0 # Suppress huge logs for Optuna
    )
    
    # Return the maximum validation accuracy achieved in this trial
    val_acc = max(history.history['val_accuracy'])
    print(f"Trial completed. Best Val Acc: {val_acc:.4f} (Dropout: {dropout_rate:.2f}, LR: {learning_rate:.4f})")
    return val_acc

if __name__ == "__main__":
    print("Starting Optuna Hyperparameter Search...")
    study = optuna.create_study(direction="maximize")
    # Run 15 different trial combinations
    study.optimize(objective, n_trials=15)

    print("\n===============================")
    print("BEST HYPERPARAMETERS FOUND:")
    print(f"Best Validation Accuracy: {study.best_value:.4f}")
    for key, value in study.best_params.items():
        print(f"    {key}: {value}")
    print("===============================\n")
