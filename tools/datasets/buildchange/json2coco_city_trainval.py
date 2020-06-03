import argparse

import os
import cv2
import json
import csv
import shutil
import numpy as np

import wwtool

import os
import cv2
import mmcv

class SIMPLETXT2COCO():
    def __init__(self, 
                imgpath=None,
                annopath=None,
                imageset_file=None,
                image_format='.jpg',
                anno_format='.txt',
                data_categories=None,
                data_info=None,
                data_licenses=None,
                data_type="instances",
                groundtruth=True,
                small_object_area=0,
                sub_anno_fold=False,
                cities=None):
        super(SIMPLETXT2COCO, self).__init__()

        self.imgpath = imgpath
        self.annopath = annopath
        self.image_format = image_format
        self.anno_format = anno_format

        self.categories = data_categories
        self.info = data_info
        self.licenses = data_licenses
        self.type = data_type
        self.small_object_area = small_object_area
        self.small_object_idx = 0
        self.groundtruth = groundtruth
        self.max_object_num_per_image = 0
        self.sub_anno_fold = sub_anno_fold
        self.imageset_file = imageset_file

        self.imgpaths, self.annotpaths = [], []

        for label_fn in os.listdir(annopath):
            basename = wwtool.get_basename(label_fn)
            self.imgpaths.append(os.path.join(imgpath, basename + '.png'))
            self.annotpaths.append(os.path.join(annopath, basename + '.json'))
                
    def get_image_annotation_pairs(self):
        images = []
        annotations = []
        index = 0
        progress_bar = mmcv.ProgressBar(len(self.imgpaths))
        imId = 0
        for imgfile, annofile in zip(self.imgpaths, self.annotpaths):
            # imgpath = os.path.join(self.imgpath, name + self.image_format)
            # annotpath = os.path.join(self.annopath, name + self.anno_format)
            name = wwtool.get_basename(imgfile)

            annotations_coco = self.__generate_coco_annotation__(annofile, imgfile)

            # if annotation is empty, skip this annotation
            if annotations_coco != [] or self.groundtruth == False:
                height, width, channels = 1024, 1024, 3
                images.append({"date_captured": "2019",
                                "file_name": name + self.image_format,
                                "id": imId + 1,
                                "license": 1,
                                "url": "http://jwwangchn.cn",
                                "height": height,
                                "width": width})

                for annotation in annotations_coco:
                    index = index + 1
                    annotation["image_id"] = imId + 1
                    annotation["id"] = index
                    annotations.append(annotation)

                imId += 1

            if imId % 500 == 0:
                print("\nImage ID: {}, Instance ID: {}, Small Object Counter: {}, Max Object Number: {}".format(imId, index, self.small_object_idx, self.max_object_num_per_image))
            
            progress_bar.update()
            
        return images, annotations

    def __generate_coco_annotation__(self, annotpath, imgpath):
        """
        docstring here
            :param self: 
            :param annotpath: the path of each annotation
            :param return: dict()  
        """
        objects = self.__simpletxt_parse__(annotpath, imgpath)
        
        coco_annotations = []

        for object_struct in objects:
            bbox = object_struct['bbox']
            segmentation = object_struct['segmentation']
            label = object_struct['label']

            roof_bbox = object_struct['roof_bbox']
            building_bbox = object_struct['building_bbox']
            roof_mask = object_struct['roof_mask']
            footprint_mask = object_struct['footprint_mask']
            ignore_flag = object_struct['ignore_flag']
            offset = object_struct['offset']
            iscrowd = object_struct['iscrowd']

            width = bbox[2]
            height = bbox[3]
            area = height * width

            if area <= self.small_object_area and self.groundtruth:
                self.small_object_idx += 1
                continue

            coco_annotation = {}
            coco_annotation['bbox'] = bbox
            coco_annotation['segmentation'] = [segmentation]
            coco_annotation['category_id'] = label
            coco_annotation['area'] = np.float(area)

            coco_annotation['roof_bbox'] = roof_bbox
            coco_annotation['building_bbox'] = building_bbox
            coco_annotation['roof_mask'] = roof_mask
            coco_annotation['footprint_mask'] = footprint_mask
            coco_annotation['ignore_flag'] = ignore_flag
            coco_annotation['offset'] = offset
            coco_annotation['iscrowd'] = iscrowd

            coco_annotations.append(coco_annotation)

        return coco_annotations
    
    def __simpletxt_parse__(self, label_file, image_file):
        """
        (xmin, ymin, xmax, ymax)
        """
        annotations = mmcv.load(label_file)['annotations']
        # roof_mask, footprint_mask, roof_bbox, building_bbox, label, ignore, offset
        objects = []
        for annotation in annotations:
            object_struct = {}
            roof_mask = annotation['roof']
            roof_polygon = wwtool.mask2polygon(roof_mask)
            roof_bound = roof_polygon.bounds    # xmin, ymin, xmax, ymax
            footprint_mask = annotation['footprint']
            footprint_polygon = wwtool.mask2polygon(footprint_mask)
            footprint_bound = footprint_polygon.bounds
            building_xmin = np.minimum(roof_bound[0], footprint_bound[0])
            building_ymin = np.minimum(roof_bound[1], footprint_bound[1])
            building_xmax = np.maximum(roof_bound[2], footprint_bound[2])
            building_ymax = np.maximum(roof_bound[3], footprint_bound[3])

            building_bound = [building_xmin, building_ymin, building_xmax, building_ymax]

            xmin, ymin, xmax, ymax = list(roof_bound)
            bbox_w = xmax - xmin
            bbox_h = ymax - ymin
            object_struct['bbox'] = [xmin, ymin, bbox_w, bbox_h]
            object_struct['roof_bbox'] = object_struct['bbox']
            xmin, ymin, xmax, ymax = list(building_bound)
            bbox_w = xmax - xmin
            bbox_h = ymax - ymin
            object_struct['building_bbox'] = [xmin, ymin, bbox_w, bbox_h]

            object_struct['roof_mask'] = roof_mask
            object_struct['footprint_mask'] = footprint_mask
            object_struct['ignore_flag'] = annotation['ignore']
            object_struct['offset'] = annotation['offset']
            
            object_struct['segmentation'] = roof_mask
            object_struct['label'] = 1
            object_struct['iscrowd'] = object_struct['ignore_flag']
            
            objects.append(object_struct)
        
        return objects

def parse_args():
    parser = argparse.ArgumentParser(description='MMDet test detector')
    parser.add_argument(
        '--imagesets',
        type=str,
        nargs='+',
        choices=['trainval', 'test'])
    parser.add_argument(
        '--release_version', default='v1', type=str)
    args = parser.parse_args()
    return args

if __name__ == "__main__":
    args = parse_args()

    # basic dataset information
    info = {"year" : 2019,
                "version" : "1.0",
                "description" : "SIMPLETXT-Building-COCO",
                "contributor" : "Jinwang Wang",
                "url" : "jwwangchn.cn",
                "date_created" : "2019"
            }
    
    licenses = [{"id": 1,
                    "name": "Attribution-NonCommercial",
                    "url": "http://creativecommons.org/licenses/by-nc-sa/2.0/"
                }]

    original_simpletxt_class = {'building': 1}

    converted_simpletxt_class = [{'supercategory': 'none', 'id': 1,  'name': 'building',                   }]

    # dataset's information
    image_format='.png'
    anno_format='.txt'

    core_dataset_name = 'buildchange'
    cities = ['shanghai']
    # sub_city_folds = {'shanghai': ['arg']}
    # cities = ['shanghai', 'beijing', 'jinan', 'haerbin', 'chengdu']

    release_version = 'v2'
    groundtruth = True
    for idx, city in enumerate(cities):
        anno_name = [core_dataset_name, release_version, 'trainval', city, 'roof_footprint']
        
        imgpath = f'./data/{core_dataset_name}/{release_version}/{city}/images'
        annopath = f'./data/{core_dataset_name}/{release_version}/{city}/labels_json'
        save_path = f'./data/{core_dataset_name}/{release_version}/coco/annotations'
        if not os.path.exists(save_path):
            os.makedirs(save_path)

        simpletxt2coco = SIMPLETXT2COCO(imgpath=imgpath,
                                        annopath=annopath,
                                        image_format=image_format,
                                        anno_format=anno_format,
                                        data_categories=converted_simpletxt_class,
                                        data_info=info,
                                        data_licenses=licenses,
                                        data_type="instances",
                                        groundtruth=groundtruth,
                                        small_object_area=0,
                                        cities=cities)

        images, annotations = simpletxt2coco.get_image_annotation_pairs()

        json_data = {"info" : simpletxt2coco.info,
                    "images" : images,
                    "licenses" : simpletxt2coco.licenses,
                    "type" : simpletxt2coco.type,
                    "annotations" : annotations,
                    "categories" : simpletxt2coco.categories}

        with open(os.path.join(save_path, "_".join(anno_name) + ".json"), "w") as jsonfile:
            json.dump(json_data, jsonfile, sort_keys=True, indent=4)