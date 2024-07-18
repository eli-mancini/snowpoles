'''
To do:
put in keypoint columns in the config file and update here

Updates: 
- switched train/test from random to 16 cameras : 4 cameras (OOD testing)
- specified columns in keypoints because we have extra columns in our df
- Specifed the __getitem__ function to look in nested folders of cameraIDs
    rather than training and testing
- specified the cameras for validation, 2 from each side, split from in and out of canopy
- hardcoded the training files path
- data aug docs: https://albumentations.ai/docs/getting_started/keypoints_augmentation/ 
- data aug docs cont. : https://albumentations.ai/docs/api_reference/augmentations/transforms/

'''

import torch
import cv2
import pandas as pd
import numpy as np
import config
#import config_cpu as config ## for cpu training
import utils
from torch.utils.data import Dataset, DataLoader
import IPython
import matplotlib.pyplot as plt
import glob
import torch
import torchvision.transforms as T
from PIL import Image
from PIL import Image, ImageFile
import albumentations as A ### better for keypoint augmentations, pip install albumentations
from torchvision.transforms import Compose, Resize, ToTensor
from sklearn.model_selection import train_test_split
import os

## to get a systematic sample: (already sorted)
# def sort_within_camera_group(group):
#     return group.sort_values(by='Filename')

# Define a function to sample every third photo
def sample_every_x(group, x):
    indices = np.arange(len(group[1]))
    every_x = len(group[1])//x
    selected_indices = indices[2::every_x]  # Select every third index starting from index 2
    return group[1].iloc[selected_indices]
#####

##### re-write this for out of domain testing
def train_test_split(csv_path, path, split, aug):
    
    df_data = pd.read_csv(csv_path)
    print(f'all rows in df_data {len(df_data.index)}')
    
    training_samples = df_data.sample(frac=0.8, random_state=100) # same shuffle everytime
    valid_samples = df_data[~df_data.index.isin(training_samples.index)]

    if config.FINETUNE == True:
        print(f"FINETUNING MODEL n\ ")
        #IPython.embed()
        # stratsmp = glob.glob(f"{config.FT_IMG_PATH}/**/*")
        # stratsmp = [item.split('/')[-1] for item in stratsmp]
        # certain number every x from camera
        groups = wa_testdata.groupby('Camera')
        training_samples = pd.DataFrame()
        for group in groups: 
            y = sample_every_x(group, config.FT_sample)
            training_samples = pd.concat([training_samples, y])

        training_samples = training_samples
        valid_samples = wa_testdata[~wa_testdata['filename'].isin(training_samples['filename'])].sample(frac=0.1, random_state=100)  # just test on 10$ of WA data
        
        if not os.path.exists(f"{config.OUTPUT_PATH}"):
            os.makedirs(f"{config.OUTPUT_PATH}", exist_ok=True)
        training_samples.to_csv(f"{config.OUTPUT_PATH}/FT_training_samples.csv")
        valid_samples.to_csv(f"{config.OUTPUT_PATH}/FT_valid_samples.csv")

    ##### only images that exist
    all_images = glob.glob(path + ('/**/*.JPG'))
    filenames = [item.split('/')[-1] for item in all_images]
    valid_samples = valid_samples[valid_samples['filename'].isin(filenames)].reset_index()
    training_samples = training_samples[training_samples['filename'].isin(filenames)].reset_index()
    
    if not os.path.exists(f"{config.OUTPUT_PATH}"):
            os.makedirs(f"{config.OUTPUT_PATH}", exist_ok=True)
    training_samples.to_csv(f"{config.OUTPUT_PATH}/training_samples.csv")
    valid_samples.to_csv(f"{config.OUTPUT_PATH}/valid_samples.csv")

    print(f'# of examples we will now train on {len(training_samples)}, val on {len(valid_samples)}')
    
    return training_samples, valid_samples


class snowPoleDataset(Dataset):

    def __init__(self, samples, path, aug): # split='train'):
        self.data = samples
        self.path = path
        self.resize = 224

        if aug == False: 
            self.transform = A.Compose([
                A.Resize(224, 224),
                ], keypoint_params=A.KeypointParams(format='xy'))
        else: 
            self.transform = A.Compose([
                A.ToFloat(max_value=1.0),
                A.CropAndPad(px=75, p =1.0), ## final model is 50 pixels
                A.ShiftScaleRotate(shift_limit=0.05, scale_limit=0.2, rotate_limit=20, p=0.5),
                A.OneOf([
                    A.RandomBrightnessContrast(p=0.5),
                    A.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.2, hue=0.2, always_apply=False, p=0.5),
                    A.ToGray(p=0.5)], p = 0.5),
                A.Resize(224, 224),
                ], keypoint_params=A.KeypointParams(format='xy'))

    def __len__(self):
        return len(self.data)

    def __filename__(self, index):
        filename = self.data.iloc[index]['filename']
        return filename
    
    def __getitem__(self, index):
        cameraID = self.data.iloc[index]['filename'].split('_')[0] ## need this to get the right folder
        filename = self.data.iloc[index]['filename']
        #IPython.embed()
        
        image = cv2.imread(f"{self.path}/{cameraID}/{self.data.iloc[index]['filename']}")
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        orig_h, orig_w, channel = image.shape
        
        # resize the image into `resize` defined above
        image = cv2.resize(image, (self.resize, self.resize))
        #IPython.embed()
        # again reshape to add grayscale channel format
        image = image / 255.0

        # get the keypoints
        keypoints = self.data.iloc[index][1:][['x1','y1','x2','y2']] 
        keypoints = np.array(keypoints, dtype='float32')
        # reshape the keypoints
        keypoints = keypoints.reshape(-1, 2)
        keypoints = keypoints * [self.resize / orig_w, self.resize / orig_h]

        transformed = self.transform(image=image, keypoints=keypoints)
        img_transformed = transformed['image']
        keypoints = transformed['keypoints']
    
        image = np.transpose(img_transformed, (2, 0, 1))
 
        if len(keypoints) != 2:
            utils.vis_keypoints(transformed['image'], transformed['keypoints'])

        return {
            'image': torch.tensor(image, dtype=torch.float),
            'keypoints': torch.tensor(keypoints, dtype=torch.float),
            'filename': filename
        }

# get the training and validation data samples
training_samples, valid_samples = train_test_split(f"{config.ROOT_PATH}/snowPoles_labels_clean_jul23upd.csv", f"{config.ROOT_PATH}", 
                                                   config.TEST_SPLIT, config.AUG)

# initialize the dataset - `snowPoleDataset()`
train_data = snowPoleDataset(training_samples, 
                                 f"{config.ROOT_PATH}", aug = config.AUG)  
#IPython.embed()
valid_data = snowPoleDataset(valid_samples, 
                                 f"{config.ROOT_PATH}", aug = False) 

wa_data = snowPoleDataset(wa_testdata, 
                            f"{config.ROOT_PATH}", aug = False) #

co_data = snowPoleDataset(co_testdata, 
                            f"{config.ROOT_PATH}", aug = False) 
# prepare data loaders
train_loader = DataLoader(train_data, 
                          batch_size=config.BATCH_SIZE, 
                          shuffle=True, num_workers = 0)
valid_loader = DataLoader(valid_data, 
                          batch_size=config.BATCH_SIZE, 
                          shuffle=False, num_workers = 0) 

print(f"Training sample instances: {len(train_data)}")
print(f"Validation sample instances: {len(valid_data)}")


# whether to show dataset keypoint plots
if config.SHOW_DATASET_PLOT:
    utils.dataset_keypoints_plot(train_data)
    utils.dataset_keypoints_plot(valid_data)




