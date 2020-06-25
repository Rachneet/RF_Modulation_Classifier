import numpy as np
import os
import glob
import h5py as h5
import random
from read_filtered import sort_matrix_entries, encode_labels
from sklearn import preprocessing
import dataloader as dl
import pandas as pd


def merge_files():

    root_folder = "/media/backup/Arsenal/interference_new/interference/ota"
    param_folder = "/no_cfo/tx_usrp/rx_usrp/intf_vsg/i_SC_16QAM"
    output_path = root_folder + "/dataset_intf_sc_16QAM.h5"
    file_paths = []

    for subdir, dirs, files in os.walk(root_folder+param_folder):
        #print(dirs)
        for directory in dirs:
            if directory == "npz":
                files_in_directory = glob.glob(os.path.join(subdir, directory) + "/*.npz")
                # subfolder = os.path.join(subdir, directory) + "/"
                # print(subfolder)
                # print(files_in_directory)
                file_paths.extend((files_in_directory))
    # print(file_paths)
    # print(len(file_paths))
    # sorted_paths =[]
    # for name in file_paths:
    #      if "intf_vsg/i_OFDM_64QAM" in name:
    #          sorted_paths.append(name)
    print("Total number of files: ",len(file_paths))
    # # print(sorted_paths)
    #
    num_samples = []
    num_iq = 50000
    total_samples = 0
    for path in file_paths:
        data = np.load(path)
        label = data['labels']
        num_samples.append(len(label))
    total_samples = sum(num_samples)
    print("Samples accounted for: {}".format(total_samples))
    print("Starting merge...")

    for i,path in enumerate(file_paths):
        data = np.load(path)
        iq = data['matrix']
        labels = data['labels']
        snrs = data['snrs']

        processed_iq = np.apply_along_axis(sort_matrix_entries, axis=1, arr=iq)
        processed_labels = encode_labels(8,labels)

        if not os.path.exists(output_path):
            with h5.File(output_path,'w') as hdf:
                hdf.create_dataset('iq',data=processed_iq,chunks=True,maxshape=(None,num_iq,2),compression='gzip')
                hdf.create_dataset('labels', data=processed_labels, chunks=True, maxshape=(None,8), compression='gzip')
                hdf.create_dataset('snrs', data=snrs, chunks=True, maxshape=(None,), compression='gzip')
                print(hdf['iq'].shape)

        else:
            with h5.File(output_path, 'a') as hf:
                hf["iq"].resize((hf["iq"].shape[0] + iq.shape[0]), axis=0)
                hf["iq"][-iq.shape[0]:] = processed_iq
                hf["labels"].resize((hf["labels"].shape[0] + labels.shape[0]), axis=0)
                hf["labels"][-labels.shape[0]:] = processed_labels
                hf["snrs"].resize((hf["snrs"].shape[0] + snrs.shape[0]), axis=0)
                hf["snrs"][-snrs.shape[0]:] = snrs
                print(hf['iq'].shape)



        print("Files merged:", i+1)


def merge_hdfset():
    path = "/media/backup/Arsenal/rf_dataset_inets/"
    path_deepsig = "/media/backup/Arsenal/2018.01.OSC.0001_1024x2M.h5/2018.01/"
    # files = [path+"dataset_intf_free_no_cfo_vsg_snr0_1024.h5",
    #          path+"dataset_intf_free_no_cfo_vsg_snr5_1024.h5",
    #          path+"dataset_intf_free_no_cfo_vsg_snr10_1024.h5",
    #          path+"dataset_intf_free_no_cfo_vsg_snr15_1024.h5",
    #          path+"dataset_intf_free_no_cfo_vsg_snr20_1024.h5"]
    files = [path + "dataset_intf_free_no_cfo_vsg_snr20_1024.h5",
             path_deepsig + "GOLD_XYZ_OSC.0001_1024.hdf5"]
    mods_skip = [8,9,18,19,23]
    with h5.File(path+'dataset_un_vsg_snr20.h5', mode='w') as file:
        row1 = 0
        i = 0
        for dataset in files:
            h5fr = h5.File(dataset, 'r')
            dset1 = list(h5fr.keys())[0]
            dset2= list(h5fr.keys())[1]
            dset3 = list(h5fr.keys())[2]
            iq_data = h5fr[dset1][:]
            label_data = h5fr[dset2][:]
            snr_data = h5fr[dset3][:]

            if dataset[-4:] == "hdf5":
                print("in hdf5")
                label_idx = [dl.label_idx(label) for label in label_data]
                idx_class = [i for i in range(len(label_idx)) if label_idx[i] not in mods_skip]

                iq_data = iq_data[idx_class]
                # label_data[idx_class] = np.array([0,0,0,0,0,0,0,0,1])
                label_data = np.array([np.array([0,0,0,0,0,0,0,0,1]) for _ in label_data[idx_class]])
                snr_data = snr_data[idx_class]
                snr_data = snr_data.astype('int8')
            else:
                label_data = np.array([np.append(label,np.array([0])) for label in label_data])
                # df = pd.DataFrame()
                # df['iq'] = list(map(lambda x: np.array(x), iq_data))
                # df['normalized_iq'] = df.iq.apply(lambda x: preprocessing.scale(x, with_mean=False))
                # df.drop('iq', axis=1, inplace=True)
                # df['labels'] = list(map(lambda x: np.array(x), label_data))
                # df['snr'] = list(map(lambda x: x, snr_data))
                # df = df.sample(frac=1, random_state=4)

            # normalize data
            norm_iq = [preprocessing.scale(sample, with_mean=False) for sample in iq_data]
            norm_iq = np.array(norm_iq)
            print("norm done")

            dslen = iq_data.shape[0]
            cols_iq = iq_data.shape[1]
            rows_iq = iq_data.shape[2]
            cols_labels = label_data.shape[1]

            # print(dslen,rows_iq,rows_iq,cols_labels,cols_snrs)
            # break
            if row1 == 0:
                file.create_dataset('iq', dtype="f", shape=(dslen, cols_iq, rows_iq), maxshape=(None, cols_iq, rows_iq))
                file.create_dataset('labels', dtype="f", shape=(dslen, cols_labels), maxshape=(None, cols_labels))
                file.create_dataset('snrs', dtype="f", shape=(dslen,), maxshape=(None,))
            if row1 + dslen <= len(file['iq']):
                file['iq'][row1:row1 + dslen, :,:] = norm_iq[:]
                file['labels'][row1:row1 + dslen, :] = label_data[:]
                file['snrs'][row1:row1 + dslen,] = snr_data.squeeze()
            else:
                file['iq'].resize((row1 + dslen, cols_iq, rows_iq))
                file['iq'][row1:row1 + dslen, :,:] = norm_iq[:]
                file['labels'].resize((row1 + dslen, cols_labels))
                file['labels'][row1:row1 + dslen, :] = label_data[:]
                file['snrs'].resize((row1 + dslen, ))
                file['snrs'][row1:row1 + dslen,] = snr_data.squeeze()
            row1 += dslen
            i = i + 1
            print("Datasets processed: {}".format(i))


def sample_from_h5(path, output_path):
    file = h5.File(path,'r')
    iq, labels, snrs = file['iq'], file['labels'], file['snrs']
    num_iq = 1024          # iq per sample
    batch = 256
    samples_per_segment = int(num_iq / batch)
    batch_labels = np.zeros((samples_per_segment,8), dtype=np.float32)
    batch_snrs = np.zeros(samples_per_segment, dtype=np.int8)

    for row in range(len(iq)):
        # print(iq[row].shape)
        batch_iq = np.array(np.split(iq[row], samples_per_segment), dtype=np.float32)
        batch_labels[:] = np.array(labels[row])
        batch_snrs[:] = np.array(snrs[row])
        # print(batch_iq.shape)
        # print(batch_labels.shape)
        # print(batch_labels)
        # print(batch_snrs.shape)
        # print(batch_snrs)

        # print(batch_iq, batch_labels, batch_snrs)

        if not os.path.exists(output_path):
            with h5.File(output_path, 'w') as hdf:
                hdf.create_dataset('iq', data=batch_iq, chunks=True, maxshape=(None, batch, 2),
                                   compression='gzip')
                hdf.create_dataset('labels', data=batch_labels, chunks=True, maxshape=(None, 8),
                                   compression='gzip')
                hdf.create_dataset('snrs', data=batch_snrs, chunks=True, maxshape=(None,), compression='gzip')
                print(hdf['iq'].shape)

        else:
            with h5.File(output_path, 'a') as hf:
                hf["iq"].resize((hf["iq"].shape[0] + batch_iq.shape[0]), axis=0)
                hf["iq"][-batch_iq.shape[0]:] = batch_iq
                hf["labels"].resize((hf["labels"].shape[0] + batch_labels.shape[0]), axis=0)
                hf["labels"][-batch_labels.shape[0]:] = batch_labels
                hf["snrs"].resize((hf["snrs"].shape[0] + batch_snrs.shape[0]), axis=0)
                hf["snrs"][-batch_snrs.shape[0]:] = batch_snrs
                print(hf['iq'].shape)


if __name__=="__main__":
    # merge_hdfset()
    pass
    # data_path = "/media/rachneet/arsenal/rf_dataset_inets/vsg_no_intf_all_normed.h5"
    # output_path = "/media/rachneet/arsenal/rf_dataset_inets/dataset_vsg_all_256.h5"
    # sample_from_h5(data_path, output_path)
