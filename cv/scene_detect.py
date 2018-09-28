# v0.2

import torch
from torch.autograd import Variable as V
import torchvision.models as models
from torchvision import transforms as trn
from torch.nn import functional as F
import os
import numpy as np
from scipy.misc import imresize as imresize
import cv2
from PIL import Image
from os import listdir
from os.path import isdir, join
import json


def load_labels():
    file_name_category = 'categories_places365.txt'

    classes = list()
    with open(file_name_category) as class_file:
        for line in class_file:
            classes.append(line.strip().split(' ')[0][3:])
    classes = tuple(classes)

    # indoor and outdoor relevant
    file_name_IO = 'IO_places365.txt'

    with open(file_name_IO) as f:
        lines = f.readlines()
        labels_IO = []
        for line in lines:
            items = line.rstrip().split()
            labels_IO.append(int(items[-1]) -1) # 0 is indoor, 1 is outdoor
    labels_IO = np.array(labels_IO)

    # scene attribute relevant
    file_name_attribute = 'labels_sunattribute.txt'

    with open(file_name_attribute) as f:
        lines = f.readlines()
        labels_attribute = [item.rstrip() for item in lines]
    file_name_W = 'W_sceneattribute_wideresnet18.npy'

    W_attribute = np.load(file_name_W)

    return classes, labels_IO, labels_attribute, W_attribute

def hook_feature(module, input, output):
    features_blobs.append(np.squeeze(output.data.cpu().numpy()))

def returnCAM(feature_conv, weight_softmax, class_idx):
    size_upsample = (256, 256)
    nc, h, w = feature_conv.shape
    output_cam = []
    for idx in class_idx:
        cam = weight_softmax[class_idx].dot(feature_conv.reshape((nc, h*w)))
        cam = cam.reshape(h, w)
        cam = cam - np.min(cam)
        cam_img = cam / np.max(cam)
        cam_img = np.uint8(255 * cam_img)
        output_cam.append(imresize(cam_img, size_upsample))
    return output_cam

def returnTF():
    tf = trn.Compose([
        trn.Resize((224,224)),
        trn.ToTensor(),
        trn.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    ])
    return tf


def load_model():
    model_file = 'wideresnet18_places365.pth.tar'

    import wideresnet
    model = wideresnet.resnet18(num_classes=365)
    checkpoint = torch.load(model_file, map_location=lambda storage, loc: storage)
    state_dict = {str.replace(k,'module.',''): v for k,v in checkpoint['state_dict'].items()}
    model.load_state_dict(state_dict)
    model.eval()

    model.eval()
    features_names = ['layer4','avgpool']
    for name in features_names:
        model._modules.get(name).register_forward_hook(hook_feature)
    return model


path = "/Users/pavel/Sources/python/concepts/insta/photos_moscow"
#areas = ["dorogomilovo-russia", "krasnaya-presnya-russia", "udelnaya-russia"]

scene_base = {}
try:
    with open('scenes_moscow.json', 'r') as f:
        scene_base = json.load(f)
except:
    pass

classes, labels_IO, labels_attribute, W_attribute = load_labels()

features_blobs = []
model = load_model()

tf = returnTF() 

params = list(model.parameters())
weight_softmax = params[-2].data.numpy()
weight_softmax[weight_softmax<0] = 0

areas = [f for f in listdir(path) if isdir(join(path, f))]
cn = 0
for area in areas:
    locations = os.listdir(os.path.join(path, area))
    for k, loc in enumerate(locations):
        cn += 1

        if loc in scene_base:
            print("already processed", loc)
            continue

        print(cn+1, loc)
        try:
            pictures = os.listdir(os.path.join(path, area, loc))
        except:
            pass

        scene_base[loc] = {}

        for pic in pictures:
            try:
                img = Image.open(os.path.join(path, area, loc, pic))
            except:
                continue

            input_img = V(tf(img).unsqueeze(0))

            try:
                logit = model.forward(input_img)
            except:
                print("NN error")

            h_x = F.softmax(logit, 1).data.squeeze()
            probs, idx = h_x.sort(0, True)
            probs = probs.numpy()
            idx = idx.numpy()

            scene_proporties = {}
            io_image = np.mean(labels_IO[idx[:10]])
            if io_image < 0.5:
                scene_proporties['enviroment'] = 'indoor'
            else:
                scene_proporties['enviroment'] = 'outdoor'

            scene_proporties['categories'] = {}
            for i in range(0, 5):
                scene_proporties['categories'][classes[idx[i]]] = str(probs[i])

            responses_attribute = W_attribute.dot(features_blobs[1])
            idx_a = np.argsort(responses_attribute)
            scene_proporties['attributes'] = [labels_attribute[idx_a[i]] for i in range(-1,-10,-1)]

            scene_base[loc][pic] = scene_proporties
        
        #print(scene_base)
        if k % 10 == 0:
            with open('scenes_moscow.json', 'w') as fp:
                json.dump(scene_base, fp, indent=4)
