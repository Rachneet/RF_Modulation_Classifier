import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset
from torch.utils.data.sampler import SubsetRandomSampler

import pytorch_lightning as pl
from pytorch_lightning import Trainer
from pytorch_lightning.loggers.neptune import NeptuneLogger

import math
import os
import csv
import h5py as h5
from argparse import ArgumentParser
from collections import OrderedDict

from sklearn import metrics

# from data_processing.intf_processing import *
import numpy as np

from dotenv import load_dotenv
load_dotenv()

torch.manual_seed(4)  # for reproducibility of results


# custom dataloader
class MyDataset(Dataset):
    def __init__(self, data_path, class_path=None):
        self.data_path = data_path
        iqs, labels, snrs = [], [], []
        with open(data_path, encoding='utf-8') as csv_file:
            reader = csv.reader(csv_file, quotechar='"')
            for idx, line in enumerate(reader):
                iq = np.array(line[0])
                label = int(line[-2])
                snr = int(line[-1])
                iqs.append(iq)
                labels.append(label)
                snrs.append(snr)

        self.iqs = iqs
        self.labels = labels
        self.snrs = snrs
        self.length = len(self.labels)
        if class_path:
            self.num_classes = sum(1 for _ in open(class_path))

    # gets the length
    def __len__(self):
        return self.length

    # gets data based on given index
    # done the encoding here itself
    def __getitem__(self, index):
        iq = self.iqs[index]
        label = self.labels[index]
        snr = self.snrs[index]
        return iq, label, snr

# -----------------------------------------------------------------------------------------------------------


class DatasetFromHDF5(Dataset):
    def __init__(self, filename, iq,labels,snrs,feature_flag=False):
        self.filename = filename
        self.iq = iq
        self.labels = labels
        self.snrs = snrs
        self.features = np.array([])
        self.feature_flag = feature_flag

    def __len__(self):
        with h5.File(self.filename, 'r') as file:
            lens = len(file[self.labels])
        return lens

    def __getitem__(self, item):
        with h5.File(self.filename, 'r') as file:
            data = file[self.iq][item]
            label = file[self.labels][item]
            snr = file[self.snrs][item]
            features = self.features

        # --------------------- Featurize data ------------------------
        if self.feature_flag:
            features = featurize(data)
            features = preprocessing.scale(features, with_mean=False).astype(np.float32)
        # -------------------------------------------------------------
        # scaler = preprocessing.StandardScaler()
        # data = scaler.fit_transform(data).astype(np.float32)
        # data = preprocessing.scale(data,with_mean=False).astype(np.float32)
        data = data.astype(np.float32)
        label = label.astype(np.float32)
        snr = snr.astype(np.int8)

        if self.feature_flag:
            return data, label, snr, features
        else:
            return data,label,snr


# ===============================================MODEL==============================================================

class LightningCNN(pl.LightningModule):
    def __init__(self,hparams):

        super(LightningCNN,self).__init__()

        self.train_dataset = None
        self.val_dataset = None
        self.test_dataset = None
        self.all_true, self.all_pred, self.all_snr = [], [], []  # for final metrics calculation
        self.hparams = hparams

        # layer 1
        self.conv1 = nn.Sequential(
            nn.Conv2d(hparams.in_dims, hparams.filters, hparams.kernel_size[0],padding=2),
            nn.BatchNorm2d(hparams.filters),
            nn.ReLU(),
            nn.MaxPool2d(hparams.pool_size)
        )

        # layer 2
        self.conv2 = nn.Sequential(
            nn.Conv2d(hparams.filters, hparams.filters, hparams.kernel_size[1],padding=2),
            nn.BatchNorm2d(hparams.filters),
            nn.ReLU(),
            nn.MaxPool2d(hparams.pool_size)
        )

        # layer 3,4,5
        self.conv3 = nn.Sequential(
            nn.Conv2d(hparams.filters, hparams.filters, hparams.kernel_size[2],padding=2),
            nn.BatchNorm2d(hparams.filters),
            nn.ReLU(),
            nn.MaxPool2d(hparams.pool_size)
        )

        self.conv4 = nn.Sequential(
            nn.Conv2d(hparams.filters, hparams.filters, hparams.kernel_size[3],padding=2),
            nn.BatchNorm2d(hparams.filters),
            nn.ReLU(),
            nn.MaxPool2d(hparams.pool_size)
        )

        self.conv5 = nn.Sequential(
            nn.Conv2d(hparams.filters, hparams.filters, hparams.kernel_size[4],padding=2),
            nn.BatchNorm2d(hparams.filters),
            nn.ReLU(),
            nn.MaxPool2d(hparams.pool_size)
        )

        # layer 6
        self.conv6 = nn.Sequential(
            nn.Conv2d(hparams.filters, hparams.filters, hparams.kernel_size[5],padding=2),
            nn.BatchNorm2d(hparams.filters),
            nn.ReLU(),
            nn.MaxPool2d(hparams.pool_size)
        )

        if hparams.featurize:
            in_dim = hparams.fc_neurons+hparams.n_features
        else:
            in_dim = hparams.fc_neurons

        # layer 7
        self.fc1 = nn.Sequential(
            nn.Linear(hparams.fc_neurons,hparams.fc_neurons),
            nn.ReLU(),
            nn.Dropout(p=0.5)
        )

        # layer 8
        self.fc2 = nn.Sequential(
            nn.Linear(hparams.fc_neurons, hparams.fc_neurons),
            nn.ReLU(),
            nn.Dropout(p=0.5)
        )

        # layer 9
        self.fc3 = nn.Linear(hparams.fc_neurons, hparams.n_classes)

    def forward(self, input, features):

        input = input.permute(0,2,1)
        input = input.unsqueeze(dim=3)
        output = self.conv1(input)
        output = self.conv2(output)
        output = self.conv3(output)
        output = self.conv4(output)
        output = self.conv5(output)
        output = self.conv6(output)
        output = output.view(output.size(0), -1)
        if self.hparams.featurize:
            # add hand crafted features to cnn features
            output = torch.cat((output, features), 1)
        output = self.fc1(output)
        output = self.fc2(output)
        output = self.fc3(output)
        # output = self.model(input)

        return output


    def configure_optimizers(self):
        optimizer = torch.optim.SGD(self.parameters(), lr=self.hparams.learning_rate,momentum=self.hparams.momentum)
        # optimizer = torch.optim.Adam(self.parameters(), lr=self.hparams.learning_rate)
        # exp_lr_scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=7, gamma=0.1)
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=3)   # dynamic reduction based on val_loss
        # scheduler = torch.optim.lr_scheduler.MultiStepLR(optimizer, milestones=[9,18,27],gamma=0.1)
        return {
            'optimizer': optimizer,
            'lr_scheduler': scheduler,
            'monitor': 'val_loss'
        }

    def cross_entropy_loss(self,logits, labels):
        loss = nn.CrossEntropyLoss()
        return loss(logits, labels)

    def training_step(self, batch, batch_idx):
        if self.hparams.featurize:
            x, y, z, f = batch
            logits = self.forward(x, f)
        else:
            x, y, z = batch
            logits = self.forward(x,0)

        y = torch.max(y, 1)[1]
        loss = self.cross_entropy_loss(logits,y)

        tqdm_dict = {'train_loss': loss}
        # comet_logger.experiment.log_model('train_loss', loss)
        output = OrderedDict({
            'loss': loss,
            'progress_bar': tqdm_dict,
            'log': tqdm_dict
        })
        return output


    def validation_step(self, batch, batch_idx):
        if self.hparams.featurize:
            x, y, z, f = batch
            y_pred = self.forward(x, f)
        else:
            x, y, z = batch
            y_pred = self.forward(x, 0)

        y = torch.max(y,1)[1]
        # print(y)
        loss = self.cross_entropy_loss(y_pred,y)

        # accuracy
        y_hat = torch.max(y_pred,1)[1]
        val_acc = torch.sum(y == y_hat).item() / len(y)
        val_acc = torch.tensor(val_acc)

        output = OrderedDict({
            'val_loss': loss,
            'val_acc': val_acc,
        })

        return output

    def validation_epoch_end(self, outputs):
        # called at the end of a validation epoch
        # outputs is an array with what you returned in validation_step for each batch
        # outputs = [{'loss': batch_0_loss}, {'loss': batch_1_loss}, ..., {'loss': batch_n_loss}]

        val_loss_mean = 0
        val_acc_mean = 0
        for output in outputs:
            val_loss = output['val_loss']

            # reduce manually when using dp
            if self.trainer.use_dp or self.trainer.use_ddp2:  # not implemented
                val_loss = torch.mean(val_loss)
            val_loss_mean += val_loss

            # reduce manually when using dp
            val_acc = output['val_acc']
            if self.trainer.use_dp or self.trainer.use_ddp2:   # not implemented
                val_acc = torch.mean(val_acc)

            val_acc_mean += val_acc

        val_loss_mean /= len(outputs)
        val_acc_mean /= len(outputs)
        tqdm_dict = {'val_loss': val_loss_mean, 'val_acc': val_acc_mean}
        result = {'progress_bar': tqdm_dict, 'log': {'val_loss': val_loss_mean,'val_acc':val_acc_mean},
                  'val_loss': val_loss_mean}
        return result

    def test_step(self, batch, batch_idx):
        # to do
        if self.hparams.featurize:
            x, y, z, f = batch
            y_pred = self.forward(x, f)
        else:
            x, y, z = batch
            y_pred = self.forward(x, 0)

        y = torch.max(y,1)[1]
        loss = self.cross_entropy_loss(y_pred,y)

        # accuracy
        y_hat = torch.max(y_pred,1)[1]
        test_acc = torch.sum(y == y_hat).item() / len(y)
        test_acc = torch.tensor(test_acc)

        # if batch_idx == int(len(y)/self.hparams.batch_size):
        output = OrderedDict({
            'test_loss': loss,
            'test_acc': test_acc,
            'true_label': y,
            'pred_label': y_hat,
            'snrs': z,
        })

        return output

    def test_epoch_end(self, outputs):
        # called at the end of a test epoch
        # outputs is an array with what you returned in test_step for each batch
        # outputs = [{'loss': batch_0_loss}, {'loss': batch_1_loss}, ..., {'loss': batch_n_loss}]
        # print(outputs)
        test_loss_mean = 0
        test_acc_mean = 0
        for output in outputs:
            test_loss = output['test_loss']

            # reduce manually when using dp
            if self.trainer.use_dp or self.trainer.use_ddp2:  # not implemented
                test_loss = torch.mean(test_loss)
            test_loss_mean += test_loss

            # reduce manually when using dp
            test_acc = output['test_acc']
            if self.trainer.use_dp or self.trainer.use_ddp2:  # not implemented
                test_acc = torch.mean(test_acc)

            test_acc_mean += test_acc
            self.all_true.extend(output['true_label'].detach().cpu().data.numpy())
            self.all_pred.extend(output['pred_label'].detach().cpu().data.numpy())
            self.all_snr.extend(output['snrs'].detach().cpu().data.numpy())

        confusion_matrix = metrics.confusion_matrix(self.all_true,self.all_pred)
        accuracy = metrics.accuracy_score(self.all_true,self.all_pred)
        # save results in csv
        fieldnames = ['True_label', 'Predicted_label', 'SNR']

        if not os.path.exists(CHECKPOINTS_DIR):
            os.makedirs(CHECKPOINTS_DIR)

        with open(CHECKPOINTS_DIR + "output.csv", 'w', encoding='utf-8') as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames, quoting=csv.QUOTE_NONNUMERIC)
            writer.writeheader()
            for i, j, k in zip(self.all_true, self.all_pred, self.all_snr):
                writer.writerow(
                    {'True_label': i.item(), 'Predicted_label': j.item(), 'SNR': k})

        test_loss_mean /= len(outputs)
        test_acc_mean /= len(outputs)
        tqdm_dict = OrderedDict({'Test_loss': test_loss_mean, 'Test_acc(mean)': test_acc_mean,
                                'True_accuracy': accuracy, 'Confusion_matrix': confusion_matrix})

        neptune_logger.experiment.log_metric('test_accuracy', accuracy)
        neptune_logger.experiment.log_metric('test_loss', test_loss_mean)
        # Log charts
        # fig, ax = plt.subplots(figsize=(16, 12))
        # plot_confusion_matrix(self.all_true, self.all_pred, ax=ax)
        # neptune_logger.experiment.log_image('confusion_matrix', fig)
        # Save checkpoints folder
        neptune_logger.experiment.log_artifact(CHECKPOINTS_DIR + "output.csv")
        result = {'progress_bar': tqdm_dict, 'log': {'test_loss':test_loss_mean}}
        return result


    def prepare_data(self, valid_fraction=0.05, test_fraction=0.2):
        dataset = DatasetFromHDF5(self.hparams.data_path, 'iq', 'labels', 'snrs', self.hparams.featurize)
        num_train = len(dataset)
        indices = list(range(num_train))
        val_split = int(math.floor(valid_fraction * num_train))
        test_split = val_split + int(math.floor(test_fraction * num_train))
        training_params = {"batch_size": self.hparams.batch_size,
                           "num_workers": self.hparams.num_workers}

        if not ('shuffle' in training_params and not training_params['shuffle']):
            np.random.seed(4)
            np.random.shuffle(indices)
        if 'num_workers' not in training_params:
            training_params['num_workers'] = 1

        train_idx, valid_idx, test_idx = indices[test_split:], indices[:val_split], indices[val_split:test_split]
        train_sampler = SubsetRandomSampler(train_idx)
        valid_sampler = SubsetRandomSampler(valid_idx)
        test_sampler = SubsetRandomSampler(test_idx)
        self.train_dataset = DataLoader(dataset, batch_size=self.hparams.batch_size,
                                   shuffle=self.hparams.shuffle,num_workers=self.hparams.num_workers,
                                   sampler=train_sampler)
        self.val_dataset = DataLoader(dataset, batch_size=self.hparams.batch_size,
                                 shuffle=self.hparams.shuffle,num_workers=self.hparams.num_workers,
                                 sampler=valid_sampler)
        self.test_dataset = DataLoader(dataset, batch_size=self.hparams.batch_size,
                                  shuffle=self.hparams.shuffle, num_workers=self.hparams.num_workers,
                                  sampler=test_sampler)


    # @pl.data_loader
    def train_dataloader(self):
        return self.train_dataset

    # @pl.data_loader
    def val_dataloader(self):
        return self.val_dataset

    # @pl.data_loader
    def test_dataloader(self):
        return self.test_dataset

# ----------------------------------------Testing the model-----------------------------------------------

# function to test the model separately
def inference(hparams):

    model = LightningCNN.load_from_checkpoint(
    checkpoint_path='/home/rachneet/thesis_results/intf_ofdm_snr10_all/epoch=29.ckpt',
    hparams=hparams,
    map_location=None
    )

    dataset = DatasetFromHDF5(hparams.data_path, 'iq', 'labels', 'snrs', hparams.featurize)
    num_train = len(dataset)
    indices = list(range(num_train))
    val_split = int(math.floor(0.05 * num_train))
    test_split = val_split + int(math.floor(0.2 * num_train))
    training_params = {"batch_size": hparams.batch_size,
                       "num_workers": hparams.num_workers}

    if not ('shuffle' in training_params and not training_params['shuffle']):
        np.random.seed(4)
        np.random.shuffle(indices)
    if 'num_workers' not in training_params:
        training_params['num_workers'] = 1

    train_idx, valid_idx, test_idx = indices[test_split:], indices[:val_split], indices[val_split:test_split]
    train_sampler = SubsetRandomSampler(train_idx)
    valid_sampler = SubsetRandomSampler(valid_idx)
    test_sampler = SubsetRandomSampler(test_idx)
    train_dataset = DataLoader(dataset, batch_size=hparams.batch_size,
                                    shuffle=hparams.shuffle, num_workers=hparams.num_workers,
                                    sampler=train_sampler)
    val_dataset = DataLoader(dataset, batch_size=hparams.batch_size,
                                  shuffle=hparams.shuffle, num_workers=hparams.num_workers,
                                  sampler=valid_sampler)
    test_dataset = DataLoader(dataset, batch_size=hparams.batch_size,
                                   shuffle=hparams.shuffle, num_workers=hparams.num_workers,
                                   sampler=test_sampler)

    model_checkpoint = pl.callbacks.ModelCheckpoint(CHECKPOINTS_DIR)
    trainer = Trainer(gpus=hparams.gpus, checkpoint_callback=True)
    trainer.test(model, test_dataloaders=test_dataset)
    # Save checkpoints folder
    neptune_logger.experiment.log_artifact(CHECKPOINTS_DIR)
    # You can stop the experiment
    neptune_logger.experiment.stop()

# -------------------------------------------------------------------------------------------------------------------
CHECKPOINTS_DIR = '/home/rachneet/thesis_results/mixed_impairments_cnn/'
neptune_logger = NeptuneLogger(
    api_key=os.environ.get("NEPTUNE_API_KEY"),
    project_name="rachneet/sandbox",
    experiment_name="mixed_impairments_cnn",   # change this for new runs
)

# ---------------------------------------MAIN FUNCTION TRAINER-------------------------------------------------------

def main(hparams):

    model = LightningCNN(hparams)
    # exp = Experiment(save_dir=os.getcwd())
    if not os.path.exists(CHECKPOINTS_DIR):
        os.makedirs(CHECKPOINTS_DIR)
    model_checkpoint = pl.callbacks.ModelCheckpoint(CHECKPOINTS_DIR)
    early_stop_callback = pl.callbacks.EarlyStopping(
        monitor='val_loss',
        min_delta=0.00,
        patience=5,
        verbose=False,
        mode='min'
    )
    trainer = Trainer(logger=neptune_logger,
                      gpus=hparams.gpus,
                      max_epochs=hparams.max_epochs,
                      checkpoint_callback=True,
                      callbacks=[model_checkpoint])
                      # early_stop_callback=early_stop_callback)
    trainer.fit(model)
    # load best model
    file_name = ''
    for subdir, dirs, files in os.walk(CHECKPOINTS_DIR):
        for file in files:
            if file[-4:] == 'ckpt':
                file_name = file
    model = LightningCNN.load_from_checkpoint(
        checkpoint_path=CHECKPOINTS_DIR+file_name,
        hparams=hparams,
        map_location=None
    )
    trainer.test(model)
    neptune_logger.experiment.log_artifact(CHECKPOINTS_DIR)
    neptune_logger.experiment.stop()
    # note: here dataloader can also be passed to the .fit function

# ==================================================PASSING ARGS=====================================================

if __name__=="__main__":

    path = "/home/rachneet/rf_dataset_inets/mixed_all_impairments.h5"
    out_path = "/home/rachneet/thesis_results/"

    parser = ArgumentParser()
    parser.add_argument('--output_path', default=out_path)
    parser.add_argument('--data_path', default=path)
    parser.add_argument('--gpus', default=[0])
    parser.add_argument('--max_epochs', default=30)
    parser.add_argument('--batch_size', default=512)
    parser.add_argument('--num_workers', default=10)
    parser.add_argument('--shuffle', default=False)
    parser.add_argument('--learning_rate', default=1e-2)
    parser.add_argument('--momentum', default=0.9)
    parser.add_argument('--in_dims', default=2)
    parser.add_argument('--filters', default=64)
    parser.add_argument('--kernel_size', type=list, nargs='+', default=[3,3,3,3,3,3])
    parser.add_argument('--pool_size', default=3)
    parser.add_argument('--fc_neurons', type=int, default=128)
    parser.add_argument('--n_classes', default=8)
    parser.add_argument('--n_features', default=10)
    parser.add_argument('--featurize', default=False)
    args = parser.parse_args()

    main(args)
    # inference(args)