from pycocotools.coco import COCO
import numpy as np
import matplotlib.pyplot as plt
import pylab
import cv2
import math
import os
import sys
import tqdm
from multiprocessing import Pool
from functools import partial

import mmcv
import wwtool
from wwtool.transforms import pointobb_flip, thetaobb_flip, hobb_flip
from wwtool.transforms import pointobb_rescale, thetaobb_rescale, hobb_rescale, pointobb2pseudomask
from wwtool.visualization import show_grayscale_as_heatmap
from wwtool.datasets import cocoSegmentationToPng
from wwtool.generation import generate_gaussian_image, generate_centerness_image, generate_ellipse_image

class PseudomaskGenerate():
    def __init__(self,
                release_version,
                imageset,
                save_vis=False,
                show_pseudomask=False,
                encode='centerness',
                heatmap_rate=0.5,
                factor=4,
                method='min_area',
                multi_processing=False,
                num_processor=16):
        self.release_version = release_version
        self.imageset = imageset
        self.encode = encode
        self.factor = factor
        self.method = method

        self.save_dir_names = {'centerness': '{}_centerness_seg'.format(imageset),
                                'gaussian': '{}_gaussian_seg'.format(imageset),
                                'ellipse': '{}_ellipse_seg'.format(imageset)}

        self.imgDir = './data/{}/{}/coco/{}/'.format(core_dataset, self.release_version, self.imageset)
        self.annFile = './data/{}/{}/coco/annotations/{}.json'.format(core_dataset, self.release_version, "_".join(ann_file_name))
        
        self.save_vis = save_vis
        self.show_pseudomask = show_pseudomask

        self.save_path = './data/{}/{}/{}/{}'.format(core_dataset, self.release_version, self.imageset, self.save_dir_names[self.encode])
        self.save_vis_path = './data/{}/{}/{}/pseudomask_vis'.format(core_dataset, self.release_version, self.imageset)

        mmcv.mkdir_or_exist(self.save_path)
        mmcv.mkdir_or_exist(self.save_vis_path)

        self.heatmap_rate = heatmap_rate

        self.gaussian_image = generate_gaussian_image(512, 512, 2.5, threshold = int(self.heatmap_rate * 255))
        self.centerness_image = generate_centerness_image(512, 512, factor=self.factor, threshold = int(self.heatmap_rate * 255))
        self.ellipse_image = generate_ellipse_image(512, 512, threshold = int(self.heatmap_rate * 255))

        self.anchor_image = {'centerness': self.centerness_image,
                            'gaussian': self.gaussian_image,
                            'ellipse': self.ellipse_image}

        self.coco = COCO(self.annFile)
        self.catIds = self.coco.getCatIds(catNms=[''])
        self.imgIds = self.coco.getImgIds(catIds=self.catIds)
        self.multi_processing = multi_processing
        self.pool = Pool(num_processor)

    def generate_pseudomask(self, imgId):
        img_info = self.coco.loadImgs(imgId)[0]
        image_name = img_info['file_name']

        if os.path.exists(os.path.join(self.save_path, image_name)):
            return
        # if image_name != 'P2802__1.0__4914___4225.png':
        #     return
        annIds = self.coco.getAnnIds(imgIds=img_info['id'], catIds=self.catIds, iscrowd=None)
        anns = self.coco.loadAnns(annIds)
        pseudomasks = []
        height = img_info['height']
        width = img_info['width']
        area_map = np.ones((height, width)) * 1024 * 1024
        pseudomasks = np.zeros((height, width), dtype=np.int32)
        
        anchor_image = self.anchor_image[self.encode]

        for ann in anns:
            pointobb = ann['pointobb']
            label_mask = self.coco.annToMask(ann) == 1
            area = np.sum(label_mask)

            transformed, mask_location = pointobb2pseudomask(pointobb, anchor_image, host_height = height, host_width = width)
            transformed = transformed.astype(np.int32)

            if self.method == 'min_area':
                temp_pseudomasks = np.zeros((height, width), dtype=np.int32)
                temp_pseudomasks[mask_location[1]:mask_location[3], mask_location[0]:mask_location[2]] = transformed
                pseudomasks[label_mask] = np.where(area < area_map[label_mask], temp_pseudomasks[label_mask], pseudomasks[label_mask])
                area_map[label_mask] = np.where(area < area_map[label_mask], area, area_map[label_mask])
            elif self.method == 'min_score':
                pseudomasks[mask_location[1]:mask_location[3], mask_location[0]:mask_location[2]] = np.where(transformed > pseudomasks[mask_location[1]:mask_location[3], mask_location[0]:mask_location[2]], transformed, pseudomasks[mask_location[1]:mask_location[3], mask_location[0]:mask_location[2]])
            
        # save pseudomask
        pseudomask_file = os.path.join(self.save_path, image_name)
        pseudomasks = np.clip(pseudomasks, 0, 255)
        # pseudomasks = pseudomasks * 255.0
        pseudomasks = pseudomasks.astype(np.uint8)
        cv2.imwrite(pseudomask_file, pseudomasks)

        if self.save_vis:
            image_file = os.path.join(self.imgDir, image_name)
            img = cv2.imread(image_file)
            pseudomask_vis_file = os.path.join(self.save_vis_path, image_name)
            pseudomasks_ = show_grayscale_as_heatmap(pseudomasks / 255.0, self.show_pseudomask, return_img=True)
            alpha = 0.6
            beta = (1.0 - alpha)
            pseudomasks = cv2.addWeighted(pseudomasks_, alpha, img, beta, 0.0)
            cv2.imwrite(pseudomask_vis_file, pseudomasks)

    def generate_pseudomask_core(self):
        if self.multi_processing:
            num_image = len(self.imgIds)
            worker = partial(self.generate_pseudomask)
            # self.pool.map(worker, self.imgIds)
            ret = list(tqdm.tqdm(self.pool.imap(worker, self.imgIds), total=num_image))
            
        else:
            progress_bar = mmcv.ProgressBar(len(self.imgIds))
            for _, imgId in enumerate(self.imgIds):
                self.generate_pseudomask(imgId)
                progress_bar.update()

    def __getstate__(self):
        self_dict = self.__dict__.copy()
        del self_dict['pool']
        return self_dict

    def __setstate__(self, state):
        self.__dict__.update(state)

if __name__ == '__main__':
    core_dataset = 'dota'
    release_version = 'v1'
    imageset = 'train'

    ann_file_name = [core_dataset, imageset, release_version, 'best_keypoint']

    encode = 'centerness'   # centerness, gaussian, ellipse
    heatmap_rate = 0.5
    factor = 4
    save_vis = False
    show_pseudomask = True
    method = 'min_area'     # min_area, min_score

    pseudomask_gen = PseudomaskGenerate(release_version=release_version,
                imageset=imageset,
                save_vis=save_vis,
                show_pseudomask=show_pseudomask,
                encode=encode,
                factor=factor,
                heatmap_rate=heatmap_rate,
                method=method,
                multi_processing=False,
                num_processor=16)

    pseudomask_gen.generate_pseudomask_core()
