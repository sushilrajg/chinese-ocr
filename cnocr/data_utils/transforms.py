# coding: utf-8
# Copyright (C) 2023, [Breezedeus](https://github.com/breezedeus).
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
import random
import cv2
import torch
import numpy as np
import albumentations as alb
from albumentations.pytorch import ToTensorV2
from albumentations.core.transforms_interface import ImageOnlyTransform

from ..utils import normalize_img_array


class RandomStretchAug(alb.Resize):
    def __init__(self, min_ratio=0.9, max_ratio=1.1, always_apply=False, p=1):
        super(RandomStretchAug, self).__init__(height=0, width=0, always_apply=always_apply, p=p)
        self.min_ratio = min_ratio
        self.max_ratio = max_ratio

    def apply(self, img, **params):
        h, w = img.shape[:2]
        new_w_ratio = self.min_ratio + random.random() * (self.max_ratio - self.min_ratio)
        new_w = int(w * new_w_ratio)
        return alb.Resize(height=h, width=new_w).apply(img)


class CustomRandomCrop(ImageOnlyTransform):
    """从图像的四个边缘随机裁剪"""

    def __init__(self, crop_size, always_apply=False, p=1.0):
        super(CustomRandomCrop, self).__init__(always_apply, p)
        self.crop_size = crop_size

    def cal_params(self, img):
        ori_h, ori_w = img.shape[:2]
        while True:
            h_top, h_bot = (
                random.randint(0, self.crop_size[0]),
                random.randint(0, self.crop_size[0]),
            )
            w_left, w_right = (
                random.randint(0, self.crop_size[1]),
                random.randint(0, self.crop_size[1]),
            )
            h = ori_h - h_top - h_bot
            w = ori_w - w_left - w_right
            if h < ori_h * 0.5 or w < ori_w * 0.5:
                continue

            return h_top, w_left, h, w

    def apply(self, img, **params):
        h_top, w_left, h, w = self.cal_params(img)
        return cv2.resize(img[h_top:h_top + h, w_left:w_left + w], img.shape[:2])


class TransparentOverlay(ImageOnlyTransform):
    """模仿标注笔的标注效果。"""

    def __init__(
        self, max_height_ratio, max_width_ratio, alpha, always_apply=False, p=1.0
    ):
        super(TransparentOverlay, self).__init__(always_apply, p)
        self.max_height_ratio = max_height_ratio
        self.max_width_ratio = max_width_ratio
        self.alpha = alpha

    def apply(self, img, x=0, y=0, height=0, width=0, color=(0, 0, 0), **params):
        original_c = img.shape[2]

        # 确保图片有四个通道（RGBA）
        if img.shape[2] < 4:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)

        # 创建一个与图片大小相同的覆盖层
        overlay = img.copy()

        # 在覆盖层上涂色
        cv2.rectangle(overlay, (x, y), (x + width, y + height), color, -1)

        # 结合覆盖层和原图片
        img = cv2.addWeighted(overlay, self.alpha, img, 1 - self.alpha, 0)

        # Convert the image back to the original number of channels
        if original_c != img.shape[2]:
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

        return img

    @property
    def targets_as_params(self):
        return ['image']

    def get_params_dependent_on_targets(self, params):
        img = params['image']
        height, width, _ = img.shape

        # Compute the actual pixel values for the maximum height and width
        max_height = int(height * self.max_height_ratio)
        max_width = int(width * self.max_width_ratio)

        x = np.random.randint(0, max(width - max_width, 1))
        y = np.random.randint(0, max(height - max_height, 1))
        rect_width = np.random.randint(0, max_width)
        rect_height = np.random.randint(0, max_height)

        color = [np.random.randint(0, 256) for _ in range(3)]

        return {
            'x': x,
            'y': y,
            'width': rect_width,
            'height': rect_height,
            'color': color,
        }


class ToSingleChannelGray(ImageOnlyTransform):
    def apply(self, img, **params):  # -> [H, W, 1]
        if img.shape[2] != 1:
            gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
            return gray[:, :, np.newaxis]  # Add an extra channel dimension
        else:
            return img


class CustomNormalize(ImageOnlyTransform):
    def apply(self, img, **params):  # -> [H, W, 1]
        return normalize_img_array(img)


def transform_wrap(transform):
    """把albumentations的transform转换成torchvision的transform"""
    def wrapper(image: torch.Tensor) -> torch.Tensor:
        """

        Args:
            image (np.ndarray): with shape [C, H, W]

        Returns: np.ndarray, with shape [C, H, W]

        """
        image = image.numpy()
        image = image.transpose((1, 2, 0))  # to: [H, W, C]
        out = transform(image=image)['image']
        out = torch.from_numpy(out.transpose((2, 0, 1)))  # to: [C, H, W]
        return out
    return wrapper


_train_alb_transform = alb.Compose(
    [
        alb.Compose(
            [
                alb.ShiftScaleRotate(
                    shift_limit=0,
                    scale_limit=(-0.15, 0),
                    rotate_limit=1,
                    border_mode=0,
                    interpolation=3,
                    value=[255, 255, 255],
                    p=1,
                ),
                alb.GridDistortion(
                    distort_limit=0.1,
                    border_mode=0,
                    interpolation=3,
                    value=[255, 255, 255],
                    p=0.5,
                ),
            ],
            p=0.15,
        ),
        # alb.RGBShift(r_shift_limit=15, g_shift_limit=15, b_shift_limit=15, p=0.3),
        alb.GaussNoise(10, p=0.2),
        alb.RandomBrightnessContrast(0.05, (-0.2, 0), True, p=0.2),
        alb.ImageCompression(95, p=0.3),
        TransparentOverlay(1.0, 0.1, alpha=0.4, p=0.2),  # 半透明的矩形框覆盖
        alb.Emboss(p=0.3, alpha=(0.2, 0.5), strength=(0.2, 0.7)),
        alb.OpticalDistortion(
            always_apply=False,
            p=0.2,
            distort_limit=(-0.05, 0.05),
            shift_limit=(-0.05, 0.05),
            interpolation=0,
            border_mode=0,
            value=(0, 0, 0),
            mask_value=None,
        ),
        alb.Sharpen(always_apply=False, p=0.3, alpha=(0.2, 0.5), lightness=(0.5, 1.0)),
        alb.ElasticTransform(
            always_apply=False,
            p=0.3,
            alpha=0.15,
            sigma=10.07,
            alpha_affine=0.15,
            interpolation=0,
            border_mode=0,
            value=(255, 255, 255),
            mask_value=None,
            approximate=False,
            same_dxdy=False,
        ),
        RandomStretchAug(min_ratio=0.5, max_ratio=1.5, p=0.2, always_apply=False),
        alb.InvertImg(p=0.3),
        ToSingleChannelGray(always_apply=True),
        CustomNormalize(always_apply=True),
        # alb.Normalize((0.7931, 0.7931, 0.7931), (0.1738, 0.1738, 0.1738)),
        # ToTensorV2(),
    ]
)

train_transform = transform_wrap(_train_alb_transform)

_test_alb_transform = alb.Compose(
    [
        ToSingleChannelGray(always_apply=True),
        CustomNormalize(always_apply=True),
    ]
)

test_transform = transform_wrap(_test_alb_transform)