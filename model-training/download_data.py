import os
from datasets import load_dataset
from PIL import Image
from tqdm import tqdm

# Configuration
OUTPUT_DIR = r"c:\fyp-eagle-eye\Downloaded_Dataset"
DATASET_NAME = "prithivMLmods/Human-vs-NonHuman"

# Create output directories
# We will create them dynamically based on labels found
os.makedirs(OUTPUT_DIR, exist_ok=True)

print(f"Downloading dataset: {DATASET_NAME}...")

# Load the dataset
try:
    ds = load_dataset(DATASET_NAME, split="train")
except Exception as e:
    print(f"Error loading dataset split 'train': {e}")
    ds_dict = load_dataset(DATASET_NAME)
    ds = ds_dict['train'] if 'train' in ds_dict else ds_dict[list(ds_dict.keys())[0]]

print(f"Dataset loaded. Contains {len(ds)} samples.")
print(f"Saving images to {OUTPUT_DIR}...")

for i, item in enumerate(tqdm(ds)):
    try:
        image = item['image']
        label = item['label']

        # Determine class name dynamically
        class_name = "Unknown"
        if hasattr(ds.features['label'], 'int2str'):
            class_name = ds.features['label'].int2str(label)
        else:
            class_name = str(label)
            
        # Create subfolder for this specific class label
        target_dir = os.path.join(OUTPUT_DIR, class_name)
        os.makedirs(target_dir, exist_ok=True)
        
        # Save image
        if image.mode != "RGB":
            image = image.convert("RGB")
            
        filename = f"image_{i}.jpg"
        image.save(os.path.join(target_dir, filename))
        
        if i % 100 == 0:
            pass # tqdm handles progress usually
            
    except Exception as e:
        print(f"Skipping index {i} due to error: {e}")

print(f"\nDownload Completed.")
print(f"Images saved in {OUTPUT_DIR}")
