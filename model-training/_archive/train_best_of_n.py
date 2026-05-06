"""
Train the model MULTIPLE times with different random seeds.
Pick the BEST model based on validation accuracy + INT8 separation.

With only 193 images/class, model quality depends heavily on
random initialization. Multiple runs + selection = reliable results.
"""
import tensorflow as tf
from tensorflow.keras import layers, models, regularizers
import pathlib
import numpy as np

DATASET_PATH = '../datasets/Human_Detection_Dataset/Human_Detection_Dataset'
IMG_HEIGHT = 48
IMG_WIDTH = 48
BATCH_SIZE = 32
EPOCHS = 100
MODEL_NAME = 'tiny_human_model_color'
NUM_RUNS = 5  # Train 5 times, pick best


def build_and_train(data_dir, seed):
    """Build and train model with given seed. Returns model, val_acc."""
    
    train_ds = tf.keras.utils.image_dataset_from_directory(
        data_dir, validation_split=0.2, subset="training",
        seed=seed, image_size=(IMG_HEIGHT, IMG_WIDTH),
        batch_size=BATCH_SIZE, color_mode='rgb', shuffle=True
    )
    val_ds = tf.keras.utils.image_dataset_from_directory(
        data_dir, validation_split=0.2, subset="validation",
        seed=seed, image_size=(IMG_HEIGHT, IMG_WIDTH),
        batch_size=BATCH_SIZE, color_mode='rgb'
    )
    
    class_names = train_ds.class_names
    
    AUTOTUNE = tf.data.AUTOTUNE
    train_ds = train_ds.shuffle(200).cache().prefetch(AUTOTUNE)
    val_ds = val_ds.cache().prefetch(AUTOTUNE)
    
    # Set random seed for reproducibility within this run
    tf.random.set_seed(seed)
    np.random.seed(seed)
    
    # Augmentation
    data_augmentation = tf.keras.Sequential([
        layers.RandomFlip("horizontal"),
        layers.RandomRotation(0.2),
        layers.RandomZoom(0.2),
        layers.RandomContrast(0.2),
        layers.RandomBrightness(0.2),
        layers.RandomTranslation(0.1, 0.1),
    ])
    
    REG = regularizers.l2(0.001)
    
    inputs = layers.Input(shape=(IMG_HEIGHT, IMG_WIDTH, 3))
    x = layers.Rescaling(1./127.5, offset=-1)(inputs)
    x = data_augmentation(x)
    
    # Proven architecture (same as original)
    x = layers.Conv2D(12, 3, strides=2, padding='same', activation='relu', kernel_regularizer=REG)(x)
    x = layers.BatchNormalization()(x)
    x = layers.Conv2D(24, 3, strides=2, padding='same', activation='relu', kernel_regularizer=REG)(x)
    x = layers.BatchNormalization()(x)
    x = layers.Conv2D(48, 3, strides=2, padding='same', activation='relu', kernel_regularizer=REG)(x)
    x = layers.BatchNormalization()(x)
    x = layers.GlobalAveragePooling2D()(x)
    x = layers.Dropout(0.5)(x)
    outputs = layers.Dense(len(class_names), activation='softmax', kernel_regularizer=REG)(x)
    
    model = models.Model(inputs, outputs)
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=0.001),
        loss='sparse_categorical_crossentropy',
        metrics=['accuracy']
    )
    
    callbacks = [
        tf.keras.callbacks.ReduceLROnPlateau(
            monitor='val_accuracy', factor=0.5, patience=5, min_lr=1e-6, verbose=0
        ),
        tf.keras.callbacks.EarlyStopping(
            monitor='val_accuracy', patience=15, restore_best_weights=True, verbose=0
        )
    ]
    
    history = model.fit(
        train_ds, validation_data=val_ds,
        epochs=EPOCHS, callbacks=callbacks, verbose=0
    )
    
    best_val = max(history.history['val_accuracy'])
    best_train = max(history.history['accuracy'])
    epochs_ran = len(history.history['accuracy'])
    
    return model, best_val, best_train, epochs_ran, train_ds, val_ds, class_names


def evaluate_tflite(model, val_ds, class_names, train_ds):
    """Convert to INT8 and evaluate score separation."""
    
    def representative_data_gen():
        for images, _ in train_ds.take(100):
            for i in range(images.shape[0]):
                yield [tf.cast(images[i:i+1], tf.float32)]
    
    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    converter.representative_dataset = representative_data_gen
    converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    converter.inference_input_type = tf.int8
    converter.inference_output_type = tf.int8
    
    tflite_model = converter.convert()
    
    interp = tf.lite.Interpreter(model_content=tflite_model)
    interp.allocate_tensors()
    inp_det = interp.get_input_details()
    out_det = interp.get_output_details()
    
    correct = 0
    total = 0
    scores = {name: [] for name in class_names}
    
    for images, labels in val_ds:
        for i in range(images.shape[0]):
            img = tf.cast(images[i], tf.float32).numpy()
            img_int8 = (img - 128).astype(np.int8)
            img_int8 = np.expand_dims(img_int8, 0)
            
            interp.set_tensor(inp_det[0]['index'], img_int8)
            interp.invoke()
            result = interp.get_tensor(out_det[0]['index'])
            
            pred = np.argmax(result[0])
            actual = int(labels[i].numpy())
            scores[class_names[actual]].append(
                (int(result[0][0]), int(result[0][1]))
            )
            if pred == actual:
                correct += 1
            total += 1
    
    tflite_acc = correct / total if total > 0 else 0
    
    # Calculate gap
    human_idx = 0 if 'Human' in class_names[0] else 1
    h_present = [s[human_idx] for s in scores[class_names[human_idx]]]
    h_absent = [s[human_idx] for s in scores[class_names[1-human_idx]]]
    
    min_h = min(h_present) if h_present else 0
    max_nh = max(h_absent) if h_absent else 0
    gap = min_h - max_nh
    
    return tflite_model, tflite_acc, gap, scores, min_h, max_nh


def main():
    data_dir = pathlib.Path(DATASET_PATH)
    print(f"{'='*60}")
    print(f"🔁 MULTI-RUN TRAINING ({NUM_RUNS} runs)")
    print(f"{'='*60}")
    print(f"Training {NUM_RUNS} models with different seeds and picking the best.\n")
    
    seeds = [42, 123, 7, 2024, 999]
    results = []
    
    for run_idx in range(NUM_RUNS):
        seed = seeds[run_idx]
        print(f"\n{'─'*40}")
        print(f"🏃 Run {run_idx+1}/{NUM_RUNS} (seed={seed})")
        print(f"{'─'*40}")
        
        # Clear session to start fresh
        tf.keras.backend.clear_session()
        
        model, val_acc, train_acc, epochs, train_ds, val_ds, class_names = build_and_train(data_dir, seed)
        print(f"  Epochs: {epochs} | Train: {train_acc:.3f} | Val: {val_acc:.3f}")
        
        # Evaluate INT8
        tflite_model, tflite_acc, gap, scores, min_h, max_nh = evaluate_tflite(model, val_ds, class_names, train_ds)
        
        print(f"  INT8 Acc: {tflite_acc:.3f} | Gap: {gap} | Min_Human: {min_h} | Max_NonHuman: {max_nh}")
        print(f"  Model size: {len(tflite_model):,} bytes")
        
        # Score quality = combination of accuracy and separation
        # Higher is better
        score_quality = tflite_acc * 100 + max(0, gap)
        
        if gap > 0:
            print(f"  ✅ Classes separated (gap={gap})")
        else:
            print(f"  ❌ Classes overlap (gap={gap})")
        
        results.append({
            'run': run_idx + 1,
            'seed': seed,
            'val_acc': val_acc,
            'tflite_acc': tflite_acc,
            'gap': gap,
            'quality': score_quality,
            'model': tflite_model,
            'scores': scores,
            'min_h': min_h,
            'max_nh': max_nh,
            'class_names': class_names,
        })
    
    # ============================
    # SELECT BEST MODEL
    # ============================
    print(f"\n{'='*60}")
    print(f"📊 ALL RESULTS")
    print(f"{'='*60}")
    print(f"{'Run':>4} | {'Seed':>5} | {'Val Acc':>8} | {'INT8 Acc':>8} | {'Gap':>5} | {'Quality':>8}")
    print("-" * 55)
    for r in results:
        marker = "⭐" if r == max(results, key=lambda x: x['quality']) else "  "
        print(f" {marker}{r['run']:>2} | {r['seed']:>5} | {r['val_acc']:>7.3f} | {r['tflite_acc']:>7.3f} | {r['gap']:>5} | {r['quality']:>7.1f}")
    
    # Pick best by quality score
    best = max(results, key=lambda x: x['quality'])
    
    print(f"\n🏆 BEST: Run {best['run']} (seed={best['seed']})")
    print(f"   Val Accuracy: {best['val_acc']:.3f}")
    print(f"   INT8 Accuracy: {best['tflite_acc']:.3f}")
    print(f"   Gap: {best['gap']}")
    
    # Score distribution of best
    class_names = best['class_names']
    print(f"\n📊 Best Model INT8 Scores:")
    for name in class_names:
        s = best['scores'][name]
        if s:
            s0 = [x[0] for x in s]
            s1 = [x[1] for x in s]
            print(f"  When actual = {name}:")
            print(f"    {class_names[0]:>10}: min={min(s0):>4}, max={max(s0):>4}, avg={np.mean(s0):>6.1f}")
            print(f"    {class_names[1]:>10}: min={min(s1):>4}, max={max(s1):>4}, avg={np.mean(s1):>6.1f}")
    
    # Threshold
    human_idx = 0 if 'Human' in class_names[0] else 1
    threshold = (best['min_h'] + best['max_nh']) // 2
    
    # ============================
    # SAVE BEST MODEL
    # ============================
    tflite_filename = f"{MODEL_NAME}.tflite"
    with open(tflite_filename, 'wb') as f:
        f.write(best['model'])
    print(f"\n💾 Saved: {tflite_filename} ({len(best['model']):,} bytes)")
    
    c_header = hex_to_c_array(best['model'], "g_human_detect_model_data", class_names)
    with open("human_detect_model_data.h", "w") as f:
        f.write(c_header)
    print("💾 Saved: human_detect_model_data.h")
    
    import shutil
    target = pathlib.Path('../../IOT_Project_FYP_integeration/esp32_camera_custom_tiny')
    if target.exists():
        shutil.copy("human_detect_model_data.h", target / "human_detect_model_data.h")
        print(f"✅ Copied to: {target}")
    
    print(f"\n{'='*60}")
    print("✅ DONE!")
    print(f"{'='*60}")
    print(f"\nESP32 Code:")
    print(f"  int8_t human_score = output->data.int8[{human_idx}];")
    print(f"  int8_t non_human_score = output->data.int8[{1-human_idx}];")
    print(f"  bool detected = (human_score > non_human_score && human_score > {threshold});")


def hex_to_c_array(data, var_name, class_names):
    c = f"// Auto-generated - Best of {NUM_RUNS} runs (48x48 RGB)\n"
    c += f"// output[0] = '{class_names[0]}', output[1] = '{class_names[1]}'\n"
    c += f"// Model size: {len(data):,} bytes\n\n"
    c += f"#ifndef {var_name.upper()}_H\n#define {var_name.upper()}_H\n\n"
    c += f"extern const unsigned char {var_name}[];\n"
    c += f"extern const unsigned int {var_name}_len;\n\n"
    c += f"const unsigned char {var_name}[] = {{\n"
    for i, val in enumerate(data):
        c += f"0x{val:02x}, "
        if (i+1)%12==0: c += "\n"
    c += "};\n"
    c += f"const unsigned int {var_name}_len = {len(data)};\n#endif\n"
    return c


if __name__ == "__main__":
    main()
