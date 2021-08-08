# coding: utf-8
from __future__ import absolute_import, division, print_function
import os
import logging
import time
import click
import json
import glob

from torchvision import transforms

from cnocr.utils import set_logger, load_model_params
from cnocr.data_utils.aug import NormalizeAug
from cnocr.dataset import OcrDataModule
from cnocr.models.densenet import DenseNet
from cnocr.models.crnn import CRNN
from cnocr.trainer import PlTrainer
from cnocr import CnOcr

_CONTEXT_SETTINGS = {"help_option_names": ['-h', '--help']}
logger = set_logger(log_level=logging.INFO)


@click.group(context_settings=_CONTEXT_SETTINGS)
def cli():
    pass


@cli.command('train')
@click.option(
    '--index-dir',
    type=str,
    required=True,
    help='索引文件所在的文件夹，会读取文件夹中的 train.tsv 和 dev.tsv 文件',
)
@click.option('--train-config-fp', type=str, required=True, help='训练使用的json配置文件')
@click.option(
    '-m', '--pretrained-model-fp', type=str, default=None, help='导入的训练好的模型，作为初始模型'
)
def train(index_dir, train_config_fp, pretrained_model_fp):
    train_transform = transforms.Compose(
        [
            transforms.RandomInvert(p=0.5),
            # transforms.RandomErasing(p=0.05, scale=(0.01, 0.05)),
            transforms.RandomRotation(degrees=2),
            transforms.RandomAutocontrast(p=0.05),
            NormalizeAug(),
        ]
    )
    val_transform = NormalizeAug()

    train_config = json.load(open(train_config_fp))

    data_mod = OcrDataModule(
        index_dir=index_dir,
        vocab_fp=train_config['vocab_fp'],
        img_folder=train_config['img_folder'],
        train_transforms=train_transform,
        val_transforms=val_transform,
        batch_size=train_config['batch_size'],
        num_workers=train_config['num_workers'],
        pin_memory=train_config['pin_memory'],
    )

    trainer = PlTrainer(train_config)
    model = gen_model(data_mod.vocab)

    if pretrained_model_fp is not None:
        load_model_params(model, pretrained_model_fp)

    trainer.fit(model, datamodule=data_mod)


def gen_model(vocab):
    net = DenseNet(32, [2, 2, 2, 2], 64)
    crnn = CRNN(net, vocab=vocab, lstm_features=512, rnn_units=128)
    return crnn


@cli.command('predict')
@click.option("--model_name", help="model name", type=str, default='densenet-s-lstm')
@click.option("--model_epoch", type=int, default=None, help="model epoch")
@click.option(
    "--context",
    help="使用cpu还是gpu运行代码。默认为cpu",
    type=click.Choice(['cpu', 'gpu']),
    default='cpu',
)
@click.option("-f", "--file", help="Path to the image file or dir")
@click.option(
    "-s",
    "--single-line",
    is_flag=True,
    help="Whether the image only includes one-line characters",
)
def predict(model_name, model_epoch, context, file, single_line):
    ocr = CnOcr(
        model_name=model_name, model_epoch=model_epoch, context=context
    )
    ocr_func = ocr.ocr_for_single_line if single_line else ocr.ocr
    fp_list = []
    if os.path.isfile(file):
        fp_list.append(file)
    elif os.path.isdir(file):
        fn_list = glob.glob1(file, '*g')
        fp_list = [os.path.join(file, fn) for fn in fn_list]

    for fp in fp_list:
        start_time = time.time()
        logger.info('\n' + '=' * 10 + fp + '=' * 10)
        res = ocr_func(fp)
        logger.info('time cost: %f' % (time.time() - start_time))
        logger.info(res)
        if single_line:
            res = [res]
        for line_res in res:
            preds, prob = line_res
            logger.info('\npred: %s, with probability %f' % (''.join(preds), prob))


if __name__ == "__main__":
    cli()