import tensorflow as tf
import pathlib
import matplotlib.pyplot as plt

def debug_data():
    DATASET_PATH = '../datasets/Human_Detection_Dataset'
    data_dir = pathlib.Path(DATASET_PATH)
    print(f"Data directory: {data_dir.resolve()}")
    
    # List subdirectories
    for item in data_dir.iterdir():
        if item.is_dir():
            print(f"Subdir: {item.name}, Count: {len(list(item.glob('*')))}")
            
    try:
        train_ds = tf.keras.utils.image_dataset_from_directory(
            data_dir,
            validation_split=0.2,
            subset="training",
            seed=123,
            image_size=(48, 48),
            batch_size=32,
            color_mode='grayscale'
        )
        
        print(f"Class names: {train_ds.class_names}")
        
        for images, labels in train_ds.take(1):
            print("First batch labels:", labels.numpy())
            print("Image stats - Min:", tf.reduce_min(images).numpy(), "Max:", tf.reduce_max(images).numpy())
            
    except Exception as e:
        print(f"Error loading dataset: {e}")

if __name__ == "__main__":
    debug_data()
